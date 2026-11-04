#!/usr/bin/env python3
"""SSH transport: run a GUI job on a remote server while the GUI stays local.

For a remote job this module:
  1. uploads in/ files + params.json to <remote_base>/jobs/<id>/,
  2. uploads the two server-side scripts to <remote_base>/bin/ and starts
     gui_remote_run.py detached (setsid),
  3. mirrors out/solution.cpp, out/trace.jsonl, llm-io.jsonl, live.json,
     log.txt and exit back over SFTP once a second.

The SSH password only lives in memory for the duration of a job; it is never
written to meta.json, the job log, or any file. All remote paths are quoted
with shlex.quote before they reach a shell.
"""
from __future__ import annotations

import json
import os
import shlex
import threading
import time
import traceback

try:
    import paramiko
    PARAMIKO_VERSION = getattr(paramiko, "__version__", "?")
except Exception:  # paramiko is optional; local mode keeps working without it
    paramiko = None
    PARAMIKO_VERSION = ""

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPTS = os.path.join(HERE, "remote")

# Per-job mirror cache: local path -> (remote size, remote mtime)
MIRROR_STAT: dict[str, tuple[int, int]] = {}
MIRROR_LOCK = threading.Lock()


def now() -> float:
    return time.time()


def defaults() -> dict:
    return {
        "pkg": os.environ.get("HLSAGENT_REMOTE_PKG",
                              "/root/autodl-tmp/46939_hlsagent"),
        "py": os.environ.get("HLSAGENT_REMOTE_PY",
                             "/root/miniconda3/bin/python"),
        "base": os.environ.get("HLSAGENT_REMOTE_BASE",
                               "/root/autodl-tmp/hlsagent-gui"),
        "upstream": os.environ.get("HLSAGENT_REMOTE_UPSTREAM",
                                   "http://127.0.0.1:11434/v1"),
        "model": os.environ.get("HLSAGENT_REMOTE_MODEL",
                                "nemotron-3.5-lightning-c512k"),
        "vitis_bin": os.environ.get("HLSAGENT_REMOTE_VITIS_BIN",
                                    "/root/autodl-tmp/Xilinx/2025.2/Vitis/bin"),
        "compat_lib": os.environ.get(
            "HLSAGENT_REMOTE_COMPAT_LIB",
            "/root/autodl-tmp/rag-hard-20261009/compat/lib/x86_64-linux-gnu"),
    }


def model_name(name: str) -> str:
    return name[:-7] if name.endswith(":latest") else name


class SshError(RuntimeError):
    pass


class SshSession:
    def __init__(self, host: str, port: int, user: str, password: str,
                 timeout: float = 20.0):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.timeout = float(timeout)
        self.client = None
        self.sftp = None
        self._lock = threading.RLock()

    # -- connection ------------------------------------------------------
    def connect(self) -> None:
        if paramiko is None:
            raise SshError("本机没有 paramiko；请用装了 paramiko 的 Python 启动 GUI"
                           "（run.bat 使用 C:\\Program Files\\Python311\\python.exe）")
        self.close()
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(self.host, port=self.port, username=self.user,
                      password=self.password, timeout=self.timeout,
                      banner_timeout=self.timeout, auth_timeout=self.timeout,
                      look_for_keys=False, allow_agent=False)
        except paramiko.AuthenticationException as exc:
            raise SshError(f"SSH 认证失败：{self.user}@{self.host}:{self.port}") from exc
        except Exception as exc:
            raise SshError(f"SSH 连接失败 {self.host}:{self.port}："
                           f"{type(exc).__name__}: {exc}") from exc
        transport = c.get_transport()
        if transport is not None:
            transport.set_keepalive(15)
        self.client = c
        try:
            self.sftp = c.open_sftp()
            self.sftp.get_channel().settimeout(60)
        except Exception as exc:
            self.close()
            raise SshError(f"SFTP 打开失败：{type(exc).__name__}: {exc}") from exc

    def close(self) -> None:
        for obj in (self.sftp, self.client):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        self.sftp = None
        self.client = None

    def alive(self) -> bool:
        try:
            tr = self.client.get_transport() if self.client is not None else None
            return bool(tr and tr.is_active())
        except Exception:
            return False

    def _ensure(self) -> None:
        if not self.alive():
            self.connect()

    # -- primitives ------------------------------------------------------
    def exec(self, cmd: str, timeout: float = 60.0) -> tuple[int, str, str]:
        with self._lock:
            self._ensure()
            try:
                _stdin, stdout, stderr = self.client.exec_command(
                    cmd, timeout=timeout)  # type: ignore[union-attr]
                out = stdout.read().decode("utf-8", "replace")
                err = stderr.read().decode("utf-8", "replace")
                rc = stdout.channel.recv_exit_status()
            except Exception as exc:
                raise SshError(f"远端命令失败：{type(exc).__name__}: {exc}") from exc
            return rc, out, err

    def put(self, local: str, remote: str) -> None:
        with self._lock:
            self._ensure()
            try:
                self.sftp.put(local, remote)  # type: ignore[union-attr]
            except Exception as exc:
                raise SshError(f"上传失败 {remote}：{type(exc).__name__}: {exc}") from exc

    def put_text(self, text: str, remote: str) -> None:
        with self._lock:
            self._ensure()
            try:
                with self.sftp.file(remote, "wb") as fh:  # type: ignore[union-attr]
                    fh.write(text.encode("utf-8"))
            except Exception as exc:
                raise SshError(f"写入失败 {remote}：{type(exc).__name__}: {exc}") from exc

    def stat(self, remote: str):
        with self._lock:
            self._ensure()
            try:
                st = self.sftp.stat(remote)  # type: ignore[union-attr]
                return int(st.st_size), int(st.st_mtime)
            except OSError:
                return None
            except Exception as exc:
                raise SshError(f"stat 失败 {remote}：{type(exc).__name__}: {exc}") from exc

    def read(self, remote: str, max_bytes: int = 8 << 20) -> bytes:
        with self._lock:
            self._ensure()
            try:
                with self.sftp.file(remote, "rb") as fh:  # type: ignore[union-attr]
                    st = fh.stat()
                    if st.st_size and st.st_size > max_bytes:
                        fh.seek(st.st_size - max_bytes)
                    return fh.read(max_bytes)
            except OSError:
                return b""
            except Exception as exc:
                raise SshError(f"读取失败 {remote}：{type(exc).__name__}: {exc}") from exc

    def read_tail(self, remote: str, limit: int = 65536) -> bytes:
        return self.read(remote, max_bytes=limit)


# --------------------------------------------------------------------------
# local helpers
# --------------------------------------------------------------------------
def _read_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
    except OSError:
        pass
    return rows


def _read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_local(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _pull(sess: SshSession, remote: str, local: str, force: bool = False,
          tail: bool = False) -> bool:
    """Fetch a remote file if its (size, mtime) changed. Returns True if written."""
    st = sess.stat(remote)
    if st is None:
        return False
    with MIRROR_LOCK:
        if not force and MIRROR_STAT.get(local) == st:
            return False
    data = sess.read_tail(remote) if tail else sess.read(remote)
    _write_local(local, data)
    with MIRROR_LOCK:
        MIRROR_STAT[local] = st
    return True


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------
def probe(ssh_cfg: dict, pkg: str = "", py: str = "",
          base: str = "") -> dict:
    d = defaults()
    pkg = (pkg or d["pkg"]).strip()
    py = (py or d["py"]).strip()
    base = (base or d["base"]).strip()
    host = str(ssh_cfg.get("host") or "").strip()
    port = int(ssh_cfg.get("port") or 22)
    user = str(ssh_cfg.get("user") or "root").strip()
    password = str(ssh_cfg.get("password") or "")
    if not host:
        return {"ok": False, "error": "未填 SSH 主机"}
    sess = SshSession(host, port, user, password, timeout=15.0)
    try:
        sess.connect()
        script = (
            "echo __PKG__; "
            f"test -d {shlex.quote(pkg + '/agent')} && echo 1 || echo 0; "
            "echo __PY__; "
            f"test -x {shlex.quote(py)} && echo 1 || echo 0; "
            "echo __PYV__; "
            f"{shlex.quote(py)} -V 2>&1 || true; "
            "echo __OLLAMA__; "
            "curl -sf -m 4 http://127.0.0.1:11434/api/tags || echo NO_OLLAMA; "
            "echo; "
            "echo __GPU__; "
            "nvidia-smi --query-gpu=name,memory.total,memory.used "
            "--format=csv,noheader 2>/dev/null || true; "
            "echo __DF__; "
            f"D={shlex.quote(base)}; [ -d \"$D\" ] || D={shlex.quote(pkg)}; "
            "[ -d \"$D\" ] || D=/; df -h \"$D\" 2>/dev/null | tail -1 || true; "
            "echo __VITIS__; "
            f"test -d {shlex.quote(d['vitis_bin'])} && echo 1 || echo 0; "
            "echo __END__"
        )
        _rc, out, err = sess.exec(script, timeout=30)
        sections: dict[str, list[str]] = {}
        cur = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("__") and line.endswith("__"):
                cur = line.strip("_")
                sections[cur] = []
            elif cur:
                sections[cur].append(line)
        pkg_ok = (sections.get("PKG") or ["0"])[0] == "1"
        py_ok = (sections.get("PY") or ["0"])[0] == "1"
        py_version = " ".join(sections.get("PYV") or []).strip()
        vitis_ok = (sections.get("VITIS") or ["0"])[0] == "1"
        ollama_lines = sections.get("OLLAMA") or []
        ollama_ok = "NO_OLLAMA" not in ollama_lines and bool(ollama_lines)
        models: list[str] = []
        for line in ollama_lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                doc = json.loads(line)
                for m in doc.get("models") or []:
                    name = m.get("name") if isinstance(m, dict) else None
                    if name:
                        models.append(str(name))
            except Exception:
                continue
        default_model = ""
        for cand in models:
            if model_name(cand) == d["model"]:
                default_model = cand
                break
        if not default_model and models:
            default_model = models[0]
        gpu = " | ".join([x for x in (sections.get("GPU") or []) if x])
        disk = " | ".join([x for x in (sections.get("DF") or []) if x])
        return {
            "ok": True,
            "host": host,
            "pkg_ok": pkg_ok,
            "py_ok": py_ok,
            "python_version": py_version,
            "vitis_ok": vitis_ok,
            "ollama_ok": ollama_ok,
            "models": models,
            "default_model": default_model,
            "gpu": gpu,
            "disk": disk,
            "paramiko": PARAMIKO_VERSION,
        }
    except SshError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        sess.close()


def quick_check(ssh_cfg: dict, pkg: str, py: str) -> None:
    """Cheap preflight before a job is created; raises SshError."""
    host = str(ssh_cfg.get("host") or "").strip()
    if not host:
        raise SshError("未填 SSH 主机")
    sess = SshSession(host, int(ssh_cfg.get("port") or 22),
                      str(ssh_cfg.get("user") or "root"),
                      str(ssh_cfg.get("password") or ""), timeout=15.0)
    try:
        sess.connect()
        cmd = (f"test -d {shlex.quote(pkg + '/agent')} && echo 1 || echo 0; "
               f"test -x {shlex.quote(py)} && echo 1 || echo 0")
        _rc, out, _err = sess.exec(cmd, timeout=20)
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        if len(lines) < 2 or lines[0] != "1":
            raise SshError(f"远端找不到 agent 包：{pkg}")
        if lines[1] != "1":
            raise SshError(f"远端 Python 不可执行：{py}")
    finally:
        sess.close()


# --------------------------------------------------------------------------
# remote job
# --------------------------------------------------------------------------
def _persist_local(job) -> None:
    try:
        with open(job.meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        if not isinstance(meta, dict):
            return
        meta.update({
            "state": job.state,
            "ended": job.ended,
            "exit_code": job.exit_code,
            "stop_requested": job.stop_requested,
            "timeout_hit": job.timeout_hit,
        })
        tmp = job.meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, job.meta_path)
    except (OSError, ValueError):
        pass


def _write_meta(job, cfg: dict) -> None:
    meta = {k: v for k, v in cfg.items() if k != "api_key"}
    meta.update({"id": job.id, "created": job.started,
                 "pkg": cfg.get("remote_pkg") or defaults()["pkg"],
                 "backend": "remote"})
    tmp = job.meta_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, job.meta_path)


def _read_int(sess: SshSession, remote: str):
    data = sess.read(remote, max_bytes=64)
    txt = data.decode("utf-8", "replace").strip()
    return int(txt) if txt.isdigit() else None


def _read_remote_json(sess: SshSession, remote: str):
    data = sess.read(remote, max_bytes=4 << 20)
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8", "replace"))
    except Exception:
        return None


def _signal_remote(sess: SshSession, jobroot: str, sig: str) -> None:
    """Signal the runner/agent/proxy process groups (best effort)."""
    q = shlex.quote
    cmd = (
        f"for f in pid agent.pid proxy.pid; do "
        f"p=$(cat {q(jobroot)}/$f 2>/dev/null); "
        f"if [ -n \"$p\" ]; then "
        f"kill -s {sig} -- -\"$p\" 2>/dev/null; "
        f"kill -s {sig} \"$p\" 2>/dev/null; "
        f"fi; done; true"
    )
    try:
        sess.exec(cmd, timeout=20)
    except Exception:
        pass


def _sync_calls(job, force: bool = False) -> None:
    rows = _read_jsonl(job.io_path)
    with job._call_lock:
        if len(rows) <= len(job.calls):
            if not force or not job.calls:
                return
            snapshot = list(job.calls)
            _rewrite_io(job, snapshot)
            return
        trace = _read_jsonl(os.path.join(job.out_dir, "trace.jsonl"))
        last_round = None
        for rec in trace:
            if rec.get("tool") == "prompt" and rec.get("round") is not None:
                try:
                    last_round = int(rec["round"])
                except (TypeError, ValueError):
                    pass
        for rec in rows[len(job.calls):]:
            if rec.get("round") is None:
                if last_round is None:
                    rec["round"] = None
                    rec["attempt"] = 0
                else:
                    rec["round"] = last_round
                    rec["attempt"] = sum(
                        1 for c in job.calls if c.get("round") == last_round) + 1
            job.calls.append(rec)
            try:
                job._seq = max(job._seq, int(rec.get("seq") or 0))
            except (TypeError, ValueError):
                pass
        snapshot = list(job.calls)
    _rewrite_io(job, snapshot)


def _rewrite_io(job, rows: list[dict]) -> None:
    """Rewrite the local llm-io.jsonl with round/attempt filled in.

    The server-side proxy cannot know rounds; the GUI assigns them from the
    trace after mirroring. Local jobs already write them into the file, so
    remote jobs rewrite the mirrored copy to match."""
    tmp = job.io_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            for rec in rows:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, job.io_path)
    except OSError:
        pass


def _set_live(job, doc) -> None:
    live = None
    if isinstance(doc, dict) and isinstance(doc.get("live"), dict):
        live = doc["live"]
    with job._call_lock:
        job.live = live


def launch_remote(job, cfg: dict, password: str) -> None:
    d = defaults()
    ssh_cfg = cfg.get("ssh") or {}
    host = str(ssh_cfg.get("host") or "").strip()
    port = int(ssh_cfg.get("port") or 22)
    user = str(ssh_cfg.get("user") or "root").strip()
    pkg = str(cfg.get("remote_pkg") or d["pkg"]).rstrip("/")
    py = str(cfg.get("remote_py") or d["py"])
    base = str(cfg.get("remote_base") or d["base"]).rstrip("/")
    upstream = str(cfg.get("base_url") or d["upstream"]).rstrip("/")
    jobroot = f"{base}/jobs/{job.id}"

    os.makedirs(job.in_dir, exist_ok=True)
    os.makedirs(job.out_dir, exist_ok=True)
    os.makedirs(job.tmp_dir, exist_ok=True)
    for name in ("prompt.txt", "interface.txt", "top.txt"):
        with open(os.path.join(job.in_dir, name), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(str(cfg.get(name[:-4]) or ""))
    _write_meta(job, cfg)

    sess = SshSession(host, port, user, password, timeout=20.0)
    try:
        sess.connect()
        q = shlex.quote
        rc, _out, err = sess.exec(
            f"mkdir -p {q(base + '/bin')} {q(jobroot + '/in')} "
            f"{q(jobroot + '/out')} {q(jobroot + '/tmp')}", timeout=30)
        if rc != 0:
            raise SshError(f"远端建目录失败 rc={rc}: {err.strip()[:300]}")

        for name in ("gui_llm_proxy.py", "gui_remote_run.py"):
            sess.put(os.path.join(REMOTE_SCRIPTS, name), f"{base}/bin/{name}")
        for name in ("prompt.txt", "interface.txt", "top.txt"):
            sess.put(os.path.join(job.in_dir, name), f"{jobroot}/in/{name}")

        extra = ""
        if cfg.get("remote_extra_body"):
            extra = '{"reasoning_effort":"none"}'
        params = {
            "job_id": job.id,
            "pkg": pkg,
            "model": str(cfg.get("model") or ""),
            "upstream": upstream,
            "max_tokens": int(cfg.get("max_tokens") or 8192),
            "max_rounds": int(cfg.get("max_rounds") or 4),
            "llm_timeout_s": float(cfg.get("llm_timeout_s") or 1800),
            "total_timeout_s": float(cfg.get("total_timeout_s") or 0),
            "temperature": cfg.get("temperature"),
            "top_p": cfg.get("top_p"),
            "csynth": str(cfg.get("csynth") or "auto"),
            "audit": str(cfg.get("audit") or "on"),
            "skills": str(cfg.get("skills") or "on"),
            "part": str(cfg.get("part") or "xczu3eg-sbva484-1-e"),
            "period_ns": str(cfg.get("period_ns") or "5"),
            "top": str(cfg.get("top") or ""),
            "extra_body": extra,
            "vitis_bin": d["vitis_bin"],
            "compat_lib": d["compat_lib"],
            "ollama_bin": os.environ.get(
                "HLSAGENT_REMOTE_OLLAMA_BIN",
                "/root/autodl-tmp/ollama/bin/ollama"),
            "ollama_models": os.environ.get(
                "HLSAGENT_REMOTE_OLLAMA_MODELS",
                "/root/autodl-tmp/ollama/models"),
            "proxy_script": f"{base}/bin/gui_llm_proxy.py",
        }
        sess.put_text(json.dumps(params, ensure_ascii=False, indent=1),
                      f"{jobroot}/params.json")

        # Keep this a *simple* background command. `cd X && setsid ... &`
        # forks a subshell for the whole `&&` list whose own stdout/stderr
        # still point at the SSH channel, so exec() would not see EOF until
        # the runner exits (long jobs then look like start failures).
        start = (f"setsid nohup {q(py)} {q(base + '/bin/gui_remote_run.py')} "
                 f"{q(jobroot)} >> {q(jobroot + '/runner.log')} 2>&1 "
                 f"< /dev/null & echo started")
        rc, out, err = sess.exec(start, timeout=30)
        if "started" not in out:
            raise SshError(f"远端启动失败 rc={rc}: {err.strip()[:300]}")
        with job.lock:
            job.state = "running"
        _mirror_loop(job, sess, jobroot, cfg)
    except Exception as exc:
        traceback.print_exc()
        with job.lock:
            if job.state in ("starting", "running"):
                job.state = "failed"
            job.ended = now()
            if job.exit_code is None:
                job.exit_code = -1
            job.proxy_error = f"{type(exc).__name__}: {exc}"
        _persist_local(job)
    finally:
        sess.close()


def _final_pull(job, sess: SshSession, jobroot: str) -> None:
    try:
        for remote, local, tail in (
            (f"{jobroot}/out/solution.cpp", os.path.join(job.out_dir, "solution.cpp"), False),
            (f"{jobroot}/out/trace.jsonl", os.path.join(job.out_dir, "trace.jsonl"), False),
            (f"{jobroot}/llm-io.jsonl", job.io_path, False),
            (f"{jobroot}/log.txt", job.log_path, True),
        ):
            _pull(sess, remote, local, force=True, tail=tail)
        live = _read_remote_json(sess, f"{jobroot}/live.json")
        _set_live(job, live)
        # The final pull overwrites llm-io.jsonl with the server-side raw copy
        # (round/attempt null). Force a rewrite from the enriched in-memory
        # records so the on-disk file matches the panel.
        _sync_calls(job, force=True)
    except Exception:
        pass


def _finish(job, ex: dict) -> None:
    try:
        rc = int(ex.get("rc"))
    except (TypeError, ValueError):
        rc = -1
    stopped = bool(ex.get("stopped")) or job.stop_requested
    timed_out = bool(ex.get("timeout")) or job.timeout_hit
    sol = os.path.join(job.out_dir, "solution.cpp")
    if not os.path.exists(sol):
        try:
            with open(sol, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("")
        except OSError:
            pass
    with job.lock:
        job.exit_code = rc
        job.ended = now()
        job.timeout_hit = bool(timed_out)
        if stopped:
            job.state = "stopped"
        elif timed_out:
            job.state = "timeout"
        elif rc == 0:
            job.state = "done"
        else:
            job.state = "failed"
    err = str(ex.get("error") or "")
    if err:
        with job.lock:
            job.proxy_error = err
    _persist_local(job)


def _mirror_loop(job, sess: SshSession, jobroot: str, cfg: dict) -> None:
    total = float(cfg.get("total_timeout_s") or 0)
    hard = now() + total if total > 0 else None
    stop_deadline = None
    dead_since = None
    last_health = 0.0
    err_streak = 0

    while True:
        t = now()
        try:
            if job.stop_requested and stop_deadline is None:
                stop_deadline = t + 10.0
                _signal_remote(sess, jobroot, "TERM")
            if hard is not None and t > hard and not job.timeout_hit:
                with job.lock:
                    job.timeout_hit = True
                stop_deadline = t + 10.0
                _signal_remote(sess, jobroot, "TERM")
            if stop_deadline is not None and t > stop_deadline:
                _signal_remote(sess, jobroot, "KILL")
                stop_deadline = None

            if job.proxy_port is None:
                try:
                    job.proxy_port = _read_int(sess, f"{jobroot}/proxy.port")
                except Exception:
                    pass

            # trace before llm-io: round attribution reads the trace
            _pull(sess, f"{jobroot}/out/trace.jsonl",
                  os.path.join(job.out_dir, "trace.jsonl"))
            _pull(sess, f"{jobroot}/out/solution.cpp",
                  os.path.join(job.out_dir, "solution.cpp"))
            _pull(sess, f"{jobroot}/llm-io.jsonl", job.io_path)
            _pull(sess, f"{jobroot}/log.txt", job.log_path, tail=True)
            doc = _read_remote_json(sess, f"{jobroot}/live.json")
            _set_live(job, doc)
            _sync_calls(job)

            ex = _read_remote_json(sess, f"{jobroot}/exit")
            if isinstance(ex, dict):
                _final_pull(job, sess, jobroot)
                _finish(job, ex)
                return

            # runner death without an exit file
            if t - last_health >= 10.0:
                last_health = t
                try:
                    pid = _read_int(sess, f"{jobroot}/pid")
                    if pid:
                        rc, out, _err = sess.exec(
                            f"kill -0 {pid} >/dev/null 2>&1 && echo alive || echo dead",
                            timeout=15)
                        if "dead" in out:
                            if dead_since is None:
                                dead_since = t
                        else:
                            dead_since = None
                    else:
                        # runner has not written its pid yet; allow a few seconds
                        if t - job.started > 15 and dead_since is None:
                            dead_since = t
                except Exception:
                    pass
            if dead_since is not None and t - dead_since > 4.0:
                ex2 = _read_remote_json(sess, f"{jobroot}/exit")
                if isinstance(ex2, dict):
                    _final_pull(job, sess, jobroot)
                    _finish(job, ex2)
                else:
                    _final_pull(job, sess, jobroot)
                    with job.lock:
                        if job.stop_requested:
                            job.state = "stopped"
                        elif job.timeout_hit:
                            job.state = "timeout"
                        else:
                            job.state = "failed"
                        job.ended = now()
                        job.exit_code = job.exit_code if job.exit_code is not None else -1
                        job.proxy_error = "远端 runner 已退出但没有写 exit（可能被 OOM/系统杀掉）"
                    _persist_local(job)
                return

            err_streak = 0
        except Exception as exc:
            err_streak += 1
            if err_streak <= 2:
                try:
                    sess.close()
                    sess.connect()
                except Exception:
                    pass
                time.sleep(1.0)
                continue
            with job.lock:
                job.state = "failed"
                job.ended = now()
                if job.exit_code is None:
                    job.exit_code = -1
                job.proxy_error = f"SSH 连接中断：{type(exc).__name__}: {exc}"
            _persist_local(job)
            return

        time.sleep(0.9)

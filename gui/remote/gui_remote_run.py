#!/usr/bin/env python3
"""Remote job runner, started detached by the local HLS Agent GUI over SSH.

argv[1] is the job root, which contains:

    in/            prompt.txt / interface.txt / top.txt
    out/           agent output (solution.cpp, trace.jsonl)
    tmp/           AGENT_TMP
    params.json    everything the runner needs (no secrets)

The runner starts the capture proxy, then `python -m agent.main`, enforces the
GUI's total timeout, and writes an `exit` JSON file. It writes its own PID to
`pid` and the children's PIDs to `agent.pid` / `proxy.pid` so the GUI can kill
the process groups if this process dies unexpectedly.

stdlib only.
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.request


STOP = {"flag": False, "sig": 0}


def now() -> float:
    return time.time()


def log(jobroot: str, msg: str) -> None:
    line = f"[gui] {msg}\n"
    try:
        with open(os.path.join(jobroot, "log.txt"), "a", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    sys.stderr.write(line)
    sys.stderr.flush()


def write_atomic(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def write_text(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def kill_group(pid: int, sig: int) -> None:
    if pid <= 0:
        return
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass
    except Exception:
        try:
            os.kill(pid, sig)
        except Exception:
            pass


def ensure_ollama(jobroot: str, params: dict) -> bool:
    tags = "http://127.0.0.1:11434/api/tags"
    if http_ok(tags, 2.0):
        return True
    bin_path = params.get("ollama_bin") or "/root/autodl-tmp/ollama/bin/ollama"
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = (params.get("ollama_models")
                            or "/root/autodl-tmp/ollama/models")
    serve_log = (params.get("ollama_serve_log")
                 or "/root/autodl-tmp/ollama/serve.log")
    log(jobroot, f"ollama not reachable; starting {bin_path}")
    try:
        out = open(serve_log, "ab", buffering=0)
        subprocess.Popen([bin_path, "serve"], stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, env=env)
    except Exception as exc:
        log(jobroot, f"ollama serve spawn failed: {type(exc).__name__}: {exc}")
        return False
    for _ in range(60):
        time.sleep(1.0)
        if http_ok(tags, 2.0):
            return True
    log(jobroot, "ollama did not come up within 60 s")
    return False


def on_signal(signum, _frame) -> None:
    STOP["flag"] = True
    STOP["sig"] = signum


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write("usage: gui_remote_run.py <job_root>\n")
        return 2
    jobroot = os.path.abspath(argv[0])
    try:
        with open(os.path.join(jobroot, "params.json"), "r",
                  encoding="utf-8") as fh:
            params = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"cannot read params.json: {exc}\n")
        return 2
    if not isinstance(params, dict):
        sys.stderr.write("params.json must be an object\n")
        return 2

    in_dir = os.path.join(jobroot, "in")
    out_dir = os.path.join(jobroot, "out")
    tmp_dir = os.path.join(jobroot, "tmp")
    for d in (out_dir, tmp_dir):
        os.makedirs(d, exist_ok=True)

    write_text(os.path.join(jobroot, "pid"), str(os.getpid()))
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    started = now()
    log(jobroot, f"runner start pid={os.getpid()} model={params.get('model')} "
                 f"pkg={params.get('pkg')}")

    if not ensure_ollama(jobroot, params):
        log(jobroot, "ollama is not reachable; the agent will fail on its first "
                     "LLM call (check ollama_bin/ollama_models in params.json)")

    # ---- capture proxy --------------------------------------------------
    proxy_py = params.get("proxy_script") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "gui_llm_proxy.py")
    port_file = os.path.join(jobroot, "proxy.port")
    io_path = os.path.join(jobroot, "llm-io.jsonl")
    live_path = os.path.join(jobroot, "live.json")
    upstream = params.get("upstream") or "http://127.0.0.1:11434/v1"
    proxy_log = open(os.path.join(jobroot, "proxy.log"), "ab", buffering=0)
    proxy = None
    proxy_port = 0
    try:
        proxy = subprocess.Popen(
            [sys.executable, proxy_py,
             "--upstream", upstream, "--io", io_path, "--live", live_path,
             "--port-file", port_file,
             "--read-timeout", str(params.get("llm_timeout_s") or 7200)],
            stdout=proxy_log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
        write_text(os.path.join(jobroot, "proxy.pid"), str(proxy.pid))
        for _ in range(300):
            txt = read_text(port_file)
            if txt.isdigit():
                proxy_port = int(txt)
                break
            if proxy.poll() is not None:
                break
            time.sleep(0.1)
    except Exception as exc:
        log(jobroot, f"proxy spawn failed: {type(exc).__name__}: {exc}")
    if not proxy_port:
        log(jobroot, "proxy did not write a port; aborting")
        if proxy is not None:
            kill_group(proxy.pid, signal.SIGKILL)
        write_atomic(os.path.join(jobroot, "exit"), {
            "rc": 90, "elapsed": round(now() - started, 1),
            "stopped": False, "timeout": False, "ended": now(),
            "error": "proxy did not start"})
        return 90
    log(jobroot, f"proxy ready on 127.0.0.1:{proxy_port} -> {upstream}")

    # ---- agent environment ---------------------------------------------
    pkg = params.get("pkg") or "/root/autodl-tmp/46939_hlsagent"
    vitis_bin = params.get("vitis_bin") or "/root/autodl-tmp/Xilinx/2025.2/Vitis/bin"
    vivado_bin = params.get("vivado_bin") or os.path.normpath(
        os.path.join(os.path.dirname(vitis_bin), "..", "Vivado", "bin"))
    compat = params.get("compat_lib") or \
        "/root/autodl-tmp/rag-hard-20261009/compat/lib/x86_64-linux-gnu"

    env = os.environ.copy()
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LLM_BACKEND": "openai",
        "LLM_BASE_URL": f"http://127.0.0.1:{proxy_port}/v1",
        "LLM_MODEL": str(params.get("model") or ""),
        "LLM_API_KEY": "ollama",
        "LLM_MAX_TOKENS": str(int(params.get("max_tokens") or 8192)),
        "LLM_TEMPERATURE": str(params.get("temperature", 0.0)),
        "LLM_TOP_P": str(params.get("top_p", 1.0)),
        "LLM_TIMEOUT_S": str(params.get("llm_timeout_s") or 1800),
        "LLM_STREAM": "1",
        "AGENT_MAX_ROUNDS": str(int(params.get("max_rounds") or 4)),
        "AGENT_DEADLINE_S": "0",
        "AGENT_TMP": tmp_dir,
        "AGENT_CSYNTH": str(params.get("csynth") or "auto"),
        "AGENT_AUDIT": str(params.get("audit") or "on"),
        "AGENT_SKILLS": str(params.get("skills") or "on"),
        "HLS_PART": str(params.get("part") or "xczu3eg-sbva484-1-e"),
        "HLS_PERIOD_NS": str(params.get("period_ns") or "5"),
        "TRACK": "hls",
    })
    extra = str(params.get("extra_body") or "").strip()
    if extra:
        env["LLM_EXTRA_BODY"] = extra
    if os.path.isdir(vitis_bin):
        env["PATH"] = vitis_bin + os.pathsep + env.get("PATH", "")
    if os.path.isdir(vivado_bin):
        env["PATH"] = vivado_bin + os.pathsep + env.get("PATH", "")
    if os.path.isdir(compat):
        env["LD_LIBRARY_PATH"] = compat + os.pathsep + env.get("LD_LIBRARY_PATH", "")

    cmd = [sys.executable, "-m", "agent.main",
           "--input", in_dir, "--output", out_dir]
    top = str(params.get("top") or "").strip()
    if top:
        cmd += ["--top", top]
    log(jobroot, "cmd=" + " ".join(shlex.quote(c) for c in cmd) + f" cwd={pkg}")

    agent = None
    rc = None
    timed_out = False
    stopped = False
    try:
        agent_log = open(os.path.join(jobroot, "log.txt"), "ab", buffering=0)
        agent = subprocess.Popen(cmd, cwd=pkg, env=env,
                                 stdout=agent_log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        write_text(os.path.join(jobroot, "agent.pid"), str(agent.pid))
        log(jobroot, f"agent pid={agent.pid}")
    except Exception as exc:
        rc = 91
        log(jobroot, f"agent spawn failed: {type(exc).__name__}: {exc}")

    total = float(params.get("total_timeout_s") or 0)
    deadline = started + total if total > 0 else None

    if agent is not None:
        while True:
            code = agent.poll()
            if code is not None:
                rc = code
                break
            if STOP["flag"]:
                stopped = True
                break
            if deadline is not None and now() > deadline:
                timed_out = True
                break
            time.sleep(0.5)
        if stopped or timed_out:
            log(jobroot, "stopping agent" + (" (timeout)" if timed_out else ""))
            kill_group(agent.pid, signal.SIGTERM)
            for _ in range(80):
                if agent.poll() is not None:
                    break
                time.sleep(0.1)
            if agent.poll() is None:
                log(jobroot, "agent did not exit on SIGTERM; SIGKILL")
                kill_group(agent.pid, signal.SIGKILL)
            try:
                rc = agent.wait(timeout=20)
            except subprocess.TimeoutExpired:
                rc = -9
            if timed_out:
                rc = -15

    # ---- wrap up --------------------------------------------------------
    if proxy is not None:
        kill_group(proxy.pid, signal.SIGTERM)
        for _ in range(30):
            if proxy.poll() is not None:
                break
            time.sleep(0.1)
        if proxy.poll() is None:
            kill_group(proxy.pid, signal.SIGKILL)
    try:
        proxy_log.close()
    except Exception:
        pass

    for name in ("solution.cpp", "trace.jsonl"):
        fp = os.path.join(out_dir, name)
        if not os.path.exists(fp):
            try:
                with open(fp, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write("")
            except OSError:
                pass

    elapsed = round(now() - started, 1)
    log(jobroot, f"exit rc={rc} elapsed={elapsed}s"
                 + (" timeout" if timed_out else "")
                 + (" stopped" if stopped else ""))
    write_atomic(os.path.join(jobroot, "exit"), {
        "rc": rc,
        "elapsed": elapsed,
        "stopped": bool(stopped or STOP["flag"]),
        "timeout": bool(timed_out),
        "ended": now(),
        "agent_pid": agent.pid if agent is not None else None,
        "proxy_port": proxy_port,
        "error": "",
    })
    return int(rc) if rc is not None else -1


if __name__ == "__main__":
    raise SystemExit(main())

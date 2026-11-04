#!/usr/bin/env python3
"""HLS Agent GUI — 本地选题、驱动智能体、分栏显示过程与代码。

只依赖 Python 标准库 + requests。默认只监听 127.0.0.1。

结构
----
* 每个作业一个目录 jobs/<id>/{in,out,tmp,log.txt,llm-io.jsonl,meta.json}
* 每个作业起一个仅本机可见的 LLM 反向代理（127.0.0.1:0）。代理只做三件事：
    1. 原样转发请求到用户填的上游（OpenAI 兼容，默认本机 Ollama）；
    2. 把流式 SSE 原样转回给 agent（不改变任何语义）；
    3. 旁路记录 content / reasoning，写进 llm-io.jsonl 供界面展示。
  代理从不记录、也不落盘 API key。
* GUI 通过子进程跑 `python -m agent.main --input ... --output ...`，
  包目录只读使用（PYTHONDONTWRITEBYTECODE=1，AGENT_TMP 指向作业目录）。
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

import iface_gen
import remote_backend

# 本机端点（Ollama 等）必须绕过系统代理；远端端点仍走用户的 HTTP(S)_PROXY。
for _var in ("NO_PROXY", "no_proxy"):
    _cur = os.environ.get(_var, "")
    _parts = [p.strip() for p in _cur.split(",") if p.strip()]
    for _host in ("127.0.0.1", "localhost", "::1"):
        if _host not in _parts:
            _parts.append(_host)
    os.environ[_var] = ",".join(_parts)

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DEFAULT = r"B:\46939_hlsagent"
DATASET_DEFAULT = r"B:\fpga2026-agent\dataset\hls-eval-tasks"
VITIS_BIN = r"B:\Vivado2025\2025.2\Vitis\bin"

JOB_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
TASK_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")

MAX_BODY = 4 << 20  # 4 MiB

JOBS: dict[str, "Job"] = {}
JOBS_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def now() -> float:
    return time.time()


def read_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------
# 从 interface.txt 还原 solution.cpp 引用的头文件（导出用；不碰 agent 包）
#
# 模型写 `#include "<foo>.h"`；agent 在**临时工作目录**里用 main.py::split_interface
# 从 interface.txt 还原同名头文件后再编译，所以自检能过。但这份头文件不随
# solution.cpp 交付、跑完就随临时目录删掉 —— 单独把 solution.cpp 拿去编译就会
# 报 `bubble_sort.h: No such file or directory`。这里按包内同一口径复刻，
# 把还原出的头文件落到作业 out/ 里，供与 solution.cpp 同目录编译。
# 口径以 B:\46939_hlsagent\agent\main.py::split_interface 为准（逐字节核对过
# 官方题 c2hlsc__add_round_key：还原结果与真实 add_round_key.h 完全相同）。
# --------------------------------------------------------------------------
_HDR_NAME = re.compile(r"([A-Za-z0-9_][\w.\-]*\.(?:h|hpp))")
_HDR_GUARD = re.compile(r"#ifndef\s+([A-Za-z_]\w*?)_+H\b")


def split_interface(interface: str) -> dict[str, str]:
    """与 agent/main.py::split_interface 同口径；改一边必须同步另一边。"""
    if not interface.strip():
        return {}
    lines = interface.splitlines()
    name, body = None, lines
    if lines[0].lstrip().startswith("//"):
        m = _HDR_NAME.search(lines[0])
        if m:
            name, body = m.group(1), lines[1:]
    if name is None:
        m = _HDR_GUARD.search(interface)
        if m:
            name = m.group(1).lower() + ".h"
    text = "\n".join(body).strip("\n")
    if name is None or not text.strip():
        return {}
    return {name: text + "\n"}


def write_headers(job: "Job", interface: str | None = None) -> dict[str, str]:
    """把 interface.txt 还原出的头文件写进 out/（与 solution.cpp 同目录）。

    interface 为 None 时读 in/interface.txt。内容相同就不写（保住 mtime）。
    """
    if interface is None:
        try:
            with open(os.path.join(job.in_dir, "interface.txt"), "r",
                      encoding="utf-8", errors="replace") as fh:
                interface = fh.read()
        except OSError:
            return {}
    headers = split_interface(interface or "")
    if not headers:
        return {}
    try:
        os.makedirs(job.out_dir, exist_ok=True)
    except OSError:
        return headers
    for name, body in headers.items():
        fn = os.path.basename(name)
        if not fn or fn in (".", ".."):
            continue
        fp = os.path.join(job.out_dir, fn)
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                if fh.read() == body:
                    continue
        except OSError:
            pass
        try:
            tmp = fp + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
            os.replace(tmp, fp)
        except OSError:
            pass
    return headers


# --------------------------------------------------------------------------
# 从 llm-io.jsonl 还原模型自写的测试台（导出用；不碰 agent 包）
#
# agent 只在**临时目录**里写 agent_tb.cpp，跑完就 `_cleanup()` 删掉，GUI 也从不
# 下载它。模型原始回复里的 Block 2 是唯一可还原的来源。抽取规则按 agent 的
# `extract_blocks` 结构判据复刻（含连开围栏的退让），并以 trace 的
# `extract.tb_sha16` 为对照尺挑选 —— 对得上就是**逐字节**同一份，对不上才退回
# 「含 main 的最长块」，返回值里如实标注 exact=false。
# --------------------------------------------------------------------------
_TB_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+.#-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_TB_FENCE_LINE = re.compile(r"^\s*```")
_TB_MAIN_LINE = re.compile(r"^[ \t]*(?:static\s+)?(?:int|void)\s+main\s*\(", re.M)
_TB_MAIN_ANY = re.compile(r"\b(?:int|void)\s+main\s*\(")
_TB_CODEISH = re.compile(r"[;{}#()]")


def sha16(text: str | None) -> str | None:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16] if text else None


def _fence_segments(text: str) -> list[str]:
    """按围栏行切段，围栏行本身不进入任何段（与 agent/llm.py 同口径）。"""
    lines = text.splitlines()
    cuts = [i for i, ln in enumerate(lines) if _TB_FENCE_LINE.match(ln)]
    out, start = [], 0
    for i in cuts:
        out.append("\n".join(lines[start:i]).strip())
        start = i + 1
    out.append("\n".join(lines[start:]).strip())
    return out


def _match_brace(code: str, i: int) -> int:
    depth, j, quote = 0, i, ""
    while j < len(code):
        c = code[j]
        if quote:
            if c == "\\":
                j += 2
                continue
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "/" and code[j:j + 2] == "//":
            j = code.find("\n", j)
            if j < 0:
                return -1
            continue
        elif c == "/" and code[j:j + 2] == "/*":
            j = code.find("*/", j + 2)
            if j < 0:
                return -1
            j += 2
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def _split_main(code: str) -> tuple[str, str]:
    """一块里同时含 kernel 与 main 时，把 main 那段切出来当测试台。"""
    m = _TB_MAIN_LINE.search(code)
    if not m:
        return code, ""
    i = code.find("{", m.end())
    if i < 0:
        return code, ""
    end = _match_brace(code, i)
    if end < 0:
        return code, ""
    seps = [x.end() for x in re.finditer(r"[};]|^[ \t]*#[^\n]*$", code[:m.start()], re.M)]
    cut = seps[-1] if seps else 0
    return (code[:cut] + code[end:]).strip() + "\n", code[cut:end].strip() + "\n"


def _tb_candidates(text: str, top: str) -> list[str]:
    """模型回复 → 可能是测试台的候选串（保序去重）。"""
    cands: list[str] = []
    for _, body in _TB_FENCE.findall(text):
        body = body.strip()
        if body and _TB_CODEISH.search(body):
            cands.append(body)

    pat = re.compile(r"\b%s\s*\(" % re.escape(top)) if top else None
    for body in _fence_segments(text):
        if not body or not _TB_CODEISH.search(body):
            continue
        if "#include" not in body and not (pat and pat.search(body)):
            continue
        cands.append(body)

    # 围栏没闭合（撞 max_tokens）：取最后一条围栏行之后的全部内容
    lines = text.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            idx = i
    if idx is not None:
        tail = "\n".join(lines[idx + 1:]).strip()
        if tail:
            cands.append(tail)

    out, seen = [], set()
    for c in cands:
        for v in (c, _split_main(c)[1].strip()):
            if v and v not in seen:
                seen.add(v)
                out.append(v)
    return out


def extract_testbench(job: "Job") -> dict:
    """找出该作业的 agent 真正用过的那份自写测试台。"""
    top = ""
    try:
        with open(os.path.join(job.in_dir, "top.txt"), "r", encoding="utf-8",
                  errors="replace") as fh:
            top = fh.read().strip()
    except OSError:
        pass

    trace = read_jsonl(os.path.join(job.out_dir, "trace.jsonl"))
    extracts = [r for r in trace if r.get("tool") == "extract" and r.get("tb_sha16")]

    sol_sha = ""
    try:
        with open(os.path.join(job.out_dir, "solution.cpp"), "r", encoding="utf-8",
                  errors="replace") as fh:
            sol_sha = sha16(fh.read()) or ""
    except OSError:
        pass

    target = None
    for r in reversed(extracts):
        if sol_sha and r.get("kernel_sha16") == sol_sha:
            target = r
            break
    if target is None and extracts:
        target = extracts[-1]

    records = [r for r in read_jsonl(job.io_path) if (r.get("content") or "").strip()]
    if target and target.get("round") is not None:
        same = [r for r in records if r.get("round") == target.get("round")]
        if same:
            records = same
    if not records:
        return {"error": "这个作业还没有模型回复，取不到 testbench"}

    want = (target or {}).get("tb_sha16") or ""
    guess: tuple[str, object] | None = None
    for rec in records:
        for cand in _tb_candidates(rec.get("content") or "", top):
            if want:
                for form in (cand, cand + "\n"):
                    if sha16(form) == want:
                        return {"testbench": form, "bytes": len(form.encode("utf-8")),
                                "round": rec.get("round"), "tb_sha16": want,
                                "exact": True, "source": "llm-io.jsonl"}
            if _TB_MAIN_ANY.search(cand):
                if guess is None or len(cand) > len(guess[0]):
                    guess = (cand, rec.get("round"))
    if guess:
        cand, rnd = guess
        return {"testbench": cand, "bytes": len(cand.encode("utf-8")),
                "round": rnd, "tb_sha16": sha16(cand),
                "exact": False, "source": "llm-io.jsonl",
                "note": "没能和 trace 的 tb_sha16 对上，按「含 main 的最长块」取的"}
    return {"error": "模型回复里没有找到含 main 的测试台块"}


def tail_text(path: str, limit: int = 14000) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(-limit, os.SEEK_END)
            raw = fh.read()
        return raw.decode("utf-8", "replace")
    except OSError:
        return ""


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=20,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def ollama_models(base_url: str) -> list[dict]:
    """尽力从 Ollama 原生接口取模型清单；失败返回空表，不影响使用。"""
    parsed = urllib.parse.urlparse(base_url)
    if not parsed.hostname:
        return []
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    url = f"http://{parsed.hostname}:{port}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data.get("models") or []
    except Exception:
        return []


# --------------------------------------------------------------------------
# LLM 抓包代理
# --------------------------------------------------------------------------
class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # 每个响应后关闭；SSE 正需要这个
    server_version = "HLSAgentGUI-Proxy/1.0"

    def log_message(self, fmt, *args):  # 静音
        pass

    # -- 转发 ------------------------------------------------------------
    def do_POST(self):
        job: Job = self.server.job  # type: ignore[attr-defined]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._plain(413, b'{"error":{"message":"bad content length"}}')
            return
        raw = self.rfile.read(length)
        try:
            req = json.loads(raw)
        except Exception:
            req = {}

        seq = job.begin_call(req)
        upstream = job.upstream_url(self.path)
        headers = {"Content-Type": "application/json"}
        if job.api_key:
            headers["Authorization"] = "Bearer " + job.api_key

        t0 = now()
        try:
            resp = requests.post(
                upstream,
                data=raw,
                headers=headers,
                stream=True,
                timeout=(15, max(60.0, job.llm_timeout_s + 120.0)),
            )
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            job.end_call(seq, "", "", {}, "", t0, error=msg)
            body = json.dumps({"error": {"message": msg}}).encode("utf-8")
            self._plain(502, body)
            return

        ctype = resp.headers.get("Content-Type", "")
        if resp.status_code != 200:
            body = resp.content
            job.end_call(
                seq, "", "", {}, "", t0,
                error=body[:2000].decode("utf-8", "replace"),
                status=resp.status_code,
            )
            try:
                self.send_response(resp.status_code)
                self.send_header("Content-Type", ctype or "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                resp.close()
            return

        if "text/event-stream" in ctype:
            self._relay_sse(job, seq, resp, t0)
        else:
            self._relay_json(job, seq, req, resp, t0)

    # -- SSE 原样转发 + 旁路解析 -----------------------------------------
    def _relay_sse(self, job: "Job", seq: int, resp, t0: float):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            resp.close()
            job.end_call(seq, "", "", {}, "", t0, error="client disconnected before headers")
            return

        content: list[str] = []
        reasoning: list[str] = []
        usage: dict = {}
        finish = ""
        client_gone = False
        try:
            for line in resp.iter_lines(decode_unicode=False):
                if line is None:
                    continue
                try:
                    self.wfile.write(line + b"\n")
                    if not line:
                        self.wfile.write(b"\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    client_gone = True
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text.startswith("data:"):
                    continue
                data = text[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj.get("usage"), dict):
                    usage = obj["usage"]
                for choice in obj.get("choices") or []:
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
                    delta = choice.get("delta") or choice.get("message") or {}
                    if delta.get("content"):
                        content.append(delta["content"])
                    think = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if think:
                        reasoning.append(think)
                    job.update_live(seq, "".join(content), "".join(reasoning))
        except Exception as exc:
            job.note_proxy_error(seq, f"{type(exc).__name__}: {exc}")
        finally:
            resp.close()
            job.end_call(
                seq, "".join(content), "".join(reasoning), usage, finish, t0,
                aborted=client_gone,
            )

    # -- 非流式：原样转发；若客户端要流式则合成 SSE ----------------------
    def _relay_json(self, job: "Job", seq: int, req: dict, resp, t0: float):
        try:
            body = resp.content
        finally:
            resp.close()
        ctype = resp.headers.get("Content-Type", "application/json")
        try:
            obj = json.loads(body)
        except Exception:
            obj = {}
        msg: dict = {}
        finish = ""
        usage: dict = {}
        try:
            choice = (obj.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            finish = choice.get("finish_reason") or ""
            usage = obj.get("usage") or {}
        except Exception:
            pass
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""

        wants_stream = bool(req.get("stream"))
        if wants_stream:
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                delta = {"role": "assistant", "content": content}
                if reasoning:
                    delta["reasoning"] = reasoning
                event = {
                    "id": obj.get("id", "chatcmpl-proxy"),
                    "object": "chat.completion.chunk",
                    "model": obj.get("model", req.get("model", "")),
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish or "stop"}],
                }
                if usage:
                    event["usage"] = usage
                self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            try:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        job.end_call(seq, content, reasoning, usage, finish, t0)

    def _plain(self, code: int, body: bytes):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, job: "Job"):
        self.job = job
        super().__init__(addr, ProxyHandler)


# --------------------------------------------------------------------------
# 作业
# --------------------------------------------------------------------------
class Job:
    def __init__(self, job_id: str, root: str, cfg: dict, pkg: str, api_key: str,
                 llm_timeout_s: float):
        self.id = job_id
        self.root = root
        self.cfg = cfg
        self.pkg = pkg
        self.api_key = api_key  # 只在内存里，不落盘
        self.ssh_password = ""  # 远端模式：只在内存里，不落盘
        self.llm_timeout_s = llm_timeout_s
        self.backend = str(cfg.get("backend") or "local")

        self.in_dir = os.path.join(root, "in")
        self.out_dir = os.path.join(root, "out")
        self.tmp_dir = os.path.join(root, "tmp")
        self.log_path = os.path.join(root, "log.txt")
        self.io_path = os.path.join(root, "llm-io.jsonl")
        self.meta_path = os.path.join(root, "meta.json")

        self.lock = threading.RLock()
        self.state = "starting"
        self.started = now()
        self.ended: float | None = None
        self.exit_code: int | None = None
        self.stop_requested = False
        self.timeout_hit = False
        self.proc: subprocess.Popen | None = None
        self.proxy: ProxyServer | None = None
        self.proxy_port: int | None = None
        self.proxy_error = ""

        self.calls: list[dict] = []
        self.live: dict | None = None
        self._seq = 0
        self._call_lock = threading.RLock()

        self.model = str(cfg.get("model") or "")
        self.base_url = str(cfg.get("base_url") or "")
        self.max_rounds = int(cfg.get("max_rounds") or 0)
        self.deadline_s = float(cfg.get("deadline_s") or 0)
        self.total_timeout_s = float(cfg.get("total_timeout_s") or 0)

    # -- 代理侧记录 ------------------------------------------------------
    def _round_hint(self) -> tuple[int | None, int]:
        """从 trace 最后一个 prompt 记录推轮次；失败则返回 (None, 0)。"""
        events = read_jsonl(os.path.join(self.out_dir, "trace.jsonl"))
        last_round = None
        for rec in events:
            if rec.get("tool") == "prompt" and rec.get("round") is not None:
                last_round = int(rec["round"])
        if last_round is None:
            return None, 0
        seen = sum(1 for c in self.calls if c.get("round") == last_round)
        return last_round, seen + 1

    def begin_call(self, req: dict) -> int:
        with self._call_lock:
            self._seq += 1
            seq = self._seq
        round_no, attempt = self._round_hint()
        with self._call_lock:
            self.live = {
                "seq": seq,
                "round": round_no,
                "attempt": attempt,
                "model": str(req.get("model") or ""),
                "max_tokens": req.get("max_tokens"),
                "stream": bool(req.get("stream")),
                "started": now(),
                "updated": now(),
                "content": "",
                "reasoning": "",
                "chars": 0,
            }
        return seq

    def update_live(self, seq: int, content: str, reasoning: str) -> None:
        with self._call_lock:
            if not self.live or self.live.get("seq") != seq:
                return
            t = now()
            # 界面 800 ms 轮询一次，没必要每个 token 都拼接整串
            if t - float(self.live.get("_pushed") or 0) < 0.08:
                return
            self.live["_pushed"] = t
            self.live["content"] = content
            self.live["reasoning"] = reasoning
            self.live["chars"] = len(content) + len(reasoning)
            self.live["updated"] = t

    def note_proxy_error(self, seq: int, msg: str) -> None:
        with self._call_lock:
            self.proxy_error = msg

    def end_call(self, seq: int, content: str, reasoning: str, usage: dict,
                 finish: str, t0: float, error: str = "", status: int | None = None,
                 aborted: bool = False) -> None:
        with self._call_lock:
            live = self.live if self.live and self.live.get("seq") == seq else {}
            rec = {
                "seq": seq,
                "round": live.get("round"),
                "attempt": live.get("attempt"),
                "model": live.get("model") or self.model,
                "max_tokens": live.get("max_tokens"),
                "stream": live.get("stream"),
                "started": t0,
                "ended": now(),
                "elapsed_s": round(now() - t0, 2),
                "content": content,
                "reasoning": reasoning,
                "usage": usage,
                "finish_reason": finish,
                "aborted": aborted,
            }
            if status is not None:
                rec["status"] = status
            if error:
                rec["error"] = error
            self.calls.append(rec)
            if self.live and self.live.get("seq") == seq:
                self.live = None
            try:
                with open(self.io_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError:
                pass

    # -- 上游地址 --------------------------------------------------------
    def upstream_url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        if path.startswith("/v1/"):
            return base + path[3:]
        if path == "/v1":
            return base
        return base + path

    # -- 生命周期 --------------------------------------------------------
    def request_stop(self) -> None:
        self.stop_requested = True
        if self.proc and self.proc.poll() is None:
            kill_tree(self.proc.pid)

    def snapshot(self, trace_since: int, calls_since: int, sol_key: str) -> dict:
        trace = read_jsonl(os.path.join(self.out_dir, "trace.jsonl"))
        with self._call_lock:
            calls = list(self.calls)
            live = dict(self.live) if self.live else None

        sol_path = os.path.join(self.out_dir, "solution.cpp")
        solution = None
        sol_sig = ""
        try:
            st = os.stat(sol_path)
            sol_sig = f"{st.st_mtime_ns}:{st.st_size}"
            if sol_sig != sol_key:
                with open(sol_path, "r", encoding="utf-8", errors="replace") as fh:
                    solution = fh.read()
        except OSError:
            pass

        error = ""
        for rec in trace:
            if rec.get("tool") == "agent" and rec.get("event") == "error":
                error = str(rec.get("excerpt") or rec.get("error") or "agent error")

        with self.lock:
            return {
                "id": self.id,
                "state": self.state,
                "backend": self.backend,
                "ssh_host": str((self.cfg.get("ssh") or {}).get("host") or ""),
                "remote_pkg": str(self.cfg.get("remote_pkg") or ""),
                "started": self.started,
                "ended": self.ended,
                "elapsed": round((self.ended or now()) - self.started, 1),
                "exit_code": self.exit_code,
                "stop_requested": self.stop_requested,
                "timeout_hit": self.timeout_hit,
                "model": self.model,
                "base_url": self.base_url,
                "max_rounds": self.max_rounds,
                "deadline_s": self.deadline_s,
                "total_timeout_s": self.total_timeout_s,
                "proxy_port": self.proxy_port,
                "proxy_error": self.proxy_error,
                "trace_total": len(trace),
                "trace": trace[trace_since:] if trace_since < len(trace) else [],
                "calls_total": len(calls),
                "calls": calls[calls_since:] if calls_since < len(calls) else [],
                "live": live,
                "solution": solution,
                "solution_bytes": len(solution.encode("utf-8")) if solution is not None else None,
                "solution_key": sol_sig,
                "log_tail": tail_text(self.log_path),
                "agent_error": error,
            }


# --------------------------------------------------------------------------
# 作业历史：服务重启后仍能打开盘上的旧作业
# --------------------------------------------------------------------------
def infer_job_state(root: str) -> str:
    """给没有落 state 的旧作业推断一个终态（新作业由 persist_job_state 写）。"""
    trace = read_jsonl(os.path.join(root, "out", "trace.jsonl"))
    for e in trace:
        if e.get("tool") == "agent" and e.get("event") == "error":
            return "failed"
    if any(e.get("tool") == "agent" and e.get("event") == "done" for e in trace):
        return "done"
    try:
        with open(os.path.join(root, "log.txt"), "r", encoding="utf-8", errors="replace") as fh:
            m = re.search(r"\[gui\] exit=(-?\d+)", fh.read())
    except OSError:
        m = None
    if m:
        return "done" if int(m.group(1)) == 0 else "failed"
    return "stopped" if trace else "failed"


def persist_job_state(job: "Job") -> None:
    """把终态写回 meta.json（只增字段，不动用户输入）。"""
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


def load_existing_jobs(jobs_dir: str, pkg: str) -> int:
    """登记 jobs_dir 下已有的作业目录；新进程里它们也能被界面打开。"""
    try:
        names = sorted(os.listdir(jobs_dir))
    except OSError:
        return 0
    loaded = 0
    for name in names:
        if not JOB_ID_RE.match(name):
            continue
        root = os.path.join(jobs_dir, name)
        if not os.path.isdir(root):
            continue
        try:
            with open(os.path.join(root, "meta.json"), "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(cfg, dict):
            continue
        job = Job(name, root, cfg, str(cfg.get("pkg") or pkg), "",
                  float(cfg.get("llm_timeout_s") or 900))
        try:
            job.started = float(cfg.get("created") or os.path.getmtime(root))
        except (TypeError, ValueError, OSError):
            pass
        job.state = str(cfg.get("state") or infer_job_state(root))
        try:
            job.ended = float(cfg["ended"]) if cfg.get("ended") is not None else None
        except (TypeError, ValueError):
            job.ended = None
        if job.ended is None:
            for rel in ("log.txt", "out/trace.jsonl", "meta.json"):
                try:
                    job.ended = os.path.getmtime(os.path.join(root, rel))
                    break
                except OSError:
                    continue
        job.exit_code = cfg.get("exit_code")
        job.stop_requested = bool(cfg.get("stop_requested"))
        job.timeout_hit = bool(cfg.get("timeout_hit"))
        calls = [r for r in read_jsonl(job.io_path) if isinstance(r, dict)]
        calls.sort(key=lambda r: r.get("seq") or 0)
        job.calls = calls
        job._seq = max([int(r.get("seq") or 0) for r in calls] or [0])
        with JOBS_LOCK:
            JOBS[name] = job
        loaded += 1
    return loaded


# --------------------------------------------------------------------------
# 作业启动
# --------------------------------------------------------------------------
def launch_job_safe(job: Job, cfg: dict, ssh_password: str = "") -> None:
    try:
        os.makedirs(job.in_dir, exist_ok=True)
        os.makedirs(job.out_dir, exist_ok=True)
        write_headers(job, str(cfg.get("interface") or ""))
    except OSError:
        pass
    try:
        if job.backend == "remote":
            remote_backend.launch_remote(job, cfg, ssh_password)
        else:
            launch_job(job, cfg)
    except Exception as exc:
        traceback.print_exc()
        with job.lock:
            if job.state in ("starting", "running"):
                job.state = "failed"
            job.ended = now()
            job.proxy_error = f"{type(exc).__name__}: {exc}"


def launch_job(job: Job, cfg: dict) -> None:
    os.makedirs(job.in_dir, exist_ok=True)
    os.makedirs(job.out_dir, exist_ok=True)
    os.makedirs(job.tmp_dir, exist_ok=True)

    for name in ("prompt.txt", "interface.txt", "top.txt"):
        text = str(cfg.get(name[:-4]) or "")
        with open(os.path.join(job.in_dir, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    meta = {k: v for k, v in cfg.items() if k != "api_key"}
    meta.update({"id": job.id, "created": job.started, "pkg": job.pkg})
    with open(job.meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)

    # 代理先起，再拉 agent
    proxy = ProxyServer(("127.0.0.1", 0), job)
    job.proxy = proxy
    job.proxy_port = proxy.server_address[1]
    threading.Thread(target=proxy.serve_forever, daemon=True,
                     name=f"proxy-{job.id}").start()

    env = os.environ.copy()
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LLM_BACKEND": "openai",
        "LLM_BASE_URL": f"http://127.0.0.1:{job.proxy_port}/v1",
        "LLM_MODEL": str(cfg.get("model") or ""),
        "LLM_API_KEY": "",
        "LLM_MAX_TOKENS": str(int(cfg.get("max_tokens") or 8192)),
        "LLM_TEMPERATURE": str(cfg.get("temperature") if cfg.get("temperature") is not None else 0.0),
        "LLM_TOP_P": str(cfg.get("top_p") if cfg.get("top_p") is not None else 1.0),
        "LLM_TIMEOUT_S": str(cfg.get("llm_timeout_s") or 1800),
        "LLM_STREAM": "1",
        "AGENT_MAX_ROUNDS": str(int(cfg.get("max_rounds") or 4)),
        "AGENT_DEADLINE_S": str(cfg.get("deadline_s") or 0),
        "AGENT_TMP": job.tmp_dir,
        "AGENT_CSYNTH": str(cfg.get("csynth") or "auto"),
        "AGENT_AUDIT": str(cfg.get("audit") or "on"),
        "AGENT_SKILLS": str(cfg.get("skills") or "on"),
        "HLS_PART": str(cfg.get("part") or "xczu3eg-sbva484-1-e"),
        "HLS_PERIOD_NS": str(cfg.get("period_ns") or "5"),
    })
    if shutil.which("vitis-run") is None and os.path.isdir(VITIS_BIN):
        env["PATH"] = VITIS_BIN + os.pathsep + env.get("PATH", "")

    cmd = [sys.executable, "-m", "agent.main",
           "--input", job.in_dir, "--output", job.out_dir]
    if str(cfg.get("top") or "").strip():
        cmd += ["--top", str(cfg["top"]).strip()]

    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    log = open(job.log_path, "ab", buffering=0)
    try:
        job.proc = subprocess.Popen(
            cmd, cwd=job.pkg, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    except Exception as exc:
        with job.lock:
            job.state = "failed"
            job.ended = now()
            job.exit_code = -1
            job.proxy_error = f"spawn failed: {type(exc).__name__}: {exc}"
        log.write((job.proxy_error + "\n").encode("utf-8", "replace"))
        log.close()
        try:
            proxy.shutdown()
            proxy.server_close()
        except Exception:
            pass
        return

    with job.lock:
        job.state = "running"
    log.write(f"[gui] pid={job.proc.pid} cmd={' '.join(cmd)} cwd={job.pkg}\n".encode("utf-8", "replace"))

    total = float(cfg.get("total_timeout_s") or 0)
    hard_deadline = now() + total if total > 0 else None

    while True:
        try:
            rc = job.proc.wait(timeout=1.0)
            break
        except subprocess.TimeoutExpired:
            if hard_deadline and now() > hard_deadline:
                with job.lock:
                    job.timeout_hit = True
                kill_tree(job.proc.pid)
                try:
                    rc = job.proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    rc = -9
                break

    try:
        log.write(f"[gui] exit={rc} elapsed={now()-job.started:.1f}s\n".encode("utf-8", "replace"))
        log.close()
    except Exception:
        pass

    # 兜底：任何路径下都保证有 solution.cpp 可展示
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
        if job.stop_requested:
            job.state = "stopped"
        elif job.timeout_hit:
            job.state = "timeout"
        elif rc == 0:
            job.state = "done"
        else:
            job.state = "failed"
        persist_job_state(job)

    try:
        proxy.shutdown()
        proxy.server_close()
    except Exception:
        pass


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
class ApiHandler(BaseHTTPRequestHandler):
    server_version = "HLSAgentGUI/1.0"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        # 只把错误打到控制台，轮询请求不刷屏
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers ---------------------------------------------------------
    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except Exception:
            return None

    def _job(self, job_id: str) -> Job | None:
        with JOBS_LOCK:
            return JOBS.get(job_id)

    # -- GET -------------------------------------------------------------
    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                self._static("ui.html", "text/html; charset=utf-8")
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if path == "/api/health":
                self._json(200, {"ok": True, "time": now()})
                return
            if path == "/api/config":
                self._api_config()
                return
            if path == "/api/tasks":
                self._api_tasks()
                return
            if path.startswith("/api/tasks/"):
                self._api_task(path[len("/api/tasks/"):])
                return
            if path == "/api/jobs":
                with JOBS_LOCK:
                    rows = [{"id": j.id, "state": j.state, "started": j.started,
                             "model": j.model} for j in JOBS.values()]
                rows.sort(key=lambda r: r["started"], reverse=True)
                self._json(200, {"jobs": rows[:30]})
                return
            if path.startswith("/api/jobs/"):
                self._api_job(path, qs)
                return
            self._json(404, {"error": "not found"})
        except Exception as exc:
            traceback.print_exc()
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _static(self, name: str, ctype: str):
        fp = os.path.join(HERE, name)
        try:
            with open(fp, "rb") as fh:
                body = fh.read()
        except OSError:
            self._json(500, {"error": f"missing {name}"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api_config(self):
        pkg = self.server.pkg  # type: ignore[attr-defined]
        dataset = self.server.dataset  # type: ignore[attr-defined]
        base_url = self.server.default_base_url  # type: ignore[attr-defined]
        models = ollama_models(base_url)
        names = [m.get("name") for m in models if m.get("name")]
        default_model = ""
        for cand in ("qwen3-8k:latest", "qwen3:8b", "qwen2.5-coder:7b"):
            if cand in names:
                default_model = cand
                break
        if not default_model and names:
            default_model = names[0]
        self._json(200, {
            "pkg": pkg,
            "pkg_exists": os.path.isdir(os.path.join(pkg, "agent")),
            "dataset": dataset,
            "dataset_exists": os.path.isdir(dataset),
            "vitis": shutil.which("vitis-run") or "",
            "vitis_bin_exists": os.path.isdir(VITIS_BIN),
            "default_base_url": base_url,
            "models": names,
            "default_model": default_model,
            "python": sys.executable,
            "jobs_dir": self.server.jobs_dir,  # type: ignore[attr-defined]
            "paramiko": remote_backend.PARAMIKO_VERSION,
            "remote_defaults": remote_backend.defaults(),
        })

    def _api_tasks(self):
        dataset = self.server.dataset  # type: ignore[attr-defined]
        rows = []
        try:
            for name in sorted(os.listdir(dataset)):
                d = os.path.join(dataset, name)
                if not os.path.isdir(d) or name.startswith("."):
                    continue
                if os.path.isfile(os.path.join(d, "prompt.txt")):
                    rows.append(name)
        except OSError:
            pass
        self._json(200, {"tasks": rows})

    def _api_task(self, name_enc: str):
        dataset = self.server.dataset  # type: ignore[attr-defined]
        name = urllib.parse.unquote(name_enc)
        if not TASK_RE.match(name):
            self._json(400, {"error": "bad task name"})
            return
        base = os.path.realpath(dataset)
        d = os.path.realpath(os.path.join(base, name))
        if not (d == base or d.startswith(base + os.sep)):
            self._json(400, {"error": "bad task path"})
            return
        if not os.path.isdir(d):
            self._json(404, {"error": "no such task"})
            return
        out = {"name": name, "prompt": "", "interface": "", "top": ""}
        for key, fn in (("prompt", "prompt.txt"), ("interface", "interface.txt"), ("top", "top.txt")):
            fp = os.path.join(d, fn)
            if os.path.isfile(fp):
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        out[key] = fh.read()
                except OSError:
                    pass
        self._json(200, out)

    def _api_job(self, path: str, qs: dict):
        rest = path[len("/api/jobs/"):].strip("/")
        parts = rest.split("/")
        job_id = parts[0]
        if not JOB_ID_RE.match(job_id):
            self._json(400, {"error": "bad job id"})
            return
        job = self._job(job_id)
        if not job:
            self._json(404, {"error": "no such job"})
            return

        if len(parts) >= 2:
            what = parts[1]
            if what == "solution":
                fp = os.path.join(job.out_dir, "solution.cpp")
                self._send_file(fp, "text/x-c++src; charset=utf-8", "solution.cpp")
                return
            if what == "header":
                headers = write_headers(job)
                if not headers:
                    self._json(404, {"error": "这个作业的 interface 里没有头文件"})
                else:
                    name, content = next(iter(headers.items()))
                    self._json(200, {
                        "name": os.path.basename(name),
                        "content": content,
                        "bytes": len(content.encode("utf-8")),
                        "headers": [os.path.basename(n) for n in headers],
                    })
                return
            if what == "testbench":
                doc = extract_testbench(job)
                if not doc.get("testbench"):
                    self._json(404, {"error": doc.get("error") or "没有可导出的 testbench"})
                else:
                    self._json(200, doc)
                return
            if what == "trace":
                fp = os.path.join(job.out_dir, "trace.jsonl")
                self._send_file(fp, "application/x-ndjson; charset=utf-8", "trace.jsonl")
                return
            if what == "log":
                fp = job.log_path
                self._send_file(fp, "text/plain; charset=utf-8", "log.txt")
                return
            if what == "llm":
                fp = job.io_path
                self._send_file(fp, "application/x-ndjson; charset=utf-8", "llm-io.jsonl")
                return
            if what == "meta":
                fp = job.meta_path
                self._send_file(fp, "application/json; charset=utf-8", "meta.json")
                return
            self._json(404, {"error": "not found"})
            return

        try:
            trace_since = max(0, int(qs.get("trace_since", ["0"])[0]))
        except ValueError:
            trace_since = 0
        try:
            calls_since = max(0, int(qs.get("calls_since", ["0"])[0]))
        except ValueError:
            calls_since = 0
        sol_key = qs.get("sol_key", [""])[0]
        self._json(200, job.snapshot(trace_since, calls_since, sol_key))

    def _send_file(self, fp: str, ctype: str, filename: str):
        try:
            with open(fp, "rb") as fh:
                body = fh.read()
        except OSError:
            self._json(404, {"error": "missing file"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'inline; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- POST ------------------------------------------------------------
    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/api/jobs":
                self._create_job()
                return
            if path == "/api/remote/probe":
                self._remote_probe()
                return
            if path == "/api/interface":
                self._gen_interface()
                return
            if path.startswith("/api/jobs/") and path.endswith("/stop"):
                job_id = path[len("/api/jobs/"):-len("/stop")].strip("/")
                job = self._job(job_id) if JOB_ID_RE.match(job_id) else None
                if not job:
                    self._json(404, {"error": "no such job"})
                    return
                job.request_stop()
                self._json(200, {"ok": True, "state": job.state})
                return
            if path.startswith("/api/jobs/") and path.endswith("/open"):
                job_id = path[len("/api/jobs/"):-len("/open")].strip("/")
                job = self._job(job_id) if JOB_ID_RE.match(job_id) else None
                if not job:
                    self._json(404, {"error": "no such job"})
                    return
                if os.name == "nt":
                    os.startfile(job.root)  # type: ignore[attr-defined]
                self._json(200, {"ok": True, "path": job.root})
                return
            self._json(404, {"error": "not found"})
        except Exception as exc:
            traceback.print_exc()
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _remote_probe(self):
        body = self._read_json()
        if not isinstance(body, dict):
            self._json(400, {"error": "bad json"})
            return
        ssh = body.get("ssh")
        if not isinstance(ssh, dict):
            self._json(400, {"error": "bad ssh"})
            return
        d = remote_backend.defaults()
        pkg = str(body.get("pkg") or d["pkg"]).strip()
        py = str(body.get("py") or d["py"]).strip()
        base = str(body.get("base") or d["base"]).strip()
        try:
            result = remote_backend.probe(ssh, pkg, py, base)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._json(200, result)

    def _gen_interface(self):
        """按题面生成 interface 内容（GUI 专用；不写盘、不进作业目录）。

        local：GUI 直接 POST 配置的上游；remote：SSH 到服务器上用同一上游口径生成。
        上游地址与作业一致 —— remote 模式下 base_url 本来就按服务器视角填。
        """
        body = self._read_json()
        if not isinstance(body, dict):
            self._json(400, {"error": "bad json"})
            return
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            self._json(400, {"error": "题面（prompt）不能为空"})
            return
        model = str(body.get("model") or "").strip()
        if not model:
            self._json(400, {"error": "模型名不能为空"})
            return
        base_url = str(body.get("base_url") or "").strip()
        if not re.match(r"^https?://", base_url):
            self._json(400, {"error": "上游 Base URL 必须以 http:// 或 https:// 开头"})
            return
        top = str(body.get("top") or "").strip()

        backend = str(body.get("backend") or "local").strip()
        if backend not in ("local", "remote"):
            backend = "local"

        # 只有远端跑会带 extra_body（remote_backend.launch_remote 同口径），
        # 本地生成就按本地作业的样子发，不额外加参数。
        extra_body = ({"reasoning_effort": "none"}
                      if backend == "remote" and bool(body.get("remote_extra_body", True))
                      else None)

        try:
            if backend == "remote":
                ssh = body.get("ssh") if isinstance(body.get("ssh"), dict) else {}
                if not str(ssh.get("host") or "").strip():
                    self._json(400, {"error": "远端模式请填写 SSH 主机"})
                    return
                if not str(ssh.get("password") or ""):
                    self._json(400, {"error": "远端模式请填写 SSH 密码（只存在内存）"})
                    return
                d = remote_backend.defaults()
                remote_py = str(body.get("remote_py") or d["py"]).strip()
                remote_base = str(body.get("remote_base") or d["base"]).strip()
                text, guess = iface_gen.generate_remote(
                    ssh, remote_py, remote_base, base_url, model, prompt,
                    top=top, extra_body=extra_body)
            else:
                text, guess = iface_gen.generate_local(
                    base_url, model, prompt, top=top,
                    api_key=str(body.get("api_key") or ""),
                    extra_body=extra_body)
        except iface_gen.IfaceGenError as exc:
            self._json(502, {"error": str(exc)})
            return
        except Exception as exc:
            traceback.print_exc()
            self._json(502, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._json(200, {"interface": text, "top": guess, "model": model})

    def _create_job(self):
        cfg = self._read_json()
        if not isinstance(cfg, dict):
            self._json(400, {"error": "bad json"})
            return
        prompt = str(cfg.get("prompt") or "").strip()
        if not prompt:
            self._json(400, {"error": "题面（prompt）不能为空"})
            return
        model = str(cfg.get("model") or "").strip()
        if not model:
            self._json(400, {"error": "模型名不能为空"})
            return
        base_url = str(cfg.get("base_url") or "").strip()
        if not re.match(r"^https?://", base_url):
            self._json(400, {"error": "上游 Base URL 必须以 http:// 或 https:// 开头"})
            return

        backend = str(cfg.get("backend") or "local").strip()
        if backend not in ("local", "remote"):
            backend = "local"

        ssh = cfg.get("ssh") if isinstance(cfg.get("ssh"), dict) else {}
        ssh_host = str(ssh.get("host") or "").strip()
        try:
            ssh_port = int(ssh.get("port") or 22)
        except (TypeError, ValueError):
            ssh_port = 22
        ssh_port = max(1, min(65535, ssh_port))
        ssh_user = str(ssh.get("user") or "root").strip() or "root"
        ssh_password = str(ssh.get("password") or "")

        d = remote_backend.defaults()
        remote_pkg = str(cfg.get("remote_pkg") or d["pkg"]).strip().rstrip("/")
        remote_py = str(cfg.get("remote_py") or d["py"]).strip()
        remote_base = str(cfg.get("remote_base") or d["base"]).strip().rstrip("/")

        pkg = self.server.pkg  # type: ignore[attr-defined]
        if backend == "local":
            if not os.path.isdir(os.path.join(pkg, "agent")):
                self._json(400, {"error": f"找不到 agent 包：{pkg}"})
                return
        else:
            if not ssh_host:
                self._json(400, {"error": "远端模式请填写 SSH 主机"})
                return
            if not ssh_password:
                self._json(400, {"error": "远端模式请填写 SSH 密码（只存在内存）"})
                return
            for label, val in (("远端包路径", remote_pkg),
                               ("远端 Python", remote_py),
                               ("远端工作目录", remote_base)):
                if not val.startswith("/"):
                    self._json(400, {"error": f"{label} 必须是绝对路径"})
                    return

        with JOBS_LOCK:
            for j in JOBS.values():
                if j.state in ("starting", "running", "stopping"):
                    self._json(409, {"error": "已有作业在运行，先停止或等它结束", "job": j.id})
                    return

        if backend == "remote":
            try:
                remote_backend.quick_check(
                    {"host": ssh_host, "port": ssh_port, "user": ssh_user,
                     "password": ssh_password}, remote_pkg, remote_py)
            except Exception as exc:
                self._json(400, {"error": f"远端预检失败：{exc}"})
                return

        # 数值夹取
        def num(key, default, lo, hi, cast=float):
            try:
                v = cast(cfg.get(key, default))
            except (TypeError, ValueError):
                v = cast(default)
            return max(lo, min(hi, v))

        clean = {
            "prompt": prompt,
            "interface": str(cfg.get("interface") or ""),
            "top": str(cfg.get("top") or ""),
            "model": model,
            "base_url": base_url.rstrip("/"),
            "max_tokens": num("max_tokens", 8192, 256, 131072, int),
            "max_rounds": num("max_rounds", 4, 1, 12, int),
            "llm_timeout_s": num("llm_timeout_s", 1800, 30, 7200),
            "deadline_s": num("deadline_s", 0, 0, 86400),
            "total_timeout_s": num("total_timeout_s", 3600, 0, 172800),
            "temperature": num("temperature", 0.0, 0.0, 2.0),
            "top_p": num("top_p", 1.0, 0.0, 1.0),
            "csynth": str(cfg.get("csynth") or "auto"),
            "audit": str(cfg.get("audit") or "on"),
            "skills": str(cfg.get("skills") or "on"),
            "part": str(cfg.get("part") or "xczu3eg-sbva484-1-e"),
            "period_ns": str(cfg.get("period_ns") or "5"),
            "task_name": str(cfg.get("task_name") or ""),
            "backend": backend,
            "ssh": {"host": ssh_host, "port": ssh_port, "user": ssh_user},
            "remote_pkg": remote_pkg,
            "remote_py": remote_py,
            "remote_base": remote_base,
            "remote_extra_body": bool(cfg.get("remote_extra_body", True)),
        }
        if clean["csynth"] not in ("auto", "on", "off"):
            clean["csynth"] = "auto"
        if clean["audit"] not in ("on", "off"):
            clean["audit"] = "on"
        if clean["skills"] not in ("on", "off"):
            clean["skills"] = "on"

        api_key = str(cfg.get("api_key") or "")

        jobs_dir = self.server.jobs_dir  # type: ignore[attr-defined]
        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        root = os.path.join(jobs_dir, job_id)
        os.makedirs(root, exist_ok=False)

        job = Job(job_id, root, clean, pkg, api_key,
                  llm_timeout_s=float(clean["llm_timeout_s"]))
        job.ssh_password = ssh_password
        with JOBS_LOCK:
            JOBS[job_id] = job

        threading.Thread(target=launch_job_safe,
                         args=(job, clean, ssh_password), daemon=True,
                         name=f"job-{job_id}").start()
        self._json(202, {"id": job_id, "state": "starting"})


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HLS Agent GUI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="启动后打开浏览器")
    ap.add_argument("--pkg", default=os.environ.get("HLSAGENT_PKG", PKG_DEFAULT))
    ap.add_argument("--dataset", default=os.environ.get("HLSAGENT_DATASET", DATASET_DEFAULT))
    ap.add_argument("--jobs", default=os.path.join(HERE, "jobs"))
    ap.add_argument("--check", action="store_true", help="只打印环境检查后退出")
    args = ap.parse_args(argv)

    pkg = os.path.abspath(args.pkg)
    dataset = os.path.abspath(args.dataset)
    jobs_dir = os.path.abspath(args.jobs)
    os.makedirs(jobs_dir, exist_ok=True)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"警告：监听 {args.host} 会把可执行本地代码的接口暴露到网络。", file=sys.stderr)

    info = {
        "pkg": pkg,
        "pkg_ok": os.path.isdir(os.path.join(pkg, "agent")),
        "dataset": dataset,
        "dataset_ok": os.path.isdir(dataset),
        "vitis": shutil.which("vitis-run") or "",
        "python": sys.executable,
        "jobs": jobs_dir,
    }
    if args.check:
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 0 if info["pkg_ok"] else 2

    default_base = "http://127.0.0.1:11434/v1"
    models = ollama_models(default_base)
    default_model = ""
    names = [m.get("name") for m in models if m.get("name")]
    for cand in ("qwen3-8k:latest", "qwen3:8b", "qwen2.5-coder:7b"):
        if cand in names:
            default_model = cand
            break
    if not default_model and names:
        default_model = names[0]
    info.update({"models": names, "default_model": default_model})
    print(json.dumps(info, ensure_ascii=False, indent=1))

    httpd = None
    last_exc = None
    for port in range(args.port, args.port + 20):
        try:
            httpd = ThreadingHTTPServer((args.host, port), ApiHandler)
            break
        except OSError as exc:
            last_exc = exc
    if httpd is None:
        print(f"无法绑定端口 {args.port}..{args.port+19}: {last_exc}", file=sys.stderr)
        return 1

    httpd.daemon_threads = True
    httpd.pkg = pkg  # type: ignore[attr-defined]
    httpd.dataset = dataset  # type: ignore[attr-defined]
    httpd.jobs_dir = jobs_dir  # type: ignore[attr-defined]
    httpd.default_base_url = default_base  # type: ignore[attr-defined]
    restored = load_existing_jobs(jobs_dir, pkg)
    if restored:
        print(f"[gui] restored {restored} job(s) from {jobs_dir}")

    url = f"http://{args.host}:{httpd.server_address[1]}/"
    print(f"[gui] listening {url}")

    def _cleanup():
        with JOBS_LOCK:
            active = [j for j in JOBS.values() if j.state in ("starting", "running", "stopping")]
        for j in active:
            j.request_stop()

    atexit.register(_cleanup)
    if args.open:
        threading.Timer(0.9, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[gui] bye")
    finally:
        _cleanup()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

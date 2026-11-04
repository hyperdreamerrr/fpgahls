#!/usr/bin/env python3
"""LLM capture proxy that runs next to ollama on the remote server.

Started by gui_remote_run.py. It accepts OpenAI-compatible requests from the
agent, forwards them verbatim to the configured upstream, and mirrors the
streamed `content` / `reasoning` into files that the local GUI pulls over SFTP:

    <job>/llm-io.jsonl   one JSON object per completed call (same shape as GUI)
    <job>/live.json      {"live": {...}|null, "calls_total": N, "updated": t}

Only stdlib is used. Request headers are never recorded, so an Authorization
token (if any) never reaches disk.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def now() -> float:
    return time.time()


class Recorder:
    def __init__(self, io_path: str, live_path: str):
        self.io_path = io_path
        self.live_path = live_path
        self.lock = threading.RLock()
        self.seq = 0
        self.calls_total = 0
        self.live: dict | None = None
        self._last_flush = 0.0

    # -- live state ------------------------------------------------------
    def begin(self, req: dict) -> int:
        with self.lock:
            self.seq += 1
            seq = self.seq
            self.live = {
                "seq": seq,
                "round": None,
                "attempt": None,
                "model": str(req.get("model") or ""),
                "max_tokens": req.get("max_tokens"),
                "stream": bool(req.get("stream")),
                "started": now(),
                "updated": now(),
                "content": "",
                "reasoning": "",
                "chars": 0,
            }
            self._flush()
            return seq

    def update(self, seq: int, content: str, reasoning: str,
               force: bool = False) -> None:
        with self.lock:
            if not self.live or self.live.get("seq") != seq:
                return
            t = now()
            self.live["content"] = content
            self.live["reasoning"] = reasoning
            self.live["chars"] = len(content) + len(reasoning)
            self.live["updated"] = t
            if force or (t - self._last_flush) >= 0.2:
                self._flush()

    def end(self, seq: int, rec: dict) -> None:
        with self.lock:
            if self.live and self.live.get("seq") == seq:
                self.live = None
            self.calls_total += 1
            try:
                with open(self.io_path, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError:
                pass
            self._flush()

    def _flush(self) -> None:
        doc = {"live": self.live, "calls_total": self.calls_total,
               "updated": now()}
        tmp = self.live_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            os.replace(tmp, self.live_path)
            self._last_flush = now()
        except OSError:
            pass


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # one response per connection; SSE likes this
    server_version = "HLSAgentGUIRemoteProxy/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] %s - %s\n" % (self.address_string(), fmt % args))
        sys.stderr.flush()

    # -- helpers ---------------------------------------------------------
    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _target_path(self) -> str:
        parsed = urlparse(self.path)
        base_path = urlparse(self.server.upstream).path  # type: ignore[attr-defined]
        incoming = parsed.path
        if incoming.startswith("/v1"):
            target = base_path.rstrip("/") + incoming[3:]
        else:
            target = (base_path.rstrip("/") or "") + incoming
        if parsed.query:
            target += "?" + parsed.query
        return target or "/"

    # -- GET /__state ----------------------------------------------------
    def do_GET(self):
        if self.path.startswith("/__state"):
            rec = self.server.recorder  # type: ignore[attr-defined]
            with rec.lock:
                self._json(200, {"calls_total": rec.calls_total, "live": rec.live})
            return
        self._json(404, {"error": "not found"})

    # -- POST ------------------------------------------------------------
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b""
            try:
                req = json.loads(body.decode("utf-8", "replace")) if body else {}
            except Exception:
                req = {}
            if not isinstance(req, dict):
                req = {}
            self._forward(req, body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self._json(502, {"error": {
                    "message": f"proxy: {type(exc).__name__}: {exc}"}})
            except Exception:
                pass

    def _forward(self, req: dict, body: bytes) -> None:
        rec = self.server.recorder  # type: ignore[attr-defined]
        up = urlparse(self.server.upstream)  # type: ignore[attr-defined]
        seq = rec.begin(req)
        t0 = now()
        conn = None
        sent_headers = False
        content: list[str] = []
        reasoning: list[str] = []
        usage: dict = {}
        finish = ""
        status = None
        aborted = False
        error = ""

        try:
            conn = HTTPConnection(
                up.hostname, up.port or 80,
                timeout=float(self.server.read_timeout_s))  # type: ignore[attr-defined]
            headers = {"Content-Type": "application/json"}
            auth = self.headers.get("Authorization")
            if auth:
                headers["Authorization"] = auth
            accept = self.headers.get("Accept")
            if accept:
                headers["Accept"] = accept
            conn.request("POST", self._target_path(), body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            ctype = resp.getheader("Content-Type") or "application/octet-stream"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            sent_headers = True

            streaming = ("text/event-stream" in ctype.lower()) or bool(req.get("stream"))
            if streaming:
                buf = b""
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        got = self._feed_line(line, content, reasoning, usage)
                        if got:
                            finish = got
                    rec.update(seq, "".join(content), "".join(reasoning))
                if buf:
                    got = self._feed_line(buf, content, reasoning, usage)
                    if got:
                        finish = got
            else:
                payload = resp.read()
                self.wfile.write(payload)
                self.wfile.flush()
                try:
                    doc = json.loads(payload.decode("utf-8", "replace"))
                    got = self._feed_json(doc, content, reasoning, usage)
                    if got:
                        finish = got
                except Exception:
                    pass
        except (BrokenPipeError, ConnectionResetError):
            aborted = True
        except (socket.timeout, TimeoutError) as exc:
            error = f"timeout: {exc}"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            c = "".join(content)
            r = "".join(reasoning)
            rec.update(seq, c, r, force=True)
            record = {
                "seq": seq,
                "round": None,
                "attempt": None,
                "model": str(req.get("model") or ""),
                "max_tokens": req.get("max_tokens"),
                "stream": bool(req.get("stream")),
                "started": t0,
                "ended": now(),
                "elapsed_s": round(now() - t0, 2),
                "content": c,
                "reasoning": r,
                "usage": usage,
                "finish_reason": finish,
                "aborted": aborted,
            }
            if status is not None:
                record["status"] = status
            if error:
                record["error"] = error
            rec.end(seq, record)
            if not sent_headers and error:
                self._json(502, {"error": {"message": "proxy: " + error}})

    # -- SSE / JSON payload parsing --------------------------------------
    def _feed_line(self, raw: bytes, content: list, reasoning: list,
                   usage: dict) -> str:
        line = raw.strip()
        if not line.startswith(b"data:"):
            return ""
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            return ""
        try:
            doc = json.loads(data.decode("utf-8", "replace"))
        except Exception:
            return ""
        return self._feed_json(doc, content, reasoning, usage)

    def _feed_json(self, doc, content: list, reasoning: list,
                   usage: dict) -> str:
        if not isinstance(doc, dict):
            return ""
        u = doc.get("usage")
        if isinstance(u, dict) and u:
            usage.clear()
            usage.update(u)
        choices = doc.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        ch = choices[0] if isinstance(choices[0], dict) else {}
        delta = ch.get("delta")
        if isinstance(delta, dict):
            self._take(delta, content, reasoning)
        msg = ch.get("message")
        if isinstance(msg, dict):
            self._take(msg, content, reasoning)
        fin = ch.get("finish_reason")
        return str(fin) if fin else ""

    @staticmethod
    def _take(piece: dict, content: list, reasoning: list) -> None:
        c = piece.get("content")
        if isinstance(c, str) and c:
            content.append(c)
        r = piece.get("reasoning")
        if r is None:
            r = piece.get("reasoning_content")
        if isinstance(r, str) and r:
            reasoning.append(r)


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def write_port(path: str, port: int) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(str(port))
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="remote LLM capture proxy")
    ap.add_argument("--upstream", required=True,
                    help="OpenAI-compatible base, e.g. http://127.0.0.1:11434/v1")
    ap.add_argument("--io", required=True, help="llm-io.jsonl path")
    ap.add_argument("--live", required=True, help="live.json path")
    ap.add_argument("--port-file", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--read-timeout", type=float, default=7200)
    args = ap.parse_args(argv)

    rec = Recorder(args.io, args.live)
    httpd = ProxyServer((args.host, args.port), ProxyHandler)
    httpd.recorder = rec  # type: ignore[attr-defined]
    httpd.upstream = args.upstream  # type: ignore[attr-defined]
    httpd.read_timeout_s = args.read_timeout  # type: ignore[attr-defined]
    write_port(args.port_file, httpd.server_address[1])
    print(f"[proxy] listening 127.0.0.1:{httpd.server_address[1]} -> {args.upstream}",
          flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

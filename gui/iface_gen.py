#!/usr/bin/env python3
"""按题面自动生成 interface.txt（GUI 专用；**不进 agent 包**）。

官方格式（`agent/main.py:split_interface()` 的解析口径）：

    // header: <name>.h
    #pragma once
    #include <stdint.h>
    #include <inttypes.h>

    void top(...);

首行 `// header:` 必须带 `.h` 文件名 —— 没有它 `split_interface()` 返回 {}，
自检就会死在模型自己编的 `top.h` 上（job 20261103-162841-a4c6 的教训）。

两个执行位置：
- local：GUI 直接 POST 当前配置的 base_url；
- remote：把同一段调用放到服务器上跑（SSH 执行），用的是服务器上的
  Ollama，与远端作业的模型同源。脚本与载荷都是临时文件，跑完即删。

安全口径：SSH 密码只在内存里传给 SshSession，不写盘、不回显、不进日志。
"""
from __future__ import annotations

import json
import os
import re
import shlex
import time
import urllib.error
import urllib.request


class IfaceGenError(RuntimeError):
    """生成失败（上游不可达 / 回复里没有可用接口）。"""


SYSTEM_PROMPT = (
    "You write the interface.txt file for an HLS C++ coding task.\n"
    "Output ONLY the interface content, nothing else: no prose, no markdown fences.\n"
    "Required format:\n"
    "// header: <name>.h\n"
    "#pragma once\n"
    "#include <stdint.h>\n"
    "#include <inttypes.h>\n"
    "\n"
    "<C++ function prototype(s)>\n"
    "Rules:\n"
    "- The header name is lowercase ASCII and ends in .h.\n"
    "- Use fixed-width types (int32_t, uint32_t, float, double).\n"
    "- Array dimensions come from the task text; if it says n <= N use [N].\n"
    "- Parameter order follows the task description exactly (inputs first as written).\n"
    "- The top-level function name must be exactly `{top}` when one is given.\n"
)

#: 第一条函数原型；`group(1)` 是函数名。
PROTO_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*;")

_FENCE_RE = re.compile(r"```[A-Za-z0-9_+.\-]*[ \t]*\n(.*?)```", re.S)
_HEADER_RE = re.compile(r"^//\s*header\b", re.I)


def build_messages(prompt: str, top: str) -> list[dict]:
    sys = SYSTEM_PROMPT.replace("{top}", top or "(choose a short lowercase name)")
    user = "Task prompt:\n\n" + (prompt or "").strip() + "\n"
    if top:
        user += "\nThe top-level function must be named `%s`.\n" % top
    return [{"role": "system", "content": sys},
            {"role": "user", "content": user}]


def build_payload(model: str, prompt: str, top: str, max_tokens: int = 800,
                  extra_body: dict | None = None) -> dict:
    payload = {
        "model": model,
        "messages": build_messages(prompt, top),
        "max_tokens": int(max_tokens),
        "temperature": 0.0,
        "stream": False,
    }
    for key, val in (extra_body or {}).items():
        payload.setdefault(key, val)
    return payload


# --------------------------------------------------------------------------
# 回复清洗
# --------------------------------------------------------------------------
def _strip_fences(text: str) -> str:
    """有围栏时优先取含 `// header` 或函数原型的那一块。"""
    blocks = _FENCE_RE.findall(text or "")
    if not blocks:
        return text or ""
    for block in blocks:
        if _HEADER_RE.search(block.lstrip()) or PROTO_RE.search(block):
            return block
    return blocks[0]


def _cut_to_code(text: str) -> str:
    """从第一行像接口代码的地方起截，末尾截到最后一个 `;`/`}` 行。

    模型经常在前后加解释（"Here is the interface:" / "This header ..."），
    这段纯粹按行过滤，不做任何语义猜测。
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if _HEADER_RE.match(s) or s.startswith("#pragma") or s.startswith("#include"):
            start = i
            break
    if start is None:
        for i, line in enumerate(lines):
            if PROTO_RE.search(line):
                start = i
                break
    if start is None:
        return ""
    end = None
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if s.endswith(";") or s.endswith("}"):
            end = j
    if end is None:
        end = start
    return "\n".join(lines[start:end + 1]).strip("\n")


def parse_reply(text: str, top: str = "") -> tuple[str, str]:
    """把模型回复清洗成 (interface 文本, 顶层函数名)；不合格就抛错。"""
    raw = _cut_to_code(_strip_fences(text))
    if not raw:
        raise IfaceGenError("模型回复里没有找到接口内容")
    proto = PROTO_RE.search(raw)
    if not proto:
        raise IfaceGenError("生成结果里没有 C/C++ 函数原型")
    name = proto.group(1)
    if top and not re.search(r"\b%s\s*\(" % re.escape(top), raw):
        raise IfaceGenError("生成结果里没有顶层函数 %s()" % top)
    if not _HEADER_RE.match(raw.lstrip()):
        # 缺 header 行时补一个：split_interface() 靠它给头文件起名。
        raw = "// header: %s.h\n%s" % (top or name, raw)
    return raw.rstrip() + "\n", (top or name)


# --------------------------------------------------------------------------
# local：GUI 直接调上游
# --------------------------------------------------------------------------
def _post_chat(base_url: str, payload: dict, api_key: str, timeout_s: float) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            doc = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise IfaceGenError("上游 HTTP %s：%s" % (exc.code, detail or exc.reason)) from exc
    except Exception as exc:
        raise IfaceGenError("%s: %s" % (type(exc).__name__, exc)) from exc
    try:
        msg = doc["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise IfaceGenError("上游回复不是 chat/completions 格式")
    return str(msg.get("content") or "")


def generate_local(base_url: str, model: str, prompt: str, top: str = "",
                   api_key: str = "", timeout_s: float = 180.0,
                   extra_body: dict | None = None) -> tuple[str, str]:
    def _ask(extra):
        return _post_chat(base_url, build_payload(model, prompt, top, extra_body=extra),
                          api_key, timeout_s)

    content = _ask(extra_body)
    try:
        return parse_reply(content, top=top)
    except IfaceGenError:
        # 空正文（qwen3-4k 实测：finish_reason=length、reasoning 3080 B、content 0 B）
        # 或回复不可用（截断/只有开头）都重试一次关思考；Ollama /v1 只有这个写法生效。
        if (extra_body or {}).get("reasoning_effort"):
            if not content.strip():
                raise IfaceGenError("模型没有返回正文（思考占满了 max_tokens）") from None
            raise
    content = _ask({**(extra_body or {}), "reasoning_effort": "none"})
    if not content.strip():
        raise IfaceGenError("模型没有返回正文（关思考重试仍为空）")
    return parse_reply(content, top=top)


# --------------------------------------------------------------------------
# remote：SSH 到服务器上跑同一段调用
# --------------------------------------------------------------------------
#: 远端脚本：读 payload.json，POST 上游，把结果打成一行 JSON。
#: `ensure_ascii` 用默认值 True —— 服务器 locale 可能是 ASCII，中文必须转义。
REMOTE_SCRIPT = r'''import json, sys, urllib.request

def post(url, body, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        doc = json.loads(resp.read().decode("utf-8", "replace"))
    msg = (doc.get("choices") or [{}])[0].get("message") or {}
    return msg.get("content") or ""

def main():
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        p = json.load(fh)
    url = p["base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": p["model"],
        "messages": p["messages"],
        "max_tokens": p.get("max_tokens", 800),
        "temperature": p.get("temperature", 0.0),
        "stream": False,
    }
    # build_payload() 把 extra_body 的键摊在顶层；也兼容嵌套写法
    for key, val in p.items():
        if key in ("base_url", "timeout_s", "model", "messages", "max_tokens",
                   "temperature", "stream", "extra_body"):
            continue
        body.setdefault(key, val)
    for key, val in (p.get("extra_body") or {}).items():
        body.setdefault(key, val)
    timeout = float(p.get("timeout_s") or 180)
    try:
        content = post(url, body, timeout)
        # 空正文 = 思考吃光了 max_tokens；关思考重试一次（与本地路径同口径）
        if not content.strip() and "reasoning_effort" not in body:
            body["reasoning_effort"] = "none"
            content = post(url, body, timeout)
        print(json.dumps({"content": content}))
    except Exception as exc:
        print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}))

main()
'''


def generate_remote(ssh_cfg: dict, remote_py: str, remote_base: str,
                    base_url: str, model: str, prompt: str, top: str = "",
                    timeout_s: float = 180.0,
                    extra_body: dict | None = None) -> tuple[str, str]:
    """在服务器上生成（上游地址按服务器视角解释，与远端作业一致）。"""
    import remote_backend  # 延迟导入：本机没装 paramiko 时只影响这个功能

    host = str((ssh_cfg or {}).get("host") or "").strip()
    if not host:
        raise IfaceGenError("远端模式请填写 SSH 主机")
    try:
        port = int((ssh_cfg or {}).get("port") or 22)
    except (TypeError, ValueError):
        port = 22
    user = str((ssh_cfg or {}).get("user") or "root").strip() or "root"
    password = str((ssh_cfg or {}).get("password") or "")
    remote_py = str(remote_py or "").strip()
    remote_base = str(remote_base or "").strip().rstrip("/")
    if not remote_py.startswith("/") or not remote_base.startswith("/"):
        raise IfaceGenError("远端 Python / 工作目录必须是绝对路径")

    def _payload(extra):
        doc = build_payload(model, prompt, top, extra_body=extra)
        doc["base_url"] = base_url
        doc["timeout_s"] = float(timeout_s)
        return doc

    token = "%d-%s" % (int(time.time()), os.urandom(4).hex())
    workdir = "%s/tmp/iface-gen-%s" % (remote_base, token)
    sess = remote_backend.SshSession(host, port, user, password,
                                     timeout=max(15.0, min(30.0, timeout_s)))
    cmd = "cd %s && %s gen.py payload.json" % (
        shlex.quote(workdir), shlex.quote(remote_py))

    def _run_once(payload_doc):
        sess.put_text(json.dumps(payload_doc, ensure_ascii=False),
                      workdir + "/payload.json")
        rc, out, err = sess.exec(cmd, timeout=float(timeout_s) + 30.0)
        doc = None
        for line in reversed((out or "").strip().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                break
            except ValueError:
                continue
        if doc is None:
            tail = (err or out or "").strip()[-300:]
            raise IfaceGenError("远端没有返回结果 rc=%s：%s" % (rc, tail))
        if doc.get("error"):
            raise IfaceGenError("远端上游失败：%s" % str(doc["error"])[:300])
        return str(doc.get("content") or "")

    try:
        rc, out, err = sess.exec("mkdir -p " + shlex.quote(workdir), timeout=20)
        if rc != 0:
            raise IfaceGenError("远端建目录失败：%s" % ((err or out)[:300] or "rc=%s" % rc))
        sess.put_text(REMOTE_SCRIPT, workdir + "/gen.py")
        content = _run_once(_payload(extra_body))
        try:
            return parse_reply(content, top=top)
        except IfaceGenError:
            # 与本地同口径：空正文或不可用回复 → 关思考重跑一次
            if (extra_body or {}).get("reasoning_effort"):
                raise
        content = _run_once(_payload({**(extra_body or {}),
                                      "reasoning_effort": "none"}))
        if not content.strip():
            raise IfaceGenError("远端模型没有返回正文（关思考重试仍为空）")
        return parse_reply(content, top=top)
    finally:
        try:
            sess.exec("rm -rf " + shlex.quote(workdir), timeout=15)
        except Exception:
            pass
        sess.close()

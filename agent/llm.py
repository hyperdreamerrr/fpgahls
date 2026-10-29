#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 后端（HLS 赛道）+ HLS 口径的代码抽取。

两个后端一条代码路径：

    LLM_BACKEND=mock      不联网、不要 key。按 interface 拼一份**形状对**的桩：
                          签名照抄、函数体把输出清零、再配一个只会检查「能跑」的
                          测试台。用来在无 GPU / 无 key 时验 run.sh 契约与判定链路。
    LLM_BACKEND=openai    任何 OpenAI 兼容的 /chat/completions。开发期用云端 API、
                          提交时必须用本地部署的开源权重，**代码不改，只改环境变量**。

★ 采样口径 = **temperature 0.0 / top_p 1.0**，逐条对齐官方 `example/baseline.py`
  2026-10-19 版那组标明「不要改」的常量：增益 g 的分子与分母必须在同一采样
  条件下测，否则比值没有意义（§3.1.5.2 也要求 run.sh 与 run_baseline.sh 用
  「同一推理服务与同一上下文配置」）。

★ `max_tokens` **不是采样口径，是每轮预算**。2026-10-22 起本模块缺省 **8192**
  （预登记 `results/deadline-removal-20261022/PREREG.md`），而 `baseline.py`
  仍是 16384 —— 它一次调用写到底，我们一题内多轮、每轮由 `plan_round()` 现算帽。
  这条不对称是**声明过的**：换它只改变每轮愿意等多久，不改变同一段
  (prompt, 采样口径) 会生成什么。改这个数必须同步 model/MODEL.md 与 manifest。

★ cap 与 timeout **必须一起看**（实测教训：`results/hls-2x2-arms-20261001.md`
  A2 臂）：42 tok/s 下 16384 token 需要 389 s，cap 提到 16384 而 timeout 留在
  180 s，等于让秒表先到 —— A2 两题在 +180.4 s 报 `ReadTimeout`，增益 1.1333 → 1.0000。
  2026-10-22 起再加一道**流式止损**：服务器3 的全量跑证明还有第二种失败形状 ——
  不是「撞帽」，而是**慢到读超时也拿不到任何 token**（64 次成功调用的 p10 =
  7.8 tok/s；8192 token 在那档要 1050 s > 900 s 读超时）。

★ 流式止损（2026-10-22）：
    - `LLM_STREAM=1`（缺省）走 SSE；`0` 回退非流式，请求体逐字节回到旧路径。
    - **停摆闸**：块间 180 s 没有任何数据（含首 token 之前）⇒ 中止。
    - **慢流闸**：首 token 起 ≥30 s 且 ≥200 块后，若 <15 tok/s ⇒ 中止。
      只对 cap > 4096 的调用生效 —— 降档重试（main.py 的 §2.8）不被它再掐。
    - `timeout_s` 仍是单次调用总时限（缺省 900），逐块检查。
  中止抛 `LLMSlowError`（`LLMError` 子类），main.py 把它与传输失败分开记 trace。

NOTE FOR SUBMISSION：最终在**断网**沙箱里跑，MODEL.md 必须申报可本地部署的开源权重。
商业 API 违反评分细则 2.1/2.3，根本拿不到运行分。
"""

from __future__ import annotations

import json
import os
import re
import time


class LLMError(RuntimeError):
    pass


class LLMSlowError(LLMError):
    """调用被**我们自己主动中止**（不是服务端拒绝）。

    `reason` 三值：
        slow-stream   流在动但太慢（< LLM_RATE_MIN_TPS）
        idle-timeout  块间超过 LLM_STREAM_IDLE_S 没有数据（含首 token 之前）
        total-timeout 单次调用总时限（min(timeout_s, budget_s)）到期
    与 `ReadTimeout` 的区别是要紧的：读超时是**被动等满**整段时限才失败
    （服务器3 的 600 s 空转就是这么烧掉的），这里是**主动止损**，几秒内就返回。
    main.py 用它决定 trace 的 rc（2）与给下一轮的修复文案。
    """

    def __init__(self, reason: str, rate: float = 0.0, chunks: int = 0,
                 elapsed: float = 0.0, detail: str = ""):
        self.reason = reason
        self.rate = rate
        self.chunks = chunks
        self.elapsed = elapsed
        super().__init__("%s（%s）" % (reason, detail) if detail else reason)


def _tri_state(raw: str, name: str) -> bool | None:
    """三态开关：未设 -> None（**不发该字段**），设了就必须是真/假。

    为什么要三态而不是默认 False：官方 `baseline.py:35` 写的是「请求仅使用
    OpenAI 标准字段，不含厂商专有参数」。**发与不发是两种不同的请求**，而
    「不发」才是与已测基线可比的形态。默认发 False 会悄悄改变请求内容。
    """
    s = raw.strip().lower()
    if s in ("", "none", "unset"):
        return None
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    raise LLMError("%s 取值无法识别：%r（期望 true/false，留空表示不发该字段）" % (name, raw))


def _parse_extra_body(raw: str) -> dict:
    """把 `LLM_EXTRA_BODY` 解析成一个要并进请求体的 JSON 对象。

    这是**唯一的通用逃生口**：vLLM 的 `chat_template_kwargs`、Ollama 的
    `num_ctx`/`options` 等厂商专有参数都从这里进，不需要为每个参数改代码。
    留空就是空 dict，请求体与标准 OpenAI 请求逐字节相同。
    """
    s = raw.strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        # 静默忽略是这里最坏的处置：参数没生效，但看起来「配了」。
        raise LLMError("LLM_EXTRA_BODY 不是合法 JSON：%s" % exc) from exc
    if not isinstance(obj, dict):
        raise LLMError("LLM_EXTRA_BODY 必须是一个 JSON 对象（用来并进请求体）")
    return obj


def _load_generation() -> dict:
    """manifest.json 里声明的思考设置（`generation` 块）。

    官方 `baseline.py` 读同一块并发进自己的请求，所以「方案」与「基线」是在
    **同一种模型模式**下跑的；评分细则也要求方案使用申报的生成设置。这里是
    官方的参考读法，白名单与基线逐字一致：`chat_template_kwargs`（只收标量值）
    与 `reasoning_effort`。

    读不到/不是 JSON 都返回 `{}` 而不是抛错：评测方直接调 run.sh，不保证
    manifest 就在旁边；此时「不发该字段」与旧口径逐字节相同，是**唯一安全**的退路。
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            gen = json.load(f).get("generation") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(gen, dict):
        return {}
    out: dict = {}
    kw = gen.get("chat_template_kwargs")
    if isinstance(kw, dict):
        kw = {k: v for k, v in kw.items()
              if isinstance(k, str) and isinstance(v, (bool, int, float, str))}
        if kw:
            out["chat_template_kwargs"] = kw
    effort = gen.get("reasoning_effort")
    if isinstance(effort, str) and effort:
        out["reasoning_effort"] = effort
    return out


class LLMResult:
    def __init__(self, text: str, tokens_in: int = 0, tokens_out: int = 0,
                 finish_reason: str = "", tokens_src: str = "usage",
                 streamed: bool = False):
        self.text = text
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        # `tokens_out` 的来源：`usage`（服务端给的）或 `chunks`（流式下按块计）。
        # 混为一谈会把「按块估的数」当成服务端读数引用；trace 里必须分开记。
        self.tokens_src = tokens_src
        # 这次调用走的是 SSE 还是一次性 JSON —— 复核时解释 token 计数口径的前提。
        self.streamed = streamed
        # 服务端为什么停下：`stop`（自己收尾）/ `length`（**撞上 max_tokens 被切断**）。
        # 只看 `tokens_out == 16384` 去反推截断是一种猜测；读这个字段才是读证据。
        # 两者不可混为一谈：`length` 说明模型**根本没轮到输出**（要改预算），
        # 「回复里没有代码块」说明模型答完了但没按约定输出（要改提示词）。
        # 混为一谈就会去改提示词。
        self.finish_reason = finish_reason

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


class LLM:
    def __init__(self) -> None:
        self.backend = os.environ.get("LLM_BACKEND", "mock").strip().lower()
        self.model = os.environ.get("LLM_MODEL", "mock-model")
        self.base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("LLM_API_KEY", "")

        # 采样口径（temperature/top_p）与官方 baseline.py 逐字对齐；`max_tokens`
        # 是**每轮预算**，2026-10-22 起缺省 8192（预登记 §2.3/§2.4），timeout 900。
        # 默认值写在这里而不只是写进 serve/env.sh 是要紧的：评测方按契约**直接调
        # run.sh**，而 run.sh **不 source** env.sh —— 代码里这个才是真正生效的那个。
        # 2026-10-22 起它是**每轮预算帽**（预登记
        # `results/deadline-removal-20261022/PREREG.md` §2.3），必须与
        # serve/env.sh 同值；`manifest.context.max_output_tokens` 申报的是
        # **模型/服务栈的输出上下文**（基线单请求也按它发），与本帽故意不同。
        # 守卫按「env == 代码」「帽 ≤ 申报上下文」两条关系查（tools/test_package_hls.py ⑤）。
        self.max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "8192"))
        self.temperature = float(os.environ.get("LLM_TEMPERATURE", "0.0"))
        self.timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "900"))
        # ── 流式与两个止损闸（预登记 §2.5–§2.7）─────────────────────────────
        # 缺省开流式；`LLM_STREAM=0` 是逐字节回退路径（旧的非流式请求体）。
        self.stream = _tri_state(os.environ.get("LLM_STREAM", ""),
                                 "LLM_STREAM") is not False
        self.rate_min_tps = float(os.environ.get("LLM_RATE_MIN_TPS", "15"))
        self.rate_gate_min_s = float(os.environ.get("LLM_RATE_GATE_MIN_S", "30"))
        self.rate_gate_min_tokens = int(os.environ.get("LLM_RATE_GATE_MIN_TOKENS", "200"))
        # 门槛用意：只掐**贵的**调用。降档重试的 4096 帽不受闸，否则慢模型
        # 会在 30 s 被反复掐死，永远写不完那一轮（见 main.py §2.8）。
        self.rate_gate_min_cap = int(os.environ.get("LLM_RATE_GATE_MIN_CAP", "4096"))
        self.stream_idle_s = float(os.environ.get("LLM_STREAM_IDLE_S", "180"))
        self.top_p = float(os.environ.get("LLM_TOP_P", "1.0"))
        # manifest.json 申报的思考设置。它本身就是申报物的一部分，是
        # 「我们申报要这么跑」与「运行时真的这么发」之间的那座桥；不在这里改。
        self.generation = _load_generation()

        # ── 厂商专有参数：**本方案与基线的差异所在** ──────────────────────
        # 官方 baseline.py 只发标准字段，所以它能发的字段是固定的；我们不在此限。
        # **缺省全关**：不开就是一条纯标准 OpenAI 请求，与已测口径逐字节相同 ——
        # 差异项必须是**显式打开**的，而不是默认就悄悄生效的。
        self.think = _tri_state(os.environ.get("LLM_THINK", ""), "LLM_THINK")
        self.extra_body = _parse_extra_body(os.environ.get("LLM_EXTRA_BODY", ""))

        if self.backend == "openai" and not self.base_url:
            raise LLMError("LLM_BACKEND=openai requires LLM_BASE_URL")

    def describe(self) -> dict:
        # `think` / `generation` / `extra_body` **总是**列出来（哪怕是 None / {}）：
        # 这段字典会被写进 trace.jsonl 的 start 行，而 trace.jsonl 是判分与复核
        # 都读的证据。差异项开着却不留痕，等于复核时无法解释我们的请求为什么
        # 与基线不同；`generation` 尤其要在，它是「申报的生成设置」与「实际请求」
        # 之间唯一的对照列。
        return {
            "backend": self.backend,
            "model": self.model,
            "base_url": self.base_url or None,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "timeout_s": self.timeout_s,
            # 流式与止损闸也是**请求形态的一部分**：复核时若 trace 里没有这一列，
            # 「这一轮为什么被中止」就只能靠猜。
            "stream": self.stream,
            "stream_idle_s": self.stream_idle_s,
            "rate_gate": ({"min_tps": self.rate_min_tps,
                           "min_s": self.rate_gate_min_s,
                           "min_tokens": self.rate_gate_min_tokens,
                           "min_cap": self.rate_gate_min_cap}
                          if self.stream else None),
            "generation": self.generation,
            "think": self.think,
            "extra_body": self.extra_body or None,
        }

    def chat(self, messages: list[dict], budget_s: float | None = None,
             max_tokens: int | None = None) -> LLMResult:
        """`budget_s` 是**调用方**给出的本次调用剩余预算（秒），None 表示不额外设限。

        为什么需要它：`timeout_s` 是**单次请求**的上限，`deadline_s` 是**整题**的上限，
        两者不是一回事。只查「还剩时间」不等于「这一轮能在剩下的时间里做完」。
        `docs/API_CONTRACT.md` 写着赛事方侧超时设为 `deadline_s + 20` 秒、
        超时该题按 **L0** —— 也就是说越界不是变慢，是**整题归零**。

        取 min 而不是二选一：两个约束都真实存在，谁更紧听谁的。

        `max_tokens` 是**这一次调用**的帽，None 表示用 `self.max_tokens`（配置值）。
        为什么要有这个覆盖（`PREREG-143.md` §3.3.1）：实测**撞帽时思考会涨满帽**
        （`results/hls-agent-20261001/cap-probe-20261001/`：cap 4096/6144/8192
        三档的 `reasoning/completion_tokens` 恒在 2.6 上下），于是
        `elapsed ≈ cap / tps` 是**确定量** —— **帽就是墙钟**。
        整题只有 `deadline_s`，逐轮削帽就是逐轮买回秒数。

        ★ 覆盖**不改** `self.max_tokens`：`describe()` 写进 trace `start` 行的是
        **配置**值，改了它会让 start 行申报一个从未发出的帽。**逐轮实际值另记一列**
        （`main.solve` 写进每轮的 `llm` 行）。
        """
        if self.backend == "mock":
            return self._chat_mock(messages)
        if self.backend == "openai":
            return self._chat_openai(messages, budget_s, max_tokens)
        raise LLMError("unknown LLM_BACKEND: %r" % self.backend)

    # ---------------------------------------------------------------- openai

    def _chat_openai(self, messages: list[dict],
                     budget_s: float | None = None,
                     max_tokens: int | None = None) -> LLMResult:
        # requests 的延迟导入下沉到 _post_once / _post_stream：mock 模式不依赖它。
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key

        payload = {
            "model": self.model,
            "messages": messages,
            # 逐轮帽在这里生效（`chat` 的 `max_tokens` 覆盖），缺省才是配置值。
            "max_tokens": self.max_tokens if max_tokens is None else int(max_tokens),
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": False,
        }
        # 三级合并，后者盖前者，顺序是有意的：
        #   1. manifest.json 的 `generation`  ← 申报值，run_baseline.sh 也发它
        #   2. LLM_THINK                        ← **开发期**开关，只用于 A/B 探针
        #   3. LLM_EXTRA_BODY                   ← 通用逃生口，盖掉以上一切
        #
        # `chat_template_kwargs` 按**字典合并**而不是整体替换：generation 里已申报
        # 的其它模板参数不该因为打开一个 think 开关就被抹掉。
        #
        # `chat_template_kwargs` 是 vLLM/llama.cpp(--jinja) 的通用字段名；
        # Ollama 的对应字段叫 `think`、上下文叫 `options.num_ctx`，那些走
        # LLM_EXTRA_BODY，不在这里硬编码 —— 两边字段名不同，同时发会被对面 400。
        ct_kwargs = dict(self.generation.get("chat_template_kwargs") or {})
        if self.think is not None:
            ct_kwargs["enable_thinking"] = self.think
        if ct_kwargs:
            payload["chat_template_kwargs"] = ct_kwargs
        for k, v in self.generation.items():
            if k != "chat_template_kwargs":
                payload[k] = v
        if self.extra_body:
            payload.update(self.extra_body)

        timeout = self.timeout_s if budget_s is None else min(self.timeout_s, budget_s)
        cap_eff = self.max_tokens if max_tokens is None else int(max_tokens)
        # 请求形态只有这一个字段不同；`LLM_STREAM=0` 时它与旧路径逐字节相同。
        payload["stream"] = self.stream
        if self.stream:
            return self._post_stream(headers, payload, timeout, cap_eff)
        return self._post_once(headers, payload, timeout)

    # ------------------------------------------------------- 非流式（回退路径）

    def _post_once(self, headers: dict, payload: dict, timeout: float) -> LLMResult:
        import requests

        # 传输层失败必须**当场**转成 LLMError。main.py 只捕获 LLMError，而 requests
        # 抛的是它自己的异常类型 —— 逃出去就落到 main() 那个兜底的 except Exception：
        # 它把 code 当空串，**前几轮已经取到的答案一并丢掉**。
        try:
            resp = requests.post(
                "%s/chat/completions" % self.base_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LLMError("%s: %s" % (type(exc).__name__, exc)) from exc
        if resp.status_code != 200:
            raise LLMError("HTTP %d: %s" % (resp.status_code, resp.text[:500]))

        try:
            body = resp.json()
        except ValueError as exc:
            raise LLMError("response is not JSON: %s" % resp.text[:500]) from exc
        try:
            choice = body["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("unexpected response shape: %s" % str(body)[:500]) from exc

        usage = body.get("usage") or {}
        return LLMResult(
            text=text,
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            tokens_out=int(usage.get("completion_tokens", 0) or 0),
            # `.get` 而不是 `[]`：这是**可选**字段，缺了不该把一次成功调用变成
            # LLMError。缺了就是空串，`truncated` 判 False —— 宁可漏报截断，
            # 不要因为少一个字段把整轮回复丢掉。
            finish_reason=str(choice.get("finish_reason") or ""),
        )

    # ------------------------------------------------------------------ 流式

    def _post_stream(self, headers: dict, payload: dict, timeout: float,
                     cap_eff: int) -> LLMResult:
        """SSE 读取 + 两个止损闸（模块 docstring「流式止损」一段的逐条实现）。

        为什么非要多这一条路径：服务器3 全量跑的失败形状是**读超时前一个 token
        都没拿到**（600 s 空转），而非流式客户端只能等满。流式把「有没有在动」
        变成可观测量，于是慢流 30–40 s 就能判死、停摆 180 s 判死。

        `tokens_out` 的口径：服务端给了 `usage` 就用它（`tokens_src="usage"`）；
        没给就按块数计（`"chunks"`）。两家本地后端（Ollama / llama.cpp）都是
        1 token = 1 chunk，但**这是实测形状，不是协议保证** —— 所以记来源。
        """
        import requests

        idle = min(self.stream_idle_s, timeout)
        # connect 单独限时（30 s）；read 是**块间**超时，它就是停摆闸本身。
        try:
            resp = requests.post(
                "%s/chat/completions" % self.base_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=(min(30.0, timeout), idle),
                stream=True,
            )
        except requests.RequestException as exc:
            raise LLMError("%s: %s" % (type(exc).__name__, exc)) from exc
        if resp.status_code != 200:
            raise LLMError("HTTP %d: %s" % (resp.status_code, resp.text[:500]))

        gate = cap_eff > self.rate_gate_min_cap
        parts: list[str] = []
        usage: dict = {}
        finish = ""
        chunks = 0
        t0 = time.time()
        first = None
        try:
            for raw in resp.iter_lines(decode_unicode=True):
                now = time.time()
                if now - t0 > timeout:
                    raise LLMSlowError(
                        "total-timeout", chunks=chunks, elapsed=now - t0,
                        detail="单次调用超过 %.0f s" % timeout)
                if not raw:
                    continue
                line = raw.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj.get("usage"), dict):
                    usage = obj["usage"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                ch = choices[0] or {}
                if ch.get("finish_reason"):
                    finish = str(ch["finish_reason"])
                delta = ch.get("delta") or {}
                msg = ch.get("message") or {}
                # 思考通道的字段名两家不同（vLLM: reasoning_content；Ollama 走
                # content 内联 <think>），能数到的都数，只有 content 进正文。
                text_piece = (delta.get("content") or msg.get("content") or "")
                think_piece = (delta.get("reasoning_content") or delta.get("reasoning")
                               or msg.get("reasoning_content") or "")
                if not (text_piece or think_piece):
                    continue
                chunks += 1
                if first is None:
                    first = now
                if text_piece:
                    parts.append(text_piece)
                if gate:
                    el = now - first
                    if el >= self.rate_gate_min_s and chunks >= self.rate_gate_min_tokens:
                        rate = chunks / el if el > 0 else 0.0
                        if rate < self.rate_min_tps:
                            raise LLMSlowError(
                                "slow-stream", rate=rate, chunks=chunks, elapsed=el,
                                detail="%.1f tok/s < %.1f（首 token 起 %.0f s / %d 块）"
                                % (rate, self.rate_min_tps, el, chunks))
        except requests.Timeout as exc:
            # 停摆：块间超过 idle 秒（含首 token 之前）。这是被动的 requests 超时，
            # 但语义上属于「我们自己判死」，所以也归 LLMSlowError（reason 不同）。
            raise LLMSlowError(
                "idle-timeout", chunks=chunks, elapsed=time.time() - t0,
                detail="%s（块间 %.0f s 无数据）" % (type(exc).__name__, idle)) from exc
        except requests.RequestException as exc:
            raise LLMError("%s: %s" % (type(exc).__name__, exc)) from exc
        finally:
            resp.close()

        text = "".join(parts)
        if usage:
            tokens_in = int(usage.get("prompt_tokens", 0) or 0)
            tokens_out = int(usage.get("completion_tokens", 0) or 0)
            tokens_src = "usage"
        else:
            tokens_in, tokens_out, tokens_src = 0, chunks, "chunks"
        return LLMResult(
            text=text, tokens_in=tokens_in, tokens_out=tokens_out,
            finish_reason=finish, tokens_src=tokens_src, streamed=True,
        )

    # ------------------------------------------------------------------ mock

    def _chat_mock(self, messages: list[dict]) -> LLMResult:
        """产出一份**形状对、内容空**的答复：能编过、能跑、但功能一定不对。

        桩模式的用途是验管道（提示词拼装 → 抽码 → 工具调用 → trace → HTTP 外壳），
        不是产出一个对的 kernel。所以它签名照抄、输出清零、测试台只检查「跑得完」，
        于是它大概能到 L2/L3 而到不了官方那关 —— 这是**诚实**的失败方式。
        """
        from .tools import declared_signature

        user = "\n".join(m["content"] for m in messages if m["role"] == "user")
        top = _top_from_prompt(user) or "top"
        sig = declared_signature(user, top) or ""

        kernel = (
            "// MOCK BACKEND -- 形状对、内容空。设 LLM_BACKEND=openai 才是真解。\n"
            "// 桩只把输出清零，签名照抄 interface；它跑得完，但结果一定不对。\n"
            "#include <cstring>\n\n"
            "void %s(%s) {\n"
            "  // 桩体：不做任何计算\n"
            "}\n" % (top, _strip_types(sig)))

        tb = _mock_tb()
        text = ("```cpp\n%s```\n\n```cpp\n%s```\n" % (kernel, tb))
        return LLMResult(text=text, tokens_in=len(user) // 4,
                         tokens_out=len(text) // 4, finish_reason="stop")


# --------------------------------------------------------------------- 抽码

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+.#-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_MAIN_ANY = re.compile(r"\b(?:int|void)\s+main\s*\(")
#: 一块「代码」至少要有一个 C/C++ 的骨架字符。纯注释/纯小节标签的块**不是代码**。
_CODEISH = re.compile(r"[;{}#()]")
_MAIN_LINE = re.compile(r"^[ \t]*(?:static\s+)?(?:int|void)\s+main\s*\(", re.M)


def _top_from_prompt(text: str) -> str:
    """从题面猜顶层函数名。只用于 mock 与兜底，正式路径由 main.py 显式传 top。"""
    m = re.search(r"top(?:-level)?\s*(?:function|函数)?\s*[:：]?\s*`?(\w+)`?", text, re.I)
    return m.group(1) if m else ""


def _strip_types(sig: str) -> str:
    """把 interface 里的形参表改写成「只有类型、没有名字」的桩参数表。"""
    out = []
    for raw in sig.split(","):
        toks = raw.replace("*", " * ").split()
        if not toks:
            continue
        if len(toks) >= 2 and re.fullmatch(r"[A-Za-z_]\w*", toks[-1]):
            toks = toks[:-1]
        out.append(" ".join(toks) or "int")
    return ", ".join(out)


def _match_brace(code: str, i: int) -> int:
    """从 code[i]（必须是 `{`）起配对，返回紧跟在配对 `}` 之后的**下标**；配不上返回 -1。

    要认字符串与注释：`printf("}")` 里的花括号不算数，一行 `// }` 也不算数。
    认得不够细没关系（大不了返回 -1、调用方放弃切分），认错才要紧 ——
    切坏的 kernel 会让模型去改一份本来正确的代码。
    """
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


def split_main(code: str) -> tuple[str, str]:
    """把 `main` 函数从一段 C++ 里切出来 → `(去掉 main 的部分, main 的部分)`。

    ★ 这**不只是**为了自验好跑，是一条硬要求：官方测试台自带 `main`，
      提交的 `solution.cpp` 里若也有一个，**链接期重复定义 ⇒ 落 L1（系数 0.1）**。
      所以切分本身就在修一个会真实扣分的错误。

    切不动就原样返回 `(code, "")` —— 宁可跳过自验，也不要递一份被我切坏的 kernel
    给模型看。判别 main 时用**行首锚定**的版本：注释里那句 `// int main() 由测试台提供`
    不该被当成真 main。
    """
    m = _MAIN_LINE.search(code)
    if not m:
        return code, ""
    i = code.find("{", m.end())
    if i < 0:
        return code, ""
    end = _match_brace(code, i)
    if end < 0:
        return code, ""
    # 往前找函数头的起点：最近的一个 `}`、`;`、或预处理指令行的行尾。
    seps = [x.end() for x in re.finditer(r"[};]|^[ \t]*#[^\n]*$", code[:m.start()], re.M)]
    cut = seps[-1] if seps else 0
    kernel = (code[:cut] + code[end:]).strip() + "\n"
    tb = code[cut:end].strip() + "\n"
    return kernel, tb


def strip_think(text: str) -> str:
    """去掉推理模型的思考段，只留正式回答。

    推理服务没配 reasoning parser 时，模型会把 `<think>…</think>` 原样放在正文里。
    不先去掉，思考过程会连同代码一起写进产物、编译必然失败；思考中打过的代码
    草稿也可能被当成答案取走。三种形态：

        <think>…</think>答案     完整的思考段 → 取最后一个结束标记之后的正文
        …</think>答案            模板已预填 `<think>`，回复里只有结束标记 → 同上
        <think>…（被截断）       输出上限耗在思考里、没有答案 → 取 `<think>` 之前
                                 （回复以 `<think>` 开头时就是空串：如实「没有代码」）

    没有标记就原样返回 —— 这条函数**只减不增**，永远不该往回复里添东西。
    """
    if "</think>" in text:
        return text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        return text.split("<think>", 1)[0]
    return text


def _unclosed_tail(text: str) -> str | None:
    """回复里只有**未闭合**的代码围栏时，取围栏那一行之后的全部内容。

    `_FENCE` 要求围栏闭合；撞上 `max_tokens` 的回复常常来不及闭合，于是
    `findall` 一个 block 都取不到，落进下面「没有围栏」的退让路 —— 那条路会把
    **整段原文**（连开头那行 ```cpp 一起）当成 kernel。交出去的文件第一行是
    ```cpp，落盘后必然解析失败。

    存档证据（`results/agent-fix2-20261025/pair20-fix2-20261025/`，
    `machsuite__aes_aes`）：三轮 `kernel_bytes` 与 `content_bytes` **逐字节相等**
    （9,230/9,183/9,183）—— 只有「整段取用」这条退让会给出这种等式。

    返回 None 表示文本里没有围栏行，交给调用方按原逻辑判断。
    """
    lines = text.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            idx = i                      # 取**最后**一个：前面的围栏早已闭合
    if idx is None:
        return None
    body = "\n".join(lines[idx + 1:]).strip()
    return body or None


# ★ fix9（改动 A）：**有围栏行 ≠ 可以整段取用**。
#   实测病灶（`agent/out/hls_polybench__fixed__small__doitgen/solution.cpp`，
#   fix8 面板 p9 的真实交付件，22,939 B）：模型把整篇回复写成了
#       **Block 1 — the kernel**
#       ```cpp        ← 开围栏
#       ```cpp        ← 又开一个（连开两个）
#       …真正的代码…
#       ```           ← 闭
#       ```           ← 再闭
#   `_FENCE`（要求闭合）把「开+开」配成一个空块、「闭+闭」配成又一个空块 ⇒
#   raw=["",""] ⇒ blocks=[]；`_unclosed_tail` 取**最后**一条围栏行之后 ⇒ 空 ⇒ None；
#   于是落进「没有围栏 ⇒ 整段按代码取用」的退让 ⇒ 整篇 markdown 成了 solution.cpp，
#   第一行是 `**Block 1 — the kernel**`，官方判分 L1（csim 都编不过）。
_FENCE_LINE = re.compile(r"^\s*```")


def _fence_segments(text: str) -> list[str]:
    """按围栏行把回复切段；**围栏行本身不进入任何段**。"""
    lines = text.splitlines()
    cuts = [i for i, ln in enumerate(lines) if _FENCE_LINE.match(ln)]
    out, start = [], 0
    for i in cuts:
        out.append("\n".join(lines[start:i]).strip())
        start = i + 1
    out.append("\n".join(lines[start:]).strip())
    return out


def _code_segments(text: str, top: str = "") -> list[str]:
    """围栏配不成对时的退让：取**全部**像代码的段（判据与整段退让同一套），按出现顺序。

    ★ fix10（改动 P）：原来只取最长的一段。真实形状（连开两个围栏）切出来是
    kernel 与测试台**两段**，只取一段必然丢另一段 —— 而下游的 named/with_main
    本来就会在同构候选里按长度挑，不需要在更早的一步就把候选扔掉。
    一段都不合格就返回空列表，由调用方如实报「没取到代码」——
    「拿整段原文当代码」这条路**永远**不再走。
    """
    pat = re.compile(r"\b%s\s*\(" % re.escape(top)) if top else None
    out = []
    for body in _fence_segments(text):
        if not body or not _CODEISH.search(body):
            continue
        if "#include" not in body and not (pat and pat.search(body)):
            continue
        out.append(body)
    return out


def _longest_code_segment(text: str, top: str = "") -> str:
    """旧名（fix9 的唯一调用点已换成 `_code_segments`）；留着只给一次性排障用。"""
    segs = _code_segments(text, top)
    return max(segs, key=len) if segs else ""


def extract_blocks(text: str, top: str = "") -> tuple[str, str, str]:
    """从模型回复里取出 `(kernel, testbench, 说明)`。

    模型把代码放进围栏，但标签写得极不统一，且**顺序不定**（测试台可能在前）。
    所以判别不靠顺序、不靠标签，靠**结构**：

        含 `main` 的块  → 测试台
        含 `top(` 的块  → kernel（用 `top` 判别比「不含 main」准得多：
                          模型常把 interface 的头文件回显成一个单独的块）

    只有一块且它含 main 时，用 split_main 劈成两半（说明里如实写「我劈了」，
    模型下一轮能看见）。

    返回的「说明」是给 trace 与模型看的**如实记录**，不是装饰。
    """
    note = ""
    text = strip_think(text or "")
    raw = [b.strip() for _, b in _FENCE.findall(text)]
    # ★ 纯注释块不算代码。实测病灶（`results/agent-fix4-20261025/pair20-fix4-20261025/`，
    #   `machsuite__aes_aes` r1）：模型连开两个围栏 ——
    #       ```cpp / // kernel block 1 / ```cpp / #include "aes_aes.h" …（截断）
    #   `_FENCE` 非贪婪配对把前三行配成一个「块」，内容 17 B 的
    #   `// kernel block 1`；真正的 23 KB 落在**第二个未闭合围栏之后**。
    #   旧逻辑只要 `blocks` 非空就不进未闭合退让 ⇒ 17 B 注释成了提交，
    #   签名闸报「找不到定义」（闸没错，喂进去的是垃圾），修复提示又把
    #   `// kernel block 1` 当「你上一版的内核」给模型看 ⇒ 后两轮只回散文、
    #   一个代码块都没有，终局 L1。判掉纯注释块，下面就落到 `_unclosed_tail()`。
    blocks = [b for b in raw if _CODEISH.search(b)]
    if raw and not blocks:
        # 「真有代码吗」由下面两支各自给结论 —— 原来这句直接写死「按没取到代码处理」，
        # fix9 之后它可能只是**连开围栏**，代码在第二个围栏之后。
        note = "围栏里只有注释/小节标签、没有代码（多半是模型连开了两个围栏）"
    if not blocks:
        # 没有**闭合**的围栏：先看是不是「开了围栏但被截断」—— 那种回复的正文
        # 要从围栏那一行之后开始，否则 kernel 的第一行就是 ```cpp（见 _unclosed_tail）。
        tail = _unclosed_tail(text)
        if tail is not None and ("#include" in tail
                                 or re.search(r"\b%s\s*\(" % re.escape(top or "x"), tail)):
            blocks = [tail]
            note = (note + "；" if note else "") + (
                "回复的代码围栏没有闭合（多半被 max_tokens 截断），"
                "已取围栏之后的那段当代码")
        # ★ fix9（改动 A）：**有围栏行却配不成对**（连开两个、或整篇又包了一层）——
        #   绝不再走下面那条「整段原文」，它会把围栏行与散文一起写进 solution.cpp。
        elif any(_FENCE_LINE.match(ln) for ln in text.splitlines()):
            # ★ fix10（改动 P）：取**全部**像代码的段落，不再只留最长的一段 ——
            #   连开两个围栏切出来的 kernel 与测试台两段都要交给下游挑选。
            segs = _code_segments(text, top)
            if not segs:
                return "", "", ((note + "；" if note else "")
                                + "围栏配不成对、围栏之间也没有像代码的段落 —— "
                                  "没取到任何代码")
            blocks = segs
            note = (note + "；" if note else "") + (
                "围栏配不成对（多半是连开了两个围栏或整篇又被包了一层），"
                "已把围栏切出来的全部代码段落按顺序取用，围栏行没有写进 kernel")
        # 没有围栏：整体形似 C++ 就整段取用（官方 baseline.py:82-89 也做同样的退让）。
        elif "#include" in text or re.search(r"\b%s\s*\(" % re.escape(top or "x"), text):
            blocks = [text.strip()]
            note = (note + "；" if note else "") + "回复没有代码围栏，整段按代码取用"
        else:
            return "", "", "回复里既没有代码围栏，也不像 C++ —— 没取到任何代码"

    # ★ fix14（2026-10-28）：**围栏之外的代码段也算候选**，即使 `_FENCE` 已经配出了块。
    #   实测病灶（自适应轮 run8b k=4 `machsuite__stencil_stencil3d`；原始回复存档在
    #   `results/agent-adaptive-20261027/probe-r1-20261028/reply.txt`）：模型把每个
    #   「块」写成 **开围栏 + 标题 + 再开一个围栏 + 代码 + 一个闭围栏**：
    #       ```cpp / // Block 1: the kernel / ```cpp / <kernel> / ```
    #       ```cpp / // Block 2: the testbench / ```cpp / <测试台> / ```
    #   `_FENCE` 的非贪婪配对允许**带标签的行**去闭合前一个围栏 ⇒ 第一对「开+开」
    #   配成 23 B 的注释块（被 `_CODEISH` 判掉），「闭+开」配成空块，**真正的
    #   kernel 整段落在围栏之外**；同时测试台被配成一个完整块 ⇒ `blocks` 非空 ⇒
    #   上面三条退让一条都走不到 ⇒ kernel 只剩 testbench 里 `main` 之前那 246 B
    #   前缀，4 轮 × 2 次运行、0 次编译（判分 L1）。
    #   ⇒ 只要文本里有围栏行，就把 `_code_segments()` 切出来的代码段**补进候选**。
    #   下游的 named/with_main 本来就按结构挑，正常回复里这两段与块逐字相同、
    #   去重后一个都不加 —— 对正常路径是 no-op。
    if blocks and any(_FENCE_LINE.match(ln) for ln in text.splitlines()):
        have = {b.strip() for b in blocks}
        extra = [s for s in _code_segments(text, top) if s.strip() not in have]
        if extra:
            nb = len(blocks)
            blocks = blocks + extra
            note = (note + "；" if note else "") + (
                "围栏只配出 %d 块，另把围栏切出来的 %d 段代码也一并做候选"
                "（围栏行没有写进 kernel）" % (nb, len(extra)))

    with_main = [b for b in blocks if _MAIN_ANY.search(b)]
    kernel_pat = re.compile(r"\b%s\s*\(" % re.escape(top)) if top else None
    named = [b for b in blocks if kernel_pat and kernel_pat.search(b)]
    plain = [b for b in blocks if b not in with_main]

    if named:
        # ★ 先在「含 `top(`」里**去掉含 main 的**：含 main 的那个按定义就是测试台。
        #   只按长度挑会踩一个**真实形状** —— 测试台里当然也要调用 `top(...)`
        #   （差分测试台有参考实现 + 遍历用例，system.md 明确要求这个形状），
        #   于是名字判据两块都命中，而测试台通常更长 ⇒ `max(key=len)` 每次都选中
        #   测试台；再被 split_main 切掉 main，剩下的是一段**一次 `top(` 都没有的
        #   残渣** ⇒ 签名闸报「找不到定义」⇒ 一份好端端的 kernel 被自己的抽取器扔了。
        #   存档证据（真实模型回复）：
        #     results/hls-agent-20261001/pilot-diag-rawreply/chstone__df_add128/attempt5
        #     kernel 265 B（无 main、含 1 次 `add128(`）/ 测试台 1111 B（含 main）
        #     → 旧规则选中测试台 → split_main 后只剩 40 B 残渣、`add128(` 0 次。
        #   形状不成立时（只有一块、或全都含 main）原样退回旧路径，见下面与既有用例。
        no_main = [b for b in named if b not in with_main]
        kernel = max(no_main or named, key=len)
        tb = max(with_main, key=len) if with_main else ""
        if len(named) > 1:
            # ★ 追加，不覆盖 —— 前面那段「围栏配不成对、取了全部代码段落」（fix10 P）
            #   是 CHECK 数 `p` 的唯一依据；覆盖掉它，P 就变成一台只会报 0 的仪器。
            note = (note + "；" if note else "") + \
                "有 %d 个块含 `%s(`，取了最长的%s一个当 kernel" % (
                    len(named), top, "不含 main 的" if no_main else "")
        if kernel in with_main:
            # 那个块里既有 kernel 又有 main —— 劈开。
            kernel, tb2 = split_main(kernel)
            tb = tb2 or tb
            note = (note + "；" if note else "") + \
                "kernel 那块里含 main，已把 main 切出来当测试台（提交里不能有 main：官方测试台自带一个，重复定义会链接失败）"
        return kernel, tb, note

    if with_main and not plain:
        kernel, tb = split_main(max(with_main, key=len))
        if not tb:
            return (max(with_main, key=len), "",
                    "唯一一块含 main 但括号配不上，**没有切分** —— 跳过自验，"
                    "本轮只能做签名与语法层面的检查")
        return kernel, tb, ("只有一个代码块，已把其中的 main 切出来当测试台"
                            "（提交里不能有 main：官方测试台自带一个）")

    if plain:
        kernel = max(plain, key=len)
        tb = max(with_main, key=len) if with_main else ""
        if not tb:
            note = "回复里没有测试台 —— 本轮跳过自验（自验是本题最大的改进轴，下一轮请给两块）"
        return kernel, tb, note

    return max(blocks, key=len), "", "块结构无法判别，整块当 kernel 用"


def extract_code(text: str, top: str = "") -> str:
    """只要 kernel。run.sh 的契约只落 `solution.cpp` 一个文件。"""
    return extract_blocks(text, top)[0]


# --------------------------------------------------------------- mock 的测试台

def _mock_tb() -> str:
    """桩测试台：**故意失败**。

    它不调用 kernel，也不校验任何数值 —— 桩的用途是把管道跑通，不是给一个绿灯。
    所以它显式 `return 1`：桩跑出来的自验等级必然是「测试台没过」，
    于是修复环、trace 里的自验记录、以及「这一轮到底有没有拿到关于设计的结论」
    这条判据全都会被走到。**一个空转却报绿的桩比崩掉的桩更危险** ——
    它会让自验看起来工作正常，而实际上什么都没验。
    """
    return (
        "// MOCK BACKEND -- 桩测试台：故意不通过。\n"
        "// 桩不实现任何功能，所以正确的做法是让自验也如实失败，\n"
        "// 而不是伪造一个「自验通过」的绿灯。\n"
        "#include <cstdio>\n"
        "int main() {\n"
        "  printf(\"MOCK: stub kernel implements nothing; self-check fails by design\\n\");\n"
        "  return 1;\n"
        "}\n"
    )

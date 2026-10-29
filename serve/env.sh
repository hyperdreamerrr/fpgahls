#!/usr/bin/env bash
# 推理配置的**参考定义** —— 由操作者/评测方 source 后再调 run.sh。
#
# ⚠ 本文件不是 run.sh 或 run_baseline.sh 的依赖。那两份是官方原件、**不得
#   修改**（官方 example/README.md 的表格里 run_baseline.sh / baseline.py 标
#   「不得修改」，SCORING.md 的提交前清单第 364 行也要求「保持赛事方原样」），
#   它们内部**不会** source 本文件。真正的注入方式由调用方在环境里给
#   （官方契约：`LLM_BACKEND=mock bash run.sh <in> <out>`）。本文件的定位因此是
#   「一份可 source 的参考配置」，不是「唯一入口」。
#
# 所有默认值都写成 `${VAR:-...}`：**环境里已有的值优先**，本文件只补缺省。
# 这样评测方用环境变量下发的配置不会被本文件覆盖。
#
# 用法：  source serve/env.sh

set -u

# ── 〇、两个模型名变量 —— 本文件最要紧的一段 ────────────────────────────────
#
# **分子与分母读的是两个不同的名字，这是官方的设计，不是笔误：**
#
#     agent/llm.py       读 `LLM_MODEL`                      （缺省 "mock-model"）
#     baseline.py        读 `MODEL_NAME`；取不到就退回 `served_model()`，
#                        而那个函数拿的是 `<LLM_BASE_URL>/models` 列表的**第 0 个**
#
# 官方栈里两者能对上，靠的是服务端把「服务名」起成与 `LLM_MODEL` 相同的值。
# 本包 `serve/llamacpp.sh` 现已**显式** `--alias "$SERVED_NAME"`（缺省
# nemotron-3.5-lightning-c512k），不再依赖 `$(basename $MODEL)` 的巧合。换一个
# 服务端（例如本机 Ollama，`/v1/models` 列出全部已装模型）第 0 个就可能**不是
# 你正在用的那个模型**：分母换了个模型，不报错，只给出一个很像真的增益。
# 官方 selftest 自己也点了这一类（「两边用不同的模型，算出来的增益没有意义，
# 却看不出异常」）。
#
# ⇒ 所以本文件**两个都导出、且归一到同一个值**，并把「两个都设了但不相等」
#   判成配置错误（die），而不是替谁做主。
export LLM_MODEL="${LLM_MODEL:-${MODEL_NAME:-nemotron-3.5-lightning-c512k}}"
export MODEL_NAME="${MODEL_NAME:-$LLM_MODEL}"
if [ "$MODEL_NAME" != "$LLM_MODEL" ]; then
    echo "!! 两个模型名不一致：LLM_MODEL=$LLM_MODEL 而 MODEL_NAME=$MODEL_NAME" >&2
    echo "   agent 发 LLM_MODEL、baseline.py 发 MODEL_NAME —— 分子分母会跑两个不同的模型。" >&2
    echo "   若这是有意的，请显式改本文件；若只是改了其中一个，两个都改。" >&2
    return 1 2>/dev/null || exit 1
fi

# ── 一、推理栈 ──────────────────────────────────────────────────────────────

# 后端。默认 mock 是刻意的：这样没有推理服务的机器也能跑通链路。代价是忘了
# 设置它就会交出桩代码（桩体自带注释、且 `backend` 会进 trace.jsonl，所以不是
# 无声的）。**申报配置要求设为 openai** —— 见 model/MODEL.md。
export LLM_BACKEND="${LLM_BACKEND:-mock}"

# 服务地址。缺省取**官方 baseline.py 的同一个缺省**（`BASE_URL` 那行的
# `http://127.0.0.1:8000/v1`）—— 指南 3.1.5.2 要求 run.sh 与 run_baseline.sh
# 指向同一服务，把缺省设成一致是最省事的保证方式。
# 开发期走宿主机 Ollama 时显式覆盖为 http://127.0.0.1:11434/v1。
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:8000/v1}"

# API key。缺省空串是对的：本地服务（llama.cpp / Ollama）不校验。**这里不能写死
# 任何真实凭据** —— 提交包会被哈希冻结并交给评测方复现，密钥进包等于泄露。
export LLM_API_KEY="${LLM_API_KEY:-}"

# ── 二、采样口径：前三项必须与官方 baseline.py 的常量同值 ───────────────────
#
# 官方 `baseline.py:34-37`（2026-10-19 版）那一段写着「以下常量构成基线口径，不要改」：
#
#     TEMPERATURE = 0.0      TOP_P = 1.0      MAX_TOKENS = 16384     TIMEOUT_S = 840
#
# 指南 3.1.5.2 要求两个入口「同一推理服务与同一上下文配置」。分母那侧的采样
# 常量由赛事方固定、不得修改，所以能动的只有本包这一侧；我们若不是这三个值，
# 增益的分子与分母就是在不同采样条件下测的，那个比值解释不了。
#
# ★ `TIMEOUT_S` 是例外，本包取 **600** 而不是 840：它是**客户端读超时**，不是
#   采样参数 —— 同一段 (prompt, 采样口径) 生成什么与等多久放弃无关。840 是
#   基线**单次请求**的读超时（基线一次调用写到底），而本智能体一题内有多轮、
#   每轮的等待由 `AGENT_DEADLINE_S` 统一收口；600 是官方 example agent 的取值。
#   （`baseline.py` 并不读 `LLM_TIMEOUT_S`，它用的是自己那个常量，两者互不影响。）
#
# **采样口径（temperature / top_p）与官方常量逐条同值**；`max_tokens` 不是采样
# 口径，是**每轮预算** —— 2026-10-22 起本包取 8192（预登记
# `results/deadline-removal-20261022/PREREG.md` §2.3），基线那侧仍是 16384。
# 本文件只是把出厂值显式化。改这里之前先想清楚分母是谁。
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-8192}"
export LLM_TEMPERATURE="${LLM_TEMPERATURE:-0.0}"
export LLM_TOP_P="${LLM_TOP_P:-1.0}"
export LLM_TIMEOUT_S="${LLM_TIMEOUT_S:-900}"

# ⚠ 本包这一组（8192 / 900）**本身还没有实测读数**。已有的 A1–A4 四臂是
#   **官方 example 智能体**的读数，口径是 4096/180（+ 温度 0.2、top_p 不夹带），
#   与本包出厂默认**在采样轴上不可比** —— 跨臂引用时必须写明这一条，
#   把这一组的分子配那四臂的分母会得到没有意义的数。

# ── 三、差异项：本方案与基线的分野（**缺省关闭**）────────────────────────────
#
# 官方 baseline.py 写着「请求仅使用 OpenAI 标准字段，不含厂商专有参数」，
# 所以它能发什么是固定死的；智能体不受这个限制。
# **两个都留空 = 请求体与标准 OpenAI 请求逐字节相同**，也就是与已测口径可比的
# 那个形态。差异项必须是**显式打开**的，不能默认就悄悄生效。
export LLM_THINK="${LLM_THINK:-}"
export LLM_EXTRA_BODY="${LLM_EXTRA_BODY:-}"

# ⚠ 两个后端的字段名不同，同时发会被对面 400，按后端选（本机实测）：
#     llama.cpp（申报路径）：LLM_THINK=false（`--jinja` 下才被模板接受）
#     Ollama（开发路径）：   LLM_EXTRA_BODY='{"reasoning_effort":"none"}'
#   注意 `options.num_ctx` 与顶层 `think` 都是**原生 /api/chat 的字段**，
#   OpenAI 兼容端点收下就丢、不报错 —— 在 /v1 上压上下文请用 Modelfile
#   派生一个模型（`PARAMETER num_ctx 4096`），blob 共享、不额外占盘。
#
# ★ `LLM_THINK` 是**开发期覆盖**，不是申报口径的一部分。申报的思考设置写在
#   manifest.json 的 `generation` 块里，agent 与 baseline 都读它；本变量只在
#   预登记的 A/B 探针里临时压过它。出厂留空 = 完全按申报值发。
#
# ★ 收益侧（HLS 赛道）**没有做过关思考的 A/B**，别把「字段可用」当成「该开」。
#   已测的是**预算**那一轴（同一套题目，agent 的 LLM_MAX_TOKENS 从 4096 提到
#   8192）：增益 1.1333 → 1.0000，一题翻满、两题归零。机制是 8192 撞在本机
#   180 s 的读超时上 —— 读超时是**致命**的（官方 example 把整个解题包在一个
#   try 里，超时从 except 逃出循环、写空产物），撞帽反而可重试。
#   本包的 LLM_TIMEOUT_S 缺省 900（2026-10-22 起；旧值 600）。
#
# ★ 2026-10-25 起，**申报口径本身就是关思考**（`manifest.json` 的
#   `generation.chat_template_kwargs = {"enable_thinking": false}`，两臂都读）。
#   起因不是「字段可用」，是**服务端实测的机制**：思考通道与正文共用
#   `max_tokens`，8,192 的帽被思考吃光时正文**零字节**
#   （`results/agent-fix-20261025/PREREG.md` §2 的探针表：关思考 ⇒ reasoning 0 B、
#   正文 2,503 B、17.5 s；不关 ⇒ 帽内全是思考）。10-23 面板 agent 52 次调用里
#   36 次零正文、7 题三轮全零，就死在这一点上。
#   本变量仍只是**开发期覆盖**：出厂留空 = 完全按申报值（现在是关）发。

# ── 四、智能体自己的预算（读它的是 agent/main.py，不是 baseline.py）─────────
#
# 单题墙钟上限。**缺省 0 = 不设内部截止**（2026-10-22 预登记
# `results/deadline-removal-20261022/PREREG.md` §2.1）。
# 为什么改：服务器3 全量跑的前 91 题里，54 次生成撞满 ~900 s 内部截止、
# 其中 48 次判 L0 —— 截止把「还能救的轮」连同已有候选一起收掉，是我们自己
# 先截了自己一刀。外层墙仍在：官方 `deadline_s + 20`、运行器的单题 kill
# （3600 s）、以及 agent 自己的 `LLM_TIMEOUT_S`（900）与 `MAX_ROUNDS`（3）。
# 设成正数即恢复旧的「内部截止」行为（例如 `AGENT_DEADLINE_S=900`）。
export AGENT_DEADLINE_S="${AGENT_DEADLINE_S:-0}"

# 其余几个预算旋钮**刻意不导出**，保持代码默认（agent/main.py 里各有一行缺省）：
#   AGENT_MAX_ROUNDS / AGENT_RESERVE_S / AGENT_MIN_TOOL_S / AGENT_CSYNTH_MIN_S /
#   AGENT_CSYNTH。导出它们等于把它们变成申报口径的一部分，而它们还没有实测
#   支撑。要用请显式在命令行给。

# ── 五、综合目标（官方 Dockerfile 也设了这两个）─────────────────────────────
#
# 器件与时钟周期必须与 model/MODEL.md 的声明一致。官方基础镜像已经把这两个
# 值写在 ENV 里，这里重复一遍是为了让**不带那个镜像**的本地跑法也能对齐。
export HLS_PART="${HLS_PART:-xczu3eg-sbva484-1-e}"
export HLS_PERIOD_NS="${HLS_PERIOD_NS:-5}"

# ── 六、赛道 ────────────────────────────────────────────────────────────────
#
# 读这个环境变量的是两处：run_baseline.sh（`${TRACK:-hls}`）与 baseline.py
# 选择 SYS / OUT_NAME 那一段。写清楚是因为「被两处读取」这种话会被下一个人
# 当真：真去改 TRACK 时，只有这两处会跟着动。
export TRACK="${TRACK:-hls}"

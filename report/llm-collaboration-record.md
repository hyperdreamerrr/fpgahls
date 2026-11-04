# 大模型协作记录

**项目：** 2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 赛道 3.1（AMD HLS）
**配套文件：** `REPORT.md`（设计报告）。本文件对应赛道指南 3.3.3.1 与 3.3.5.3 的「大模型协作记录」。
**版本：** 1.0 · 2026-11-04
**引用约定：** 引文逐字；节选处标「节选」，省略处用 `……`；文件哈希为 sha256；`trace.jsonl` 里的 `sha16` 是该轮抽出件 sha256 的前 16 位十六进制。**分数只引官方判分链**，大模型给出的任何分数、增益或归因都不作证据。

---

## 0. 官方要求与记录范围

赛道指南（`docs/TRACK_GUIDE_2026.md`）在两处规定了本文件的内容：

- 3.3.3.1：「允许使用任意公开大模型、微调后的本地模型，以及基于大模型构建的智能体应用。**须提交体现大模型协作过程的交互记录**，含提示词、模型回答与自我纠错轨迹。」
- 3.3.5.3：设计报告须含「大模型协作记录：提示词、模型回答、自我纠错轨迹、智能体工作流设计（如有）」。

本记录按**两层**写，因为本项目的「大模型协作」发生在两个互不相交的位置：

1. **运行时协作（在评测链路上）**：提交包内的智能体在每一题上调用申报模型，按轮生成、自验、修补。提示词、工具反馈与逐轮事件都在包内，运行时写入 `trace.jsonl`。这是方案的一部分，参与评分。
2. **开发期协作（不在评测链路上）**：Claude Code CLI 作为开发助手，参与代码审阅、故障诊断、仪器脚本与文档修订。它不是方案的一部分，不参与评测运行，也不产生任何得分。

两层共用同一条证据规则：**能追到文件与哈希的才写进来；不能追到的，明确写「未落盘」或「未测」。**

---

## 1. 协作角色与边界

| 角色 | 模型 / 工具 | 版本与配置 | 在评测链路上？ | 证据 |
| --- | --- | --- | --- | --- |
| 运行时生成模型（申报） | Nemotron-3.5-Lightning-30B-A3B（GGUF UD-Q4_K_M） | `llama-server 0.4.0-dev`；`-c 524288 -ngl 999 --jinja`；本地权重、断网；T=0.0、top_p=1.0、max_tokens=8192 | **是**（方案臂；与基线共用同一服务） | `manifest.json`；`trace.jsonl` 的 `agent/start` |
| 基线 | 同一服务，官方 `baseline.py` | 赛事方原件，未改动 | **是**（基线臂） | `run_baseline.sh` |
| 开发期候选模型 | qwen3-8k / qwen3.8-c192k / muse / glm / devstral / nemotron / qwen3.6 / gemma / qwen3-coder / seed-oss / qwen3.8-distill | 开发栈 20 题同协议双臂 | 否（选型用，不进申报包） | `REPORT.md` §12.1 |
| 开发助手 | Claude Code CLI，会话底层模型 `deepseek-v4.1-flash`（服务名 `deepseek-flash`） | 经 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 接入 | **否**（不在 `run.sh` / `run_baseline.sh` / `judge.py` / `score.py` 的任何调用路径上） | `REPORT.md` §12.1 |
| 技能包 | 15 条 `SKILL.md` + 确定性加载器 | 第 1 轮不注入，其后每轮至多 2 条；按日志签名匹配 | 是（文本可被注入提示词） | `skill/README.md`；`agent/skills.py` |

**边界声明。**

- 评测沙箱断网；包里没有开发助手的配置、凭据或调用代码。
- 运行时只有一个生成式模型。技能包是**确定性加载的文本**，不是第二个模型；加载器不调用模型做路由（`agent/skills.py` 的注释写明：「Selection is deliberately dumb. A model-driven router would be more flexible but costs a round trip, and a wrong route is expensive under a wall clock budget.」）。
- 本记录不把开发助手的任何建议当结论。每条建议的落地都经过编译、判分或对账（§5.2）；没有经过这些的，标为「未验证」。

---

## 2. 智能体工作流设计（运行时）

### 2.1 单题契约

```
run.sh <输入目录> <输出目录>
  输入：prompt.txt / interface.txt / top.txt
  输出：solution.cpp / trace.jsonl
```

- 智能体只读这三件；**不读**输入目录里的 `*_tb.cpp` 与 `reference/`（官方明禁，见 #116）。
- 无论成败都写出 `solution.cpp` 与 `trace.jsonl` 并退出 0 —— 「解不出来」与「服务坏了」必须在协议层分得开。
- 交付件只保留 kernel（`solution.cpp`）；测试台只在运行目录里使用，不随交付件落盘。

### 2.2 主循环

```
for rnd in 1..MAX_ROUNDS:
    plan_round(...)            # k / fair_s / 本轮 max_tokens
    拼提示词                    # r1: system + task；r2+: 会话 + repair 模板
    llm.generate               # T=0, top_p=1, stream, max_tokens=8192
    extract two blocks         # kernel + testbench
    signature gate             # 零 EDA 成本的确定性签名比对
    selfcheck                  # host syntax → csim setup → csim run
    失败分类                    # kernel-compile / tb-compile / runtime / ...
    repair-log                 # 失败类别 + 历史 + 工具原文 + 上一版 kernel
    if 自验 level >= 3: csynth # 综合关（内部 L4 候选）
    保留 best（按 (kernel_ok, level) 排序）
写 solution.cpp、trace.jsonl
```

这是「**生成 → 过闸 → 修补**」的闭环：模型只在生成步出手；签名、编译、运行、综合都是确定性工具，模型看不到也改不了判据。

内部等级与官方阶梯的对应关系要说清楚，不能混：

| 内部事件 | 含义 | 与官方阶梯的关系 |
| --- | --- | --- |
| `signature` | 交付 kernel 的签名与接口一致 | 官方 L2 的必要条件，不是充分条件 |
| 自验 level 1 | 源码自己编不过（host syntax 或 csim setup 失败） | 官方 L1/L2 之前 |
| 自验 level 3 | **自写**测试台编译并运行通过 | **不等于官方 L3**；官方测试台仍可能挂（`selfcheck` 的 note 原文：「自写测试台通过（**不是**官方测试台，官方那关仍可能挂）」） |
| `csynth` rc 0 + `accept-l4` | 综合通过，智能体接受为 L4 候选 | 官方 L4 的必要条件；官方仍可能判低 |
| 官方判分 `judge.py` | 官方测试台 + 官方阶梯 | **唯一得分依据** |

### 2.3 轮次预算

墙钟是被计分的资源，因此每轮的可生成预算不是固定值，而是按剩余时间现算。`REPORT.md` §13.1 抄录的 `plan_round()`：

```python
k = 0
for cand in range(max(1, rounds_left), 0, -1):
    if remaining_s / cand - MIN_TOOL_S >= MIN_LLM_S:
        k = cand; break
fair_s = remaining_s / k - MIN_TOOL_S
return k, fair_s, int(min(cap_hard, max(CAP_MIN, TPS_EST * fair_s)))
```

这是 `REPORT.md` §13.1 的节选式抄录（`k = cand; break` 折成一行），完整函数（`agent/main.py:255-287`）还含两个分支：一个候选都装不下时**不放弃**，回退到 `k = 1` —— 注释原文「★ 一组都装不下时**回退到 1**，而不是放弃：**截断的一轮不是零**。」（`agent/main.py:277-283`）；`fair_s <= 0` 时返回 `k = 0`、本轮不开（`agent/main.py:285-286`）。

`trace.jsonl` 的 `round-plan` 事件逐轮记下 `k`、`fair_s`、`max_tokens`、`remaining_s`。本记录引用的两次运行里，`k` 逐轮递减（add 为 4→3→2，gram 为 4→3→2→1），`max_tokens` 恒为 8192 —— 因为这两次运行 `deadline_s=0.0`（`agent/start` 记录，不设内部截止），`remaining_s` 是哨兵值 `1000000000.0`，预算不构成绑定约束。**这一点必须写明**：这两条轨迹展示的是「轮次与反馈」的形状，不是「预算压缩」的形状；预算机制的证据在 `REPORT.md` §6.4 与 §9。

### 2.4 失败分类与修补

修补轮的模板是 `agent/prompts/repair.md`（324 B，sha256 `6df7624935f09fa66553dbe1247849d89e370967e747d7b681dbcb509a6216f7`）。全文：

````text
## Your previous attempt failed

**Failure class:** {{KIND}}
{{HISTORY}}
**What the tools reported:**

```
{{LOG}}
```
{{FOCUS}}
**Your previous kernel:**

```cpp
{{CODE}}
```

Reply with the same two blocks as before: the corrected kernel first, then the
testbench. Keep the parts that were not implicated in this failure.
````

模板只有槽位，没有题目名、没有答案。槽位由同一条修补管线填：

1. **失败类别** `{{KIND}}`：kernel-compile / tb-compile / runtime / …。
2. **历史** `{{HISTORY}}`：前几轮交了什么、各自被判成什么、哪两轮交的是同一份文件（`agent/main.py:1706` 的注释）。
3. **工具原文** `{{LOG}}`：编译器的行号与错误文本，或测试台的退出码与打印。
4. **聚焦段** `{{FOCUS}}`：编译器指着的那一行，连同插入符，从 `{{CODE}}` 里就地取出来（`agent/main.py:1707`）。
5. **上一版 kernel** `{{CODE}}`：只回 kernel，不回测试台（`agent/main.py:533` 的注释：「`repair.md` 只有 `{{CODE}}`（kernel），TB 原文从来没回过模型」）。

在此之上，`repair-log` 事件会按错误类型追加一条**针对性规则**。本记录的成功例里命中的是 `array-bitop`（§4.1）；`trace.jsonl` 的 `rule` 字段记下规则名。**`add_log_bytes` 不是规则文本的字节数**：它只记 `_diagnosis_tail` 那一段（level 2 或测试台超时等情形），规则文本并入 `log` 的总字节 `bytes`；`agent/main.py:2105-2109` 是 `add_log_bytes` 唯一的赋值点（只取 `_diagnosis_tail`）；`agent/main.py:2115-2117` 的注释明确说规则文本的字节不并进 `add_log_bytes`（与 rule2/rule3 同一约定，「那是 fix7 以来的一把尺子」）。本记录引用的两次运行里 `add_log_bytes` 都是 0，而 `array-bitop` 的规则文本确实在 `log` 里（`bytes` 1,220 / 1,559）—— 这正是两把尺子不同义的现场。另一条与「原地打转」有关的机制是**逐字节停滞检测**：当本轮抽出件与上一轮逐字节相同，下一轮的 `repair-log` 会前置一段「不许原样重贴」的指令（§4.1 / §4.2 各引一次原文）。

技能注入是另一条并行通道，但**不是每轮都开**：`skills` 策略为 `mode=on, limit=2, min_round=2`，即第 1 轮不注入，其后每轮至多 2 条，只有当日志命中某条技能的 `Log signatures` 时才被选中。本记录引用的两条 trace 里没有出现注入事件（`skills` 事件只记了 `loaded` 的 15 条名录）——**这两例的修补由提示词与工具反馈驱动，不能记在技能包头上**。

### 2.5 trace.jsonl

每一次模型调用与工具调用写一行 JSON。每行都有 `tool` 字段；只有 `agent` 这一路另带 `event`，本表把这类行写成 `agent/<event>`（`agent/start` 即 `{"tool":"agent","event":"start"}`），其余行直接写 `tool` 的取值（如 `round-plan` 即 `{"tool":"round-plan", …}`，没有 `event` 字段）。与本记录相关的字段：

| 事件 | 关键字段 | 用途 |
| --- | --- | --- |
| `agent/start` | `llm`（模型、T、top_p、max_tokens、stream）、`max_rounds`、`deadline_s`、`skills` 策略、`interface_bytes`、`prompt_bytes` | 运行身份与配置 |
| `env` | `vitis_available`、`vitis`、`part`、`period_ns` | 工具链环境 |
| `skills` | `loaded` | 加载了哪些技能（不是注入） |
| `headers` | `recovered` | 从 interface 恢复出的头文件 |
| `round-plan` | `round`、`k`、`fair_s`、`max_tokens`、`remaining_s` | 本轮预算 |
| `prompt` | `sha16`、`user_bytes`、`msg_bytes`、`msgs`、`code_src`、`code_sha16`、`repair`、`attempts`、`focus` | 拼出的提示词形状 |
| `llm` | `tokens_out`、`content_bytes`、`finish_reason`、`truncated`、`elapsed_s` | 模型回复的元数据 |
| `extract` | `kernel_bytes`、`tb_bytes`、`kernel_sha16`、`tb_sha16`、`note` | 从回复里抽出的两个代码块 |
| `signature` | `ok`、`note` | 签名闸 |
| `selfcheck` | `level`、`kok`、`kind`、`note`、`stages`、`excerpt` | 自验结果与工具原文 |
| `agent/selfcheck-pass` | `level` | 自验通过（本记录的成功例为 level 3） |
| `repair-log` | `kind`、`log`、`bytes`、`add_log_bytes`、`rule`、`stagnant` | 下一轮修补文本的构成 |
| `csynth` | `rc`、`elapsed_s`、`excerpt` | 综合关 |
| `agent/accept-l4` | `round` | 内部接受为 L4 候选 |
| `agent/done` | `bytes` | 最终交付的 kernel 字节数 |

本记录引用的两条完整轨迹：

- `results/agent-adaptive-20261027/remote/run2/agent/out/c2hlsc__add_round_key/trace.jsonl`（12,587 B，sha256 `de8a3bc14f5b918599213bbcfc228fe6290627092db36fb3dfbac7bd60834da3`）
- `results/agent-adaptive-20261027/remote/run2/agent/out/hls_polybench__fixed__small__gramschmidt/trace.jsonl`（19,819 B，sha256 `01564f0a212398dc86469e3336246a091cdc67f2324eeb9f82a562ffd50da979`）

这两条轨迹来自同一次 20 题面板运行（2026-10-27/28，AMD 实例）；全量 122 题的结果见 `REPORT.md` §6.2.1。本记录只从面板里取两题做「一次成功、一次失败」的逐轮解剖，**不把面板读数当全量结论**。

---

## 3. 提示词记录

### 3.1 系统提示词

文件：`agent/prompts/system.md`；10,606 B；sha256 `e339ce645ddcb4ae65481e5fdab0c5ebf84191f7723fcc5b66bdbde654177bd6`。它是每一轮第一条 system 消息的主体，决定了回复形状与判据边界。以下为逐字节节选（原文换行保留）。

**（a）回复格式：恰好两个围栏块，先 kernel 后测试台。**

````text
## Your reply format — exactly two fenced blocks, in this order

**Block 1 — the kernel.** ` ```cpp ` … ` ``` `. A complete translation unit that
implements the top-level function. It must:

- define the top-level function with the **exact signature from the interface** —
  same name, same parameter types in the same order, same array dimensions.
  The official testbench calls it by that name and includes the given header.
  A changed signature does not compile-and-link, and a submission that fails to
  link scores **lower than one that merely computes the wrong answer**.
````

**（b）接口就是规格：不许自己发明输入。**

```text
## The interface is the specification — never invent an input

The signature is the contract, not a hint. The official testbench passes every
parameter, and the reference output was produced by an implementation that used
every one of them.
```

**（c）数值必须匹配一个特定实现，不是「数学等价」。**

```text
## Your numbers must match one specific implementation

Your output is compared element by element against the output of **one
particular reference implementation**, at a tight tolerance (typically 1e-6
relative). "Mathematically equivalent" is not the standard. Floating-point sums
depend on which terms are added, in what order, and how they round; the
comparison sees only the numbers, never your intent.
```

**（d）判分阶梯：L1 解析 / L2 编译 / L3 官方测试 / L4 综合。**

```text
## How you will be judged

Your kernel is compiled together with the **official** testbench — which you do
not see — and graded on a strict ladder:

    L1  the source parses
    L2  it compiles together with the official testbench into a csim executable
    L3  that executable runs and passes every official test case
    L4  it additionally synthesizes

Each rung requires all the rungs below it. "It compiles" and "it synthesizes" say
**nothing** about whether it computes the right answer; only running it does.
```

**（e）看到失败时，只改被指出的那一处。**

```text
## If you are shown a failure from a previous attempt

Fix that specific failure. Do not silently rewrite the whole kernel — a rewrite
throws away the parts that were already verified. When the previous attempt is
shown, prefer a minimal, targeted edit.
```

**一个必须说明的版本差异。** 本记录第 4 节的两条轨迹**不是**用当前这版 10,606 B 的 `system.md` 产生的。部署树当时的 `system.md` 是 **8,932 B**，有两处独立互证：

- 两条 trace 的 R1 都满足 `msg_bytes − user_bytes = 8,932`（add_round_key：11,933 − 3,001；gramschmidt：9,797 − 865）；
- 探针归档 `probe-r1-20261028/report.txt` 第一行记 `system.md 8932 B`。

当前包内版本在此后经过开发迭代增至 10,606 B。**本记录因此把「提示词设计」与「轨迹的因果」分开陈述**：§3 引用当前包内文本，§4 引用轨迹当时实际产生的工具事件；不把两者当作同一次因果。

### 3.2 任务块

题面与接口由 `build_task_block()` 拼成（`agent/main.py:396-404`，逐字节）：

```python
def build_task_block(prompt: str, interface: str, top: str) -> str:
    return (
        "## Task\n\n" + (prompt or "(empty)") +
        "\n\n## Top-level interface (the signature must not change)\n\n```cpp\n"
        + (interface or "(empty)") + "\n```\n"
        + "\nThe top-level function is named exactly `%s`. "
          "The official testbench calls it by that name and includes the header above.\n" % top
    )
```

它只做三件事：放题面、放接口、点名顶层函数。**不注入题目目录里的测试台或金标**（#116）。两条轨迹的任务规模：

| 题 | `prompt_bytes` | `user_bytes`（R1） | `msg_bytes`（R1） | `interface_bytes` |
| --- | ---: | ---: | ---: | ---: |
| `c2hlsc__add_round_key` | 2,338 | 3,001 | 11,933 | 452 |
| `hls_polybench__fixed__small__gramschmidt` | 383 | 865 | 9,797 | 264 |

### 3.3 一轮会话的拼装

R1 是 `[system, user]` 两条消息；R2 起是「会话 + 一条修补消息」，`msgs` 逐轮增加。`trace.jsonl` 的 `prompt` 事件给出形状：

| 轮 | `msgs` | `user_bytes` | `msg_bytes` | `prompt.sha16` | `code_src` |
| --- | ---: | ---: | ---: | --- | --- |
| add R1 | 2 | 3,001 | 11,933 | `20a4e7d04610fe83` | `-` |
| add R2 | 4 | 2,179 | 16,019 | `7e425c6ce31fc071` | `last` |
| add R3 | 6 | 2,869 | 20,425 | `4e1b97d6719ce2fd` | `last` |
| gram R1 | 2 | 865 | 9,797 | `b14c69e39021135b` | `-` |
| gram R2 | 4 | 4,040 | 22,764 | `16a6ad33cfc302de` | `last` |
| gram R3 | 6 | 3,542 | 32,893 | `ef9e2e982300ec4d` | `last` |
| gram R4 | 8 | 4,301 | 43,793 | `6f43c6b7713d7a11` | `last` |

这张表本身就是一条证据：**修补消息携带的是上一版 kernel 与工具原文，不是整段重写**；`user_bytes` 不随轮数单调增长，说明每次只带必要上下文。

---

## 4. 模型回答记录

### 4.1 一次成功的修复循环：`c2hlsc__add_round_key`

**运行配置**（`agent/start`）：模型 `nemotron-3.5-lightning-c512k`；T=0.0、top_p=1.0、max_tokens=8192、stream；`max_rounds=4`；技能 `mode=on, limit=2, min_round=2`。**该次运行未命中技能注入**（无注入事件），修补由提示词与工具反馈完成。

**逐轮读数**（`trace.jsonl`；kernel 字节数与 sha16 均来自 `extract`）：

| 轮 | 回复 `content_bytes` | kernel | kernel sha16 | 自验 level | 工具原文（节选） | 关键事件 |
| --- | ---: | ---: | --- | ---: | --- | --- |
| R1 | 1,907 | 330 B | `6c3af826cfc34005` | 1 | `invalid operands ... 'operator^'` | `selfcheck` |
| R2 | 1,537 | 330 B | `6c3af826cfc34005` | 1 | 同一错误 | `repair-log`：`rule=array-bitop` |
| R3 | 1,540 | 333 B | `2634fffe3d479af6` | 3 | — | `selfcheck-pass` → `csynth rc 0` → `accept-l4`；`done bytes=333` |

**R1 的失败原文**（`selfcheck.note` / `excerpt`，逐字）：

```text
kernel.cpp:9:25: error: invalid operands of types ‘uint8_t [4]’ {aka ‘unsigned char [4]’} and ‘uint8_t’ {aka ‘unsigned char’} to binary ‘operator^’
```

**R2 的修补文本**（`repair-log.log` 的规则段，逐字；`rule=array-bitop`。该事件 `add_log_bytes=0`、`bytes=1,220` —— 规则文本在 `log` 里，不记进 `add_log_bytes`，见 §2.4）：

````text
上一轮的编译错误里，`^` 两侧的操作数是**数组类型** —— 数组**不能整体做位运算**，这个写法在语法上就走不通。正确写法是按下标循环，对每个元素单独做一次（例如 `out[i] = a[i] ^ k;`）。只改这一处，不要重写算法。★ 先把星号与括号数清：形参写成 `T (*p)[A][B]` 时，`p[i]` 是**第 i 个数组**、`p[i][j]` 仍是**一维数组** —— 要落到元素上得写 `(*p)[i][j]`；形参写成 `T *p` 时 `p[i]` 就已经是元素。按**形参声明的层级**决定还要补几层下标，不要照抄示例的下标个数。
````

**模型在 R2 做了什么。** R2 的 kernel 与 R1 **逐字节相同**（sha16 同为 `6c3af826cfc34005`），但测试台变了（`tb_sha16` 从 `1ffe8663c38b9811` 变为 `c2e45e4ce9aee704`）。也就是说：模型把修补力气花在了测试台上，没有动被编译器点名的 kernel。结果 R2 仍然在同一行、同一错误上失败。

**R3 的停滞提示**（`repair-log.log` 前缀，逐字；该轮 `stagnant="kernel"`）：

```text
**你这一轮交的 kernel 与上一轮逐字节相同**（变的是测试台）。若测试台已经把错误定位到具体一行，就只改那一行：先写两行「改前 / 改后」，再给完整代码块；若定位不到，就改测试台让它打印出错的用例下标与两边的值，不要原样重贴同一份 kernel。
```

**R3 的回答**（`solution.cpp`，333 B，sha256 `2634fffe3d479af64e6f118239f388ab7d980c594832c5514f43bc018414f26f`，逐字）：

```cpp
// add_round_key.cpp
#include "add_round_key.h"
#include <stdint.h>

void AddRoundKey(uint8_t round, state_t *state, const uint8_t *RoundKey) {
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {
            int idx = (round * Nb * 4) + (i * Nb) + j;
            (*state)[i][j] ^= RoundKey[idx];
        }
    }
}
```

改动就是规则说的那一处：从「对数组整体做 `^`」改成「按 `(*state)[i][j]` 逐元素做」。签名一个字符没动；`{`/`}` 各 3 个，平衡；333 B。

**结果（内部与外部分开记）。** 内部：自验 level 3（自写测试台通过），`csynth rc 0`，`agent/accept-l4`。外部：同一次面板运行的官方判词 `agent.c2hlsc__add_round_key.s1.json` 给出 **level 4、coefficient 1.0、parse/compile/run/synth 全 true、elapsed 15.3 s**。这是「内部自验到 L4 候选，官方判分确认 L4」的一例；它**不能**推广成「自验 level 3 就等于官方 L3」——`REPORT.md` §6.5 记了反例：有 4 题自验 level 3 仍判 L2。

### 4.2 一次失败的震荡：`hls_polybench__fixed__small__gramschmidt`

**运行配置**同上（同一批、同一模型、同一策略）。**该次运行同样没有技能注入事件。**

**逐轮读数**：

| 轮 | 回复 `content_bytes` | kernel | kernel sha16 | 自验 level | 工具原文（节选） | 关键事件 |
| --- | ---: | ---: | --- | ---: | --- | --- |
| R1 | 8,921 | 3,004 B | `9c040a50e9f13b37` | 1 | `kernel.cpp:96:2: error: expected '}'` | `extract` 记「围栏配不成对」 |
| R2 | 6,581 | 2,462 B | `8f65903470e7bf0d` | 1 | `kernel.cpp:83:2: error: expected '}'` | 仍缺右花括号 |
| R3 | 6,587 | 2,462 B | `8f65903470e7bf0d` | 1 | 同一错误 | `stagnant` 在下一轮置 `both` |
| R4 | 6,922 | 2,511 B | `2ba028e2e433e6c4` | 1 | 仍为第 83 行同一错误 | `repair-log` 前置「不许原样重贴」 |

**R1 的失败原文**（逐字）：

```text
../../../../kernel.cpp:96:2: error: expected '}'
```

**R1 的抽取器记录**（`extract.note`，节选；逐字）：

```text
围栏里只有注释/小节标签、没有代码（多半是模型连开了两个围栏）；围栏配不成对（多半是连开了两个围栏或整篇又被包了一层），已把围栏切出来的全部代码段落按顺序取用，围栏行没有写进 kernel；有 2 个块含 `kernel_gramschmidt(`，取了最长的不含 main 的一个当 kernel
```

这条 note 是理解整段震荡的钥匙：**模型回答本身的围栏形态是坏的**（双开围栏、配不成对），抽取器只能把围栏内外的代码段按顺序拼起来；拼出来的 kernel 在结构上缺一个右花括号。后面的三轮都在这个坏结构里改，错误行从 96 变到 83，但「缺一个 `}`」这个根因没被消掉。

**最终交付件**（`solution.cpp`，3,004 B，sha256 `9c040a50e9f13b37eaa5621563f3a667ee87c96493572041e37f6a361aa140cc`）就是 R1 的 kernel。节选开头（第 1–16 行）与结尾（第 85–96 行）：

```cpp
#include "gramschmidt.h"
#include <stdint.h>
#include <stddef.h>
#include <cmath>

// Helper: dot product of two columns of A (length M)
static t_ap_fixed dot_product(const t_ap_fixed A[60][80], int col_a, int col_b, int M) {
    t_ap_fixed sum = 0;
    for (int i = 0; i < M; i++) {
        sum = sum + A[i][col_a] * A[i][col_b];
    }
    return sum;
}

// Helper: scale a column of A by a scalar
static void scale_column(const t_ap_fixed A[60][80], t_ap_fixed A_out[60][80], int col, t_ap_fixed scalar, int M) {
```

```cpp
            t_ap_fixed qj_buf[60];
            for (int i = 0; i < M; i++) {
                qj_buf[i] = work[i][j] - rkj * Q[i][k];
            }

            // Store updated column back to work
            for (int i = 0; i < M; i++) {
                work[i][j] = qj_buf[i];
            }
        }
    }
}
```

**本记录对落盘件做的一个独立核对：** 全文 96 行，`{` 有 19 个、`}` 有 18 个 —— **恰好缺 1 个右花括号**，与编译器在文件末尾报 `expected '}'` 一致。这不是模型的自述，是按 `solution.cpp` 逐字节数出来的。

**R4 的停滞提示**（`repair-log.log` 前缀，逐字；该轮 `stagnant="both"`）：

```text
**你这一轮交的与上一轮逐字节相同**（kernel 与测试台都没改）。同一个文件再看一遍不会有新结论 —— 这一轮**不许原样重贴**：先用两行写出要改的**那一行**的「改前 / 改后」，再给完整代码块。若确实不该改，就写一句理由，并把**测试台**换成能定位问题的那种（打印出错的用例下标与两边的值）。
```

**结果。** 内部：4 轮全部 level 1，`done.bytes=3,004`。外部：官方判词 `agent.hls_polybench__fixed__small__gramschmidt.s1.json` 给出 **level 1、coefficient 0.1、parse true / compile false / run false / synth false、elapsed 12.3 s**，note 为「待测源码可解析，但未能与测试台编译出 csim.exe」。

**这段失败要照实记。** 循环的停滞检测**发现了**原地打转（R3 与 R2 抽出件逐字节相同），也**发出了**「不许原样重贴」的指令；但它没有能力**强制**模型修对。R4 的字节数变了（2,511），错误行没变（83），说明模型在坏结构里做了局部编辑，根因仍在。把这段和 §4.1 并排放在记录里，是为了说明：**反馈环能提高修复概率，不能保证修复成功**；失败样本同样是协作记录的一部分。

### 4.3 原始回复的落盘边界与一个真实回复形状

必须说清楚证据边界：**`trace.jsonl` 不存原始回复正文**，只存 `content_bytes`、抽取件的 `kernel_sha16`/`tb_sha16` 与工具原文。因此本记录能逐字引用的「模型回答」只有两类：

1. 落盘的 `solution.cpp`（§4.1 的 333 B 与 §4.2 的 3,004 B）；
2. 专门保留下来的探针回复 `reply.txt`。

探针归档：`results/agent-adaptive-20261027/probe-r1-20261028/reply.txt`，6,260 B，sha256 `2bc98ea0526ed32c805a101ce3e279472633031e05f1ff8383c10024759564da`。它是对 `machsuite__stencil_stencil3d` 的单轮请求（零 EDA、不改树、只发一次 LLM 请求），参数取自部署树 `manifest.json`：T=0.0 / top_p=1.0 / max_tokens=8192 / `enable_thinking=false`。开头三行（逐字）：

````text
```cpp
// Block 1: the kernel
```cpp
````

第 1 行开了围栏、第 2 行是标题、第 3 行又开了一个围栏 —— 这正是 §4.2 里抽取器 note 所说的「双开围栏」。探针的 `report.txt`（3,944 B，sha256 `e22740095a2732468f084f6b71a9258cba756b3657317ff0f6de588cee637492`）把后果量化了：

```text
[b1] lang='cpp' bytes=23 main=False top_def_call=False first='// Block 1: the kernel'
[b2] lang='' bytes=0 main=False top_def_call=False first=''
[b3] lang='cpp' bytes=3688 main=True top_def_call=True first='#include "stencil_stencil3d.h"'
...
--- seg1  2492 B  codeish=True ---
```

即：围栏配出 3 块（23 B 注释、0 B 空块、3,688 B 测试台），**完整 kernel（2,492 B）落在围栏之外**；当时的提取器只给出 108 B 的 `#include` 前缀，判分 L1。这份探针不是一次计分运行，它的用途是给「围栏形态」这一类失败留下可复算的原文与块表。

**没有落盘的，就不引。** 本记录不虚构「模型在 R1 说了什么」；R1/R2 的内容只以字节数、sha16、工具原文与抽取器 note 为证。

---

## 5. 自我纠错轨迹

### 5.1 运行时：错误 → 工具反馈 → 修改 → 复验

把 §4 的两例并排，自我纠错的机制与边界就清楚了：

| 环节 | 成功例（add_round_key） | 失败例（gramschmidt） |
| --- | --- | --- |
| 错误 | 数组整体做 `^`，编译器指名第 9 行 | 花括号不平衡，编译器在文件末尾报 `expected '}'` |
| 工具反馈 | 编译器原文（类型 + 运算符） | 编译器原文（行号）+ 抽取器 note（围栏配不成对） |
| 模型动作 | R2 改测试台、kernel 未动（逐字节相同） | R2 缩到 2,462 B，仍缺 `}` |
| 系统纠偏 | R3 前置「kernel 与上一轮逐字节相同」，并给出 `array-bitop` 规则与指针层级提示 | R4 前置「kernel 与测试台都没改，不许原样重贴」 |
| 下一轮 | 改成 `(*state)[i][j] ^= ...`，自验 level 3 | 2,511 B，错误仍在第 83 行 |
| 结局 | `csynth rc 0` → `accept-l4` → 官方 L4 | 4 轮 level 1 → 官方 L1 |

两条纪律在成功例里都起了作用，在失败例里都只起了一半作用：

1. **只改被点名的那一处**（`repair.md` 的结尾句与 system.md 的最后一节都这么说）。成功例的 R3 只改了一个表达式；失败例的 R2/R4 在整体结构上动，错误行跟着漂，根因没消。
2. **不许原样重贴**（停滞检测的指令）。成功例的 R3 因此从「改测试台」转回「改 kernel」；失败例的 R4 照做了「不重贴」，但模型在坏结构里改不出正确的括号位置 —— **检测到停滞不等于能修好**。

这也是为什么报告里把「自验 level 3」与「官方 L3」分开：内部工具能告诉你「这次编译/跑通了」，不能告诉你「官方测试台也会过」。

### 5.2 开发期：助手建议的采纳、证伪与更正

开发助手的建议不是结论，是待验证的假设。下表每一行的「发现方式」都是工具输出或文件对账，不是记忆：

| # | 助手给出的建议 / 陈述 | 发现方式 | 更正与落地 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | 独立测试台首版用 POSIX `srand48` / `drand48` | Windows/MSVC 编译日志：未声明，编译失败 | `#ifdef _WIN32` 下改用确定性 LCG shim | `REPORT.md` §12.4-1 |
| 2 | `csim.setup=1`（跳过实际执行） | 日志里没有一条 `PASS <case>`；与用例清单对账即发现「假绿」 | 改回 `csim.setup=0`；放行判据定为「日志包含全部用例 PASS 行 + `CSim done with 0 errors`」 | `REPORT.md` §12.4-2 |
| 3 | GUI 默认模型沿用 `qwen3-8k:latest` | 远端服务器没有该模型，四轮 HTTP 404；GUI 作业日志 | 切到 nemotron；同一流程出 703 B 正常解（job `20261103-232844-0971`：第 3 轮 703 B、签名过、自检 level 3、`csynth rc 0`、`accept-l4`） | `REPORT.md` §12.4-3 / §12.3-3 |
| 4 | 报告草稿「申报栈得分尚未测」 | 2026-10-28 全量跑归档与文档对账；该陈述已过时 | 改为 0.5730 / 0.3705、g 0.3217（§6.2.1） | `REPORT.md` §12.4-4 |
| 5 | 报告 §6.3 曾把 pass@5 填成与 pass@1 相同的数 | 逐次检查生成口径：全部运行都是 T=0、每题 1 次采样，**从未做过 5 次采样** | 改为「未测」；稳定性改按同题重复跑估计（§6.5），不再用恒等式冒充实测 | `REPORT.md` §6.3；提交 `1565861` |
| 6 | 把内部「口径尺」误判为不可复现 | 重新找到定义（`rel\0` + **原始字节**）并逐位复现旧值 | 撤回「不可复现」结论；两尺现值重新登记 | `results/hls-agent-20261001/_run/caliber-s3.sh::fingerprint_agent()`；`tools/kb_ab_read.py::caliber_fp()` |

第 5 行值得单独说，因为它是「没有实测就不写实测」的典型：报告模板要求 pass@1 / pass@5 两行，早先的草稿把 pass@5 填成与 pass@1 相同的数。检查生成口径后确认，全部运行都是温度 0、每题一次采样（`n_samples=1`），官方语义下 pass@5 需要每题独立生成 5 次，单次运行给不出这个数；填成恒等式等于把「未测」伪装成「测过」。更正后的 §6.3 原文：

> 两组都是**温度 0、每题一次采样**，**pass@5 未测**——该指标要求每题独立生成 5 次，
> 单次运行给不出这个数；因此也不存在 pass@5−pass@1 的稳定性诊断，稳定性按同题
> 重复跑估计（§6.5）。

第 6 行是开发期仪器的一次自我纠错，列在这里是因为它和运行时纠错是同一条纪律：**先找定义，再下结论**。把「口径尺」按「逐文件 sha256 摘要」重实现时，旧值复现不出来；当时的第一反应是「旧值不可复现」。进一步找到 `caliber-s3.sh::fingerprint_agent()` 与 `tools/kb_ab_read.py::caliber_fp()` 的定义后发现，口径尺拼的是 `rel\0` + **文件原始字节**（不是摘要），按定义重算后旧值逐位复现。错误的不是旧值，是复算器。

### 5.3 判别纪律

- **得分只认官方判分链。** 方案与基线同一次运行产出（`run.sh` / `run_baseline.sh` → `judge.py` → `score.py`）；大模型给出的任何分数、增益或归因都不作证据。开发助手不参与评分，也不对任何得分负责。
- **双指纹。** 包尺（`tools/package_hash.py`）与口径尺跑前跑后各一次；跑时树与当前树逐件比对，文档修订与运行时行为分开记账。
- **证据闸。** 技能条目逐条过闸，每条闸配能把种子错抓住的负对照；`verify_all.sh` 全绿为准，判成败不用 `| tail`。
- **语义边界。** L3 = 「csim 跑完、退出码 0」，L4 = 「csynth 通过」，**都不核对功能**（`judge.py:178-182` 的 `stages` 由 `level` 反推）。报告 §8.3 的静态普查把「功能可信」单列；L4 题数只能读作「综合通过」，不能读作「功能正确」。
- **可复算。** 能确定性复算的才进管线（挖掘聚类用频次与全序，不用 embedding）；不能复算的读数（单次采样的逐题级别）只作配对比较。
- **文档纪律。** 口径级改动先写 PREREG，跑后只追加 ADDENDUM；发现异常先归因，绝不自行重跑或广播。

---

## 6. 从协作到技能包

赛道指南 3.3.5.2 要求技能包「把与大模型协作过程中沉淀下来的经验显式提炼出来」，并写明适用场景、使用方法与失效条件。本项目的技能包是 `skill/` 下的 **15 条**，每条一个目录，含 `SKILL.md`（英文正文，注入提示词）与 `EVIDENCE.md`（人读证据，列出从哪些失败样本总结而来）；总说明在 `skill/README.md`。

**提炼管线**（开发期离线，评测运行内不学习）：

```
已归档的失败样本
   │  kb_mine.py（确定性；不调模型）
   ▼
候选簇 + 拒绝簇 + 输入清单      # 只收跨题出现 ≥3 次且覆盖 ≥2 题的簇
   │  kb_draft.py（本地模型只负责措辞；引文由脚本回填，模型只填引用号）
   ▼
kb/hls/kb.jsonl                  # 唯一真源，append-only
   │  kb_validate.py（证据闸 + 负对照）
   │  kb_render.py（幂等渲染）
   ▼
skill/<id>/SKILL.md + EVIDENCE.md
   │  kb_ab_run.sh（off/on 两臂，同一棵树，开关走环境变量）
   ▼
FREEZE（冻结后只读）
```

与本记录直接相关的一条线索：`c2hlsc__add_round_key` 的失败族（「有实现但编译不过；`state[i][j] ^=` 而形参是 `uint8_t(*)[4][4]`，正解是 `(*state)[i][j]`」）是两条人工技能（接口契约、自我验证）的主要样本之一（`REPORT.md` §5.2 表 A 族）。注意：§5.2 记的是更早一次离线归因里的 **369 B** 样本，本记录 §4.1 的 **330→333 B** 是 2026-10-27/28 的另一次运行；两次是不同 run，不能逐字节互比。

**有效性验证要照实说。** `REPORT.md` §5.3 记了一次 20 题开关对照：off 臂官方总分 0.6700 vs on 臂 0.6650，`delta = -0.0050`，噪声带 0.1000 ⇒ 判词 **neutral**；on 臂 `skills/inject` 事件总数为 **0**（20 题全部零注入轮）⇒ 六条条目 verdict = **not_exercised，不得声称有效**。这是「技能包在本面板上没有可测增益」的诚实记录，不是「技能包无效」的结论 —— 两者都不是。技能包的文本、证据与边界仍然随包提交；是否有效，按这套口径继续测。

**本记录的两条轨迹同样没有技能注入事件。** 因此 §4.1 的成功不能记在技能包头上，§4.2 的失败也不能记在技能包头上；它们检验的是「提示词 + 工具反馈 + 停滞检测」这条主环。

---

## 7. 证据索引

**包内文件（随提交包分发）：**

| 文件 | 字节 | sha256 | 用途 |
| --- | ---: | --- | --- |
| `agent/prompts/system.md` | 10,606 | `e339ce645ddcb4ae65481e5fdab0c5ebf84191f7723fcc5b66bdbde654177bd6` | 系统提示词（§3.1） |
| `agent/prompts/repair.md` | 324 | `6df7624935f09fa66553dbe1247849d89e370967e747d7b681dbcb509a6216f7` | 修补模板（§2.4） |
| `manifest.json` | — | — | 模型身份、上下文、服务栈、轮数 / 工具 / 技能名录 |
| `skill/README.md` | — | — | 15 条技能的目录、加载规则、写法与边界（§6） |

**开发档案（工程仓，不随提交包分发；本记录引用其逐字节摘录）：**

| 文件 | 字节 | sha256 | 用途 |
| --- | ---: | --- | --- |
| `results/agent-adaptive-20261027/remote/run2/agent/out/c2hlsc__add_round_key/trace.jsonl` | 12,587 | `de8a3bc14f5b918599213bbcfc228fe6290627092db36fb3dfbac7bd60834da3` | 成功例逐轮事件（§4.1） |
| `…/c2hlsc__add_round_key/solution.cpp` | 333 | `2634fffe3d479af64e6f118239f388ab7d980c594832c5514f43bc018414f26f` | 成功例最终 kernel（§4.1） |
| `results/agent-adaptive-20261027/remote/run2/agent/out/hls_polybench__fixed__small__gramschmidt/trace.jsonl` | 19,819 | `01564f0a212398dc86469e3336246a091cdc67f2324eeb9f82a562ffd50da979` | 失败例逐轮事件（§4.2） |
| `…/hls_polybench__fixed__small__gramschmidt/solution.cpp` | 3,004 | `9c040a50e9f13b37eaa5621563f3a667ee87c96493572041e37f6a361aa140cc` | 失败例最终 kernel（§4.2） |
| `results/agent-adaptive-20261027/remote/run2/results/agent.c2hlsc__add_round_key.s1.json` | — | — | 官方判词：level 4（§4.1） |
| `results/agent-adaptive-20261027/remote/run2/results/agent.hls_polybench__fixed__small__gramschmidt.s1.json` | — | — | 官方判词：level 1（§4.2） |
| `results/agent-adaptive-20261027/probe-r1-20261028/reply.txt` | 6,260 | `2bc98ea0526ed32c805a101ce3e279472633031e05f1ff8383c10024759564da` | 真实回复形状（§4.3） |
| `results/agent-adaptive-20261027/probe-r1-20261028/report.txt` | 3,944 | `e22740095a2732468f084f6b71a9258cba756b3657317ff0f6de588cee637492` | 围栏块表与 `system.md 8932 B`（§3.1 / §4.3） |
| `results/agent-adaptive-20261027/probe-r1-20261028/probe_r1_shape.py` | 4,224 | `d7b033f0551cd83a3b5f43b2d79c07b35ca9a9b35f49a0c4344416487625a3c9` | 探针脚本，可复算 |

**怎么复核。** 包内文件可直接 `sha256sum`；trace 是逐行 JSON，`python -m json.tool` 或任何 JSONL 阅读器都能逐事件读。§4 的每个字节数、sha16、错误原文与 `stagnant` 值都能在对应的 trace 行里对上；§4.2 的花括号计数（19/18）可按 `solution.cpp` 逐字节复算。

---

## 8. 结论：三条可复用的经验

1. **提示词是契约，不是愿望。** 固定回复形状（两个围栏块）、固定签名、固定判分阶梯、失败时只改被点名的一处 —— 这些约束让工具能确定性地抽取与判级，也让模型的错误变成可分类、可修补的事件。`system.md` 里最长的一节不是算法提示，而是「接口就是规格」与「数值必须匹配一个特定实现」；这两节直接对应 L1/L2 的两大失败族。
2. **自我纠错要先有仪器，再有循环。** 签名闸、编译、csim、csynth、停滞检测都是确定性工具；没有它们，「修补」只是重写。有了它们，才能把「模型改了什么」变成 `extract` 的 sha16、`selfcheck` 的 level 与 `repair-log` 的规则名 —— 也才能在这份记录里逐轮复盘，而不是复述模型的自我评价。
3. **成功与失败都要照实记。** 成功例（add_round_key：R1 编译错 → R2 未改 kernel → R3 定点修复 → 官方 L4）说明「定点修补 + 停滞提示」有效；失败例（gramschmidt：4 轮都在缺一个 `}` 的结构里打转 → 官方 L1）说明它不保证成功。技能包的开关对照（delta −0.0050、零注入、neutral）与 pass@5（未测）同样照实写。**不把未测写成测过，不把 neutral 写成有效，不把开发助手的建议写成结论** —— 这是这份协作记录最重要的部分。

---

**声明。** 本记录由参赛队编写，开发助手（Claude Code CLI）参与了资料整理与文字修订；文中每条引文、字节数与哈希均可在 §7 所列文件中复核。开发助手不是参赛方案的一部分，不在评测链路上，不参与评测运行，也不对任何得分负责。所有得分只来自官方判分链。

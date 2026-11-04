# 46939 · HLS 本地智能体

赛道 3.1（AMD HLS）的提交方案包。对外只有一个契约：**读一个目录，写一个目录，单题运行** ——
评测方调用 `run.sh <输入目录> <输出目录>`，包内智能体生成一份可综合的 HLS C++ 内核，
并留下逐次调用的 trace。

本文件是仓库的文件地图：每个文件/目录是什么、做什么用。方案设计与实验记录在
`REPORT.md`。

## 输入 / 输出契约

```
<输入>/prompt.txt        题面
<输入>/interface.txt     顶层函数签名与类型定义
<输入>/top.txt           （可选）顶层函数名

<输出>/solution.cpp      生成的 HLS C++；失败时是一个空文件
<输出>/trace.jsonl       每次模型 / 工具调用一行 JSON
```

`run.sh` 无论成败都写出这两个文件并退出 0 —— 「解不出来」与「服务坏了」必须在协议层
分得开。

## 顶层

| 路径 | 说明 |
|---|---|
| `run.sh` | 单题入口。赛事方原件，未改动；内部调用 `python3 -m agent.main`。 |
| `run_baseline.sh` | 基线入口。赛事方原件，未改动；转调 `baseline.py`。 |
| `baseline.py` | 官方基线：无智能体、无技能包、单次直接生成。赛事方原件，未改动。 |
| `manifest.json` | 申报清单：模型身份与来源、量化方式、上下文配置、推理栈、智能体的轮数 / 工具 / 技能名录。 |
| `Dockerfile` | 镜像构建。基于官方基础镜像（`BASE_IMAGE` 是占位符，构建时用赛前公布的镜像名覆盖），装依赖、拷入整个包、设定环境缺省值。评测沙箱断网，所有依赖与权重必须提前烘进镜像。 |
| `requirements.txt` | 运行时依赖四个：`requests` / `fastapi` / `uvicorn` / `pydantic`。 |
| `REPORT.md` | 项目报告：方案、实验过程、复现说明。 |
| `.gitignore` | 不提交运行产物（`out/`、日志）与本地权重（`*.gguf` 等）。 |
| `agent/` | 智能体本体：控制流、模型接入、工具、技能加载、提示词。 |
| `skill/` | 技能包：15 条，每条一个目录。 |
| `serve/` | 推理服务与投题服务。 |
| `model/` | 模型申报说明。 |
| `tests/` | 离线守卫：不需要 EDA、不需要模型、不需要联网。 |

## agent/ —— 智能体

| 文件 | 说明 |
|---|---|
| `main.py` | 控制流。多轮循环（轮数由 `AGENT_MAX_ROUNDS` 控制）：生成 → 签名检查 → 自验（编译 / 运行）→ 按失败类别修补；规划每轮的输出预算，拼提示词，写 `trace.jsonl`。 |
| `llm.py` | 模型接入与代码抽取。两个后端一条代码路径：`LLM_BACKEND=mock` 不联网，按 interface 拼一份形状正确的桩；`openai` 接任何 OpenAI 兼容的 `/chat/completions`。采样口径常量也在这里。 |
| `tools.py` | 工具面。`check_signature()`：零 EDA 成本的确定性签名比对。`HlsToolchain.run()`：用与判分器同一套 tcl 模板 / 器件 / 时钟，跑测试台编译、csim 运行与 csynth。 |
| `skills.py` | 技能包加载与选择。解析 `SKILL.md` 的 front matter 与 Skill Metadata；按日志签名匹配，第 1 轮不注入，其后每轮至多 2 条。格式与 AMD 官方技能兼容，官方技能可原样放入 `skill/` 使用。 |
| `prompts/system.md` | 系统提示词：回复格式（两个代码块，先内核后测试台）与接口契约。 |
| `prompts/repair.md` | 修补轮模板：失败类别、历史、工具日志、上一版内核的槽位。 |
| `__init__.py` | 空文件，标记 `agent` 为 Python 包。 |

## skill/ —— 技能包

| 路径 | 说明 |
|---|---|
| `README.md` | 技能包说明：目录结构、加载器读什么、注入上限、写法约定，以及每条技能的来源与适用边界。 |
| `<id>/SKILL.md` | 一条技能：front matter（`name` + 单行 `description`）+ 正文（触发条件、日志签名、处方）。加载器把正文注入模型提示词。 |
| `<id>/EVIDENCE.md` | 同一条技能的证据档案（人读）：从哪些失败样本里总结出来的。不进提示词。 |

15 条技能各管一类失败：

| 技能目录 | 管的失败 |
|---|---|
| `hls-interface-contract` | 内核与测试台编译 / 链接不上：签名不符、重复 `main`、符号缺失 |
| `hls-self-verification` | 内核能编译但结果错 / 缺、退出非 0 —— 先写差分测试台，再动内核 |
| `hls-self-test-passes-official-fails` | 自写的测试台过了，官方判定不过 |
| `hls-empty-round-recovery` | 上一轮被截断 / 没出代码块 / 只出一个块 / 调用失败 —— 先把产物补齐 |
| `hls-truncated-response` | 回复被 `max_tokens` 截断时怎么收尾 |
| `hls-testbench-callsite` | `csim.exe` 产不出来，首个编译错指向 `agent_tb.cpp` 的调用点 |
| `hls-testbench-compilation-errors` | 测试台编译失败：标识符 / 初始化器错误 |
| `hls-testbench-compile-errors` | 测试台编译失败：函数调用歧义、缺 std 命名空间成员 |
| `hls-testbench-function-mismatch` | 测试台编译失败：指针 / 整数比较、未声明标签 |
| `hls-testbench-type-mismatch` | 测试台编译失败：类型转换歧义、缺函数定义 |
| `hls-testbench-undeclared-identifiers` | 测试台编译失败：未声明的标识符 |
| `hls-testbench-integration` | 源码单独编得过，与测试台一起链接失败 |
| `hls-testbench-validation` | 测试台编译成功但退出码非 0 —— 测实现与测试台是否一致 |
| `hls-runtime-functional-errors` | 测试台能编译但退出码非 0：功能性 / 边界不匹配 |
| `hls-runtime-algorithm-mismatch` | 测试台能编译但退出码非 0：算法写错 |

## serve/ —— 服务

| 文件 | 说明 |
|---|---|
| `README.md` | 服务说明：进程与端口、为什么只暴露 7860、评测日启动顺序、两个模型名变量、两层超时、断网约束。 |
| `start.sh` | 常驻服务的唯一启动点。幂等：已就绪立即返回 0。每个常驻进程 `setsid` 到自己的会话（评测方停 `run.sh` 时按进程组发信号，常驻服务不能跟着死）。负责起推理服务与 EDA 临时目录清理。 |
| `llamacpp.sh` | 申报推理栈：llama.cpp `llama-server`，OpenAI 兼容，8000 端口；`-c 524288`、全层上卡、显式 `--alias`、`--jinja`、钉在单卡。 |
| `start-ollama.sh` | 开发栈参考：Ollama + 同一份 GGUF。不是申报路径，只为让开发期读数可复现。 |
| `serve_api.py` | 投题 HTTP 服务（7860）。异步协议：`POST /v1/solve` 立即回 202 + job_id，`GET /v1/jobs/<id>` 轮询；令牌校验；一次一题、按到达顺序串行。 |
| `env.sh` | 参考配置，可 source。两个模型名变量（`LLM_MODEL` / `MODEL_NAME`）归一到同一值；采样、超时、每轮预算、目标器件与时钟的缺省值。 |

## model/ 与 tests/

| 文件 | 说明 |
|---|---|
| `model/MODEL.md` | 模型申报：来源、revision、校验和、量化方式、显存占用、上下文配置、推理栈、综合目标器件与时钟。 |
| `tests/test_hls_agent.py` | 单元测试：不需要 EDA、模型、网络；每条断言配一条负对照（改掉被测代码的一个字面量，必须有且只有那一条转红）。 |
| `tests/readscope_probe.py` | 读域守卫：真的跑一遍，记录实际打开的文件，证明智能体只读输入目录里的 `prompt.txt` / `interface.txt` / `top.txt`。`--inject` 是它自己的负对照。 |
| `tests/run_all.sh` | 一次跑完全部离线守卫；负对照必须被抓到，否则整轮判失败。 |

## 怎么跑

```bash
# 1) 不接模型，先验契约与链路（产出桩代码）
LLM_BACKEND=mock bash run.sh <输入目录> <输出目录>

# 2) 本地推理 + 单题
source serve/env.sh
./serve/start.sh
bash run.sh <输入目录> <输出目录>

# 3) 官方投题方式：常驻服务 + HTTP
source serve/env.sh
export FPGACHINA_TOKEN=<赛事方发放的令牌>
./serve/start.sh
python3 -m uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860
# 再经 rc-tunnel 暴露 7860（先起服务，后暴露端口，顺序不能反）
```

`run_baseline.sh` 与 `run.sh` 用同一推理服务、同一模型名、同一上下文配置 —— 增益项的
分子与分母必须可比。

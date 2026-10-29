# serve/ —— 服务面

本目录定义**推理服务怎么起、怎么被评测方访问**。智能体本身不在这里：它读一个
目录、写一个目录（`run.sh` 的契约，见仓库根的 `run.sh`）。

| 进程 | 端口 | 绑定 | 对谁可见 | 干什么 |
|---|---|---|---|---|
| `serve/start.sh` | — | — | — | **唯一常驻入口**：起 `llamacpp.sh`、起 `/tmp/eda` 清理环，全部就绪才返回 0；幂等 |
| `serve/llamacpp.sh` | 8000 | 127.0.0.1 | **仅本机** | 起 llama.cpp `llama-server`，提供 OpenAI 兼容端点（申报路径） |
| `serve/serve_api.py` | 7860 | 127.0.0.1 | 赛事方（经 rc-tunnel） | 异步收题：`POST /v1/solve` → 202 + `job_id`，`GET /v1/jobs/<id>` 轮询结果 |
| `serve/start-ollama.sh` | 11434 | 127.0.0.1 | 仅开发期自用 | 开发栈参考启动（**不是申报路径**） |

`serve/env.sh` 是一份**可 source 的参考配置**（采样口径、两个模型名变量、差异项、
预算、器件与时钟）。它不是 `run.sh` / `run_baseline.sh` 的依赖 —— 那两份是官方
原件、不得修改，配置由调用方在环境里给。

## 为什么只暴露 7860

Radeon Cloud 的 `rc-tunnel` **只接管绑在环回口上的 HTTP 服务**；绑 `0.0.0.0` 的
服务永远不会被暴露，而在赛事方那一侧「没暴露」与「崩了」长得一模一样。每个实例
只能暴露一个端口，所以推理服务的 8000 留在内部。

```bash
rc-tunnel expose --port 7860
```

## 启动顺序（评测日）

```bash
# 1) 常驻服务（**唯一入口**）：起 llama-server，等到 /v1/models 应答才返回 0
bash serve/start.sh                    # 内部起在 127.0.0.1:8000；重复跑是 no-op

# 2) 提交端点
export FPGACHINA_TOKEN=<赛事方发放的令牌>
export MODEL_NAME=nemotron-3.5-lightning-c512k   # 健康检查回报它；见下方「两个模型名」
uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860

# 3) 自检
curl -H "Authorization: Bearer $FPGACHINA_TOKEN" http://localhost:7860/v1/health
# → {"ready":true,"track":"hls","model":"nemotron-3.5-lightning-c512k","vram_gb":<rocm-smi 读数>}
```

投题是**异步**的：`POST /v1/solve` 立刻返回 `202 {"job_id":…,"status":"queued"}`，
之后轮询 `GET /v1/jobs/<job_id>`（赛事方每 2 秒一次）。`status=done` 时才带
`solution` / `trace` / `elapsed_s`；`solution` 是空串表示「这题没解出来」，
不是「还在跑」。

`track` 必须是 `hls`：赛事方按它核对投递的赛道，不符会被拒收。这一行在
`serve/serve_api.py` 里是常量，不要改。

## 令牌检查不是可选项

`/v1/health` 与 `/v1/solve` 都要求 `Authorization: Bearer $FPGACHINA_TOKEN`。
公开的 app URL 上没有平台级认证，**没有这道检查，任何知道 URL 的人都能投题**。
未设 `FPGACHINA_TOKEN` 时服务返回 500 而不是放行 —— 这是刻意的：
宁可起不来，也不要无声地裸奔。

## 两个模型名（★ 最容易出错的一格）

- `run.sh` 一侧：`agent/llm.py` 读 **`LLM_MODEL`**（缺省 `mock-model`）；
- `run_baseline.sh` 一侧：官方 `baseline.py` 读 **`MODEL_NAME`**，取不到就退回
  `<LLM_BASE_URL>/models` 列表的**第 0 个**。

分子与分母读的是两个不同的名字。官方栈里两者能对上纯属服务端把服务名起成
缺省模型路径的巧合；本包 `serve/llamacpp.sh` 显式 `--alias nemotron-3.5-lightning-c512k`，
把巧合换成声明。换一个 `/models` 会列出多个模型的服务端（例如 Ollama），第 0 个
可能**不是你正在跑的那个** —— 分母悄悄换了模型，不报错，只给出一个很像真的增益。
`serve/env.sh` 因此两个都导出并归一到同一个值，并把「两个都设了但不相等」判成配置错误。

## 超时有两层，不要混

- **外层（硬墙）**：`serve_api.py` 给子进程的超时是 `left - 10`（`left` = 题的
  `deadline_s` 减去**已排队与已运行**的时间），在赛事方超时之前自行收手并返回已有产物；
- **内层（预算）**：同一个 `left` 作为 `AGENT_DEADLINE_S` 下发（不是固定的 900），
  智能体据此在墙前停止生成、把已写好的 `solution.cpp` 交出去。

**排队时间计入 `left`**：异步协议下题目先入队，轮到它时可能已经过去几十秒。
单题墙钟占分（代价项），而超时按 L0 计 —— 所以内层必须比外层早收手。

## 评测日与开发期的投题形态不同（★ 已知差异）

`serve_api.py` 只往输入目录里写 **`prompt.txt` 与 `interface.txt`**，**不写
`top.txt`**。而我们的开发期投题（官方 `selftest/run_selftest.sh`）是拿题目目录
整个当输入目录，`top.txt` 在场。智能体两者都支持：`agent/main.py` 的
`resolve_top()` 顺序是 `top.txt` → 题面（`Top-Level Function :` 标记）→
interface 的第一条函数声明，并把**实际来源**写进 `trace.jsonl` 的
`tool=agent` / `event=start` 记录（字段名 `top_source`，取值即上列四级加
`--top`），所以评测日那一格是可审计的，不是靠运气。

★ 但「可审计」不等于「已测过」：离线守卫 `tests/readscope_probe.py` 是**拿题目
目录整个当输入目录**投题的（= 有 `top.txt` 的那一格），测试台里也总是写
`top.txt`。**「无 `top.txt`」这一格目前只有实现、没有单独立测** —— 已知缺口，
不拿实现存在冒充测过。

## 断网

服务在容器里起，容器没有网络。权重必须**已经在本地盘上**：
`huggingface-cli download` 之类的在线获取在沙箱里会失败（见 Dockerfile 里的
`COPY models/` 注释）。

## 连续运行

评测是连续几百次 `/v1/solve`。中间件都无状态：每次请求建一个临时目录（落在
`AGENT_TMP`；镜像 ENV 设为 `/var/tmp`，因为平台上的 `/tmp` 是 4 GB 内存盘），
跑完即删，产物只从临时目录读。`start.sh` 另外拉起一个只看 `EDA_TMP` 的清理环，
只删**整棵子树空闲两小时**的目录。**不要**把中间文件写进包目录 —— 包要被哈希
冻结，多出来的字节都是噪声。

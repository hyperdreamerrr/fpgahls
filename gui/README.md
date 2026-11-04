# HLS Agent 控制台（工程外 GUI）

在**不改动** `B:\46939_hlsagent` 的前提下，本地输入题目、驱动包内智能体，
并把「思考过程」与「最终代码」分栏显示。

## 启动

双击 `run.bat`，或：

```bat
cd /d E:\hlsagent-gui
"C:\Program Files\Python311\python.exe" server.py --open
```

浏览器会自动打开 `http://127.0.0.1:8765/`（端口被占用时自动往后找）。
服务只监听 127.0.0.1，**不要**改成 `0.0.0.0`——这个接口能执行本地命令。

## 用法

1. 左上「从题集载入」可选 `B:\fpga2026-agent\dataset\hls-eval-tasks` 里的题，
   只复制 `prompt.txt` / `interface.txt` / `top.txt`，**不会**读取测试台或 `reference/`。
2. 也可以直接手填题面、接口、顶层函数。
3. 「模型与运行参数」里填 OpenAI 兼容端点。默认 `http://127.0.0.1:11434/v1`
   （本机 Ollama），模型默认 `qwen3-8k:latest`。用云端 API 时改成对应 Base URL 并填 Key。
4. 点「开始运行」。右上「过程」有三栏：
   - **时间线**：智能体每一轮的计划、提示词、取码、签名、自验、综合、修补；
   - **模型输出**：每次调用的**思考过程**与**完整回复**（分开显示）；
   - **运行日志**：子进程 stdout/stderr。
   右下是实时写入的 `out/solution.cpp`，可复制、下载。

## 服务器模式（SSH 远程）

包和模型都在 Linux 服务器上、GUI 跑在本机时，顶部「后端」选
「服务器——SSH 远程执行」，填：

| 界面项 | 典型值 |
|---|---|
| SSH 主机 / 端口 / 用户 | 服务器地址 / 22 / root |
| 密码 | 只存内存，不写 `meta.json` / localStorage |
| 远端包路径 | `/root/autodl-tmp/46939_hlsagent`（`agent/` 所在目录，只读） |
| 远端 Python | `/root/miniconda3/bin/python` |
| 远端工作目录 | `/root/autodl-tmp/hlsagent-gui`（只放 `bin/` 和 `jobs/`） |
| 模型 | 先点「读取远端状态 / 模型」，选 `nemotron-3.5-lightning-c512k:latest` |
| Base URL | `http://127.0.0.1:11434/v1`（**服务器本机**的 Ollama，不是本机的） |

勾选「用 reasoning_effort=none 关思考」——服务器 Ollama 只有这一写法能真正
关掉思考（`enable_thinking` / `think:false` 会被忽略）。

运行时本机会把 `remote/gui_llm_proxy.py` 与 `remote/gui_remote_run.py` 传到
远端工作目录的 `bin/`，在服务器上起「捕获代理 + 智能体」，本机每秒 SFTP
镜像 `llm-io.jsonl`、`live.json`、`trace.jsonl`、`solution.cpp`、`log.txt`
到本地作业目录，所以三栏显示和本机模式一致。停止按钮发 `TERM` 给远端进程组
（10 秒后 `KILL`），总超时由本机看门狗与远端 runner 双重兜底；两者都会在
`solution.cpp` 保留最后一次原子写入的版本。远端只增删自己的工作目录，不改包。

## 思考过程从哪里来

包内 `agent/llm.py` 的流式解析只把 `content` 收进回复，`reasoning_content` /
`reasoning` 只计数、不保存，所以 `trace.jsonl` 里没有原始思考。
本 GUI 在每个作业前起一个**只监听本机的 LLM 代理**：把 SSE 原样转发给智能体，
同时旁路记录 `content` 与 `reasoning`，写进作业目录的 `llm-io.jsonl`。
API Key 只在内存里用于向上游发请求，不写进任何文件、不出现在接口返回里。

## 作业目录

```
E:\hlsagent-gui\jobs\<id>\
  in\prompt.txt interface.txt top.txt
  out\solution.cpp trace.jsonl
  tmp\                 # AGENT_TMP，EDA 临时文件都在这
  log.txt              # 子进程输出
  llm-io.jsonl         # 每次模型调用：思考 + 回复 + usage
  meta.json            # 本次配置（不含 Key）
```

作业目录可用右下角「作业目录」按钮打开。服务重启时会扫描 `jobs\` 下的旧作业，
界面会自动恢复上次打开的作业（完成/失败状态从 `meta.json` 读取，旧作业则按
`out\trace.jsonl` 与 `log.txt` 推断）。

## 运行方式与隔离

- 子进程：`python -m agent.main --input jobs/<id>/in --output jobs/<id>/out`，
  cwd 固定为包目录；包目录**只读**使用。
- `PYTHONDONTWRITEBYTECODE=1`（不往包里写 `__pycache__`），
  `AGENT_TMP` 指向作业的 `tmp\`。
- `AGENT_DEADLINE_S=0`（智能体内部不设截止），由界面「总超时」在服务端
  到点杀进程树兜底；即使被杀，已原子写入的 `solution.cpp` 仍保留。
- 同一时间只允许一个作业，避免抢显卡/EDA 许可。

## 常用参数

| 界面项 | 环境变量 | 说明 |
|---|---|---|
| 模型 | `LLM_MODEL` | OpenAI 兼容模型名 |
| 上游 Base URL | `LLM_BASE_URL` | 须含 `/v1` |
| max_tokens | `LLM_MAX_TOKENS` | 每轮输出帽；包内 `plan_round` 可能抬到 `AGENT_CAP_MIN`(5000) |
| 最大轮数 | `AGENT_MAX_ROUNDS` | 包内默认 4 |
| 单次调用超时 | `LLM_TIMEOUT_S` | 流式读超时 |
| 总超时 | — | GUI 服务端看门狗，0=不限 |
| 综合检查 | `AGENT_CSYNTH` | auto / on / off |
| 审计 | `AGENT_AUDIT` | on / off |
| 技能包 | `AGENT_SKILLS` | on / off |
| 器件 / 时钟 | `HLS_PART` / `HLS_PERIOD_NS` | 默认 `xczu3eg-sbva484-1-e` / 5 |

本机 `qwen3-8k` 的上下文只有 8192，而题面+系统提示约 3k tokens，所以界面默认
`max_tokens=4096`。需要更长输出时，换 `qwen3:8b`（40960）或云端模型再把帽调大；
否则 Ollama 会截断提示词或生成。

## 排查

- `--check` 只打印包、题集、Vitis、Python 的检查结果：
  `python server.py --check`
- 本机 Ollama 首次调用要把权重读进显存/内存，可能几十秒没有首 token；
  界面会停在「生成中」，属正常。显卡小时 8B 模型会退到 CPU，速度很慢，
  可把「总超时」调大或换更小的模型。
- 若上游是云端 API 且本机开了系统代理，远端请求仍走代理；本机地址已自动加入
  `NO_PROXY`。

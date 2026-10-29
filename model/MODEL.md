# MODEL.md

> 官方要求：提交前清单（官方仓库根 `SCORING.md` §5.3）有一条
> 「`MODEL.md` 已写明**来源、版本号或校验和、量化方式、实测显存、上下文配置**」，
> 而 §2.4 把这一条与**增益项 40 分**绑在一起（未如实填写 ⇒ 增益项不得分）。
> §5.1 的方案包树里这一格写的是「模型来源、版本、量化方式、**显存占用实测**、上下文配置」。
>
> 本文件所填内容须与 `manifest.json`、`REPORT.md` 第 3 节一致。

---

## 〇 填写状态：申报栈已实测（2026-10-19，AMD Radeon Cloud）

**申报配置 = 本地开源权重（GGUF，UD-Q4_K_M）+ llama.cpp `llama-server` + 单卡 ROCm。**
2026-10-19 在 AMD Radeon Cloud 的 gfx1100 实例上把服务栈起了起来（镜像
`radeon-cloud-global/fpgachina-rtlhls@sha256:a7cf627e1170`，W7900D、ROCm 7.15.26333），
原先两项待测均已填实：

| 项 | 读数 | 对应 `manifest.json` |
|---|---|---|
| 单卡实测显存占用 | **26.59 GiB**（请求全部结束后的 `rocm-smi` 读数：28,549,861,376 B） | `model.measured_vram_gb` = 26.59 |
| 推理栈版本 | `llama-server 0.4.0-dev (build 1, commit f114f91)` | `serving.version` |

**为什么不是 vLLM**：平台镜像里的 vLLM 0.27.1 **没有 GGUF 加载器**，起服务在加载
权重之前就退出（`results/amd-bringup-20261019/RUNLOG.md` 续记 2）。llama.cpp 是
镜像自带、可用的那条路，于是申报后端改为 llama.cpp。这不是偏好，是**能力边界**。

★ 读数的三点限定（引用时一并带上，不要把其中任何一条丢掉）：
① 实例是 **48 GB** 的 W7900D，不是 32 GB 档。26.59 GiB 是权重 + 524288 窗口
   KV cache 的实际占用（不随卡容量缩放），**低于 32 GB**；但「在 32 GB 卡上起得来」
   是由这个读数**推得**，不是在那张卡上实测的。
② 测于**加 `--jinja` 之前**。`--jinja` 是 manifest `generation` 生效的前提
   （官方 FAQ Q6）；它不改变权重与显存占用，但这组读数**不是**加了它的读数。
③ 59.85 tok/s 是冒烟请求的解码速率，不是 20 题评测的吞吐；预算算式里的
   42 tok/s 是判分臂历史读数，两者不互换。

**为什么不拿开发栈的数字顶上**：开发栈是 **NVIDIA 卡 + Ollama**，申报配置是
**ROCm 卡 + llama.cpp**。量化方式是同一个 GGUF 文件，但硬件架构与推理后端两项
仍不同，显存分配（KV cache 预分配与页管理）和溢出行为不可互推。**两侧数字不得互搬。**

**另：显存核查不靠本文件。** §2.2 的判据是**运行时显存采样**，赛事方自己采，不看本页
填了什么；本页的职责是**如实声明**，不是自我评分。

**选型注明**：2026-10-19 用户拍板，申报模型终选 **nemotron-3.5-lightning-c512k**
（`unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF`，GGUF UD-Q4_K_M）。本页、
`manifest.json`、`REPORT.md` 三处已同批改齐。

---

## 1. 模型

| 项 | 内容 |
| --- | --- |
| 模型名称 | `unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF`（服务名 `nemotron-3.5-lightning-c512k`） |
| 来源 | https://huggingface.co/unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF |
| 版本号 | **仓库 revision（commit 哈希）：`f2d3fe3694501008786e81e5f20360cbf715496a`**（2026-10-28 经 `hf-mirror.com` API 取得）；同 revision 下该 GGUF 的 `lfs.oid` = `sha256:edcb5d4650796ed2fb412498de6f83b585862312c747ddb74f0ea04b22206181`，与本队落盘文件**64 位逐字相同** |
| 权重校验和 | 同上（全 64 位）；权重文件名 `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q4_K_M.gguf`，**25,266,255,936 B**（落盘现测） |
| 参数量 | 32.9B（`ollama show` 的 `parameter_size` 读数） |
| 原生精度 | **未在本机复核**：本机只有上游发布的 GGUF（UD-Q4_K_M），未取全精度原权重；不写猜测值 |
| 许可证 | **未在本机复核**（2026-10-19 HF 页面不可达）；不写猜测值 |
| 是否微调 | 否（直接用上游发布的量化权重，未做任何微调） |

**必须是可本地部署的开源权重。** 决赛在断网沙箱中运行，商用 API 不满足 §2.1/§2.3
（官方 `SCORING.md` 亦写明 `MODEL.md` 里声明的必须是可本地部署的开源权重）。

**版本锚有两条腿：revision 定位「哪一份仓库快照」，文件校验和定位「哪一份字节」**。
2026-10-19 对 `huggingface.co` 的 API 请求超时，当时只落下了文件级校验和；2026-10-28
经 `hf-mirror.com` 取得仓库 revision `f2d3fe36…496a`，并按该 revision 拉目录树核对——
`lfs.oid` 与落盘文件的 sha256 64 位逐字相同、`size` 25,266,255,936 B 也逐字相同。
两者互证：revision 供赛事方复现下载，校验和供逐字节验收。

**参数量不写自算分解**：32.9B 取 `ollama show` 的 `parameter_size` 读数；上游
`config.json` 的逐层核算未在本机重做（HF 不可达），故不写「由 config 独立算得」
一类更弱的声明。

**历史注记（前任申报模型 Qwen3-8B）**：2026-10-13 及以前本页声明 Qwen/Qwen3-8B
（bf16，`config.json` 核算 8.18B、bf16 下约 16.4 GB；git revision
`b968826d9c46dd6066d109eabc6255188de91218`，经 `hf-mirror.com` 复核过存在性）。
该声明已被 2026-10-19 的终选替换，原读数只作历史对照，不混入现行申报。

### 选型理由与备选

| 候选 | 开发栈题集得分（20 题，官方判分器） | 是否推理模型 |
|---|---|---|
| **nemotron-3.5-lightning-c512k（本页声明）** | **0.5200**（agent 臂）/ 0.2850（baseline 臂），Δ+0.2350（2026-10-12，判词见 `REPORT.md` §6） | 是（`capabilities` 含 `thinking`） |
| Qwen3-8B（前任申报，历史） | 0.2800（2026-10-05）/ 0.3600（2026-10-07 同协议） | 是（先产思考 token） |
| 2026-10-07 以后的多模型对比轮 | 见 `REPORT.md` §3.2 与 `docs/model-eval-results.md` | — |

选型不是只看分数：本赛道的墙钟占分（代价项 10 分）与**生成速率**直接挂钩 —— deadline
是墙钟驱动的，慢模型会被切得更狠（`REPORT.md` 有这一条的实测）。所以对比轮同时记
速率与显存档位，不单看得分。

---

## 2. 量化与显存

| 项 | 内容 |
| --- | --- |
| 申报量化方式 | **GGUF UD-Q4_K_M**（Unsloth Dynamic 4-bit；申报与开发栈用的是**同一个**权重文件） |
| 量化工具与版本 | 不适用（量化由上游发布，本方案未自行量化；转换工具版本未在本机复核） |
| **实测显存占用** | **26.59 GiB**（2026-10-19，ROCm 申报栈，请求结束后的 `rocm-smi` 读数 28,549,861,376 B；三点限定见第〇节） |
| 测量方式 | `rocm-smi --showmemuse`（官方 `serve/serve_api.py` 的 `/v1/health` 用的就是它） |
| 测量硬件 | AMD Radeon Cloud gfx1100（W7900D 48 GB），单卡；验证窗口的目标架构正是 gfx1100 |

**上限单卡 32 GB，不允许跨卡**（官方 `SCORING.md` §2.2；`serve/llamacpp.sh` 把
`HIP_VISIBLE_DEVICES` 钉在单卡、`-ngl 999` 全层上卡，并注明 gfx1201 无 XGMI、
张量并行起不来）。

### 2.1 开发栈实测（**三项口径都不同，数字不可互搬**）

开发栈 = **NVIDIA 32 GB 单卡 + Ollama + GGUF UD-Q4_K_M**；申报栈 = **ROCm + llama.cpp +
同一份 GGUF**。以下是开发栈的读数，用途只有一个：**决定开发栈自己的上下文窗口**，
以及证明「窗口必须显式压、不压会静默溢出」这条机制。

开发栈服务配置：`Ollama 0.34.4`；被测模型 `nemotron-3.5-lightning-c512k`
（GGUF UD-Q4_K_M，**`num_ctx` = 524288**，与评测模型名的 c512k 一致）。
历史注记：前任申报模型 `qwen3:8k` 是由 `qwen3:8b` 派生（Q4_K_M，权重层
5225399145 B）、`num_ctx` 压到 8192 的旧配置；`/v1` 端点的 `options.num_ctx`
会被收下再丢掉、不报错，故窗口只能走派生 Modelfile —— 这条机制对两者同样成立。

**显存预算规则**（写死，见 `REPORT.md` 的对比轮预登记）：单卡 32760 MiB，
取「`used ≤ 30000 MiB` 且 `PROCESSOR` 为 100% GPU」的最大档。
`PROCESSOR` 不是 100% GPU 就是**有层溢出到 CPU**，该档作废。

2026-10-07 加窗阶梯（同一台卡，逐档实测；**模型不是申报模型**，此处它们只是把这张卡的
预算用满，用来刻画规则本身）：

| 被测模型 | 档位 | used (MiB) | PROCESSOR | tok/s |
|---|---|---|---|---|
| muse-glimmer-30B Q4_K_M | 65536 (c64k) | 16922 | 100% GPU | 20.2 |
| muse-glimmer-30B Q4_K_M | 131072 (c128k) | 17586 | 100% GPU | 20.2 |
| qwen3.8-27B Q4_K_M | 65536 (c64k) | 19426 | 100% GPU | 19.98 |
| qwen3.8-27B Q4_K_M | 131072 (c128k) | 23586 | 100% GPU | 19.68 |
| qwen3.8-27B Q4_K_M | **196608 (c192k)** | **27746** | **100% GPU** | **19.92** |
| qwen3.8-27B Q4_K_M | 262144 (c256k) | 31034 | **8%/92% CPU/GPU** | **4.76** |

末行是本页要留的那条反例：**溢出是静默的** —— 不报错，只是速率掉到四分之一。
`used` 越帽（>30000）与 `PROCESSOR` 掉 GPU 两件事同时发生。

**结论**：① 上下文窗口必须显式指定，不能吃服务端默认（默认按模型**原生**上下文预分配
KV cache，27B 一只的原生上限是 262144，直接吃满即溢出）；② 每一档都要实测，不能按
参数量估算。

**申报模型本体的开发栈读数**：`nemotron-3.5-lightning-c512k`（同一份 GGUF，
`num_ctx=524288`）在 **RTX 4080 SUPER（32760 MiB）** 上量得 —— `nvidia-smi`
`memory.used` = **26,844 MiB**、`PROCESSOR` = **100% GPU**；生成速率 **84.33 tok/s**
（2026-10-12 批 C）。它证明「这份权重 + 这个窗口在这张卡上装得下、不溢出」，
**不是**申报配置的显存读数：后端（Ollama ≠ llama.cpp）与硬件（N 卡 ≠ ROCm 卡）两项都
不同，KV cache 的分配策略也不可互推。

**申报栈的实测结论**（2026-10-19，替换原先「可能装不下」的风险条）：权重本身
25.27 GB，加 524288 窗口的 KV cache（该构建 `kv_unified=true`，`n_ctx_slot` 与
`n_ctx` 同为 524288），申报栈实占 **26.59 GiB = 28,549,861,376 B**，低于 32 GB。
测在 48 GB 卡上；32 GB 档由读数推得（占用不随卡容量缩放），不是实测。按现读数，
本页与 `manifest.json` 的声明**无需回改**。

**历史注记（前任申报模型 Qwen3-8B）**：其 Q4_K_M 形态、`num_ctx=32768` 在同一张
卡上量得 `10.0 GB / 100% GPU`、`nvidia-smi` used = 9822 MiB（2026-10-05）。该读数
说明的是「8B 级模型余量很大」，与现行申报无关，只作历史留存。

---

## 3. 上下文配置

| 项 | 值 |
| --- | --- |
| `max_model_len` | 524288（`serve/llamacpp.sh` 的 `MAX_LEN` 缺省值，该文件注明「须在 MODEL.md 里声明，不是自由参数」；启动日志与 `/v1/models` meta 双双实测为 524288） |
| 单次输出上限（申报上下文） | **16384**（= 官方 `baseline.py` 的 `MAX_TOKENS`；服务栈与基线单请求的上限） |
| 智能体每轮输出帽 | **8192**（2026-10-22 起的**预算旋钮**，不是采样口径；见下与 `results/deadline-removal-20261022/PREREG.md` §2.3） |
| 采样温度 | **0.0** |
| 核采样 `top_p` | **1.0** |
| 请求超时 | **900 s**（客户端读超时；2026-10-22 起由 600 提高，见预登记 §2.4。官方 baseline 的 840 s 是它自己的单请求读超时，不是采样口径 —— 见下） |
| RoPE 外推方式 | 无 |

**524288 的来由**：模型原生上下文 1,048,576，取一半（c512k，与评测模型名一致）。
申报栈已在该窗口下实测：`/v1/models` meta `n_ctx: 524288`、启动日志
`n_ctx_slot = 524288`、占用 26.59 GiB（见 §2.1）。

**采样口径两项（温度 / `top_p`）取与基线相等的值。** 官方 `baseline.py`
（2026-10-19 版）顶部把 `TEMPERATURE` / `TOP_P` / `MAX_TOKENS` / `TIMEOUT_S` 固定为
**0.0 / 1.0 / 16384 / 840** 且该文件**不得修改**，而 §5.3 要求「方案与基线在
**同一次运行**中产出」。采样轴上不等 ⇒ 增益的**分子与分母是在两套采样条件下测出来的**，
那个比值解释不了。

**`MAX_TOKENS` 自 2026-10-22 起不再是采样口径，而是智能体的每轮预算帽（8192）。**
`manifest.context.max_output_tokens` 仍申报 **16384**，与 `baseline.py` 的
`MAX_TOKENS` 逐字相同 —— 那一格是**服务栈 / 基线单请求的输出上下文**。智能体一题内
最多 3 轮、每轮各自成一次请求；每轮帽取 8192 的实测依据是服务器3 全量跑前 91 题的
配对读数（帽 ~12,320 与 600 s 读超时叠加 ⇒ 54 次生成 ≥860 s、48 次判 L0），预登记
`results/deadline-removal-20261022/PREREG.md` §1–§2。

**`TIMEOUT_S` 不是采样参数**：它是**客户端读超时**，同一段 (prompt, 采样口径) 会生成
什么，与等多久放弃无关。本包取 **900 s**（2026-10-22 起；旧值 600，官方 example agent
是 600；baseline 不读这个环境变量，它用自己那个 840 s 常量）。真正要守住的是不变量
**`max_tokens / 吞吐 < timeout_s`**：8192 / 42 tok/s ≈ 195 s < 900 s（旧口径
16384 / 42 ≈ 390 s < 600 s 也成立；A2 臂反例是 cap 8192 + timeout 180 s：两题在
+180.4 s 报 `ReadTimeout`，增益 1.1333 → 1.0000）。

**`serve/env.sh` 与 `agent/llm.py` 两处的缺省值同时对齐（8192 / 900）**，不只是在一处：
评测方按契约**直接调 `run.sh`**，不保证先 source 过谁的配置，所以**代码缺省值才是没人
配置时真正生效的那个**。`serve/env.sh` 里那份是给操作者的显式版本，代码里那份是兜底。
两处不一致本身有守卫；「帽 ≤ 申报上下文」「申报上下文 == baseline 的 `MAX_TOKENS`」
也各有一条（`tools/test_package_hls.py` ⑤）。

**基线运行必须使用与方案完全相同的模型与上下文配置**，否则增益项不可比。

### 3.1 两个模型名（本赛道最容易出错的一格）

分子与分母读的是**两个不同的环境变量**，这是官方设计、不是笔误：

- `agent/llm.py` 读 **`LLM_MODEL`**（缺省 `mock-model`）；
- 官方 `baseline.py` 读 **`MODEL_NAME`**，取不到就退回 `<LLM_BASE_URL>/models`
  列表的**第 0 个**。

`serve/llamacpp.sh` 现已**显式** `--alias "$SERVED_NAME"`（缺省
`nemotron-3.5-lightning-c512k`），不再依赖 `basename $MODEL` 的巧合；`serve/env.sh`
**两个都导出并归一到同一个值**，并把「两个都设了但不相等」判成配置错误。换一个
`/models` 会列出多个模型的服务端时，第 0 个可能**不是你正在跑的那个**：分母悄悄换了
模型，不报错，只给出一个很像真的增益。**这一条属于上下文配置的申报口径，运行时不得
只设其中一个。**

★ `manifest.model.name` 申报的是**权重身份**（`unsloth/…-GGUF` 仓库），不是
`/v1/models` 报的服务名；两者不同是有意的（官方 example 里两者相同，只是 vLLM 拿
模型路径当服务名的巧合）。分子/分母/服务端三处对齐的是**服务名**，见上。

### 3.2 智能体自己的墙钟预算

`AGENT_DEADLINE_S`（2026-10-22 起缺省 **0 = 不设内部截止**，预登记
`results/deadline-removal-20261022/PREREG.md` §2.1；旧值 900）**不是**推理服务参数，
而是智能体的自控预算：正数时它在墙钟前停止生成、把已写好的 `solution.cpp` 交出去。
改成 0 的实测依据：服务器3 全量跑前 91 题里 54 次生成撞满 ~900 s 内部截止、其中 48 次
判 L0 —— 截止把还能救的轮连同已有候选一起收掉。不设内部截止后，外层墙仍在：官方
`serve_api.py` 下发的 `deadline_s + 20`、运行器的单题 kill（3600 s）、以及 agent 自己的
`LLM_TIMEOUT_S`（900）与 `MAX_ROUNDS`（3）。两层超时的关系（外层 `left − 10` 硬墙 /
内层 `AGENT_DEADLINE_S = left`，其中 `left` 已扣除**排队与已运行**时间）见
`serve/README.md`（该段描述的是正数截止时的行为）。

---

## 4. 推理栈

| 项 | 内容 |
| --- | --- |
| 后端 | llama.cpp `llama-server`（OpenAI 兼容端点；申报后端，实测可行） |
| 版本 | `0.4.0-dev (build 1, commit f114f91)`（平台镜像自带） |
| 关键启动参数 | `serve/llamacpp.sh`：`-c 524288` / `-ngl 999`（全层上卡）/ `--alias "$SERVED_NAME"` / `--jinja`（manifest `generation` 生效的前提，FAQ Q6）/ `--no-webui` / `HIP_VISIBLE_DEVICES=0` |
| 接口 | `/v1/chat/completions`（智能体与 `baseline.py` 走同一个端点） |
| 并发策略 | 每卡一实例，单实例串行处理投题 |
| 运行时依赖 | `requirements.txt`（`requests` / `fastapi` / `uvicorn` / `pydantic`），全部烘进镜像 |
| 环境变量补丁 | 镜像把 rocBLAS 的 Tensile 内核库与 `.so` 分开放：启动前需把 `ROCBLAS_TENSILE_LIBPATH` 指到 `/opt/llamacpp/rocblas/library`（官方 FAQ Q6）；脚本里有三级回退，找不到只告警不退出 |

**vLLM 为什么不在表里**：平台镜像的 vLLM 0.27.1 没有 GGUF 加载器（第〇节）。
上游官方 example 用的是 vLLM，这是本方案与官方栈的**已知差异**，也是申报后端
标 `llamacpp` 的原因 —— 申报与实测一致，不写没跑过的栈。

**`LLM_BACKEND` 在评测时必须为 `openai`。** `serve/env.sh` 的缺省是 `mock`（刻意的：
没有推理服务的机器也能跑通链路），忘了设它就会交出桩代码——不是无声的（桩体自带注释，
且 `backend` 进 `trace.jsonl`），但那仍然是一个自伤。

开发期用 **Ollama**（`serve/start-ollama.sh`；开发栈实测版本 **0.34.4**），**不作为
申报配置**，仅用于让开发期读数可复现。两套栈的显存读数不可互搬（第 2 节）。

**断网**：容器没有网络，权重必须已经在本地盘上（`serve/llamacpp.sh` 的 `MODEL` 默认值就是
一个本地路径 `/models/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q4_K_M.gguf`，不是
Hub id）。在线获取权重在沙箱里会失败。

---

## 5. 综合目标（器件与时钟）

| 项 | 值 | 谁读它 |
| --- | --- | --- |
| 目标器件 | `xczu3eg-sbva484-1-e` | `agent/tools.py` 的 `HLS_PART`；综合与实现（L4）用它 |
| 时钟周期 | 5 ns | `agent/tools.py` 的 `HLS_PERIOD_NS` |

- 两处的**代码缺省值**就是上表的值，且与官方 example 的 `Dockerfile` ENV 同值；
  `serve/env.sh` 亦导出同值，并注明「器件与时钟必须与 `model/MODEL.md` 的声明一致」
  —— 本表即该声明。
- **L4 需要综合通过**，而综合必须用赛事方给的目标器件与周期：换器件等于换判据。
  开发期实测工具链为 **Vitis HLS 2025.2（Build 6295257）**，`v++` 须在 PATH
  （详见 `REPORT.md`）。

---

## 6. 微调

**否。** 直接使用上游开源权重，未做任何微调；训练数据不适用。

---

## 7. 声明

- [x] 上述模型为**可本地部署的开源权重**，不是商用 API
- [x] 实测单卡显存占用 **26.59 GiB（28,549,861,376 B），不超过 32 GiB** —— 读数
  取自 48 GB 的 W7900D（第〇节限定①）：重量 + 524288 窗口 KV cache 的占用**不随卡
  容量缩放**，但「32 GB 卡上起得来」是由该读数**推得**，不是在 32 GB 卡上实测
- [x] `run_baseline.sh` 使用与 `run.sh` 完全相同的模型、量化方式与上下文配置 ——
  两者共用同一 `LLM_BASE_URL` 与同一组四项采样常量，且 `run_baseline.sh` 与
  `baseline.py` 均为**赛事方原件、未被改动**
- [x] 若经微调：权重已开源且链接可达 —— **不适用**，未微调
- [x] 本文件内容与 `manifest.json`、`REPORT.md` 一致 —— **本批三处同改后已逐项核对**

**本页 ↔ `manifest.json` 逐项核对**：模型名/来源/revision（manifest 取 commit 哈希
`f2d3fe36…496a`，本页 §1 同时给出同 revision 的文件校验和）/`quantization: "gguf-ud-q4_k_m"` ↔ 第 2 节、
`context.max_model_len: 524288` ↔ 第 3 节、`context.max_output_tokens: 16384` ↔ 第 3 节、
`context.rope_scaling: null` ↔ 第 3 节「无」、`serving.backend: "llamacpp"` ↔ 第 4 节、
`serving.start_command: ./serve/start.sh` ↔ 第 4 节（唯一常驻入口，内部起
`serve/llamacpp.sh`）、`serving.version` ↔ 第〇节的实测版本串、`serving.port: 8000` ↔
`serve/llamacpp.sh` 的 `PORT` 缺省值、`model.measured_vram_gb: 26.59` ↔ 第 2 节、
`agent.skills` 15 条 ↔ `skill/` 下 15 个目录。**无 `null` 待测项**（2026-10-19
实测后已填实，原「两处 `null`」条目作废）。manifest 里仍有两处 `null`：
`finetune_weights_url`（未微调 ⇒ 不适用）与 `generation.reasoning_effort`
（`null` = **不发送**该字段）；两者都是语义上的「无」，不是待测。

**本页 ↔ `REPORT.md`**：`REPORT.md` 第 3 节与本页同源；第 6 节的得分读数出自
**开发栈**（N 卡 + Ollama + 同一份 GGUF + nemotron 权重），凡引用处都标明是开发栈
读数，不冒充申报配置实测。申报配置（ROCm + llama.cpp）的**服务栈**已于 2026-10-19
实测（第〇节）——已测的是「起得来、显存多少、速率多少」，**尚未测的是同一批题在
申报栈上的得分**；两者的差属于栈差，不得把开发栈的分数搬进申报列。

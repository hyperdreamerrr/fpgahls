#!/usr/bin/env bash
# 开发栈的参考启动脚本 —— **不是申报路径**。
#
# 申报路径是 serve/llamacpp.sh（llama.cpp，OpenAI 兼容端点）。
# 本脚本服务的是开发期的那条路：Ollama + GGUF 量化权重，用在一台 32 GB 的
# 开发实例上做模型对比与调参。两套栈的**取值不可互搬**，理由见
# model/MODEL.md 的「两套栈」一节：量化方式、上下文、显存预算全都不同。
#
# 保留这份脚本是为了让开发期读数可复现 —— 报告里引用的每一个开发栈数字，
# 都能用这里的口径重来一遍。
set -euo pipefail

# --- 服务绑定 --------------------------------------------------------------
# 开发期服务与智能体同机不同进程，绑环回口即可；容器内要访问宿主机时才需要
# 0.0.0.0。对外暴露的只有 serve_api.py 的 7860（见 serve/README.md）。
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"

# --- 并发 ------------------------------------------------------------------
# 单卡上并发请求只会互相挤 KV cache，实测无收益。保持 1。
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"

# --- 常驻 ------------------------------------------------------------------
# 只留一个模型常驻。多模型轮流加载会把墙钟烧在换入换出上，而墙钟是计分的。
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"

# --- 上下文（★ 不在本脚本里设）---------------------------------------------
# num_ctx 走**派生的 Modelfile**，不走请求参数：
#
#     # Modelfile-<tag>
#     FROM <base-model>                 # 例：qwen3:8b
#     PARAMETER num_ctx 32768
#
#     ollama create <model>-c32k -f Modelfile-<tag>
#
# 原因：OpenAI 兼容端点（/v1）会收下 `options.num_ctx` 然后丢掉它、不报错，
# 于是你以为压了上下文，其实按原生上下文预分配了 KV cache。派生模型共享
# blob、不额外占盘，是唯一可靠的压法。
#
# 窗口不要拍脑袋定：按「used ≤ 30000 MiB 且 PROCESSOR=100% GPU」逐档实测。
# 实测反例（同一台 32 GB 卡，qwen3.8-27B-Q4_K_M）：c256k 档 used 31034 MiB、
# PROCESSOR 变成 8%/92% CPU/GPU、生成速率从 19.9 掉到 4.76 tok/s —— 溢出是
# **静默**的，不报错，只是慢十倍。逐档读数落在开发树的 results/model-sweep-20261007/
# （开发记录，不随本包交付）。

# 模型名从 env.sh 取，避免预热用的模型与实际跑的模型不是同一个
# （那样预热等于白做，第一题仍要承担加载时间，而墙钟计分）。
# shellcheck source=env.sh
source "$(dirname "$0")/env.sh"

echo "starting ollama (dev stack): OLLAMA_HOST=$OLLAMA_HOST model=$LLM_MODEL"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama 不在 PATH" >&2
  exit 1
fi

ollama serve &
SERVE_PID=$!

# 等就绪再返回，避免调用方 curl 到半启动的服务。
for _ in $(seq 1 60); do
  if curl -sf "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    echo "ollama ready (pid $SERVE_PID)"
    # 预热：把权重先读进显存，避免第一题承担加载时间（墙钟计分）。
    curl -sf "http://${OLLAMA_HOST}/api/chat" \
      -d "{\"model\":\"$LLM_MODEL\",\"messages\":[]}" >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 1
done

echo "ERROR: ollama 60s 内未就绪" >&2
exit 1

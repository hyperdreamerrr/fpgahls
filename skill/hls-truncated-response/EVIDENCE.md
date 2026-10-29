# 证据 — hls-truncated-response

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — c2hlsc__overlapping（失败样本）

- run: `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both/agent/c2hlsc__overlapping/s0/trace.jsonl`
- artifact_sha256: `7187139366ae4434b63a3c5f84a991a13e92569d2769b9c1b4df4d5c8912c3f6`
- artifact_bytes: 2675
- quote_ref: `bytes:1874-2041`
- 引文: `gth，tokens_out=5249）—— 是**预算不够**，不是格式不对。本轮务必把测试台写短：只写必要的驱动与比对，不要打印中间过程。`
- subcause: `empty-sol`
- observed_level: L0 ← `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both/results/agent.c2hlsc__overlapping.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261013/out-20261013T035756-qwen3.8-35b-distill-c128k-full20-both/results/agent.c2hlsc__overlapping.s0.json`

## Q2 — chstone__df_add128（失败样本）

- run: `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both/agent/chstone__df_add128/s0/trace.jsonl`
- artifact_sha256: `93d0be9024d1e3f68a316714ca90e357101ec3fda18bed65345e3ff6ba9a8487`
- artifact_bytes: 2666
- quote_ref: `bytes:1864-2031`
- 引文: `gth，tokens_out=5249）—— 是**预算不够**，不是格式不对。本轮务必把测试台写短：只写必要的驱动与比对，不要打印中间过程。`
- subcause: `empty-sol`
- observed_level: L0 ← `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both/results/agent.chstone__df_add128.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.chstone__df_add128.s0.json`

## Q3 — flowgnn__fgnn_linear（失败样本）

- run: `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both/agent/flowgnn__fgnn_linear/s0/trace.jsonl`
- artifact_sha256: `9e07dae3ef08af377f306019651a24db520dd8d1fcc483a37d580410cfde3832`
- artifact_bytes: 2662
- quote_ref: `bytes:1860-2027`
- 引文: `gth，tokens_out=5249）—— 是**预算不够**，不是格式不对。本轮务必把测试台写短：只写必要的驱动与比对，不要打印中间过程。`
- subcause: `empty-sol`
- observed_level: L0 ← `results/cloud-retest-20261013/out-20261013T085012-gemma-4-31b-qat-c128k-full20-both/results/agent.flowgnn__fgnn_linear.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.flowgnn__fgnn_linear.s0.json`

## 附注

- N1: 草稿来源：node:truncated:-:L0（family=node，count=88，跨 19 题，观测 12 条，弃 15 条）

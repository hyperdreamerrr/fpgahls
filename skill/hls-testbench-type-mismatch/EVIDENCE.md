# 证据 — hls-testbench-type-mismatch

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — hls_polybench__fixed__small__doitgen（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 3
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/hls_polybench__fixed__small__doitgen/s0/trace.jsonl`
- artifact_sha256: `d759cae0dbf7c842e40939b7ce7743165f7d21b913d35b1af4459905687826ec`
- artifact_bytes: 7404
- quote_ref: `bytes:6110-6272`
- 引文: `../../../../agent_tb.cpp:89:54: error: conditional expression is ambiguous; 'ap_fixed<33 aka 33, 17 aka 17>' can be converted to 'ap_fixed<32, 16>' and vice versa`
- subcause: `mismatch`
- observed_level: L2 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.hls_polybench__fixed__small__doitgen.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.hls_polybench__fixed__small__doitgen.s0.json`

## Q2 — machsuite__aes_aes（失败样本）

- run: `results/cloud-retest-20261013/out-20261013T121130-qwen3-coder-30b-a3b-c128k-full20-both`
- round: 3
- artifact: `results/cloud-retest-20261013/out-20261013T121130-qwen3-coder-30b-a3b-c128k-full20-both/agent/machsuite__aes_aes/s0/trace.jsonl`
- artifact_sha256: `670490d1cba58e66c51d85b66799e81410e5e932209bda7ba5632d50b2979c0b`
- artifact_bytes: 10430
- quote_ref: `bytes:6792-6870`
- 引文: `../../../../agent_tb.cpp:38:38: error: function definition is not allowed here`
- subcause: `rc`
- observed_level: L2 ← `results/cloud-retest-20261013/out-20261013T121130-qwen3-coder-30b-a3b-c128k-full20-both/results/agent.machsuite__aes_aes.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.machsuite__aes_aes.s0.json`

## 附注

- N1: 草稿来源：edge:runtime->testbench-compile（family=edge，count=6，跨 6 题，观测 12 条，弃 0 条）

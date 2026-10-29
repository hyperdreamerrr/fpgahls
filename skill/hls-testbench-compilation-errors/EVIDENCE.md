# 证据 — hls-testbench-compilation-errors

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — c2hlsc__add_round_key（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/c2hlsc__add_round_key/s0/trace.jsonl`
- artifact_sha256: `9d426e1551486bb8b2c7acd2d810806c8177cc7cd704ad85baa940f9f1c07911`
- artifact_bytes: 6611
- quote_ref: `bytes:5131-5205`
- 引文: `../../../../agent_tb.cpp:38:9: error: excess elements in array initializer`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.c2hlsc__add_round_key.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.c2hlsc__add_round_key.s0.json`

## Q2 — machsuite__gemm_ncubed（失败样本）

- run: `results/cloud-retest-20261012/out-20261013T011759-glm-4.7-flash-c198k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261012/out-20261013T011759-glm-4.7-flash-c198k-full20-both/agent/machsuite__gemm_ncubed/s0/trace.jsonl`
- artifact_sha256: `2d52261ee1f10dfffe8ac9ad8cf11a4901281f40b962da8a0b04c207bd19095e`
- artifact_bytes: 6594
- quote_ref: `bytes:5117-5197`
- 引文: `../../../../agent_tb.cpp:41:22: error: no member named 'cout' in namespace 'std'`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261013T011759-glm-4.7-flash-c198k-full20-both/results/agent.machsuite__gemm_ncubed.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.machsuite__gemm_ncubed.s0.json`

## 附注

- N1: 草稿来源：node:testbench-compile:00:L4（family=node，count=25，跨 10 题，观测 12 条，弃 0 条）

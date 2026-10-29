# 证据 — hls-testbench-integration

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — c2hlsc__add_round_key（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both/agent/c2hlsc__add_round_key/s0/trace.jsonl`
- artifact_sha256: `f14f2935802c1bb9e45a6ee9dd691a8b20a4c9ec4f789ef06bf6a6420dd5a1cb`
- artifact_bytes: 4833
- quote_ref: `bytes:3973-4093`
- 引文: `源码自己编过了，但**与测试台编不到一起**（最常见：形参不符、缺符号、重复定义 main）`
- subcause: `build-fail`
- observed_level: L1 ← `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both/results/agent.c2hlsc__add_round_key.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.c2hlsc__add_round_key.s0.json`

## Q2 — chstone__df_add128（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both/agent/chstone__df_add128/s0/trace.jsonl`
- artifact_sha256: `9ec7d02c7853cdfad27eaae1f31bced78cc0e023721cd8899c550d78a88733ca`
- artifact_bytes: 4957
- quote_ref: `bytes:4097-4217`
- 引文: `源码自己编过了，但**与测试台编不到一起**（最常见：形参不符、缺符号、重复定义 main）`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both/results/agent.chstone__df_add128.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.chstone__df_add128.s0.json`

## Q3 — flowgnn__fgnn_linear（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both/agent/flowgnn__fgnn_linear/s0/trace.jsonl`
- artifact_sha256: `7ebe750e045c2b970444e6a3bf437c4e68f8a4b728141644ed3ad1a880d1d611`
- artifact_bytes: 4921
- quote_ref: `bytes:4060-4180`
- 引文: `源码自己编过了，但**与测试台编不到一起**（最常见：形参不符、缺符号、重复定义 main）`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T221523-muse-c128k-full20-both/results/agent.flowgnn__fgnn_linear.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.flowgnn__fgnn_linear.s0.json`

## 附注

- N1: 草稿来源：edge:compile->llm-transport（family=edge，count=5，跨 5 题，观测 5 条，弃 5 条）

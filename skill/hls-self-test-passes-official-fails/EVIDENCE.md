# 证据 — hls-self-test-passes-official-fails

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — c2hlsc__add_round_key（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/c2hlsc__add_round_key/s0/trace.jsonl`
- artifact_sha256: `9d426e1551486bb8b2c7acd2d810806c8177cc7cd704ad85baa940f9f1c07911`
- artifact_bytes: 6611
- quote_ref: `bytes:6159-6238`
- 引文: `自写测试台通过（**不是**官方测试台，官方那关仍可能挂）`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.c2hlsc__add_round_key.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.c2hlsc__add_round_key.s0.json`

## Q2 — chstone__df_add128（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 3
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/chstone__df_add128/s0/trace.jsonl`
- artifact_sha256: `1dc5a16421758443af5ae001e84385ce00a41c9643ce45051efbb6e32fdb9a24`
- artifact_bytes: 11622
- quote_ref: `bytes:9502-9581`
- 引文: `自写测试台通过（**不是**官方测试台，官方那关仍可能挂）`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.chstone__df_add128.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.chstone__df_add128.s0.json`

## Q3 — flowgnn__fgnn_linear（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 1
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/flowgnn__fgnn_linear/s0/trace.jsonl`
- artifact_sha256: `ffffa8c1ab023d42cbc8383daabfc92bda29383ec39383d9a8bd58a0ede272c7`
- artifact_bytes: 3808
- quote_ref: `bytes:1687-1766`
- 引文: `自写测试台通过（**不是**官方测试台，官方那关仍可能挂）`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.flowgnn__fgnn_linear.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.flowgnn__fgnn_linear.s0.json`

## 附注

- N1: 草稿来源：node:sc-ok:11:L4（family=node，count=55，跨 12 题，观测 12 条，弃 0 条）

# 证据 — hls-runtime-functional-errors

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — gnnbuilder__compute_neighbor_tables（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/gnnbuilder__compute_neighbor_tables/s0/trace.jsonl`
- artifact_sha256: `b73d7689f6b708f1aa2bbbbbca203c92826512da0ff8ab2ec1dfd0254da1e54b`
- artifact_bytes: 4560
- quote_ref: `bytes:3365-3417`
- 引文: `测试台返回非零退出码 1 —— 功能不对`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.gnnbuilder__compute_neighbor_tables.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.gnnbuilder__compute_neighbor_tables.s0.json`

## Q2 — polybench__doitgen（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 3
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/polybench__doitgen/s0/trace.jsonl`
- artifact_sha256: `c37728ae1c6280d0d071a5e8b00a4b5ad30017ef7624503111954e68f13a7500`
- artifact_bytes: 9264
- quote_ref: `bytes:6102-6154`
- 引文: `测试台返回非零退出码 1 —— 功能不对`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.polybench__doitgen.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.polybench__doitgen.s0.json`

## 附注

- N1: 草稿来源：node:runtime:10:L4（family=node，count=7，跨 5 题，观测 7 条，弃 0 条）

# 证据 — hls-runtime-algorithm-mismatch

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — hls_polybench__fixed__small__gramschmidt（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 3
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/hls_polybench__fixed__small__gramschmidt/s0/trace.jsonl`
- artifact_sha256: `cd4df406bbf0801930b3483c3fe0b9c96b9e1a67d9755ea2905c6e07e566a3d0`
- artifact_bytes: 9613
- quote_ref: `bytes:6064-6157`
- 引文: `与测试台**编译成功**了，但测试台运行结果不对 —— 算法或边界错了`
- subcause: `rc`
- observed_level: L2 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.hls_polybench__fixed__small__gramschmidt.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.hls_polybench__fixed__small__gramschmidt.s0.json`

## 附注

- N1: 草稿来源：node:runtime:10:L2（family=node，count=17，跨 7 题，观测 12 条，弃 0 条）

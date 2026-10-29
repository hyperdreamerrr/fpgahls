# 证据 — hls-testbench-validation

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — pp4fpga__block_mm（失败样本）

- run: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both`
- round: 3
- artifact: `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/agent/pp4fpga__block_mm/s0/trace.jsonl`
- artifact_sha256: `1aa47deaaf221f3c658e54bb93cf4dcbd5731357a6a6aa54ff08ed8e12cc91dd`
- artifact_bytes: 7440
- quote_ref: `bytes:6369-6422`
- 引文: `测试台返回非零退出码 -6 —— 功能不对`
- subcause: `ok`
- observed_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.pp4fpga__block_mm.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.pp4fpga__block_mm.s0.json`

## Q2 — machsuite__sort_radix（失败样本）

- run: `results/cloud-retest-20261013/out-20261013T121130-qwen3-coder-30b-a3b-c128k-full20-both`
- round: 2
- artifact: `results/cloud-retest-20261013/out-20261013T121130-qwen3-coder-30b-a3b-c128k-full20-both/agent/machsuite__sort_radix/s0/trace.jsonl`
- artifact_sha256: `1d9c39eb70348f1208d4d5313f3778d01212e35a804494b3be27867615f8582b`
- artifact_bytes: 4529
- quote_ref: `bytes:2155-2209`
- 引文: `测试台返回非零退出码 -11 —— 功能不对`
- subcause: `rc`
- observed_level: L2 ← `results/cloud-retest-20261013/out-20261013T121130-qwen3-coder-30b-a3b-c128k-full20-both/results/agent.machsuite__sort_radix.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261012/out-20261012T205312-devstral-small-2-c96k-full20-both/results/agent.machsuite__sort_radix.s0.json`

## 附注

- N1: 草稿来源：edge:runtime->runtime（family=edge，count=4，跨 2 题，观测 7 条，弃 0 条）

# 证据 — hls-testbench-compile-errors

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — chstone__df_packFloat64（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 3
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/chstone__df_packFloat64/trace.jsonl`
- artifact_sha256: `4f8c3f34f5fd3e39a80ccf22349271b53453ce17ac49d268d18f40510c809bd0`
- artifact_bytes: 21859
- quote_ref: `bytes:4989-5053`
- 引文: `../../../../agent_tb.cpp:14:9: error: call to 'abs' is ambiguous`
- subcause: `rc`
- observed_level: L2 ← `results/hls-agent-20261001/traj-probe-20261006/judge/chstone__df_packFloat64/r03.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.chstone__df_packFloat64.s0.json`

## Q2 — machsuite__sort_radix（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 2
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/machsuite__sort_radix/trace.jsonl`
- artifact_sha256: `e004d4d572b8384f08c428e4edc6c562ccb79dbf30be552200ea15ee814c525e`
- artifact_bytes: 24800
- quote_ref: `bytes:2224-2304`
- 引文: `../../../../agent_tb.cpp:28:10: error: no member named 'sort' in namespace 'std'`
- subcause: `rc`
- observed_level: L2 ← `results/hls-agent-20261001/traj-probe-20261006/judge/machsuite__sort_radix/r02.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both/results/agent.machsuite__sort_radix.s0.json`

## Q3 — hls_polybench__fixed__small__gramschmidt（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 1
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/hls_polybench__fixed__small__gramschmidt/trace.jsonl`
- artifact_sha256: `86727fc276e1e5802139d581e599387a393d22cf3e1c36bcff36484e7e5160af`
- artifact_bytes: 16847
- quote_ref: `bytes:1639-1703`
- 引文: `../../../../agent_tb.cpp:69:8: error: call to 'abs' is ambiguous`
- subcause: `mismatch`
- observed_level: L2 ← `results/hls-agent-20261001/traj-probe-20261006/judge/hls_polybench__fixed__small__gramschmidt/r01.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.hls_polybench__fixed__small__gramschmidt.s0.json`

## 附注

- N1: 草稿来源：node:rc:1100:L2（family=node，count=31，跨 4 题，观测 12 条，弃 4 条）

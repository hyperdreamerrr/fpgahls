# 证据 — hls-testbench-undeclared-identifiers

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — hls_polybench__fixed__small__2mm（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 1
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/hls_polybench__fixed__small__2mm/trace.jsonl`
- artifact_sha256: `aa519636e51000cce870583bbbe570d63faf50029f934420ae63817f2cabab77`
- artifact_bytes: 14521
- quote_ref: `bytes:1624-1699`
- 引文: `../../../../agent_tb.cpp:52:16: error: use of undeclared identifier 'alpha'`
- subcause: `mismatch`
- observed_level: L2 ← `results/hls-agent-20261001/traj-probe-20261006/judge/hls_polybench__fixed__small__2mm/r01.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both/results/agent.hls_polybench__fixed__small__2mm.s0.json`

## Q2 — hls_polybench__fixed__small__gramschmidt（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 2
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/hls_polybench__fixed__small__gramschmidt/trace.jsonl`
- artifact_sha256: `86727fc276e1e5802139d581e599387a393d22cf3e1c36bcff36484e7e5160af`
- artifact_bytes: 16847
- quote_ref: `bytes:4695-4771`
- 引文: `../../../../agent_tb.cpp:11:32: error: use of undeclared identifier 'rand_r'`
- subcause: `mismatch`
- observed_level: L2 ← `results/hls-agent-20261001/traj-probe-20261006/judge/hls_polybench__fixed__small__gramschmidt/r02.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.hls_polybench__fixed__small__gramschmidt.s0.json`

## Q3 — polybench__gramschmidt（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 1
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/polybench__gramschmidt/trace.jsonl`
- artifact_sha256: `ff6671770ad5aac608bf70a0681aa802184331cb102dde1811828cb737778db3`
- artifact_bytes: 19733
- quote_ref: `bytes:1640-1727`
- 引文: `../../../../agent_tb.cpp:40:5: error: use of undeclared identifier 'kernel_gramschmidt'`
- subcause: `rc`
- observed_level: L2 ← `results/hls-agent-20261001/traj-probe-20261006/judge/polybench__gramschmidt/r01.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.polybench__gramschmidt.s0.json`

## 附注

- N1: 草稿来源：edge:mismatch->mismatch（family=edge，count=9，跨 2 题，观测 11 条，弃 0 条）

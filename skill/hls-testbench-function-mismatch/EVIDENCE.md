# 证据 — hls-testbench-function-mismatch

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — polybench__nussinov（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 1
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/polybench__nussinov/trace.jsonl`
- artifact_sha256: `a69a329c22c1373b3719eb43302c781d25bbdc0a76be75b04ae43cb42f6a2859`
- artifact_bytes: 21986
- quote_ref: `bytes:1634-1733`
- 引文: `../../../../agent_tb.cpp:10:53: error: comparison between pointer and integer ('void *' and 'char')`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/traj-probe-20261006/judge/polybench__nussinov/r01.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T042034-muse-c128k-full20-both/results/agent.polybench__nussinov.s0.json`

## 附注

- N1: 草稿来源：node:build-fail:1000:L1（family=node，count=31，跨 4 题，观测 12 条，弃 14 条）
- N2: rev v3.3（2026-10-09）：正文按 v3.1 后的签名族（ptr/int 比较 + 未声明标号）重写；id 保留历史簇名

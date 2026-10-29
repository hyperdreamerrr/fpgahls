# 证据 — hls-self-verification

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — polybench__2mm（失败样本）

- run: `results/hls-agent-20261001/online-score20-20261004`
- round: 1
- artifact: `results/hls-agent-20261001/online-score20-20261004/out/agent/polybench__2mm/s0/trace.jsonl`
- artifact_sha256: `07747597ded64f7c2b4920543a3ca46b373438770e3937afac81fc77c4cbd94f`
- artifact_bytes: 10036
- quote_ref: `bytes:1600-1676`
- 引文: `../../../../agent_tb.cpp:20:32: error: use of undeclared identifier 'rand_r'`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/online-score20-20261004/out/results/agent.polybench__2mm.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261008T093537-devstral2-full20-both/results/agent.polybench__2mm.s0.json`

## Q2 — polybench__2mm（失败样本）

- run: `results/hls-agent-20261001/localopt7-20261007/control`
- round: 1
- artifact: `results/hls-agent-20261001/localopt7-20261007/control/out/agent/polybench__2mm/s0/trace.jsonl`
- artifact_sha256: `5f7aaa67b357172ae779a01b0e54094c9acdae351f0a888643474abde72ef06d`
- artifact_bytes: 37249
- quote_ref: `bytes:1439-1491`
- 引文: `测试台返回非零退出码 1 —— 功能不对`
- subcause: `rc`
- observed_level: L2 ← `results/hls-agent-20261001/localopt7-20261007/control/out/results/agent.polybench__2mm.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both/results/agent.polybench__2mm.s0.json`

## 附注

- N1: 迁移条目（2026-10-09 用户拍板 ③）：源 = hls-agent/skill/hls-self-verification/SKILL.md（5766 B，手写件）。转换规则与验收判据见 kb/hls/drafts/migrate-20261009/MIGRATION-POLICY.md。
- N2: 去任务化：源件的差分测试样例（题名、具体维度）改写为中性名（kernel_fn/ref_fn）与中性形状；渲染件对证据题名零命中（V6 预检现测）。
- N3: 签名重导（不属 superset）：源 9 条原签名在 note/log 字段级实测为死串（mismatch 0/81、returned non-zero 0、Segmentation fault 0、nan 0/1、inf 0/422、exceeds tolerance 0、golden mismatch 0；FAILED 13/252 与 expected 30/54 有命中但不被本条证据见证）。按三条规则重导为 2 条（模型自写的测试台 0.1391、测试台返回非零退出码 0.0812）。use of undeclared identifier（0.0759）有意不收 —— 归 hls-testbench-undeclared-identifiers 族。
- N4: 无 refuted_approaches：在手证据里没有「不能失败的测试台」的样本（本条两件证据的测试台都如实报了失败），宁缺勿造；该字段可选。
- N5: 源件「the step repeated six times」类数值断言不迁移（错的数不搬）；保留其强调的台阶（0.2→0.8 是最大一跳，正文写作 largest single step）。源件的症状→原因对照表折进 diagnosis。
- N6: 观测/期望等级来源同 hls-interface-contract：run 终局官方判词 + cloud-retest-20261007 实测最高档。

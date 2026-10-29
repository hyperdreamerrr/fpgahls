# 证据 — hls-interface-contract

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — machsuite__gemm_ncubed（失败样本）

- run: `results/hls-agent-20261001/localopt7-20261007/control`
- round: 1
- artifact: `results/hls-agent-20261001/localopt7-20261007/control/out/agent/machsuite__gemm_ncubed/s0/trace.jsonl`
- artifact_sha256: `4dabd11c80a5af47129eca7d3b984510765628b2b7e77d19167e8c81d2edabdb`
- artifact_bytes: 17736
- quote_ref: `bytes:1277-1367`
- 引文: `顶层函数 `gemm` 只有**声明**没有**定义** —— 产出里找不到函数体。`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/localopt7-20261007/control/out/results/agent.machsuite__gemm_ncubed.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both/results/agent.machsuite__gemm_ncubed.s0.json`

## Q2 — gnnbuilder__compute_neighbor_tables（失败样本）

- run: `results/hls-agent-20261001/online-score20-20261004`
- round: 1
- artifact: `results/hls-agent-20261001/online-score20-20261004/out/agent/gnnbuilder__compute_neighbor_tables/s0/trace.jsonl`
- artifact_sha256: `0ad44fe020d65f19d4c9add385b7b0f0bdab47067373b3fd6260373dfd2e2580`
- artifact_bytes: 4250
- quote_ref: `bytes:1449-1552`
- 引文: `待测源码可解析，但没能与测试台编译出 csim.exe（形参不符/符号缺失最常见）`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/online-score20-20261004/out/results/agent.gnnbuilder__compute_neighbor_tables.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261008T042034-muse-c128k-full20-both/results/agent.gnnbuilder__compute_neighbor_tables.s0.json`

## Q3 — c2hlsc__add_round_key（失败样本）

- run: `results/hls-agent-20261001/online-score20-20261004`
- round: 1
- artifact: `results/hls-agent-20261001/online-score20-20261004/out/agent/c2hlsc__add_round_key/s0/trace.jsonl`
- artifact_sha256: `3cacdc9f23e9b248a61a3f736e323ed6ce9ede880dc8d7216f1d81a20e8ff443`
- artifact_bytes: 3372
- quote_ref: `bytes:1265-1338`
- 引文: `顶层函数 `AddRoundKey` 的形参与题目给的接口**不一致**。`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/online-score20-20261004/out/results/agent.c2hlsc__add_round_key.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.c2hlsc__add_round_key.s0.json`

## Q4 — machsuite__gemm_ncubed（反证）

- run: `results/hls-agent-20261001/localopt7-20261007/control`
- round: 20
- artifact: `results/hls-agent-20261001/localopt7-20261007/control/out/agent/machsuite__gemm_ncubed/s0/trace.jsonl`
- artifact_sha256: `4dabd11c80a5af47129eca7d3b984510765628b2b7e77d19167e8c81d2edabdb`
- artifact_bytes: 17736
- quote_ref: `bytes:17313-17403`
- 引文: `顶层函数 `gemm` 只有**声明**没有**定义** —— 产出里找不到函数体。`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/localopt7-20261007/control/out/results/agent.machsuite__gemm_ncubed.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both/results/agent.machsuite__gemm_ncubed.s0.json`

## 附注

- N1: 迁移条目（2026-10-09 用户拍板 ③）：源 = hls-agent/skill/hls-interface-contract/SKILL.md（3680 B，手写件，无结构化证据）。转换规则与验收判据先写于 kb/hls/drafts/migrate-20261009/MIGRATION-POLICY.md，本条目按它落地。
- N2: 去任务化：源件的签名样例（含题名与具体维度形状）改写成中性名与中性形状；渲染件对证据题名零命中（V6 预检现测）。
- N3: 签名重导（不属 superset）：源件 12 条原签名经字段级活度实测只有 undefined symbol（49/1330）在 note/log 命中；error: no matching function（61/1330）有意不收（归 hls-testbench-callsite 族，不抢族）；其余 10 条在 note/log 零命中（duplicate symbol 9 件全在 excerpt，签名够不着）。5 条新签名逐条满足「语料率 ∈ (0,0.6] ∧ 在本条自身证据上下文里命中 ∧ 不抢族」。
- N4: Q4 是反证型**引文**（不是派生）：该 trace 不存 sha16 ⇒ all_rounds_same_sha16 不可算；改用第 1 轮与第 20 轮的同一拒文各引一次，round 连续 1..20 现测成立。
- N5: 观测等级 = 该 run 终局官方判词（out/results/*.s0.json）；期望等级 = 该题在 cloud-retest-20261007 五个模型目录实测最高档（逐目录现测，非自评）。
- N6: V2 的退化坑：本条 id 与包内手写件同名 ⇒ V2 可能被包内件代绿；tools/kb_migrate_check.py 的 V2b（pool=[自身]）单独堵这条路，superset 锚点保证源内容不丢。

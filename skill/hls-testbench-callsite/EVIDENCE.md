# 证据 — hls-testbench-callsite

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — polybench__nussinov（失败样本）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- round: 2
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/polybench__nussinov/trace.jsonl`
- artifact_sha256: `a69a329c22c1373b3719eb43302c781d25bbdc0a76be75b04ae43cb42f6a2859`
- artifact_bytes: 21986
- quote_ref: `bytes:4903-4980`
- 引文: `../../../../agent_tb.cpp:39:31: error: no matching function for call to 'max'`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/traj-probe-20261006/judge/polybench__nussinov/solution.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T042034-muse-c128k-full20-both/results/agent.polybench__nussinov.s0.json`

## Q2 — c2hlsc__add_round_key（失败样本）

- run: `results/hls-agent-20261001/localopt7-20261007/control`
- round: 1
- artifact: `results/hls-agent-20261001/localopt7-20261007/control/out/agent/c2hlsc__add_round_key/s0/trace.jsonl`
- artifact_sha256: `92c56557b915372b4e904ae013a50d9bead101610c3496cbf39b84a48fd0285a`
- artifact_bytes: 57161
- quote_ref: `bytes:1635-1719`
- 引文: `../../../../agent_tb.cpp:34:5: error: no matching function for call to 'AddRoundKey'`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/localopt7-20261007/control/out/results/agent.c2hlsc__add_round_key.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.c2hlsc__add_round_key.s0.json`

## Q3 — hls_polybench__fixed__small__gramschmidt（失败样本）

- run: `results/hls-agent-20261001/localopt7-20261007/control`
- round: 3
- artifact: `results/hls-agent-20261001/localopt7-20261007/control/out/agent/hls_polybench__fixed__small__gramschmidt/s0/trace.jsonl`
- artifact_sha256: `bda5edaafebd36c7ebc18321f5fb4dce7dc7e556d27c4249b594fe6df63c2c6d`
- artifact_bytes: 33946
- quote_ref: `bytes:8273-8364`
- 引文: `../../../../agent_tb.cpp:77:5: error: no matching function for call to 'kernel_gramschmidt'`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/localopt7-20261007/control/out/results/agent.hls_polybench__fixed__small__gramschmidt.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.hls_polybench__fixed__small__gramschmidt.s0.json`

## Q4 — polybench__nussinov（反证）

- run: `results/hls-agent-20261001/traj-probe-20261006`
- artifact: `results/hls-agent-20261001/traj-probe-20261006/runs/polybench__nussinov/rounds/index.jsonl`
- artifact_sha256: `b732bbd175108aae95f4165c6fa03d72e2c710d038c1e48ff013a945f3b3ed1b`
- artifact_bytes: 651
- 派生事实: `all_rounds_same_sha16` = `1ad0f2e9a915f4e2`
  （含义：该 JSONL 全部记录的 sha16 字段两两相同（内核在整段 run 里字节级未变））
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/traj-probe-20261006/judge/polybench__nussinov/solution.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T042034-muse-c128k-full20-both/results/agent.polybench__nussinov.s0.json`

## 附注

- N1: 签名只取两个精确形。更宽的 agent_tb.cpp（实测语料命中 233/1330 = 0.175）被有意排除：它会把运行期失败也拉进注入面，而本条讲的是编译期调用点失败。
- N2: 观测等级 = 各 run 的终局官方判词（traj-probe 的 judge/*.json、localopt7 的 out/results/*.s0.json）；期望等级 = 该题在归档判词里实测到过的最高等级。两者都取自外部判词，不是自评。
- N3: 进包时需同步更新 hls-agent/skill/README.md 的表（包内人读入口），并复核官方 5–15 条要求。
- N4: Q4 是派生型证据（不是引文）：单条引文证不了「七轮全同」，所以由 all_rounds_same_sha16 重算，V4d 判红。

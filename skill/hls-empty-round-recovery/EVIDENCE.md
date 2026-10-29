# 证据 — hls-empty-round-recovery

本文件由 `python -m tools.kb_render` 从 `kb/hls/kb.jsonl` 生成；改条目请改 JSONL。

`quote_ref` 是**原始文件字节**的半开区间（`bytes:<start>-<end>`），校验方式：区间字节按 UTF-8 解码后与 `quote` **逐字相等**；`artifact_sha256` 是整文件原始字节的 sha256。任一对不上，`python -m tools.kb_validate` 判红。

`observed_level` = 该 run 终局官方判词的等级（附来源判词文件）；`expected_level` = 该题在归档判词里实测到过的最高等级（附来源判词文件）。

## Q1 — c2hlsc__add_round_key（失败样本）

- run: `results/cloud-retest-20261007/out-20261008T005755-qwen3.8-c192k-full20-both`
- round: 1
- artifact: `results/cloud-retest-20261007/out-20261008T005755-qwen3.8-c192k-full20-both/agent/c2hlsc__add_round_key/s0/trace.jsonl`
- artifact_sha256: `f91309dc191bdd1dbdc93deb67a09ddad80e573dac6c020ffcb82322955c3604`
- artifact_bytes: 1838
- quote_ref: `bytes:1007-1202`
- 引文: `{"tool": "llm", "round": 1, "max_tokens": 5249, "tokens_in": 1601, "tokens_out": 5249, "content_bytes": 0, "finish_reason": "length", "truncated": true, "elapsed_s": 273.66, "ts": 1791392552.394}`
- subcause: `empty-sol`
- observed_level: L0 ← `results/cloud-retest-20261007/out-20261008T005755-qwen3.8-c192k-full20-both/results/agent.c2hlsc__add_round_key.s0.json`
- expected_level: L4 ← `results/cloud-retest-20261007/out-20261008T093537-devstral2-full20-both/results/agent.c2hlsc__add_round_key.s0.json`

## Q2 — machsuite__aes_aes（失败样本）

- run: `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both`
- round: 1
- artifact: `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/agent/machsuite__aes_aes/s0/trace.jsonl`
- artifact_sha256: `30bbf888b546730075fcb279f303b594fe3eed88f68b7d7436460005bb40bd30`
- artifact_bytes: 2578
- quote_ref: `bytes:1012-1205`
- 引文: `{"tool": "llm", "round": 1, "max_tokens": 5249, "tokens_in": 2201, "tokens_out": 5249, "content_bytes": 0, "finish_reason": "length", "truncated": true, "elapsed_s": 86.2, "ts": 1791418465.487}`
- subcause: `empty-sol`
- observed_level: L0 ← `results/cloud-retest-20261007/out-20261008T072304-glm47flash-full20-both/results/agent.machsuite__aes_aes.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T093537-devstral2-full20-both/results/agent.machsuite__aes_aes.s0.json`

## Q3 — machsuite__sort_radix（失败样本）

- run: `results/model-sweep-20261007/muse-c128k-run/out`
- round: 1
- artifact: `results/model-sweep-20261007/muse-c128k-run/out/agent/machsuite__sort_radix/s0/trace.jsonl`
- artifact_sha256: `7dac21b3ffeca00bd1f7bed187f1c0624d0139c90b439ee20ddfced7a5ce842d`
- artifact_bytes: 1837
- quote_ref: `bytes:1005-1200`
- 引文: `{"tool": "llm", "round": 1, "max_tokens": 5249, "tokens_in": 2523, "tokens_out": 5249, "content_bytes": 0, "finish_reason": "length", "truncated": true, "elapsed_s": 265.03, "ts": 1791375625.521}`
- subcause: `empty-sol`
- observed_level: L0 ← `results/model-sweep-20261007/muse-c128k-run/out/results/agent.machsuite__sort_radix.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T093537-devstral2-full20-both/results/agent.machsuite__sort_radix.s0.json`

## Q4 — c2hlsc__overlapping（失败样本）

- run: `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both`
- round: 3
- artifact: `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both/agent/c2hlsc__overlapping/s0/trace.jsonl`
- artifact_sha256: `70ae63877e9abd8f8f1dd1f2270e38fa4335e1be1023a9a9c7ee76cb737b7722`
- artifact_bytes: 2206
- quote_ref: `bytes:1932-2136`
- 引文: `{"tool": "llm", "round": 3, "rc": 1, "max_tokens": 5000, "excerpt": "ReadTimeout: HTTPConnectionPool(host='127.0.0.1', port=11434): Read timed out. (read timeout=78.22920942306519)", "ts": 1791383770.638}`
- subcause: `empty-sol`
- observed_level: L0 ← `results/cloud-retest-20261007/out-20261007T222636-qwen3-8k-full20-both/results/agent.c2hlsc__overlapping.s0.json`
- expected_level: L3 ← `results/cloud-retest-20261007/out-20261008T093537-devstral2-full20-both/results/agent.c2hlsc__overlapping.s0.json`

## Q5 — machsuite__aes_aes（失败样本）

- run: `results/hls-agent-20261001/localopt7-20261007/control/out`
- round: 1
- artifact: `results/hls-agent-20261001/localopt7-20261007/control/out/agent/machsuite__aes_aes/s0/trace.jsonl`
- artifact_sha256: `04743ee5b40651117c41247b4e597de9114930ceb523e908301d526e15c816c7`
- artifact_bytes: 15006
- quote_ref: `bytes:1034-1231`
- 引文: `{"tool": "llm", "round": 1, "max_tokens": 6229, "tokens_in": 2267, "tokens_out": 6229, "content_bytes": 8657, "finish_reason": "length", "truncated": true, "elapsed_s": 154.1, "ts": 1791344197.681}`
- subcause: `build-fail`
- observed_level: L1 ← `results/hls-agent-20261001/localopt7-20261007/control/out/results/agent.machsuite__aes_aes.s0.json`
- expected_level: L2 ← `results/cloud-retest-20261007/out-20261008T093537-devstral2-full20-both/results/agent.machsuite__aes_aes.s0.json`

## 附注

- N1: Signatures are drawn verbatim from the four repair texts the runtime rebuilds for these classes (truncated / no-code / no-testbench / llm-transport); this skill is injected on the round that follows such a class.
- N2: The transport class includes rounds whose excerpt shows the 500 caused by the old second-system injection format (fixed in the 2026-10 tree upgrade); the recovery action is the same either way.
- N3: Coverage measurement (replay over 13 archived corpora, 2026-10-10). Attempt level (the unit that matters for injection): 950 attempts; the six existing entries fired on 813; 137 were dead - truncated 121 / no-testbench 11 / llm-transport 2 / csynth-fail 3. This entry converts 134 of the dead attempts (every dead attempt in the three template classes it covers; sole selected entry on all 134), raising fired to 947, with 0 displacements and 0 regressions on already-firing attempts. Round level (census, a different unit): 217 template-class rounds (truncated 146 / llm-transport 60 / no-testbench 11), of which 134 became attempts and 83 did not (32 were their run's final round; 51 were followed by a round with no LLM call). The two units must not be pooled.

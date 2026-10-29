---
name: hls-empty-round-recovery
description: Use when the previous round was cut off by the token cap, produced no code block, produced only one block, or the model call failed
---

# Agent Skill: Recovering an unusable round: emit the artifacts now

## Skill Metadata
- **Name:** hls-empty-round-recovery
- **Description:** The previous round left nothing usable — recover by re-emitting the minimal kernel plus testbench in this round, not by restarting the design.
- **Trigger:** The previous round produced nothing usable — its reply was truncated by the max_tokens cap, contained no fenced code block, contained only the kernel block, or the model call itself failed (timeout / HTTP error) — and the run still has rounds left.
- **Log signatures:** `截断（finish_reason=length`, `本轮务必把测试台写短`, `上一轮回复里没有找到代码块`, `上一轮只给了一个代码块`, `上一轮模型调用失败`

## Symptom

The run is mid-task and the previous exchange produced no usable artifact. Three trace shapes lead here: an llm event with content_bytes=0 and finish_reason="length" (the cap hit before any text was emitted); an llm event with rc=1 (read timeout or HTTP error); or an extract step that found no fenced block, or only the kernel block. In every case the harness rebuilds a one-paragraph repair note and the run continues to the next round. What is at stake in this round: the budget already spent, and the fact that a capped reply leaves no memory of its own content — left alone the next reply tends to re-plan from scratch and truncate again in the same place.

## Diagnosis

The previous round failed on shape and budget, not on content. A cap-truncated round is not evidence that the approach was wrong: the reply was cut before it became an artifact, so nothing was tested and nothing was disproved. Re-planning from scratch re-spends the same budget on the same over-long reply. A missing testbench block is not a wrong kernel either — it is the self-check half of the reply that never arrived. A transport failure says nothing about the kernel at all. The correct move in all four cases is the smallest possible next reply that still advances the run: the two artifacts the harness parses (kernel first, then a minimal testbench), or, if a kernel already survived, both blocks again so the reply is self-contained.

## Procedure

1. Do not restart the design and do not re-derive the algorithm. If a complete kernel survived an earlier round, keep it unchanged; change only what the failure requires.
2. Reply with exactly two ```cpp fenced blocks — kernel first (no main), then the testbench (with main) — and nothing else: no apology, no plan, no analysis of the previous attempt.
3. If the harness note says a code block was already found, still send both blocks: the reply is parsed on its own, and a lone testbench block without its kernel cannot be checked.
4. Keep the kernel minimal: fixed-size buffers, no debug prints, no long comments, no unrolled or pipelined variants left in the file. Correct beats clever — a correct simple kernel fits the budget; an optimized one usually does not.
5. Keep the testbench short: one small deterministic input, one plain reference implementation, compare and print a single PASS/FAIL line. No timing code, no random loops, no large dumps.
6. Assume the cap can hit again: every sentence outside the two blocks is budget taken from the code that has to pass the gates.

## Behavioral Constraints

- The first characters of the reply must be the opening fence of the kernel block — no preamble of any kind.
- Do not paste the previous attempt back as commentary; blocks only.
- Do not drop the testbench block to save budget: without it the round cannot self-check and the run stalls at the interface level.
- Do not switch algorithm or restructure a kernel that already compiled and passed an earlier gate — cap damage is not correctness evidence.

## Applicability

**Applies when:** The previous round's trace shows an empty or unusable reply (cap-truncated, no code block, only one block, or a transport failure), the run continues, and a minimal kernel plus testbench can still fit in a single reply.

**Does not apply when:**

The previous round produced a usable kernel + testbench pair — then the failure is build or numeric and the callsite / interface-contract / self-verification entries own it. Also not applicable when the round keeps truncating because even a minimal pair does not fit the budget: reduce scope first (smaller fixed sizes, no unrolling) instead of spending another identical round. And when the transport failure is persistent, it is an environment problem, not a prompt-shape problem.

## Refuted approaches

- Re-prompting with the full original task and a bare 'try again' — the model re-plans from scratch, produces the same over-long reply, and truncates at the same place.
- Asking for the kernel only ('skip the testbench to save budget') — saves one budget hit but forfeits self-check; the run cannot recover past the interface level.

## Common mistakes

- Treating a cap-truncated round as evidence the algorithm was wrong and switching strategies mid-task — the truncation carries no information about correctness.
- Spending the recovery round on an explanation of what went wrong instead of code.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

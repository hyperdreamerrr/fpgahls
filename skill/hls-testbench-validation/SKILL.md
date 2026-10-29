---
name: hls-testbench-validation
description: Use when testbench returns non-zero exit code despite successful compilation
---

# Agent Skill: Validate testbench compatibility with implementation

## Skill Metadata
- **Name:** hls-testbench-validation
- **Description:** Ensure implementation matches testbench expectations
- **Trigger:** Testbench returns non-zero exit code after successful compilation
- **Log signatures:** `测试台返回非零退出码 -6 —— 功能不对`, `测试台返回非零退出码 -11 —— 功能不对`

## Symptom

Testbench returns non-zero exit code (-6/-11) despite successful compilation. Algorithmic or boundary errors cause functional mismatch with testbench expectations.

## Diagnosis

The implementation does not produce results consistent with the testbench's expected behavior, indicating algorithmic errors or incorrect handling of edge cases.

## Procedure

1. Verify testbench input/output specifications match implementation requirements
2. Compare intermediate results with testbench reference values at critical computation stages
3. Validate boundary conditions and edge case handling against testbench expectations

## Behavioral Constraints

- Testbench must be fully functional and correctly implemented
- Implementation must adhere to all interface constraints specified in the testbench

## Applicability

**Applies when:** When the implementation compiles successfully but fails functional validation against the testbench

**Does not apply when:**

When compilation errors or syntax issues prevent testbench integration

## Refuted approaches

- Assuming testbench validation is automatic with successful compilation
- Ignoring testbench output when encountering non-zero exit codes

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

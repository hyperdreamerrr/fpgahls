---
name: hls-runtime-algorithm-mismatch
description: Use when testbench compiles but returns non-zero exit code due to functional errors
---

# Agent Skill: Runtime Mismatch Due to Algorithmic Errors

## Skill Metadata
- **Name:** hls-runtime-algorithm-mismatch
- **Description:** Fix algorithmic errors causing testbench failure
- **Trigger:** Testbench compiles successfully but returns non-zero exit code
- **Log signatures:** `测试台返回非零退出码 -8 —— 功能不对`

## Symptom

Testbench runs but produces incorrect results. Exit codes indicate functional mismatch between implementation and specification.

## Diagnosis

The implementation contains algorithmic errors or boundary condition violations that diverge from the expected behavior defined in the testbench.

## Procedure

1. Verify algorithm logic matches the testbench specification
2. Validate all edge cases and boundary conditions
3. Compare output against expected results from the testbench

## Behavioral Constraints

- Must align with the testbench interface requirements
- Cannot assume implicit behavior beyond specified constraints

## Applicability

**Applies when:** When testbench compiles successfully but returns non-zero exit code indicating functional mismatch

**Does not apply when:**

When compilation errors exist or the issue is due to missing symbol definitions

## Refuted approaches

- Relying on partial test cases without full validation
- Ignoring exit code values during debugging

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

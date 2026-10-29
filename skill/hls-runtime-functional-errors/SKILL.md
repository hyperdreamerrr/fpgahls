---
name: hls-runtime-functional-errors
description: Use when testbench compiles but returns non-zero exit code indicating functional failure
---

# Agent Skill: Runtime Functional Errors Due to Algorithmic or Boundary Mismatches

## Skill Metadata
- **Name:** hls-runtime-functional-errors
- **Description:** Fix algorithmic errors or boundary condition mismatches
- **Trigger:** Testbench compiles successfully but returns non-zero exit code
- **Log signatures:** `测试台返回非零退出码 1 —— 功能不对`

## Symptom

Testbench runs but produces incorrect results. Exit codes like 1 or -6 indicate functional failures rather than compilation errors.

## Diagnosis

The implementation contains algorithmic errors or incorrect boundary handling that cause the testbench to fail despite successful compilation.

## Procedure

1. Verify algorithm logic matches problem requirements
2. Validate all boundary conditions and edge cases
3. Compare output against expected results from testbench

## Behavioral Constraints

- Ensure code adheres to specified interface requirements
- Use complete test cases for validation

## Applicability

**Applies when:** When testbench compiles successfully but returns non-zero exit code indicating functional failure

**Does not apply when:**

When compilation errors or undefined symbols are present

## Refuted approaches

- Relying on partial test cases
- Ignoring testbench exit codes

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

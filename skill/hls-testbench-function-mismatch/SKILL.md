---
name: hls-testbench-function-mismatch
description: Use when testbench compilation fails with pointer/integer comparisons or undeclared labels
---

# Agent Skill: Testbench Type and Label Errors in Compilation

## Skill Metadata
- **Name:** hls-testbench-function-mismatch
- **Description:** Testbench compilation errors from mismatched expression types (pointer vs integer) or jumps to undefined labels
- **Trigger:** Compilation failure in testbench files (agent_tb.cpp) with pointer/integer comparisons or undeclared labels
- **Log signatures:** `error: comparison between pointer and integer ('void *' and 'char')`, `error: use of undeclared label 'b'`

## Symptom

Compiler reports 'comparison between pointer and integer' or 'use of undeclared label' errors
Testbench fails to compile before kernel code is reached

## Diagnosis

The testbench contains expressions that do not type-check (for example comparing a pointer against a character constant) or a jump to a label that is never defined. These errors are independent of the kernel implementation itself.

## Procedure

1. Open the testbench at the reported line and column and inspect the flagged expression
2. Fix pointer/integer comparisons so both operands have compatible types (dereference or cast the pointer side as needed)
3. For an undeclared label, add the missing label target or remove the jump that references it
4. Recompile testbench and confirm the type and label errors are cleared

## Behavioral Constraints

- Do not modify kernel implementation code
- Ensure compared values have compatible types
- Avoid jumps to labels that are not defined in the same function

## Applicability

**Applies when:** Testbench compilation errors explicitly mention pointer/integer comparisons or undeclared labels

**Does not apply when:**

Kernel code compilation errors dominate the log output

## Refuted approaches

- Modifying kernel code to satisfy testbench errors
- Ignoring type mismatch warnings

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

---
name: hls-testbench-compile-errors
description: Use when testbench compilation fails with ambiguous function calls or missing std-namespace members
---

# Agent Skill: Testbench Compilation Errors in HLS Workflow

## Skill Metadata
- **Name:** hls-testbench-compile-errors
- **Description:** Fix testbench compilation errors by resolving ambiguous function calls and missing dependencies
- **Trigger:** Testbench compilation fails with ambiguous function calls or missing std-namespace members
- **Log signatures:** `call to 'abs' is ambiguous`, `no member named 'sort' in namespace 'std'`

## Symptom

Compiler reports errors in testbench file (agent_tb.cpp) such as 'call to 'abs' is ambiguous' or a missing member of namespace 'std'.
Grader returns non-zero exit codes indicating testbench failure, not kernel issues.

## Diagnosis

The testbench contains unresolved dependencies or incorrect function calls. Ambiguous function calls suggest multiple overloaded functions or missing namespace qualifiers. Missing std-namespace members indicate a missing standard-library include or a name used without its namespace.

## Procedure

1. Check for ambiguous function calls and add namespace qualifiers (e.g., std::abs)
2. Verify all used functions are declared or included in the testbench
3. Ensure standard library functions like sort() are properly qualified with std::
4. Recompile testbench and confirm the ambiguous-call and missing-member errors are cleared

## Behavioral Constraints

- Do not modify kernel implementation files
- Focus only on testbench code modifications
- Ensure all changes comply with HLS toolchain requirements

## Applicability

**Applies when:** Testbench compilation errors occur before kernel compilation starts

**Does not apply when:**

Kernel compilation fails first or errors are unrelated to testbench code

## Refuted approaches

- Modifying kernel code to fix testbench errors
- Using non-standard library functions without proper qualification

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

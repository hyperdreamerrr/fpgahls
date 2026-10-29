---
name: hls-testbench-undeclared-identifiers
description: Use when testbench compilation errors indicate undeclared identifiers
---

# Agent Skill: Testbench Compilation Fails Due to Undeclared Identifiers

## Skill Metadata
- **Name:** hls-testbench-undeclared-identifiers
- **Description:** Compilation errors in testbench code due to missing variable declarations or function definitions
- **Trigger:** Testbench compilation fails with errors about undeclared identifiers
- **Log signatures:** `use of undeclared identifier`, `error: use of undeclared identifier 'alpha'`, `error: use of undeclared identifier 'rand_r'`

## Symptom

Compiler reports errors like 'use of undeclared identifier'.
Testbench code fails to compile before kernel implementation is reached.

## Diagnosis

The testbench code references variables or functions that are not properly declared or included. These errors originate from the testbench implementation, not the kernel logic.

## Procedure

1. Verify all variables used in testbench code are declared in scope
2. Check for missing include directives for required headers
3. Ensure every referenced function has a visible declaration or prototype in the testbench
4. Recompile testbench and confirm every referenced name resolves

## Behavioral Constraints

- Do not modify kernel implementation until testbench is fully validated
- All variables must be declared before first use in testbench
- Every referenced function must be declared or included before use in testbench

## Applicability

**Applies when:** Testbench compilation errors explicitly mention undeclared identifiers

**Does not apply when:**

Kernel implementation errors occur before testbench compilation completes

## Refuted approaches

- Modifying kernel code to resolve testbench compilation errors
- Ignoring compiler warnings about undeclared identifiers

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

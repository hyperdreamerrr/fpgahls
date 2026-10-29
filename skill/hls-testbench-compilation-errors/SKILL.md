---
name: hls-testbench-compilation-errors
description: Use when testbench fails to compile with identifier/initializer errors
---

# Agent Skill: Fix Testbench Compilation Errors in HLS

## Skill Metadata
- **Name:** hls-testbench-compilation-errors
- **Description:** Address testbench-specific compilation failures
- **Trigger:** Testbench compilation errors pointing to agent_tb.cpp
- **Log signatures:** `excess elements in array initializer`, `cannot take the address of an rvalue of type 'int'`, `no member named 'cout' in namespace 'std'`

## Symptom

Compiler errors in testbench file (agent_tb.cpp) unrelated to kernel code

## Diagnosis

Testbench contains type mismatches, missing includes, or incorrect parameter order. Common issues include ap_fixed/double conversion, missing hls::abs, and undeclared identifiers.

## Procedure

1. Verify all kernel parameters are correctly ordered in testbench calls
2. Add missing includes for hls libraries and standard headers
3. Explicitly cast between ap_fixed and double types in testbench
4. Replace std::abs with hls::abs in testbench code

## Behavioral Constraints

- Do not modify kernel implementation
- Only fix testbench code
- Preserve original algorithm logic

## Applicability

**Applies when:** When compiler errors originate from testbench files (agent_tb.cpp) and not the kernel implementation

**Does not apply when:**

When errors stem from kernel code itself or hardware synthesis constraints

## Refuted approaches

- Rewriting algorithm implementation
- Ignoring compiler error messages
- Removing necessary type conversions

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

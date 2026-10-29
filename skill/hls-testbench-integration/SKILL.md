---
name: hls-testbench-integration
description: Use when source code compiles alone but fails to link with testbench
---

# Agent Skill: Ensure Testbench Compatibility in HLS Projects

## Skill Metadata
- **Name:** hls-testbench-integration
- **Description:** Fix integration issues between generated code and testbench
- **Trigger:** Compilation succeeds for source code but fails when combined with testbench
- **Log signatures:** `源码自己编过了，但**与测试台编不到一起**（最常见：形参不符、缺符号、重复定义 main）`, `待测源码可解析，但没能与测试台编译出 csim.exe（形参不符/符号缺失最常见）`

## Symptom

Csim.exe not generated despite source code being compilable. Common errors include parameter mismatches, missing symbols, or duplicate main function definitions.

## Diagnosis

The generated code lacks required symbols or has incompatible function signatures that prevent successful linking with the testbench environment.

## Procedure

1. Verify function parameter types and counts match testbench expectations
2. Check for duplicate main() definitions in both source and testbench
3. Ensure all required symbols are exported and available in the linkage

## Behavioral Constraints

- Do not modify the testbench interface without explicit approval
- Maintain parameter consistency between implementation and interface

## Applicability

**Applies when:** When the source code compiles successfully on its own but fails to link with the provided testbench

**Does not apply when:**

When the testbench itself contains compilation errors or when the code is intentionally isolated from the testbench

## Refuted approaches

- Assuming code correctness without testbench integration verification
- Ignoring parameter type mismatches between implementation and interface

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

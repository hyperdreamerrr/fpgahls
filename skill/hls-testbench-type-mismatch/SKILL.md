---
name: hls-testbench-type-mismatch
description: Use when testbench fails to compile with ambiguous type conversions or missing function definitions
---

# Agent Skill: Testbench Compilation Errors Due to Type Mismatches and Missing Includes

## Skill Metadata
- **Name:** hls-testbench-type-mismatch
- **Description:** Fix testbench compilation errors caused by type mismatches and missing includes
- **Trigger:** Testbench compiles but fails with ambiguous type conversions or missing function definitions
- **Log signatures:** `conditional expression is ambiguous; 'ap_fixed<33 aka 33, 17 aka 17>' can be converted to 'ap_fixed<32, 16>' and vice versa`, `function definition is not allowed here`

## Symptom

Compiler reports ambiguous type conversions between ap_fixed types, missing function definitions, or undeclared identifiers in testbench code

## Diagnosis

The testbench contains type mismatches between ap_fixed widths/precision, missing include directives for HLS functions, or incorrect function signature implementations that don't match the kernel's interface

## Procedure

1. Explicitly cast between ap_fixed types using static_cast or explicit conversion operators
2. Add missing include directives for hls_math.h and hls_stream.h
3. Verify function parameter order and data types match the kernel's interface declaration
4. Replace std::abs with hls::abs for fixed-point operations

## Behavioral Constraints

- Do not modify kernel implementation code
- Preserve original algorithm logic
- Only adjust testbench code for type conversions

## Applicability

**Applies when:** When testbench compilation fails with ambiguous type conversions between ap_fixed types or missing function definitions

**Does not apply when:**

When kernel code contains syntax errors or when testbench errors are caused by incorrect simulation environment setup

## Refuted approaches

- Rewriting algorithm implementation
- Ignoring compiler error messages
- Changing kernel interface parameters

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

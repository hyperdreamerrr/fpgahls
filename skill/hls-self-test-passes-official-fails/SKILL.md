---
name: hls-self-test-passes-official-fails
description: Use when self-test bench compiles but official validation fails
---

# Agent Skill: Self-written test bench passes but official fails

## Skill Metadata
- **Name:** hls-self-test-passes-official-fails
- **Description:** Ensure test bench matches official interface requirements
- **Trigger:** Self-written test bench passes but official validation fails
- **Log signatures:** `自写测试台通过（**不是**官方测试台，官方那关仍可能挂）`

## Symptom

Self-written test bench compiles and passes (tool log: 自写测试台通过（**不是**官方测试台...)), but official validation may still fail

## Diagnosis

The test bench implementation does not align with the official validation interface requirements, leading to successful self-testing but failure in official validation

## Procedure

1. Verify the test bench matches the official interface specifications
2. Reimplement test bench using official validation parameters
3. Validate against official test vectors and constraints

## Behavioral Constraints

- Do not use unofficial test benches for final validation
- Must adhere to problem-specific interface requirements

## Applicability

**Applies when:** When the test bench passes self-validation but fails official validation

**Does not apply when:**

When the test bench is explicitly required to be self-written and verified

## Refuted approaches

- Relying solely on self-written test benches for validation
- Assuming interface consistency between self-test and official validation

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

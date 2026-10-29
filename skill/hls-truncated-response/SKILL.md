---
name: hls-truncated-response
description: Use when HLS responses are truncated by max_tokens limits
---

# Agent Skill: Avoid truncation due to token budget limits

## Skill Metadata
- **Name:** hls-truncated-response
- **Description:** Prevent response truncation by optimizing testbench size
- **Trigger:** When response is truncated with finish_reason=length
- **Log signatures:** `本轮务必把测试台写短：只写必要的驱动与比对，不要打印中间过程`

## Symptom

Grader reports truncation errors with max_tokens limits. Testbench fails to compile or execute due to incomplete code.

## Diagnosis

The model's response exceeds the token budget limit, causing partial output. This often happens when testbenches include unnecessary code or verbose diagnostics.

## Procedure

1. Write minimal testbench with only required stimulus and verification
2. Avoid printing intermediate debug information
3. Ensure testbench matches exactly with the required interface specifications

## Behavioral Constraints

- Testbench must contain only essential code
- No additional debug prints or comments
- Must adhere strictly to interface requirements

## Applicability

**Applies when:** When the error indicates truncation due to token limits, and the response contains incomplete testbench code

**Does not apply when:**

When the error is caused by syntax errors, missing implementations, or interface mismatches

## Refuted approaches

- Adding extra debug prints to the testbench
- Including full waveform dumps or verbose diagnostics
- Using complex test patterns with multiple stimuli

## Common mistakes

- None recorded.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

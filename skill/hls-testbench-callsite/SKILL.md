---
name: hls-testbench-callsite
description: Use when csim.exe is never produced and the first compiler error points at a call site inside agent_tb.cpp
---

# Agent Skill: Testbench call-site mismatch

## Skill Metadata
- **Name:** hls-testbench-callsite
- **Description:** When the testbench's own call does not match the kernel's declaration, the fix belongs in the call's arguments, never in the kernel.
- **Trigger:** csim.exe is not produced and the first error line points at a call site inside agent_tb.cpp, the testbench the agent wrote itself.
- **Log signatures:** `no matching function for call to`

## Symptom

The build stops before linking: the compiler reports `no matching function for call to '<name>'` (or that an overload `is ambiguous`), and the quoted error line points into `agent_tb.cpp` -- the testbench the agent wrote itself in an earlier round. No error line points into the kernel source file.

## Diagnosis

Testbench and kernel are compiled together, and the kernel is never reached: compilation stopped at the testbench's call. The one thing the message establishes is that the call's argument list does not match the function's declaration. It says nothing about the kernel's algorithm, its numeric format, or its pragmas.

Usual causes, in order of frequency: argument count; argument type (for example `unsigned char*` where the declaration wants `unsigned char (*)[4][4]`); a dropped trailing array dimension; a missing `const` or reference qualifier; or an overload that needs an explicit cast to be disambiguated.

## Procedure

1. Open the call site the error line names (`agent_tb.cpp:<line>:<column>`) and compare it token by token with the kernel's declaration of that function: argument count, each argument's type and qualifiers, each array dimension.
2. First check the kernel's top-level declaration against the interface the task gave, verbatim. If they differ, the kernel is what needs fixing -- restore its signature and follow the `hls-interface-contract` skill; the rest of this skill does not apply.
3. If they agree, the fault is in the testbench's call. Rewrite the arguments to match the declaration: explicit casts, `&` where the parameter is a pointer, the declared array shape. Change only `agent_tb.cpp`.
4. On `is ambiguous`, add an explicit cast to the exact parameter type the declaration names. Still only the testbench changes.
5. Re-run. Do not touch the kernel's arithmetic, loops, or pragmas in the same round: nothing in this log points at them.

## Behavioral Constraints

- In this failure class the kernel source file does not change, not by one character; only the call inside `agent_tb.cpp` does.
- Never add, drop, or widen a kernel parameter to make an error go away: the top-level signature is part of the graded interface, and changing it turns a gradable build failure into an unlinkable one.
- A rewritten testbench is acceptable only if its call still matches the declaration and the checks it performed survive; deleting the failing call is not a fix.
- If the first error line points into the kernel source file instead of `agent_tb.cpp`, stop -- the kernel has its own compile error.

## Applicability

**Applies when:** The first compiler error line points into `agent_tb.cpp`, and no error line points into the kernel source file.

**Does not apply when:**

- The first error line points into the kernel source file: that is the kernel's own compile error.
- `csim.exe` was produced and the failure is at run time (non-zero exit status, timeout, or values outside tolerance): separate failure classes.
- The failure is environmental (a missing tool, a judging timeout).

## Refuted approaches

- Rewriting the kernel to satisfy the testbench's call. In the recorded failure the kernel stayed byte-identical across all seven rounds (Q4 in `EVIDENCE.md`) while the same call-site error kept coming back, so those rounds were spent without the log changing at all.
- Commenting out the failing call, or replacing it with one that compiles. The build goes green, but the testbench no longer exercises the intended interface, and a later pass verdict is a false pass.

## Common mistakes

- Reading `agent_tb.cpp:<line>:<column>` as a line of the kernel: both files live in the same work directory, and the wrong file gets edited.
- Matching the argument count but not the types: the trailing dimension of a multi-dimensional array, and pointer-to-array spellings, are the usual miss.
- Tidying up the top-level signature while already in the file: the graded interface changed and the link now fails.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

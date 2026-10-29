---
name: hls-interface-contract
description: Use when the kernel fails to compile or link together with the testbench — signature mismatch, duplicate main, missing symbol
---

# Agent Skill: Kernel / testbench interface contract

## Skill Metadata
- **Name:** hls-interface-contract
- **Description:** The three ways a kernel can be correct in itself and still fail to link with the official testbench.
- **Trigger:** The kernel compiles on its own but csim.exe is never produced; the compiler complains about the top-level function's arguments, a conflicting declaration, or a duplicate main.
- **Log signatures:** `只有**声明**没有**定义**`, `产出里找不到`, `与题目给的接口**不一致**`, `没能与测试台编译出 csim.exe`, `undefined symbol`

## Symptom

csim.exe is never produced, and the failing step is the kernel's own interface. The log arrives in one of three shapes:

- a link-time undefined symbol for the top-level function, even though the kernel file appears to define it;
- the top-level function's parameters differ from the interface the task declares — an extra parameter, a dropped one, or a spelling/typedef difference in a parameter type;
- a duplicate main, because the kernel defines its own entry point.

In all three the arithmetic is irrelevant: `csynth` compiles the kernel alone, so a wrong interface still synthesizes perfectly. Nothing in the log implicates a loop, a pragma, or a numeric format.

## Diagnosis

The official testbench is compiled against the interface the task declares. If the kernel's definition of the top-level function does not match that declaration — a changed parameter type, a dropped parameter, a rewritten array dimension, a different name, or no definition at all because only a prototype was emitted — the testbench's call binds to the declaration and nothing defines it. That is a link error, not a compile error, and it caps the whole run: the submission reaches neither L2 nor L3.

The scoring ladder is strict and each rung needs the ones below it: L1 parses (coefficient 0.1), L2 builds against the official testbench (0.2), L3 runs and passes (0.8), L4 also synthesizes cleanly (1.0). An interface failure stops at the first rung, so the largest single step on the ladder — 0.2 to 0.8 — is lost before anything about the kernel's design has been judged.

The three failure shapes:

1. The signature was changed. Array dimensions are part of the type: in an array parameter the first dimension may be written or omitted (the parameter decays to a pointer-to-array), but the trailing dimensions may not change. The fix is to copy the declaration out of the interface verbatim and use it as the definition — do not retype it from memory, do not tidy it up.
2. The kernel defines main. The official testbench has its own main, so two definitions is a duplicate-symbol link error. The kernel is a library, not a program. (The self-check testbench the agent writes itself is a separate main in the other code block; that one is correct.)
3. A helper was declared but not defined. A `static inline` helper in a header, or a prototype with no body, produces an undefined symbol at link time even though every file compiled. Either define the helper in the kernel, or mark it `static inline` and give it a body.

When an interface check refuses the submission, it is this same failure seen earlier: the parameters were compared token by token against the interface the task gave, and they differ by a spelling, a typedef, or a dimension. The refusal is telling the agent which of the two texts to trust: the task's.

## Procedure

1. Read the failing symbol name out of the log — it is the thing to fix; do not rewrite the arithmetic, nothing in the log implicates it.
2. Compare the kernel's definition of the top-level function against the interface, token by token: return type, name, each parameter's type in order, and each array's trailing dimensions.
3. Make the definition character-identical to the declaration: copy it out of the interface, do not retype it.
4. Delete any main the kernel defines; the kernel is a library.
5. Give every declared helper a body, or mark it `static inline` and give it a body.
6. Re-emit both blocks — the kernel and the testbench — unchanged except for the interface fix.

## Behavioral Constraints

- In this failure class the kernel's arithmetic does not change, not by one character; only the declaration matching the interface does.
- Never rename the top-level function: the name is the testbench's to call, not the agent's to choose.
- Do not add `extern "C"`: both files are compiled as C++, so there is no name-mangling mismatch to solve, and the wrapper changes the function's type.
- A prototype with no body is not a definition: re-emitting it unchanged reproduces the identical refusal in every round of a recorded run (first round and last round are Q1 and Q4 in `EVIDENCE.md`).

## Applicability

**Applies when:** csim.exe is never produced and the log shows one of: an undefined link-time symbol for the top-level function, a parameter mismatch against the interface the task gave, or a duplicate main.

**Does not apply when:**

- The first error line points into the testbench the agent wrote itself: that is the call-site family, not the kernel's interface.
- csim.exe was produced and the failure is at run time: a wrong exit status or values outside tolerance belong to the self-verification family.
- The failure is environmental (a missing tool, a judging timeout).

## Refuted approaches

- Re-emitting the prototype instead of a function body. In the recorded failure the identical refusal came back in every one of the 20 rounds, and the submission never gained a function body (Q1 is the first round, Q4 the last).

## Common mistakes

- Fixing the arithmetic when the log says the top-level symbol is undefined: the log never implicated it, and the edit risks what already worked.
- Adding `extern "C"` to fix the link: there is no name-mangling mismatch (both files are C++), and the wrapper changes the function's type.
- Renaming the top-level function to something clearer: the testbench calls it by the name the interface gives.
- Reading an interface-check refusal as a testbench problem: the refusal quotes the interface, so the kernel's declaration is the text to correct.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

---
name: hls-self-verification
description: Use when the kernel compiles but the result is wrong, missing, or the run exits non-zero — build a differential testbench before touching the kernel
---

# Agent Skill: Proving a kernel computes the right answer

## Skill Metadata
- **Name:** hls-self-verification
- **Description:** Write a reference implementation and test the kernel against it on fixed, reproducible inputs before claiming anything about correctness.
- **Trigger:** csim.exe builds but the run fails: wrong values, a non-zero exit status, or no output at all.
- **Log signatures:** `模型自写的测试台`, `测试台返回非零退出码`

## Symptom

The kernel compiles and links, so the interface is not the problem; the failure is at run time. Typical shapes: the run exits non-zero; a value mismatch against the expected result; nan or inf where a finite number was expected; or the testbench crashing before printing anything.

You never see the official testbench: during a run only the task statement is visible, and the real testbench is applied by the judge afterwards, so guessing what it checks teaches nothing. The only instrument available for finding out why the values are wrong is a testbench the agent writes itself. That matters because of where the run stands — the ladder is L1 parses (0.1), L2 builds (0.2), L3 runs and passes (0.8), L4 also synthesizes cleanly (1.0): a run-time failure has already banked L2, and L3 is one correct run away.

## Diagnosis

Guessing at fixes with no instrument is how a run burns its rounds: every wrong guess recompiles and re-runs the whole pipeline with nothing learned. Build the instrument first — a self-contained differential testbench: a reference implementation written from the task statement, checked against the kernel on inputs that are fixed and reproducible.

The shape that works:

```cpp
#include "kernel.h"

// Reference: the same computation, written the naive way straight from the
// task statement -- scalar loops, no pragmas, no buffer reuse.
static void ref_fn(const double A[8][6], const double B[6][5], double Y[8][5]) {
    for (int i = 0; i < 8; i++)
        for (int j = 0; j < 5; j++) {
            double acc = 0.0;
            for (int k = 0; k < 6; k++) acc += A[i][k] * B[k][j];
            Y[i][j] = acc;
        }
}

int main() {
    // Fixed, reproducible inputs: no rand(), no clock, no file reads.
    static double A[8][6], B[6][5], want[8][5], got[8][5];
    for (int i = 0; i < 8; i++)
        for (int j = 0; j < 6; j++) A[i][j] = (i * 37 + j * 11) % 17 * 0.25 - 2.0;
    for (int i = 0; i < 6; i++)
        for (int j = 0; j < 5; j++) B[i][j] = (i * 13 + j * 7) % 19 * 0.25 - 2.0;

    ref_fn(A, B, want);
    kernel_fn(A, B, got);

    int bad = 0;
    for (int i = 0; i < 8; i++)
        for (int j = 0; j < 5; j++) {
            double tol = 1e-6 * (want[i][j] < 0 ? -want[i][j] : want[i][j]) + 1e-9;
            double diff = got[i][j] - want[i][j];
            if (diff < 0) diff = -diff;
            if (diff > tol) {
                if (bad < 3)
                    printf("mismatch [%d][%d] got %.9g want %.9g\n", i, j, got[i][j], want[i][j]);
                bad++;
            }
        }
    printf("mismatches: %d\n", bad);
    return bad ? 1 : 0;
}
```

Why this works: the reference is written from the task statement, not from the kernel, so agreement between two independently written versions is evidence; a shared misunderstanding is possible but much less likely than a shared typo. The comparison is tolerant — 1e-6 relative plus 1e-9 absolute — because the two sides accumulate in a different order and exact equality would fail a correct kernel. The mismatch report names the first failing elements, which turns "values are wrong" into a location.

Reading the first mismatch is the whole point of the instrument:

| What the output looks like | Most likely cause |
|---|---|
| a whole row or column is wrong | an off-by-one loop bound, or two dimensions swapped |
| only the last iteration is wrong | the accumulator was not reset per iteration, or a boundary case is skipped |
| values are close but never equal | accumulation order or precision — inspect the tolerance before the kernel |
| nan or inf appear | an uninitialised array read, or a division by zero on an edge element |
| everything is wrong, including element [0][0] | the kernel was never called, or its output is transposed |
| no output at all, the run crashed | a large local array overflowed the stack — make it static |

Honesty rules that keep a failure reproducible: never `fopen` anything (the testbench is not visible during a run anyway); use fixed arithmetic seeds instead of `rand()`; print at most the first three mismatches plus the total; report failure through the exit code; and keep two separate copies of any array the kernel updates in place.

When the self-check passes, the run is genuinely at L3: the kernel was exercised on inputs the agent chose and produced the reference answer within tolerance. That is the largest single step on the ladder, 0.2 to 0.8.

## Procedure

1. Before touching the kernel, write a small self-contained testbench: a reference implementation from the task statement plus a main that compares the two.
2. Use fixed, reproducible inputs — arithmetic on the indices; no `rand()`, no clock, no file reads.
3. Compare with a tolerance, not equality: 1e-6 relative plus 1e-9 absolute covers accumulation-order differences.
4. Run it, read the first mismatch, and fix the kernel at the location the mismatch names.
5. Re-run the same testbench after every fix, and keep it until the run is green.
6. Report failure through the exit code, and print at most the first three mismatches plus the total.

## Behavioral Constraints

- Never `fopen` the official testbench or any golden data: the testbench is not visible during a run, and reading files it provides is reading the answer.
- Keep two separate copies of any array the kernel updates in place — one for the reference, one for the kernel; sharing one buffer makes the comparison meaningless.
- Put large arrays in `static` storage, not on the stack: a big local array overflows the stack and the run dies before printing anything.
- Fix the kernel, not the testbench — unless the mismatch is a genuine bug in the reference, in which case say so in the run log.
- A testbench that cannot fail is worse than none: calling the kernel and returning 0, comparing values guessed and pasted in from the kernel's own output, or checking only element [0][0] each turn an unknown into a false pass.

## Applicability

**Applies when:** The kernel builds and links with the testbench but the run fails: a non-zero exit status, values outside tolerance, nan/inf, or a crash before any output.

**Does not apply when:**

- csim.exe was never produced: that is a build/interface failure, not a run-time one.
- The agent's own testbench fails to compile: fix the testbench's call site first.
- The failure is environmental (a missing tool, a judging timeout).

## Refuted approaches

- None recorded.

## Common mistakes

- Calling the kernel and returning 0 — a testbench that cannot fail proves nothing.
- Comparing against values guessed and pasted in, rather than computed by a reference.
- Checking only element [0][0]: the first element of an in-place kernel often stays correct even when everything else is wrong.
- Using `rand()` without a seed, so a failure cannot be reproduced on the next run.

## Provenance

Every claim above is tied to recorded failure samples: verbatim quotes with raw byte
ranges and whole-file SHA-256 values are in `EVIDENCE.md`, next to this file.
Generated from `kb/hls/kb.jsonl` by `python -m tools.kb_render` — edit the JSONL,
never this file.

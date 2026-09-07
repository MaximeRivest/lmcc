# Plan 06 — structured fix hints on refusals  ✅ done (D-25)

**Motivation.** Every refusal names its offender in prose. An agent
repairing a program benefits from a machine-readable next action —
"install pack X", "bind a format for field Y", "declare fact Z" — it can
act on without parsing English.

**What landed.**
- `Refusal(code, hint, fix, partial)` in Python, `Error{Code, Detail,
  Fix, Partial}` in Go; `describe()` on both. `refuse(code, hint,
  fix=...)` / `refuseFix(code, fix, detail)` — additive, no breaking
  change to codes.
- A closed action vocabulary in `spec/errors.md` (eleven actions, fixed
  parameter sets, locator grammar) mirrored one-to-one by
  `schema/fix.schema.json`; the `fix` column of the code table says
  which action(s) each code carries, or `—`.
- **The rule.** Every refusal that fires before render (construct,
  signature, load, bind) carries a fix; render, parse, and registration
  refusals carry none. `no-format`, which can fire either side, carries
  one on both. One fix per refusal — the primary repair; the hint prose
  may list alternatives.
- The corpus pins fixes: every pre-render refuse case (18 existing, 6
  new: 74–79) carries `expect.fix`; the harness compares it exactly in
  both drivers. Both kernels emit identical payloads for all of them.

**Acceptance criteria.**
- [x] `spec/errors.md` gains a fix-action vocabulary section (closed list).
- [x] Every bake-time refusal in the kernel carries a `fix` — enforced at
      every call site of both kernels by `tests/test_coherence.py`
      (Python by AST, Go by the `refuseFix` naming rule), and the
      documented action set equals the emitted set in both.
- [x] `tests/test_coherence.py` asserts fix actions ⊆ the documented list
      (and the schema's branch set == the documented list).
- [x] At least two corpus refuse-cases assert the fix payload — all 24
      pre-render refuse cases do, and every documented action is pinned
      by at least one.
- [x] `tests/test_fix_hints.py` drives the Python-only surfaces
      (`@lmcc.fn`, `ship`, `udf-unplaceable`, `format-direction`) and
      validates every fix against `fix.schema.json`.

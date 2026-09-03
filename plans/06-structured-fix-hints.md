# Plan 06 — structured fix hints on refusals

**Motivation.** Every refusal names its offender in prose. An agent
repairing a program benefits from a machine-readable next action —
"install pack X", "bind a codec for field Y", "declare fact Z" — it can
act on without parsing English.

**Design sketch.**
- `LMCCError` gains an optional `fix: dict | None`, e.g.
  `{"action": "bind-codec", "field": "rows"}` or
  `{"action": "declare-capability", "fact": "native_structured_output"}`.
- A closed action vocabulary (spec'd like everything else); prose
  messages stay for humans and do not change.
- `refuse(code, detail, fix=...)` — additive, no breaking change.

**Acceptance criteria.**
- `spec/errors.md` gains a fix-action vocabulary section (closed list).
- Every bake-time refusal in the kernel carries a `fix`.
- `tests/test_coherence.py` asserts fix actions ⊆ the documented list.
- At least two corpus refuse-cases assert the fix payload.

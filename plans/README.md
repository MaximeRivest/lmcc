# Plans — the work queue

Each plan is executable by one agent session: motivation, design sketch,
and **acceptance criteria** (the corpus cases and tests that must exist
for "done"). A plan without acceptance criteria is a wish.

Protocol per plan: spec → corpus (hand-authored bytes) → code →
`./check` green → decision-log entry if a rule changed.

Python is the one implementation while the language is designed (D-41).
Plans that mention the Go kernel describe work done at kernel ≤ 0.6; that
code is at the git tag `kernel-0.6`.

| plan | one line | size |
|---|---|---|
| `01-streaming.md` | ✅ sans-I/O reducer; every parse case replayed at every scalar/part split through both kernels | M |
| `02-parse-combinators.md` | declared recovery pipelines for messy replies (level 1) · kernel 0.8 (D-42) did the obvious part in the kernel: marker repair, the repair report, truncation; what stays open is declared recovery beyond markers | M |
| `03-turns-face.md` | ✅ `turns` face on strategies + the bind-time probe (`turns-drift`); native turns pass verbatim as lm15 messages | M |
| `04-tools-citations-strategies.md` | ✅ `native_tools`/`fenced_tools`, `native_citations`/`inline_citations`, five formats; roles live; proven live on two providers | M |
| `05-second-implementation.md` | ✅ Go kernel; harness passes byte-exact (84/90 claimed; 6 `udf:python` cases declared unclaimed) | L |
| `06-structured-fix-hints.md` | ✅ every pre-render refusal carries a `fix` from a closed action vocabulary; corpus-pinned in both kernels | S |
| `07-dspy-parity.md` | ✅ any DSPy signature lowers, renders, parses; 16-row catalog vs real DSPy | L |
| `08-v3-alignment.md` | ✅ the contract is the v3 design: formats by type, strategies by role, parts/spans, UDFs, `@lmcc.fn`, plan faces | XL |
| `09-audit-triage.md` | classify 114 audit findings; ratify policy gates, then pin defects and missing contract rules | XL |
| `10-declared-extensions.md` | ✅ phase 1 (kernel 0.3): declared extensions, host bindings, scoped claims, `pattern/legacy-re2` default tier declared by the constructor · phase 2 demand-driven: exact tiers by binding an engine, never authoring one | L |
| `11-heredoc-turns.md` | ✅ kernel 0.6: formatted arguments and explicit turns samples; raw-code heredoc writer/reader, portable tests and runnable notebook | M |
| `12-turns.md` | ✅ kernel 0.7 (Python): one `Turn` record replaces `demos` and `history`; named slots as messages or text, guards, writers for hidden fields, recorded or value replay, unique ids · open: Go port, live-provider checks, dspy_session on turns | L |
| `13-helpers.md` | ✅ `lmcc.find` / `put` / `when` / `choose` helpers that return today's plain data, for autocompletion | S |

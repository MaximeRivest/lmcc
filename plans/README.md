# Plans — the work queue

Each plan is executable by one agent session: motivation, design sketch,
and **acceptance criteria** (the corpus cases and tests that must exist
for "done"). A plan without acceptance criteria is a wish.

Protocol per plan: spec → corpus (hand-authored bytes) → code →
`./check` green → decision-log entry if a rule changed.

| plan | one line | size |
|---|---|---|
| `01-streaming.md` | ✅ sans-I/O reducer; every parse case replayed at every scalar/part split through both kernels | M |
| `02-parse-combinators.md` | declared recovery pipelines for messy replies (level 1) | M |
| `03-turns-face.md` | ✅ `turns` face on strategies + the bind-time probe (`turns-drift`); native turns pass verbatim as lm15 messages | M |
| `04-tools-citations-strategies.md` | ✅ `native_tools`/`fenced_tools`, `native_citations`/`inline_citations`, five formats; roles live; proven live on two providers | M |
| `05-second-implementation.md` | ✅ Go kernel; harness passes byte-exact (84/90 claimed; 6 `udf:python` cases declared unclaimed) | L |
| `06-structured-fix-hints.md` | ✅ every pre-render refusal carries a `fix` from a closed action vocabulary; corpus-pinned in both kernels | S |
| `07-dspy-parity.md` | ✅ any DSPy signature lowers, renders, parses; 16-row catalog vs real DSPy | L |
| `08-v3-alignment.md` | ✅ the contract is the v3 design: formats by type, strategies by role, parts/spans, UDFs, `@lmcc.fn`, plan faces | XL |
| `09-audit-triage.md` | classify 114 audit findings; ratify policy gates, then pin defects and missing contract rules | XL |
| `10-declared-extensions.md` | ✅ phase 1 (kernel 0.3): declared extensions, host bindings, scoped claims, `pattern/legacy-re2` default tier declared by the constructor · phase 2 demand-driven: exact tiers by binding an engine, never authoring one | L |

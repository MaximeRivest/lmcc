# Plans — the work queue

Each plan is executable by one agent session: motivation, design sketch,
and **acceptance criteria** (the corpus cases and tests that must exist
for "done"). A plan without acceptance criteria is a wish.

Protocol per plan: spec → corpus (hand-authored bytes) → code →
`./check` green → decision-log entry if a rule changed.

| plan | one line | size |
|---|---|---|
| `01-streaming.md` | sans-I/O reducer; streaming = a refinement law over the corpus | M |
| `02-parse-combinators.md` | declared recovery pipelines for messy replies (level 1) | M |
| `03-turns-face.md` | tool calls/results spelled into the next prompt, probe-checked | M |
| `04-tools-citations-strategies.md` | strategy vocabularies for the reserved roles | M |
| `05-second-implementation.md` | ✅ Go kernel; harness passes byte-exact (46/46) | L |
| `06-structured-fix-hints.md` | refusals carry a machine-actionable `fix` payload | S |
| `07-dspy-parity.md` | ✅ any DSPy signature lowers, renders, parses; 16-row catalog vs real DSPy | L |
| `08-v3-alignment.md` | ✅ the contract is the v3 design: formats by type, strategies by role, parts/spans, UDFs, `@lmcc.fn`, plan faces | XL |

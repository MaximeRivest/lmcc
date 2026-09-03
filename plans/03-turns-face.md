# Plan 03 — the `turns` face (tool calls/results across exchanges)

**Motivation.** A tool exchange spans two calls: the model asks; we run
the tool; the next prompt must *show* the call and its result. Carrying
is orchestration (outside lmcc); **spelling is the adapter's** — it
varies by LM family, not by program. Today lmcc has no home for it.
(Proven once in dspy-greenfield; port the design, not the code.)

**Design sketch.**
- Strategy rules gain an optional face:
  `turns: { assistant: T, result: T }` where
  `T = {"kind": "native"} | {"kind": "template", "content": ...}`.
  Template content speaks a closed slot set: loops over `calls` /
  `results` with `{c.name}`, `{c.args}` (canonical JSON), `{c.id}`,
  `{r.name}`, `{r.value}`, `{r.id}`.
- `native` emits provider shapes: assistant turn with tool-use parts,
  `role: "tool"` result messages with call ids (structurally
  lm15-shaped dicts, no import).
- History rendering consults the active tools rule's face when a past
  turn carries tool calls; a rule without `turns` keeps today's generic
  path.
- **The probe (the lens law at strategy level):** at validation, render
  a synthetic call through `turns.assistant`, read it back through the
  rule's own tool-calls routing; `parse(render(call)) == call` or the
  rule is refused at the door, naming the drift. Native skips (the
  provider owns both directions).

**Acceptance criteria.**
- [ ] `spec/kernel.md` strategies section: the face, the closed slot
      set, the probe as normative.
- [ ] Corpus: one text-style rule (heredoc or XML) rendering a past
      call+result byte-exact; one native-style case; one refusal case
      for a deliberately drifted rule (probe fires).
- [ ] Entries with `turns` bump the strategy vocab version; roundtrip
      case pins it.
- [ ] `./check` green; decision-log entry (carrying vs spelling split).

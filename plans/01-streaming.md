# Plan 01 — streaming parse (sans-I/O)

**Motivation.** UIs and pipelines need values as they arrive. The lens
reads full replies only.

**The law (this is the whole design).** Streaming is a *refinement* of
batch parse, never a second parser:

> Feed the same bytes in any chunking — the final values equal
> `parse()` of the concatenated text, exactly. Per-field, the
> concatenation of emitted deltas equals the batch raw text.

**Design sketch.**
- Kernel: `state = baked.stream()`, `events = state.feed(chunk)`,
  `values = state.finish()`. Pure state machine; the client owns I/O
  (h11/h2 precedent). Chunks are text deltas or part deltas,
  structurally lm15-shaped.
- Events: `field_started(name)`, `field_delta(name, text)`,
  `field_done(name, typed_value)` (typed only at close; codecs need the
  whole value).
- Marker lenses stream via hold-back: emit only text that cannot begin
  an anchor; the longest anchor bounds the buffer.
- Routings: `between` / `line_prefixed` / `parts` stream; `pattern`
  (regex) buffers to `finish()` — stated in the spec, not hidden.
- Lens socket: streaming is optional per lens; a lens without a
  streaming form buffers to `finish()` and says so in `describe()`.

**Prerequisite.** None remaining (marker ambiguity already refuses:
`parse-ambiguous`).

**Acceptance criteria.**
- [ ] `spec/kernel.md` §streaming with the refinement law verbatim.
- [ ] Harness gains a streaming mode: every existing parse case is
      replayed at **every byte split**; final values must match batch.
      No new fixture files needed — the law is the fixture.
- [ ] Adversarial splits covered: mid-anchor, mid-`<think>` span,
      mid-tail.
- [ ] Unit tests: delta concatenation equals batch raw per field;
      `finish()` refusals identical to batch (`parse-missing-fields`,
      `parse-ambiguous`).
- [ ] `./check` green; decision-log entry for the pattern-routing
      buffering trade-off.

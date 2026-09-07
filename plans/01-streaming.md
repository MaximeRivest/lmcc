# Plan 01 — streaming parse (sans-I/O)  ✅ done (D-26)

**D-31 update:** regex execution is a declared optional extension in the next
version, not a mandatory engine in every kernel. Plan 10 gates the extension
contract, migration, and backend choice. Existing 0.2 evidence stays historical.

**Motivation.** UIs and pipelines need raw values as they arrive. The
lens previously read full replies only.

**The law (the whole design).** Streaming is a *refinement* of batch
parse, never a second parser:

> Feed the same response in any chunking — the final values equal
> `parse()` of the concatenated response, exactly. Per-field, the
> concatenation of emitted deltas equals the batch raw text.

**What landed.**
- Python: `state = plan.stream()`, `events = state.feed(delta)`,
  `result = state.finish()` (`result.events`, `result.values`). Go:
  `Plan.Stream`, `Feed`, `Finish`. Pure state machines; the client owns
  I/O and incremental network-byte decoding.
- Fixed-shape events: `field_started`, non-empty `field_delta`, and typed
  `field_done` (whose value is the same host type as batch parse). `finish` returns EOF events because EOF can close a
  field or release held whitespace. Typed done waits for full batch
  validation, so it is never speculative.
- Derived markers stream with hold-back for outer ASCII whitespace and
  partial anchors/closes/tails. `between` streams after close,
  `line_prefixed` after newline, and channel parts as adjacent deltas;
  consuming stages pass stable text to the next stage and lens.
- Regex-routed fields buffer; a consuming regex buffers the lens too;
  multiple routings into one field buffer because batch concatenates by
  routing declaration order. Every choice and reason appears in
  `plan.describe()["streaming"]`.
- Vocabulary lenses have an optional, exact stream face; lenses without
  it buffer visibly. Stream EOF invokes the shared batch parse path,
  which makes refusal code, fix, partial, validation order, and typed
  values identical by construction.

**Acceptance criteria.**
- [x] `spec/kernel.md` §8 contains the refinement law verbatim and pins
      delta inputs, event shapes, EOF, optional lens face, routing
      behavior, hold-back, buffering, and refusal timing.
- [x] The harness replays every existing parse case whole, one Unicode
      scalar at a time, at every scalar split, and at every text-bearing
      part split in both drivers. Final values and concatenated deltas
      are chunk-independent. No fixture files duplicate parse truth.
- [x] Adversarial splits are covered: mid-anchor, mid-close, held ASCII
      whitespace, channel-part deltas, consuming `<think>` spans,
      incomplete lines, unclosed fields, and EOF.
- [x] Unit tests prove delta concatenation equals batch raw per field;
      `finish()` refusals are the complete same refusal as batch
      (`code`, `hint`, `fix`, `partial`).
- [x] Pattern and multi-routing buffering is visible in `describe()`;
      optional custom-lens streaming is tested in both kernels.
- [x] `./check` green; D-26 records all trade-offs.
- [x] Linear cost (D-27): per-feed work is constant; marker overlap holds
      instead of crashing (corpus 80); both kernels carry a random
      multi-chunk fuzz and a scaling test; the harness pins event timing
      across kernels through the stream trace.

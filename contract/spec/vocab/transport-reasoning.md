# The reasoning transports — 0.1.0 (`reasoning_tags` 0.3.0)

Three ways to serve one `reasoning` purpose. Same signature, same program;
the choice is a function of the model, made at bake. All three are pure
data (predicate + tell + find rules) — printable with the entry.

## transport/prefix_cot

The classic. Requires `instruct`. The field stays **visible**: it renders
as a normal section the model writes before the others. `tell` (system):

> Reason step by step in the '{field}' section before writing any other
> section.

`{field}` binds to the purpose's field name at bind.

## transport/reasoning_tags

Interleaved thinking on any instruct model — no engine support needed.
Requires `instruct`. **Hidden** (`in_template: false`). Options: `open`
(default `<think>`), `close` (default `</think>`). `tell` (system):

> After every sentence of output, add your thinking inside
> {open}...{close} tags.

Find rule: `{from: text, between: [open, close], to: @purpose, remove: true,
repair: true}` — the tags are repaired like markers (kernel §4a: `<Think>`
reads as `<think>`, unless the adapter is `strict`); the captures are removed from the text the reader sees, so thinking never
pollutes other fields; the field's format reads `capture.text` (the
matches, stripped, joined by newlines). Spelling: `{position: before}` — in
an earlier turn written from values, the reasoning is written between its
own tags *before* the answer (kernel §3a). 0.2.0 adds that declaration.

## transport/native_reasoning

Models with a native thinking channel. Requires `native_reasoning`.
**Hidden.** No tell. The transport does everything its meaning
needs: it *asks* for thinking — request_settings `{config: {reasoning: {effort,
thinking_budget?}}}`, a partial lm15 request (kernel §3); options
`effort` (an lm15 `Reasoning.effort` word, default `medium`) and
`thinking_budget` (int) — and *reads* it back: find rule `{from:
part:thinking, to: @purpose}`.

**Corpus.** `10-refuse-bind-capability.json` (predicate refusal),
`15-std-reasoning-tags.json` (find + strip).

**0.3.0** — the find rule declares `repair: true` (kernel 0.8, D-43): a
misspelled tag is read and reported, not left in the answer.

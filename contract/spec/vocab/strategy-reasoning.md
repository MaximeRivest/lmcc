# The reasoning strategies — 0.1.0

Three ways to serve one `reasoning` role. Same signature, same program;
the choice is a function of the model, made at bake. All three are pure
data (predicate + fragments + routings) — printable with the entry.

## strategy/prefix_cot

The classic. Requires `instruct`. The field stays **visible**: it renders
as a normal section the model writes before the others. Fragment (system):

> Reason step by step in the '{field}' section before writing any other
> section.

`{field}` binds to the role's field name at bake.

## strategy/reasoning_tags

Interleaved thinking on any instruct model — no engine support needed.
Requires `instruct`. **Hidden** (`visible: false`). Options: `open`
(default `<think>`), `close` (default `</think>`). Fragment (system):

> After every sentence of output, add your thinking inside
> {open}...{close} tags.

Routing: `{from: text, between: [open, close], to: @role, consume: true}`
— the spans are removed from the text the lens sees, so thinking never
pollutes other fields; the field's format reads `span.text` (the
matches, stripped, joined by newlines).

## strategy/native_reasoning

Models with a native thinking channel. Requires `native_reasoning`.
**Hidden.** No fragments. The strategy does everything its meaning
needs: it *asks* for thinking — controls `{config: {reasoning: {effort,
thinking_budget?}}}`, a partial lm15 request (kernel §3); options
`effort` (an lm15 `Reasoning.effort` word, default `medium`) and
`thinking_budget` (int) — and *reads* it back: routing `{from:
channel:thinking, to: @role}`.

**Corpus.** `10-refuse-bind-capability.json` (predicate refusal),
`15-std-reasoning-tags.json` (route + strip).

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

Routing: `between {open, close}` → the role field, `join: "\n"`,
`strip: true` — spans are removed from the visible text before section
splitting, so thinking never pollutes other fields.

## strategy/native_reasoning

Models with a native thinking channel. Requires `native_reasoning`.
**Hidden.** No fragments, no token cost. Routing: `parts {part:
"thinking"}` → the role field, `join: "\n"`.

**Corpus.** `10-refuse-bake-capability.json` (predicate refusal),
`15-std-reasoning-tags.json` (route + strip).

# The purpose vocabulary — 0.1.0

A **purpose** names what a signature field is for in the exchange — what
the exchange does with it, never what the data is (that is the shape's
job) and never how it travels (that is the transport's job).

## The governing rule

Every output-carrying part kind in the wire layer (lm15) gets a purpose name
**aligned** with it, so the two vocabularies never fragment on naming. But
purposes are named for the *function*, owned by this vocabulary, and never
limited to what any wire protocol can carry today:

- A purpose is an intent; a part is one possible transport. Every purpose must
  be servable with **no native part at all** — by tell + find rules on
  a plain instruct model. Native parts are an optimization a transport
  may claim behind a capability predicate, never a requirement for the
  purpose to exist.
- The single place lmcc touches part names is a find rule reading parts
  of one type (`from: part:thinking`) — per transport, as data, only when
  the model's native part is actually used.

## Named purposes

| purpose | function | aligned lm15 part | shipped transports |
|---|---|---|---|
| `plain` | ordinary typed value (the default) | — (text) | — (kernel sections) |
| `reasoning` | the model's working-out; may leave the token stream | `thinking` | `prefix_cot`, `reasoning_tags`, `native_reasoning` |
| `tools` | **input**: what the model may call (`tools`); **output**: what it asked for (`tools.calls`) | `tool_call` | `native_tools`, `fenced_tools` (`transport-tools.md`) |
| `citations` | claims grounded in sources | `citation` | `native_citations`, `inline_citations` (`transport-citations.md`) |
| `citations.sources` | **input**: sources citations may point into (was reserved as `citable`; spelled as a sub-purpose like `tools.calls`) | — (input-side; `inline_citations` spells it; lm15 has no per-document citation flag yet, so no native pair) | `inline_citations` |

## Openness and growth

Purpose names are mechanically open: the kernel accepts any string, and an
unknown purpose with no transport bound renders as a plain visible field.
This is deliberate — purposes are a research surface, and inventing one must
cost nothing. The vocabulary exists for the *shared* names: publishing a
transport pack against a purpose name is a claim about this table. Promoting
a new purpose here is a versioned change (minor to add, breaking to change
meaning), same discipline as formats.

Reserved rows name the function now so the ecosystem does not fork on
naming before the transports land.

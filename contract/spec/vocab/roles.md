# The role vocabulary — 0.1.0

A **role** names the conversational function of a signature field — what
the exchange does with it, never what the data is (that is the shape's
job) and never how it travels (that is the strategy's job).

## The governing rule

Every output-carrying part kind in the wire layer (lm15) gets a role name
**aligned** with it, so the two vocabularies never fragment on naming. But
roles are named for the *function*, owned by this vocabulary, and never
limited to what any wire protocol can carry today:

- A role is an intent; a part is one possible transport. Every role must
  be servable with **no native part at all** — by fragments + routings on
  a plain instruct model. Native channels are an optimization a strategy
  may claim behind a capability predicate, never a requirement for the
  role to exist.
- The single place a15 touches part names is the `parts` extractor inside
  a strategy routing (`extract: {kind: "parts", part: "thinking"}`) —
  per strategy, as data, only when a native transport is actually used.

## Named roles

| role | function | aligned lm15 part | shipped strategies |
|---|---|---|---|
| `plain` | ordinary typed value (the default) | — (text) | — (kernel sections) |
| `reasoning` | the model's working-out; may leave the token stream | `thinking` | `prefix_cot`, `reasoning_tags`, `native_reasoning` |
| `tools` | tool invocation and its call format | `tool_call` | *(reserved — no strategies shipped)* |
| `citations` | claims grounded in supplied sources | `citation` | *(reserved — no strategies shipped)* |
| `citable` | **input**: a source that citations may point into | — (input-side; pairs with `citations`) | *(reserved)* |

## Openness and growth

Role names are mechanically open: the kernel accepts any string, and an
unknown role with no strategy bound renders as a plain visible field.
This is deliberate — roles are a research surface, and inventing one must
cost nothing. The vocabulary exists for the *shared* names: publishing a
strategy pack against a role name is a claim about this table. Promoting
a new role here is a versioned change (minor to add, breaking to change
meaning), same discipline as codecs.

Reserved rows name the function now so the ecosystem does not fork on
naming before the strategies land.

# The LMCC kernel — normative specification

**Version 0.8.1** (kernel). Status: the v3 design (`plans/08`). One
implementation, `python/lmcc`, passes the corpus; it is the reference while
the language is being designed. Other languages are rebuilt from this
document and the corpus, and join through the driver protocol (§9); the
Go kernel that passed kernel 0.6 is kept at the git tag `kernel-0.6`
(D-41). Where this document and the corpus disagree, fix the corpus first,
then the implementation.

**What 0.8.1 adds (D-46, D-47).** The prefill (§3): a template's last
assistant message is the start of the reply, sent under `assistant_prefill`
and read as its beginning. Parts inside the pattern (§4b): a non-text part
goes to the field whose section it sits in, and past turns write it back in
place. Additions only: 0.8.0 artifacts load unchanged (patch versions are
compatible, §9).

**What 0.8 changes (D-42).** The derived reader repairs a misspelled
marker — `<Answer>` for `<answer>`, `**Answer:**` for `Answer:`,
`[[## answer ##]]` for `[[ ## answer ## ]]` — by one exact rule, and
reports every repair (§4a); so do the delimiters of a find rule that
declares `repair: true` (`<Think>` for `<think>`), and the kernel's
default reads forgive a value slip (`42.`, `"positive"`, `Positive`,
`None`, §7a). An adapter turns every repair off with `strict: true`.
The exact spelling always
wins, so no reply that 0.7 read changes values, with one stated exception
(decoration around an exact marker, §4a). A reply the provider cut at
its length limit (`finish_reason: "length"`) is no longer read as a
finished answer: an output that may have been cut refuses
`parse-truncated`. `plan.read(reply)` returns the values and the repairs;
`parse` is its values. A recorded reply that needed a marker repair is
written back from its values, so a conversation never teaches the model
its own slip (§3a). Every 0.7 artifact refuses `version-incompatible`;
migrating one is changing its kernel pin.

**What 0.7 changes (D-39).** One record, the **turn**, replaces demos
and history. A turn is one call of one signature: the inputs, the steps
(model replies and tool results, in order) and the outputs, kept as
values. Examples, past exchanges and the exchange in progress are all
turns, written into the prompt by the plan's own writers (§3a), so past
replies always match the current adapter's spelling. The template places
turns in named **slots**, as messages or as text (§2); the `demos` and
`history` directives, `render(demos=, history=)` and lm15-message
history items are gone. Every hidden field a transport finds gets a writer, and a
tool's non-text result parts are no longer dropped on text transports.
Every 0.6 artifact refuses `version-incompatible`; migrating one is
replacing its `demos`/`history` directives with one `turns` directive.
0.7 also renames the vocabulary so each word means one thing (D-40,
`docs/glossary.md`): strategy → transport, a field's role → purpose,
lens → reader, span → capture, routings → `find`, placement → `put`.

**What 0.4 changes (D-35).** The wire layer *is* the lm15 contract
(`../LM15_CONTRACT_PIN` names the ratified commit): parts carry `type`,
messages carry `parts`, `system` is a request field, and what `render`
produces is an lm15 request minus its model — feedable to any lm15
implementation without translation. The request settings are a partial
lm15 request (`config.<field>`, `tools`), deep-merged and validated
against the pinned field names. No case expectation changed meaning; the
bytes were re-spelled in lm15's words.

**What 0.3 changes (D-33).** The kernel is a small mandatory core; any
behavior outside it is a named, versioned **extension** the artifact
declares and the host binds or refuses (§10, `portability.md`). The one
extension so far is the find rule `pattern` dialect: a 0.3 artifact that
uses `pattern` must declare `extensions: {"pattern/<name>": version}`.
A 0.2 artifact refuses `version-incompatible` as before; migrating it is
two edits, spelled out in §10. No case expectation changed meaning.

**One sentence.** When a program calls a function in another language, a
calling convention says where each argument goes, how the result comes
back, and how each type crosses. A model is another language; LMCC is its
calling convention.

```
signature (your typed function)
        │  write: each value → its place on the wire
        ▼
   the wire: messages, parts, request settings        ← the adapter lays this out
        │  read: the reply → each typed value
        ▼
your typed return value
```

LMCC never touches the network. It lays out the call and reads the
return. The nouns: **signature, adapter, template, reader, format, part,
capture, purpose, transport, capability, turn**; the verb: **bind**. The kernel ships
no formats and no transports beyond the defaults §5 names.

**The wire is lm15.** Every message, part, request field and response
lmcc reads or writes is the lm15 canonical JSON of the contract commit
in `../LM15_CONTRACT_PIN` — the same bytes lm15's own serde produces in
every language it exists in. lmcc adds nothing to that vocabulary and
never renames a field; its own objects (signatures, artifacts, plans,
refusals, stream *events*) are lmcc's and are the only things spelled in
lmcc's words.

---

## 1. Signature

```
Signature = { instructions: str, fields: [Field] }
Field = { name, direction: "input"|"output", shape: JSONSchema,
          type?: str, purpose?: str = "plain", desc?: str }
```

Plain-data form: `schema/signature.schema.json`. Field names are ASCII
identifiers, unique; `signature-malformed` names the offender. `shape`
is JSON Schema; the kernel reads only these keywords and carries every
other one untouched for formats to use:

| shape | kernel meaning |
|---|---|
| `{"type": "string" \| "integer" \| "number" \| "boolean"}` | kernel scalar (§5 defaults) |
| `{"enum": [...]}` | membership; strings or integers |
| nullable forms `{"type": [T, "null"]}`, `{"anyOf": [S, {"type": "null"}]}` | the scalar/enum plus `null` |
| `{"media": type}` | an lm15 part of that `type` (`image`, `document`, `function`, …; §5 defaults) |
| `{"type": "array", "items"?}` · `{"type": "object", ...}` · anything else | **structured**: needs a format, no default |

`type` is the type's name **as the frontend spells it** (`Person`,
`pd.DataFrame`, `list[Person]`). Formats resolve by it first (§5); it is
the one place the artifact touches a host language, and it does so by
name only. `purpose` is what the field is for in the exchange
(`spec/vocab/purposes.md`); purposes are namespaced strings (`tools`,
`tools.calls`), each bound to at most one field.

**Frontends.** `@lmcc.fn` (Python: parameters → inputs, return type →
outputs, dataclass return for several, docstring → instructions,
`Purpose["reasoning", T]` for purposes), `lmcc_dspy`, JSON, or a host language's own syntax —
every syntax lowers to this form; none is the contract. A type a
frontend cannot lower refuses `unmapped-type`, naming the field.

## 2. Adapter and template

An adapter is a template, a reader, transports by **purpose**, and
formats by **type** — never a field name. That is what lets one adapter
serve every signature. The template is a message list of `{role, text}`
(roles `system`, `developer`, `user`, `assistant`; `system` messages
lead) and turn directives `{"directive": "turns", "slot"?: name}`
(§3a), with four constructs:

| construct | example | meaning |
|---|---|---|
| slot | `{instruction}`, `{format}`, `{question}`, `{answer}`, `{f.name}`, `{f.value}` | a value goes here |
| loop | `{% for f in inputs %} … {% endfor %}` (also `outputs`); `{% for m in examples %} … {% endfor %}` over a turn slot | once per visible field, signature order; or once per message of the slot's turns (§3a) |
| guard | `{% if examples %} … {% endif %}` | the body renders only when the turn slot is not empty (§3a) |
| escape | `{{`, `}}` | a literal brace; a bare brace is `template-syntax` |

Loop attributes: `name`, `desc` ("" when absent), `type` ("" when
absent), `schema` (the format's `describe`, else the mechanical hint),
`purpose`, `value`. `instruction` and `format` are reserved. An input slot
renders the value through its format; an **output slot** (`{answer}` or
`{f.value}` in an outputs loop) renders the field's **placeholder**:
`desc`, else the format's `describe`, else the mechanical hint, else
`...` — the shape is shown, never merely described. In a past turn's
user side (§3a) an inputs loop iterates only the fields the turn
supplies; a bare slot with no value refuses `missing-input`.

A loop over any source other than `inputs` and `outputs` is a turn loop;
guards and turn loops are §3a's. The adapter may carry `replay`:
`"recorded"` (the default, never written by `dump`) or `"values"` (§3a).

Every input must be reachable from a slot or an inputs loop
(`field-uncovered`).

## 3. Bind, render, parse

```
bind(adapter, signature, capabilities, registry) → plan   every refusal fires here
plan.render(inputs | turn, turns?) → rendered            pure (§3a)
rendered.request(model?) → lm15 request                    {system?, messages, config?, tools?}
rendered.step(reply) → turn                                pure: parse + record (§3a)
plan.read(response) → {values: {field: value}, repairs: [repair]}   pure (§4a)
plan.parse(response) → {field: value}                      plan.read(response).values
plan.stream() → stream                                     pure, sans-I/O
stream.feed(delta) → [event, …]
stream.finish(finish_reason?) → {events, values, repairs}
plan.describe() · plan.explain() · plan.skeleton() · plan.prefix()
```

A refusal is `Refusal(code, hint, fix, partial)`: `code` is stable
(`errors.md`), `hint` names the offender for a human, `fix` is the one
next action as data from the closed action vocabulary of `errors.md` —
present on every refusal that fires before render (signature, load,
bind), absent on render and parse refusals — and `partial` is what a
parse recovered. The corpus pins codes and fixes; every implementation emits the
same fix for the same refusal.

**Render output** is an lm15 request minus its model:
`{"system"?: text | [part], "messages": [{"role", "parts"}], "config"?,
"tools"?}`. The template's `system` messages (which must lead the
template, contiguous — `entry-malformed` otherwise) fold into `system`:
one text part becomes the string, anything else the part list. Template
message roles are `system`, `developer`, `user`, `assistant`; messages
render as `{"role", "parts": [part, …]}`, adjacent text parts merge,
empty messages drop. Everything after `messages` is the **request settings**: the
deep merge of every transport's `request_settings` and the reader's own, a
partial lm15 request whose first path segment is `config` or `tools` and
whose `config` keys are the pinned lm15 `Config` fields (`max_tokens`,
`temperature`, `top_p`, `top_k`, `stop`, `response_format`,
`tool_choice`, `reasoning`, `cache`, `service_tier`, `user_id`, `store`,
`extensions`); anything else refuses `entry-malformed` at the control's
path. Below those two levels the value is opaque, as in lm15. Two
sources disagreeing on one leaf is `setting-conflict`; agreeing is fine.
The plan adds one control of its own: when the model declares
`stop_sequences` and the reader's skeleton has `stops`, `config.stop` is
those stops — where the reply ends is the layout's knowledge, not the
caller's chore. A provider omits the stop sequence from the reply; the
reader reads a capture to its close *or end of text*, so nothing changes
in parsing.

**The prefill.** When the template's last message is an `assistant`
message, it is the **prefill**: the beginning of the reply, written for
the model. It holds literal text only (`template-syntax` otherwise, at
construct). Its trailing whitespace (§7a) is never sent: providers reject
it (Anthropic answered HTTP 400 in the first live run) and it splits the
model's next token; an empty prefill is not sent at all. It is sent only
when the model declares `assistant_prefill`:
then it is the request's last message, after the current turn's steps,
and every read of this plan's reply (`parse`, `read`, `stream`, truncation)
reads the prefill as sent followed by the reply, as one text, before the find
rules. Without the fact it is not sent, the reply is read alone, and
nothing else changes, so one adapter serves both kinds of model; like
`config.stop` under `stop_sequences`, the layout offers it and the model's
declared facts decide. `rendered.step(reply)` records the whole assistant
message (prefill, then the reply), so a replayed turn shows what the model
effectively wrote; a recorded message is read whole, never re-prefixed.
`describe()["prefill"]` is `{"text", "sent"}` (D-46; cases 179–182).

**Parse input** is a string (the reply text), an lm15 message
(`{"role", "parts"}`; the role is not read), or an lm15 response
(`{"message": {…}, "finish_reason"?, …}`; only `message` and
`finish_reason` are read — the latter for truncation, §4a). Past exchanges and
examples enter a request only as turns (§3a).

`skeleton()` is what the derived reader knows the reply must contain:
`{"prefill": text before the first output hole, "stops": [the last
close or tail]}` (a `grammar` face is a stated gap). `prefix()` is the
rendered request prefix that does not depend on inputs
(`{"system"?, "messages"}`: everything before the first message that
renders an input, turn slots included; `prefix(turns?)` takes the same
slot values as `render`) — the cache-stable bytes. A message an input is
`put` into (§6) renders an input too. When the system text depends on
inputs, nothing is stable: the prefix is `{"messages": []}` (cases 170,
171; plan 09 F19).

## 3a. Turns: examples, past exchanges, and the one in progress

**The record.** A turn is one call of one signature:

```
Turn = { signature: "sha256:<hex>", inputs: {field: value}, steps: [Step],
         outputs?: {field: value} | null, score?: number | null, meta?: {} }
Step = { kind: "model", outputs: {field: value}, message?: lm15 message,
         request?: "sha256:<hex>", calls_field?: name }
     | { kind: "tool", id: text, name: text, output: [lm15 part], children?: [Turn] }
```

Form: `schema/turn.schema.json`. Values are JSON in their field's shape;
a host lifts them to its own types against a signature. `score`, `meta`,
`request` and `children` are carried and never read by render. A turn
with no steps and outputs is an **example**; a finished turn's outputs
are its last model step's.

- `signature` is `"sha256:"` and the lowercase hex SHA-256 of the
  canonical JSON of the signature's fields in signature order, each
  `{"direction", "name", "purpose", "shape", "type"}` (`purpose` `"plain"` and
  `type` `""` when absent). Instructions and descriptions are left out:
  editing or optimizing prose does not orphan recorded turns.
- `request` is `"sha256:"` and the hex SHA-256 of the canonical JSON of
  the rendered request without `model`: it names the exact bytes the
  reply answered without storing them, so a stored conversation grows
  with its replies, not with the square of its length.
- **Canonical JSON**: object keys sorted by code point, separators `,`
  and `:` with no whitespace, non-ASCII written as UTF-8, integers
  without a fraction.

**A turn in progress.**

```
plan.turn(inputs) → turn                        no steps
plan.example(inputs, outputs) → turn            no steps; outputs set
plan.render(turn, turns?) → rendered            render(inputs) = render(plan.turn(inputs))
rendered.step(reply) → turn + model step        outputs = parse(reply); message, request, calls_field
turn.tool(id, output, children?) → turn + tool step
turn.finish() → turn                            outputs = the last model step's outputs
```

A model step's **pending calls** are its `calls_field` value (the field
with purpose `<p>.calls`), minus the tool steps after it, in call order.
`tool(id, …)` answers the first pending call of the last model step, or
refuses `turn-invalid`; `output` is a text or an lm15 part list.
`finish` with pending calls or no model step, a render of a current
turn with pending calls, and a field name the signature does not have
all refuse `turn-invalid`. Refusals on turns carry no `fix`: their cause
is a program value.

**Slots.** The template places turns in named slots, once each:

- **messages form**: `{"directive": "turns", "slot"?: name}` (default
  `turns`) — the slot's turns become ordinary messages at that place;
- **text form**: a loop `{% for m in name %} … {% endfor %}` in any
  message — once per message the messages form would write, with
  `{m.role}` (`user`, `assistant` or `tool`, after spelling), `{m.kind}`
  (`input`, `model` or `tool`: where the message came from) and
  `{m.text}` (its text parts, concatenated). A message holding a part
  that is not text refuses `turn-not-renderable`, naming the slot and
  the part type; nothing is dropped silently. A turn loop's body holds
  text and `m.` attributes only;
- **guard**: `{% if name %} … {% endif %}` renders its body when the slot
  has at least one turn (for `steps`, one step). It does not place the
  slot; it names a slot the template places. A guard may instead name an
  **input** field: its body renders when that input has a value that is
  not null, `""` or `[]`. So `{% if context %}Context: {context}{% endif %}`
  lets a past turn be written without its bulky input, where a bare
  `{context}` would refuse `missing-input` (case 177). An output pattern
  inside any guard is `not-readable`, as before.

Slot names are ASCII identifiers other than `inputs`, `outputs`,
`instruction` and `format`; placing a slot twice or any other attribute
in a turn loop is `template-syntax`. A guard naming neither a placed
slot nor an input field refuses `unknown-slot` at bind (the signature is
known only then).
A slot named like a signature field refuses `turns-layout` at bind.

`steps` is reserved: the current turn's own steps. A template that
places any slot is a **turns template**; in it, an unplaced `steps`
writes its messages after the last template message. Messages-form slots
other than `steps` precede the first non-`system` message that renders
an input (a slot of an input, or an inputs loop), and a messages-form
`steps` follows it, else `turns-layout` at bind (fix `edit-template`);
`system` messages always lead and fold into the request's `system`. A template that places no slot writes no turns: a
current turn with steps, or a slot value, refuses `turns-unplaced` at
render.

`render(turn, turns)`: `turns` maps slot names to lists of turns (a
list alone fills the slot `turns`); an absent slot is empty. A
non-empty list for a slot the template does not place, or for `steps`,
refuses `turns-unplaced`. Every turn's `signature` must be the plan's
(`turn-invalid`).

**Writing a turn.** A past turn writes, in order: its **user side** —
each template `user` message rendered over the turn's inputs (turn loops
and guards render empty there; an empty message is dropped) — then, with
no steps, one assistant message written from its outputs, or, with
steps, one message per step in order; its outputs are not written again.
The current turn writes only its steps: its inputs are the live
template. Children of tool steps are never written.

Within a turn, each model step's calls are answered by the tool steps
that follow it, in call order, before the next model step; a past turn
with an unanswered call, or a tool step answering no pending call,
refuses `turn-invalid` naming the turn and the step.

**A model step's message.** With `replay: "recorded"` (the default), a
step with a recorded `message` that this plan reads into exactly the
step's outputs (JSON equality), with no `marker`, `unclosed` or `value` repair
(§4a), is written verbatim: the plan reads it as it was, so it is a
valid spelling of those values, and nothing the model wrote is lost. A
reply that needed such a repair is a misspelling; replayed verbatim it
would teach the model its own slip. Otherwise — and always with `replay: "values"` —
the message is written from the outputs:

1. for each `part:<type>` find rule that does not read the calls
   field's own channel, the recorded message's parts of that type,
   first, in recorded order; a step without a recorded message has none,
   and `describe()` lists the field under `replayed` (such values cannot
   be forged from text);
2. then one text part: the `before` writers (signature order), the reader
   body (the reader writing the visible outputs present), the `after`
   writers (signature order), joined by `\n`, empty pieces skipped;
3. then the calls: the calls field's value written through its format,
   which must yield `tool_call` parts (else `turn-not-renderable`); with
   a `spelling.call` on the owning transport each becomes text through it,
   appended to the text after `\n` when the text is not empty; without
   one they stay `tool_call` parts.

The reader writes every visible output the step holds, `null` included
(a nullable field's `null` is information). A hidden output that is
absent, `null`, an empty string or an empty list is not written: no
`<think></think>` for a turn without reasoning.

**Writers for hidden fields.** Each hidden output that a `from: text`
find rule targets needs a writer. Find rules with the same `from` and the
same delimiters (`between` pair, `line_prefixed` prefix, `pattern`) read
the same capture, as do two find rules from one `part:<type>`. In a capture
shared with the calls field, only the calls field writes; the others are
**projections**, recovered by reading it (reasoning spelled as comments
inside a call, native or text). A text find rule with
`remove: false` that shares its capture with nothing reads text it leaves
for the reader: its field is a projection of the body (inline citation
markers). For the rest:

| find rule | writer |
|---|---|
| `between: [open, close]` | derived: `open + T + close` |
| `line_prefixed: p` | derived: each line of `T` prefixed by `p`, joined by `\n` |
| `pattern` | declared: `spelling.value` on the owning transport |
| the calls field, from text | `spelling.call` (§6) |

`T` is the value written through the field's format: text parts only,
from a format that writes (`direction` `both` or `in`) with
`round_trip: true` — else bind refuses `spelling-drift` naming the field
(fix: give the format a write, or declare `spelling.value: null`); a `T`
containing `close` refuses `value-collides`. `spelling.value` (text with
one `{value}` slot, `{{`/`}}` escapes) overrides a derived writer;
`spelling.value: null` drops the field from written turns on purpose.
`spelling.position` (`"before"` or `"after"`, default `"after"`) says which
side of the reader body the writer's piece goes. In a turns template, bind
refuses `spelling-drift` naming the field when a hidden output found in text
has no writer, a derived writer's format cannot write text, the calls
format cannot write, or two fields share a capture the calls field does
not own.

**A tool step's message** is `{"role": "tool", "parts": [{"type":
"tool_result", "id", "name", "content": output}]}`. With `spelling.result`
on the transport owning the calls field, it becomes a `user` message: the
`spelling.result` text (`{output}` is the output's text parts joined by
`\n`), then the output's other parts (an image a tool returned), in
order.

**Call ids.** A call's id is the provider's when the step's recorded
message holds `tool_call` parts, and assigned by the calls format
otherwise (`call_1`, … per reply). A step written from values as native
`tool_call` parts writes an assigned id as `s<k>_<id>`, where `k` is the
0-based index of that step among the model steps written as messages in
this request, in request order, and its tool steps answer with the same
id; ids stay unique in the request. Provider ids and text spellings are
never changed.

`describe()["turns"]` is the whole plan of it: `slots` (`name`, `form`),
`steps` (`"placed"`, `"after the template"`, or `null`), `replay`,
`writers` (per hidden output a transport finds: how it is written and where),
`projections`, `replayed`, and `input_formats` (§6).

## 4. The template is the reader

`reader: {"kind": "derived"}` (the kernel reader). The **output pattern** is
the set of output holes in the template — `{f.value}` in one outputs
loop, or bare output slots — and it must live in one message. Read
backwards:

- a template whose **only** visible output is a bare slot with no
  literal before it **and nothing but whitespace after it in its
  message** is the *whole-reply* pattern: the capture is the whole reply
  (a chat-style adapter: `{instruction}\n{answer}`). Any other anchorless
  hole — two or more outputs, a loop, or prose after the slot such as
  `<answer>\n{answer}\n</answer>` — refuses `not-readable` as always;
  a refusal is never quietly reinterpreted;
- per visible output field, the literal before its hole (loop body
  instantiated with the field's `name`/`desc`/`type`/`schema`/`purpose`)
  is its **anchor**; the literal after it, up to the next hole, its
  **close**; the literal after an outputs loop, up to the next slot and
  to the end of its line, is the pattern's **tail** — the marker that
  ends the reply, never the prose that may follow it. For bare output slots the lines holding the
  holes are the pattern: an anchor starts at the later of its line's
  start or the previous hole, a close ends at the earlier of the next
  hole or the line's end;
- anchors are matched by their whitespace-stripped forms, first
  occurrence, any order; a capture runs to the field's close, the next
  anchor, the tail, or end of text, and is stripped (§7a). Boundaries are
  positions, so when the next anchor begins inside this field's anchor
  (`**Reasoning:**Answer:**` reads the answer marker from the reasoning
  marker's last two bytes) the capture is empty, never negative and
  never a guess;
- past turns and the `{format}` skeleton are written through the same
  pattern: `join` (values) and `format` (placeholders) are the reader
  writing forward.

Refusals: no pattern or two (`not-readable`); a hole with no literal
before it, two holes sharing an anchor, nested loops in the pattern
(`not-readable`, naming the field); an anchor, close, or tail occurring
twice in its region (`parse-ambiguous`); missing fields
(`parse-missing-fields`, `.partial` carries what was read); a spelled
turn value containing a marker the reader reads (`value-collides`).
Invertibility, stated exactly: `split(join(x)) == x` for marker-free,
outer-whitespace-free values; a reply that omits its close *and*
contains it inside the value is the one undetectable double fault.

**The JSON rule.** "Reply with a JSON object" names a format, not a
pattern; it cannot be read backwards. Spell the pattern
(`{{"answer": {answer}}}` with a `json` format on `answer`), or use a
document-form reader from vocabulary: `reader.kind` may name a registered
reader (`reader/json_object`), which declares the capability facts it needs
and the request settings it adds. Unknown kinds refuse `unknown-reader`.

## 4a. Repairs and truncation: reading the reply the model actually wrote

Models misspell the layout they were shown: `<Answer>` for `<answer>`,
`**Answer:**` for `Answer:`, `[[## answer ##]]` for `[[ ## answer ## ]]`,
`### Answer:` for `Answer:`. The derived reader repairs these by the one
rule below, and reports every repair and every tolerance it applied. It
never guesses: when a repair leaves two readings, the reply refuses as
§4 says. Value slips are repaired by the kernel's default reads (§7a),
and reported here too.

```
adapter entry: {"strict"?: true | false}   default false
find rule:     {"from": "text", "between": [open, close], "repair"?: true | false}
```

`strict: true` turns off every repair: markers, delimiters, values. The
other reports (`unclosed`, `ignored`) and truncation still apply. A
`strict` that is not a boolean refuses `entry-malformed` (fix
`edit-entry`, path `strict`); so does `repair` on a rule that is not a
`between` text rule, or not a boolean (path: the rule). The derived
reader takes no key besides `kind` (path `reader`).

**Two passes.** Pass 1 runs on the reply text before the find rules
(§6), over the delimiters of every `between` rule that declares `repair:
true`. Pass 2 runs on the text the find rules leave for the derived
reader, over its markers. Each pass is the rule below, with its own
markers; a mention removed by a find rule (a tag named inside
reasoning) is therefore never an exact marker for pass 2. Repair is
opt-in for find rules because their captures can be raw code, where a
loose match inside the code would cut it; a transport that captures
prose (`reasoning_tags`) opts in.

**Markers and keys.** The markers of pass 2 are the ones §4 searches:
each field's anchor (right-stripped), each non-empty close and the tail
(stripped); the markers of pass 1 are the delimiters, as written. The **ignorable** characters are U+0009, U+000B, U+000C,
U+000D, U+0020 (§7a whitespace without the line feed) and `*`, `_`, `#`
(markdown emphasis and headings). A text's **key** is the text with
every ignorable character removed and ASCII `A`–`Z` lowercased. A
marker is **repairable** when its key is not empty and no other marker string of its pass has the same key;
`describe()["reader"]["unrepaired"]` lists pass 2's others.

**Occurrences.** Remove the ignorable characters from the reader text
and lowercase ASCII, remembering each remaining character's position.
A **loose occurrence** of a marker is a match of its key in that
sequence, found leftmost first and without overlap (the next search
starts after the match). A marker's **leading line feeds** are left out
of the key searched: `\nSentiment:` also matches `Sentiment:` written in
the middle of a line (a live reply from `gpt-oss-20b` did exactly this,
case 169). Its **core** runs in the reader text from the
first matched character to the last. The line feed is not ignorable, so
a core crosses a line only where its marker does. Its **span** is the
core widened over decoration:

- **left** — the ignorable characters directly before the core, back to
  the previous character that is not ignorable, or the start of text. Among them, the decoration starts at the first `*`, `_` or `#` whose
  preceding character is §7a whitespace or the start of text; if there
  is none, there is no left decoration.
- **right** — when the left decoration holds a `*` or `_`, the run of
  `*` and `_` directly after the core.

The span starts at the decoration's start, else the core's; then, for a
marker with `n` leading line feeds, it widens left over spaces (U+0009,
U+000B, U+000C, U+000D, U+0020) and up to `n` line feeds directly before
them, when there are any. So `\n### Answer:` is seen whole, and
`Sentiment:` mid-line is rewritten to `\nSentiment:`. The streaming stage
holds a trailing line feed and the spaces after it while such a marker
could still follow.

**Choosing.** A marker is **written exactly** when it occurs as plain
text, as §4 searches it, and that occurrence does not lie inside a
longer span of one of its loose occurrences (inside one, it is the word
of a decorated spelling: `Answer:` in `**Answer:**`). For each repairable
marker written exactly, nothing is repaired — the exact spelling wins and
other spellings are content. Otherwise every
loose occurrence of it is repaired: its span is rewritten to the marker.
Two repaired spans that overlap refuse `parse-ambiguous`. The reader
then reads the rewritten text exactly as §4 says, so two repaired
anchors of one field refuse `parse-ambiguous`, like two exact ones.

Consequences, stated: a reply 0.7 read gives the same values, except
when decoration touches an exact marker: `**Answer:** 42` was the answer
`** 42` and is now `42` (reported). A marker the model writes in another
case while also writing it exactly elsewhere is content, never a
second anchor.

**The report.** `plan.read(reply).repairs` lists, in this order: pass
1's marker repairs in reply order, pass 2's in the order of its text, the
reader's tolerances in the order of the rewritten text, then value
repairs in the order outputs are read (visible outputs in signature
order, then fields found by find rules in find rule order):

| repair | when | keys |
|---|---|---|
| `marker` | a marker's or delimiter's span was rewritten | `marker`, `saw` (the span as written) |
| `value` | a kernel-default read needed the forgiving read (§7a) | `field`, `saw` (the stripped capture), `as` (the value as §7a writes it) |
| `unclosed` | a field with a non-empty close ended at the next marker or the tail without it | `field`, `close` |
| `ignored` | text that is not whitespace, outside every capture and marker: before the first marker, between a field's close and the next marker, after the tail | `saw` (stripped); or, for a non-text part outside every capture (§4b), `part` (its type) |

A capture that runs to the end of the text without its close is not
reported: that is what a provider stop sequence produces (§3). Replies
read by a vocabulary reader report nothing. The report is data, in the
same order in every implementation; the corpus pins it
(`expect.repairs`). A recorded reply whose reading has a `marker`,
`unclosed` or `value` repair is written back from its values (§3a).

## 4b. Parts inside the pattern: interleaved replies

A reply is a sequence of parts. The reader reads the text parts as one
text (§3, other parts are transparent to markers); every other part is an
**atom** at a position in that text: the length of the text parts before
it. Parts of a type a `part:<type>` find rule reads belong to that rule
and are not atoms.

**Reading.** An atom's position is followed through every edit made to
the text before the reader (pass 1 repairs, removing find rules, pass 2
repairs, §4a); an atom inside a span an edit removed or rewrote belongs to
no field. An atom whose position lies within a field's section — from the
end of its anchor to the start of its close, or of the next marker, or
the end of the text, both ends included — belongs to that field. The
field's capture is then the section's text split at its atoms, in order:
text, atom, text…, with the outer whitespace of the whole stripped and
empty text pieces dropped. Its `.text` is exactly the section's text as
without atoms (§4), so a text-reading format reads the same value as
before; a format that reads parts (the kernel's media default reads the
first part of its kind, §7b) gets them. Every other atom is reported as
`{"repair": "ignored", "part": <type>}`, after the reader's tolerances, in
reply order. A vocabulary reader sees no atoms.

**Writing.** A visible output whose format writes parts (`writes:
"parts"`, round-tripping) is written at its hole: the text before it, its
parts, the text after it, in one message. So a past turn with an image
output reads back as written (case 185). A text value containing U+FFFC
(the placeholder for that spot) refuses `value-collides`.

Streaming is unchanged: field deltas are text; atoms arrive with the
values at `finish`, which are batch's (§8). Not covered, stated: atoms
inside a find rule's match (they are ignored, not given to that rule's
field), and structured values made of several parts (a list of text and
image pairs) — those need a format that reads a parts capture, which is
vocabulary.

**Truncation.** An lm15 response whose `finish_reason` is `"length"`
was cut by the provider. It is read as usual; then parse refuses
`parse-truncated` — before any format reads — when a visible output is
missing, or when the derived reader's capture of a visible output ran to
the end of the text (no close, next marker or tail after it). The hint
names the field; `partial` carries the raw text of the outputs that
ended before the cut. `parse-ambiguous` still comes first;
`parse-truncated` takes the place of `parse-missing-fields`. A vocabulary reader cannot say where its captures
end, so with it a cut reply always refuses `parse-truncated`. A text or
a message carries no finish reason and is read as before. A cut reply
whose outputs all ended before the cut is read normally: the model was
talking after its answer.

## 5. Formats: how a type is written and read

A **format** is how one type crosses: `write(value, field) → parts`
(text is a part; a string is one text part), `read(capture, field) →
value`, and optionally `describe(field) → text` (what the model is told
when it must reply with one; default: the type's name, else the
mechanical hint). A format declares:

| fact | meaning |
|---|---|
| `accepts` | what it carries: type names, structural keys (`object`, `list[*]`, `list[object]`, `string`, `media:image`), or `*` |
| `direction` | `in`, `out`, `both` |
| `writes` | `text` or `parts` |
| `round_trip` | whether `read(write(v)) == v`; a lossy format cannot write turns (`turn-not-renderable`) |

**Resolution**, per field at bind, recorded in the plan:

1. the artifact's `formats[type]` — exact type name;
2. the artifact's most specific structural key: `list[object]` before
   `list[*]` before `object` before `string` …; `media:image` before
   `media:*` — never `*` here;
3. the runtime's type binding (code, per language, never serialized);
4. the kernel default: scalars, enums and nullables by §7a; a media
   value that is already a part passes through;
5. the artifact's `*` — so a wildcard format catches what nothing else
   spells, and never overrides a scalar default (cases 48, 49, 107);
6. refuse `no-format`, naming the field and its shape.

A format owns the whole value it accepts; the kernel never nests
formats. A format that composes (a list layout writing each element) asks
the plan for the element's format and refuses `no-format` at the path
(`answer[].age`) itself. Binding a format to a field it does not accept
refuses `format-shape-mismatch`; an input-only format on an output,
`format-direction`. `write` failures surface as `format-write-error`,
`read` failures as `format-read-error`; a value the kernel defaults
cannot spell is `value-invalid`, text they cannot read is `parse-value`.

**Artifact entries** under `formats`, keyed by type name or structural
key, are either a **reference** `{"use": name, "options"?}` to a named
format the runtime registers (vocabulary: `format-json.md` …, versioned
as `format/<name>`), or a **shipped UDF**. A reference is resolved at
load: the factory runs on `options`, and a factory that fails refuses
`entry-malformed` naming the reference's path — a pack has no
privilege, and a bad option is a defect of the artifact, never a bind
surprise or a host exception:

```json
{"language": "python", "deps": [], "write": "def write(v, f): …",
 "read": "def read(capture, f): …", "describe"?: "…", "sha256": "…",
 "authored_by": "…"}
```

Loading never runs a UDF. A runtime that will not place code refuses
`format-untrusted`; a tampered hash `udf-tampered`; source that reaches
into globals `format-not-self-contained`; a language the host cannot
place `udf-unplaceable`. Where it runs is the host's rule. A type with
no artifact entry uses the runtime binding or the kernel default, and
`plan.describe()` says which — this is the stated place where two
runtimes may legitimately spell the same type differently.

## 6. Transports: how a meaning travels

```
Transport = { when?: Predicate, requires?: [fact], in_template?: bool = true,
             tell?: {message role: text}, request_settings?: {…},
             put?: {"@purpose": "request.<key>" | "message:<role>"},
             written_as?: {"@purpose": format name}, find?: [FindRule], spelling?: Spelling }
         | { choose: [{when: Predicate, use: Transport}…, {else: Transport}] }
FindRule  = { from: "text" | "part:<part type>",
             between?: [open, close] | pattern?: regex | line_prefixed?: prefix,
             to: "@purpose" | "@purpose.<sub>", remove?: bool, complete_reply?: bool,
             repair?: bool }                       (repair: between only, §4a)
Spelling = { call?: text, result?: text, input_format?: {use, options?},
             probe?: {name, input, id?}, value?: text | null,
             position?: "before" | "after" }   (slots {id} {name} {input} {output}; value: {value})
Predicate = {capability} | {not} | {all} | {any}
```

Transports are keyed by purpose in the artifact, as data, or referenced
`{"use": name, "options"?}` (vocabulary, `transport/<name>`). A reference
is resolved at load, and what the factory returns is checked by the
kernel's own rules exactly as inline data (an empty `between`
delimiter, a bad predicate, an unrecoverable hidden field): a failing
factory or malformed result refuses `entry-malformed` naming the
reference's path. At bind, in
signature order: `choose` picks the first alternative whose `when`
holds (`capability-missing` if none and no `else`); `when`/`requires`
are checked against the declared capabilities (`capability-missing`
names purpose, transport, fact); `@purpose` binds to the field bearing the
purpose, `@purpose.<sub>` to the field bearing purpose `<purpose>.<sub>`
(`purpose-ambiguous` if two fields share one); `{field}` in tell binds
the name; `in_template: false` hides the field from loops and the pattern;
`put` writes the field's parts through its format into the request
request settings (`request.<key>`) or appends them to a message (`message:<role>`,
after a blank line when the message already has text, like `tell` text)
instead of a slot; `tell` text appends to the named message (created if
absent, system first). Both target the template's own messages, never a
message a turn slot wrote: the current input's sources never land in a
past turn's question; request_settings deep-merge into the request settings (§3;
`setting-conflict` on a disagreeing leaf). A `put` into the request whose
path equals, contains or lies inside a fixed setting's path (the
skeleton's `config.stop` included) or another `put`'s refuses
`setting-conflict` at bind: its value is only known at render, and one
write would silently replace the other (case 173; plan 09 G15).
A field both in the template and found by a transport is `field-double-covered`;
so is an input with a bare slot (a guard's body included) that a transport
also `put`s: it would be sent twice (case 172; plan 09 F14).

Batch parse normalizes response parts, before the find rules run, by the same logical-part
rule as streaming (§8): adjacent same-type text-bearing parts coalesce,
including empty text; a type change or a part without text ends the run.
Every response part is an object with a string `type`; `text`, when present,
is a string. Otherwise batch parse and part-delta `feed` refuse
`response-malformed`, without a `fix`. A bare string is valid as a text
response or text delta, but not as an element of a part list.
Metadata keys accumulate within a run; the last supplied value of each key
wins. Normalization does not change the caller's parts.

Find rules run **before** the reader. `from: text` scans the reply text —
`between` (plain scan), `line_prefixed` (lines split on `\n`), `pattern`
(the artifact's declared `pattern/*` extension, §10: it defines the
syntax, what a match is, and what is captured) — each match becomes a
text part; `remove` removes the matches from the text the reader sees.
`between` and `line_prefixed` are core: plain scans, no regex engine.
`from: part:<type>` collects the response parts of that lm15 part
type. The collected parts are the field's **capture**; the field's format
reads it.
`capture.text` is the stripped text parts joined by `\n`.

Two contracts, checked at bind: a find rule's capture kind must be one the
format's `read` accepts (`format-capture-mismatch`); a put's kind
must match what the format `writes` (`format-put-mismatch`).

**`written_as`: a put's own spelling.** Formats resolve by type (§5),
and one type may need two spellings for two transports — a tool spec is
an lm15 `function` tool in `Request.tools` and a line of text in a
system prompt. `written_as` names, per placed field, the registered format that
put writes through, instead of the type's; the format must exist
(`unknown-format`) and must write what the put needs. This is the
one stated exception to format-by-type, scoped to put, because
how a placed value is spelled is inseparable from where it is placed.

**A complete-reply find rule.** `complete_reply: true` says a non-empty capture on
this find rule is a complete reply on its own (a tool call instead of an
answer). When any complete-reply find rule captured something, visible outputs
the reader cannot find are *omitted* from the values instead of refusing
`parse-missing-fields`; everything found is still read and typed.
Without a capture, nothing changes. Streaming emits no events for an
omitted field.

**Spelling.** A transport may spell past protocol parts as text for a model
that has no native part: `spelling.call` renders each call of a written
model step, `spelling.result` each tool step (whose role becomes `user`,
§3a); slots `{id}`, `{name}`, `{input}` (canonical JSON), `{output}`
(the result's text parts joined by `\n`), `{{`/`}}` escape a brace. A
transport without them writes native `tool_call` and `tool_result` parts.
`spelling.value` and `spelling.position` govern how the transport's own `@purpose`
field is written into past turns (§3a).
**The probe:** at bind, a transport with `spelling.call` and a find rule to
`@purpose.calls` renders `{"id": "probe", "name": "probe", "input":
{"probe": true}}` through `call`, runs its own text find rules on the
result and reads the capture with the field's format; if that does not
yield one call named `probe` with that input, bind refuses
`spelling-drift` naming the transport — the template-is-the-reader law, at
transport level.

**Formatted arguments (0.6).** `spelling.input_format` is a normal named
format reference (`{use, options?}`), governing only the `{input}` slot.
Without it the existing JSON spelling remains. With it, the bound format
writes the call's input object using a synthetic input field named `input`,
shape `{"type":"object"}`. It must accept that field, write inputs and
write text; otherwise bind refuses `entry-malformed` at the transport's
`.spelling.input_format`. References resolve at load (including all `choose`
branches and named transports), and at bind for code-built adapters; unknown
names, bad options and version mismatch use the existing format refusals.
Dump pins their `format/<name>` versions in `versions.vocab`.

`spelling.probe` supplies a representative call: nonempty string `name`,
object `input`, optional nonempty string `id` (default `probe`), no other
keys. It requires `spelling.call`; so does `input_format`. Invalid structure
refuses `entry-malformed` at `.spelling`. The default sample remains unchanged.
A formatted call writer requires exactly one bound `@purpose.calls` target
and a text find rule to it; lack of either refuses `spelling-drift` at `.spelling`.
`spelling.call` and `spelling.result` belong to the transport whose purpose has a
`<purpose>.calls` field: on any other transport they would be a second
spelling of one call, or a spelling nothing uses, and refuse
`entry-malformed` at that transport's `.spelling`. The probe and turn
writing use **the same bound writer**. The probe
compares the recovered name and full input object with its sample, ignoring
IDs (text transports may assign them). A refusal while spelling or reading
the sample becomes `spelling-drift`, never a render-time refusal at bind.
This is a sample check, not proof of arbitrary round trips or safe execution.

Call write failures are `format-write-error`; delimiter collisions may
refuse `value-collides`. A format's output is inserted verbatim, never
reparsed as template syntax. Plans expose the input-format reference and
version in their `turns` inspection. No sample or formatter is inferred
from a tool's name or from the model.

## 7. Kernel defaults and text rules

### 7a. Text rules (normative for every implementation and every format)

- **Whitespace** — *strip* means exactly U+0009, U+000A, U+000B, U+000C,
  U+000D, U+0020. Unicode spaces are content.
- **Strings** — Unicode scalar values, never normalized; `\r\n` kept.
- **Integer text** — `-?[0-9]+`; else `parse-value`. Written in decimal.
  Implementations carry at least int64.
- **Number text** — `-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?`; binary64.
  A number read whose binary64 result is not finite refuses `parse-value`.
  Written with the ECMAScript `Number::toString` algorithm (`3`, `0.5`,
  `1e-7`, `1e+21`); non-finite refuses `value-invalid`.
- **Booleans** — read `true|yes` / `false|no` after ASCII case-folding;
  written `true`/`false`.
- **Enum** — the stripped text equals a member's spelling.
- **Null** — nullable shapes only: written `null`, read `null` exactly.
- **Forgiving reads** — when the exact read of a kernel-default scalar,
  enum or nullable refuses and the adapter is not `strict`, the reader
  tries, in order: the stripped text without one pair of matching `"`,
  `'` or `` ` `` around it; then that without one trailing `.` (not
  `..`), each re-read exactly; then, on those two texts, a nullable's
  `null` or `none` in any ASCII case, and an enum's string member equal
  in ASCII case when exactly one member is. The first that reads wins
  and is reported (§4a); if none does, the exact refusal stands. Strings
  never get here. `N/A` and `42.0` stay refusals: one could be content,
  the other is a different spelling, not a slip.
- **Rounding** — half-to-even in binary64: `roundeven(x·10ⁿ)/10ⁿ`.
- **Regex** — none in the core. A `pattern` find rule's syntax and matching
  are the declared `pattern/*` extension's (§10); the kernel never
  interprets the string itself.

### 7b. Kernel default formats

Scalars, enums and nullables write and read by §7a; strings are one
text part, verbatim. A field whose shape is `{"media": type}` writes a
value that is the part's data (a dict; a `type` key equal to the field's
kind is ignored, a different one refuses `value-invalid` — plan 09 G25) as
that lm15 part (`{"type": type, …}`), and reads the first part of that
type from its capture as its data **without** the `type` key: the field's
shape already says the type, so a value round-trips unchanged whether it
was given with `type` or not. Nothing structured has a default.

## 8. Streaming parse (sans-I/O)

Streaming is a *refinement* of batch parse, never a second parser:

> Feed the same response in any chunking — the final values equal
> `parse()` of the concatenated response, exactly. Per field, the
> concatenation of emitted deltas equals the batch raw text.

`stream = plan.stream()` creates a pure state machine; it opens no
connection and owns no I/O. `stream.feed(delta)` accepts either a text
string or one lm15 part delta `{"type": string, "text"?, …}` (an lm15
`TextDelta`/`ThinkingDelta` as canonical JSON; `part_index` and other
keys are metadata) and returns zero or more structurally fixed events. `field_done.value` is the same
host-typed value as `parse()` (and therefore need not be JSON data).
`stream.finish(finish_reason?)` marks end-of-stream
and returns `StreamResult(events, values, repairs)`: the final events caused by
EOF and the same typed values and repairs as batch `read`. `finish_reason`
is the lm15 stream end's (§4a truncation); absent, none is known. EOF can end a field and
release its held trailing whitespace, so final events cannot honestly
be returned by `feed`; this is why `finish` returns both. Calling
`feed` after `finish`, or `finish` twice, is host API misuse, not a
`Refusal`.

Text strings are deltas of the response's `text` channel. Adjacent
part deltas with the same `type` and string `text` coalesce into one
logical part by concatenating `text`; a change of type closes that
part. A part delta without text is one complete part. Thus a provider
can pass its text/thinking deltas without inventing part boundaries.
A malformed delta refuses `response-malformed` at `feed`.

Events have one of these exact shapes, in signature field order when
one input delta advances several fields:

```
{"kind": "field_started", "field": name}
{"kind": "field_delta",   "field": name, "text": raw_text_delta}
{"kind": "field_done",    "field": name, "value": typed_value}
```

One `field_started` and one `field_done` occur per recovered field;
empty `field_delta` events never occur. `field_delta` is raw text after
the same §7a outer strip as batch parse. The reducer holds leading and
trailing ASCII whitespace and any suffix that can begin an anchor,
close, tail, find rule delimiter, or line; it emits only a prefix no
future delta can change. A marker occurrence acts — opens a field's
section, ends the previous one, or fixes a close — only once no boundary
marker can still be growing across it: a later marker may begin inside
an earlier one (§4, `**Reasoning:**Answer:**`), and the section it
shrinks must not have emitted yet. This hold is exact, not a fixed
delay: it costs nothing where no marker prefix is in sight. `field_done`
is emitted by `finish`, after the
whole reply passes the batch structural checks and formats read in the
same order. This deliberately avoids speculative typed values: an
anchor or close that arrives later can still make the reply ambiguous.
Every `feed` does work proportional to its delta, never to the reply:
an implementation must not rescan the accumulated text per delta.

The derived marker reader streams incrementally. A vocabulary reader may
provide the optional streaming face
`reader.stream(field_names) → reducer`, where
`reducer.feed(text_delta) → {field: stable_raw_prefix}` and
`reducer.finish() → {field: final_raw}`. Calls receive the stable text
left by find rules. Prefixes must only grow; `finish` checks them against
the batch reader and a disagreement is an implementation bug. A reader
without this face (the base method returns `None`) buffers and produces all events
at `finish`. Find rule behavior is:

- `between` emits a capture after its close arrives;
- `line_prefixed` emits a capture after its newline arrives (or at EOF);
- `from: part:<type>` streams text from matching part deltas;
- `pattern` buffers its field until `finish` because a later byte
  can change a regex match;
- a removing find rule passes only stable, non-matching text to the next
  find rule and the reader; find rule stages compose in declaration order;
- when more than one find rule writes one field, that field buffers until
  `finish`, because batch `capture.text` concatenates by find rule order,
  not response arrival order.

Marker repair (§4a) is a stage between the find rules and the derived
reader. It passes text on unchanged while nothing can need a repair,
holding only a suffix that could still grow into a loose occurrence or
its decoration. From the first span that needs a repair (a loose
occurrence whose span is not its marker) it holds the rest of the reply
until `finish`, where the batch rewrite decides: a later exact marker
can still make that span content. A well-spelled reply therefore streams
as before; a misspelled one streams up to its first slip. The repairs
themselves are known at `finish` only.

`plan.describe()["streaming"]` declares `mode` (`incremental`,
`hybrid`, or `buffered`), the reader mode, each find rule's mode and reason,
`repairs` (`{"mode": "strict"}`, or `"forgiving"` with the reason a repair
stage can hold),
and `field_done: "finish"`; buffering is visible, never hidden.

**Refusal law.** `finish()` runs the same structural parse and typed
reads as `parse()`, in the same order; it therefore raises the same
`code`, `fix`, and `partial`. `feed` does not raise a content refusal
that batch parse could supersede later; it only refuses a malformed
delta. Events already emitted before a final refusal are observations,
not a successful result.

The conformance harness replays every parse case at every Unicode-scalar
split (and every text-bearing part split), compares final values with
batch parse, and compares concatenated field deltas across all splits.
It also records the one-scalar replay's event log (every feed's events,
then the EOF events or the refusal code) as the case's *stream trace*;
an external driver's trace must equal the reference kernel's, so *when*
raw text becomes visible is pinned across implementations, not only
what it finally is.
Transport byte decoding stays outside lmcc: clients must decode network
bytes incrementally before `feed`, so a split inside a UTF-8 scalar is
not a distinct lmcc chunking.

## 9. Versioning and conformance

Kernel and every vocabulary entry version independently (semver; while
major = 0, minor is breaking). Artifacts pin what they need; loaders
refuse `version-incompatible` naming both sides; unknown names refuse
(`unknown-format`, `unknown-transport`, `unknown-reader`).

The corpus (`corpus/cases/*.json`, `schema/case.schema.json`) is the
authority: an implementation is conformant when the harness passes every
case byte-exactly — rendered text and parts, parsed values, refusal
codes and their fixes. Case kinds: `render`, `parse`, `roundtrip`, `refuse`,
`plan`. A render, plan or refuse case renders the current turn from `inputs`
and optional `steps`, with optional `turns` (slot → turns); a turn in a case
may omit `signature`, and the harness then writes the case signature's
fingerprint, computed by its own §3a implementation (case 128 pins the value
itself; 139 pins the mismatch). A case
declares in `requires` everything beyond the core it needs: a UDF
placement (`udf:python`) or an extension (`pattern/legacy-re2`). A
driver builds its registry with exactly those and nothing more, so a
case that forgets a requirement refuses instead of passing by accident;
a driver that lacks one answers `{"ok": true, "unclaimed": "<it>"}` and
the harness counts it apart — declared, never silent, never a pass.
A conformance claim therefore names the core version and each
extension it passes; "core only" is a complete, honest claim.

**The driver protocol.** `runner.py --driver CMD` starts one process and
streams JSON Lines: one case per line in, one `{"ok", "detail"?,
"unclaimed"?, "stream_trace"?}` per line out. Values compare by JSON
equality: objects unordered, arrays ordered, numbers by value. For
`parse` cases and `refuse` cases at `parse`, `stream_trace` is the §8
one-scalar event log — a list per feed of `[kind, field]` or
`[kind, field, text]` digests, then the EOF list or `{"refusal": code}`;
the harness compares it with the reference kernel's.

## 10. Extensions: declared, bound, or refused

The core is everything above except regex execution. An **extension**
is a named, versioned semantic contract for behavior the core does not
define; `spec/extensions/README.md` indexes them, one spec file each.
An extension name is `<family>/<name>` (`pattern/legacy-re2`): the
family is the construct it governs, the name the contract. The artifact
declares what it needs; the host binds an implementation or refuses.

```
entry.extensions = { "<family>/<name>": "MAJOR.MINOR.PATCH", … }
```

**Declaration rules**, checked at load (and again at bind for adapters
built in code — a refusal fires before any plan exists):

1. every key is a well-formed name and every value a semver string, else
   `entry-malformed` at `extensions`;
2. at most one extension per family, else `entry-malformed` at
   `extensions` — the construct's meaning would be ambiguous;
3. every declared extension is one the host binds, else
   `extension-unsupported` naming it (fix `bind-extension`);
4. the bound version is compatible with the declared one by the §9
   rule, else `version-incompatible` (fix `match-version`, entry
   `<family>/<name>`);
5. every construct that needs a family — today, a find rule carrying
   `pattern` — has that family declared, else `extension-undeclared`
   naming the construct's path (fix `declare-extension`); a find rule the
   artifact reaches through a named transport counts, at the same path;
6. after that, the binding admits each construct it governs: a `pattern`
   the dialect rejects refuses `entry-malformed` at the find rule's path,
   exactly as a malformed `between` does.

Declaring an extension the artifact does not use is allowed; it only
narrows where the artifact runs. `dump` writes `extensions` back
verbatim.

**The default tier.** The adapter *constructor* (`lmcc.adapter`,
`NewAdapter`) — never the loader — fills in the default when an inline
transport carries `pattern` and no `pattern/*` is declared:
`pattern/legacy-re2` at the version the kernel binds natively. The line
is written into the adapter, so the dumped artifact says it; an explicit
`pattern/*` declaration is never overridden; a transport reached by name
(`{"use": …}`) is not seen by the constructor and its author declares by
hand. This is a tooling convenience with the same effect as typing the
line: the artifact on disk always speaks for itself, and `load` refuses
one that does not.

**Host side.** A registry carries **extension bindings**: for each
extension name, the version it implements and a binding label
(`python:re`, `go:regexp`, a library, a service — never a secret).
`registry.describe()["extensions"]` is the discovery surface, separate
from model capabilities: `native_reasoning` is a fact about the model,
`pattern/legacy-re2` is a fact about this process. A kernel may bind the
extensions its own runtime can honestly implement by default; a
**core-only** registry is always constructible and refuses every
extension-dependent artifact before model I/O. Binding never runs
artifact code and never starts anything; it is a table entry.

`plan.describe()["extensions"]` lists, per required extension, the
declared version, the bound version, and the binding label — what
resolved, inspectable before spending.

**Migration from 0.2.** Set `versions.kernel` to `0.3.0`. If the
artifact has any `pattern` find rule, add
`"extensions": {"pattern/legacy-re2": "0.1.0"}` — that contract is,
by definition, what 0.2 did (`spec/extensions/pattern-legacy-re2.md`),
so the meaning is preserved exactly; nothing is relabeled silently
because nothing is assumed: an undeclared `pattern` refuses.

## Clarifications from the clean-room audit (plan 09, Bin 2)

Behaviors the reference always had but this document did not state,
pinned in `tests/test_audit_holes.py` (audit IDs in brackets). Each is
normative.

- §9 — `dump` records the running kernel version and, for each referenced
  vocabulary entry, its registered version; loading ignores the patch
  number and pins for entries the artifact never references [C2, G22,
  G23]. Load checks the kernel version before resolving references [I1].
- §7a — an integer is written from an integer value; an integral float
  (`3.0`) refuses `value-invalid` [E4].
- §4 — the tail is found on the first non-empty line after the outputs
  loop; a tail found twice refuses `parse-ambiguous` [F7, F8]. Structural
  checks (ambiguity, missing sections) come before any typed read [I3].
- §2 — a hidden output in a bare slot renders its placeholder there and
  is not read from there [F13]. An unknown attribute in an inputs loop
  refuses `unknown-slot` [F26].
- §5 — structural keys are computed from a nullable's base shape [G1]; an
  enum resolves through `enum`, never through its members' scalar key [G2].
  Placeholders are mechanical: `(integer)`, `(number)`, `(boolean)`,
  `one of: a, b` for an enum, `(<kind>)` for media, `...` for a string [F17, F18].
- §6 — a `between` rule whose close never comes captures nothing and
  removes nothing; its field reads the empty capture [G17, G18, G26]. A
  removed `line_prefixed` line leaves its line feed [G19]. A message `put`
  accepts parts, so an image joins the message [G12]. Equal settings from
  two transports merge once [G14]. A transport's `when` is checked before
  its `requires`, and the first missing required fact is the one named
  [G20, I4, G21].
- §3 — the reply text is the concatenation of every text part in response
  order, across parts of other types [H4]. A `parse-missing-fields`
  refusal's `partial` holds raw text, before typed reads [F11].
- §3 — the skeleton's stop is the stripped tail, else the stripped last
  close; an empty one is omitted [A5].

## Deliberate gaps (0.8)

Repairs of `line_prefixed` prefixes and of provider parts; the `grammar` face of `skeleton()`, declared parse
combinators beyond marker repair (plan 02), a
rigorously specified pattern dialect with library evidence (plan 10,
remaining items), and field-level layouts of a turn in the text form
(`{% for f in t.inputs %}`; plan 12). Each lands as a versioned addition.

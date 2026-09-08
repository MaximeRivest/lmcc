# The LMCC kernel — normative specification

**Version 0.4.0** (kernel). Status: the v3 design (`plans/08`), built with
two implementations (`python/lmcc`, `go/lmcc`) against the corpus. Where
this document and the corpus disagree, fix the corpus first, then both.

**What 0.4 changes (D-35).** The wire layer *is* the lm15 contract
(`../LM15_CONTRACT_PIN` names the ratified commit): parts carry `type`,
messages carry `parts`, `system` is a request field, and what `render`
produces is an lm15 request minus its model — feedable to any lm15
implementation without translation. The controls patch is a partial
lm15 request (`config.<field>`, `tools`), deep-merged and validated
against the pinned field names. No case expectation changed meaning; the
bytes were re-spelled in lm15's words.

**What 0.3 changes (D-33).** The kernel is a small mandatory core; any
behavior outside it is a named, versioned **extension** the artifact
declares and the host binds or refuses (§10, `portability.md`). The one
extension so far is the routing `pattern` dialect: a 0.3 artifact that
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
   the wire: messages, parts, request controls        ← the adapter lays this out
        │  read: the reply → each typed value
        ▼
your typed return value
```

LMCC never touches the network. It lays out the call and reads the
return. The nouns: **signature, adapter, template, lens, format, part,
span, role, strategy, capability**; the verb: **bind**. The kernel ships
no formats and no strategies beyond the defaults §5 names.

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
          type?: str, role?: str = "plain", desc?: str }
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
name only. `role` is what the field means to the exchange
(`spec/vocab/roles.md`); roles are namespaced strings (`tools`,
`tools.calls`), each bound to at most one field.

**Frontends.** `@lmcc.fn` (Python: parameters → inputs, return type →
outputs, dataclass return for several, docstring → instructions,
`Role["reasoning", T]` for roles), Go struct tags, `lmcc_dspy`, JSON —
every syntax lowers to this form; none is the contract. A type a
frontend cannot lower refuses `unmapped-type`, naming the field.

## 2. Adapter and template

An adapter is a template, a parse rule, strategies by **role**, and
formats by **type** — never a field name. That is what lets one adapter
serve every signature. The template is a message list of `{role, text}`
(roles `system`, `developer`, `user`, `assistant`; `system` messages
lead) and directives `{"directive": "demos" | "history"}`, with exactly
three constructs:

| construct | example | meaning |
|---|---|---|
| slot | `{instruction}`, `{format}`, `{question}`, `{answer}`, `{f.name}`, `{f.value}` | a value goes here |
| loop | `{% for f in inputs %} … {% endfor %}` (also `outputs`) | once per visible field, signature order |
| escape | `{{`, `}}` | a literal brace; a bare brace is `template-syntax` |

Loop attributes: `name`, `desc` ("" when absent), `type` ("" when
absent), `schema` (the format's `describe`, else the mechanical hint),
`role`, `value`. `instruction` and `format` are reserved. An input slot
renders the value through its format; an **output slot** (`{answer}` or
`{f.value}` in an outputs loop) renders the field's **placeholder**:
`desc`, else the format's `describe`, else the mechanical hint, else
`...` — the shape is shown, never merely described. In demo and history
turns an inputs loop iterates only the fields the turn supplies; a bare
slot with no value refuses `missing-input`.

Every input must be reachable from a slot or an inputs loop
(`field-uncovered`).

## 3. Bind, render, parse

```
bind(adapter, signature, capabilities, registry) → plan   every refusal fires here
plan.render(inputs, demos?, history?) → {messages, patch}   pure
plan.parse(response) → {field: value}                      pure
plan.stream() → stream                                     pure, sans-I/O
stream.feed(delta) → [event, …]
stream.finish() → {events: [event, …], values: {field: value}}
plan.describe() · plan.explain() · plan.skeleton() · plan.prefix()
```

A refusal is `Refusal(code, hint, fix, partial)`: `code` is stable
(`errors.md`), `hint` names the offender for a human, `fix` is the one
next action as data from the closed action vocabulary of `errors.md` —
present on every refusal that fires before render (signature, load,
bind), absent on render and parse refusals — and `partial` is what a
parse recovered. The corpus pins codes and fixes; both kernels emit the
same fix for the same refusal.

**Render output** is an lm15 request minus its model:
`{"system"?: text | [part], "messages": [{"role", "parts"}], "config"?,
"tools"?}`. The template's `system` messages (which must lead the
template, contiguous — `entry-malformed` otherwise) fold into `system`:
one text part becomes the string, anything else the part list. Template
message roles are `system`, `developer`, `user`, `assistant`; messages
render as `{"role", "parts": [part, …]}`, adjacent text parts merge,
empty messages drop. Everything after `messages` is the **patch**: the
deep merge of every strategy's `controls` and the lens's `patch`, a
partial lm15 request whose first path segment is `config` or `tools` and
whose `config` keys are the pinned lm15 `Config` fields (`max_tokens`,
`temperature`, `top_p`, `top_k`, `stop`, `response_format`,
`tool_choice`, `reasoning`, `cache`, `service_tier`, `user_id`, `store`,
`extensions`); anything else refuses `entry-malformed` at the control's
path. Below those two levels the value is opaque, as in lm15. Two
sources disagreeing on one leaf is `control-conflict`; agreeing is fine.

**Parse input** is a string (the reply text), an lm15 message
(`{"role", "parts"}`; the role is not read), or an lm15 response
(`{"message": {…}, …}`; only `message` is read). **Demos** are field
dicts: the user templates over the demo's inputs, then one assistant
turn written by the lens over the outputs the demo supplies (absent
outputs are omitted). **History** items are lm15 messages (verbatim) or
`{"fields": {…}}` turns rendered like demos; anything else refuses
`value-invalid`.

`skeleton()` is what the derived lens knows the reply must contain:
`{"prefill": text before the first output hole, "stops": [the last
close or tail]}` (a `grammar` face is a stated gap). `prefix()` is the
rendered request prefix that does not depend on inputs
(`{"system"?, "messages"}`: system, demos, history turns before the
first message with an input slot) — the cache-stable bytes.

## 4. The template is the lens

`parse: {"kind": "derived"}` (the kernel lens). The **output pattern** is
the set of output holes in the template — `{f.value}` in one outputs
loop, or bare output slots — and it must live in one message. Read
backwards:

- per visible output field, the literal before its hole (loop body
  instantiated with the field's `name`/`desc`/`type`/`schema`/`role`)
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
- demos and the `{format}` skeleton are written through the same
  pattern: `join` (values) and `format` (placeholders) are the lens
  writing forward.

Refusals: no pattern or two (`not-lensable`); a hole with no literal
before it, two holes sharing an anchor, nested loops in the pattern
(`not-lensable`, naming the field); an anchor, close, or tail occurring
twice in its region (`parse-ambiguous`); missing fields
(`parse-missing-fields`, `.partial` carries what was read); a spelled
demo value containing a marker the lens reads (`value-collides`).
Invertibility, stated exactly: `split(join(x)) == x` for marker-free,
outer-whitespace-free values; a reply that omits its close *and*
contains it inside the value is the one undetectable double fault.

**The JSON rule.** "Reply with a JSON object" names a format, not a
pattern; it cannot be read backwards. Spell the pattern
(`{{"answer": {answer}}}` with a `json` format on `answer`), or use a
document-form lens from vocabulary: `parse.kind` may name a registered
lens (`lens/json_object`), which declares the capability facts it needs
and the request patch it adds. Unknown kinds refuse `unknown-parse-kind`.

## 5. Formats: how a type is written and read

A **format** is how one type crosses: `write(value, field) → parts`
(text is a part; a string is one text part), `read(span, field) →
value`, and optionally `describe(field) → text` (what the model is told
when it must reply with one; default: the type's name, else the
mechanical hint). A format declares:

| fact | meaning |
|---|---|
| `accepts` | what it carries: type names, structural keys (`object`, `list[*]`, `list[object]`, `string`, `media:image`), or `*` |
| `direction` | `in`, `out`, `both` |
| `emits` | `text` or `parts` |
| `round_trip` | whether `read(write(v)) == v`; a lossy format cannot write demos (`demo-not-renderable`) |

**Resolution**, per field at bind, recorded in the plan:

1. the artifact's `formats[type]` — exact type name;
2. the artifact's most specific structural key: `list[object]` before
   `list[*]` before `object` before `string` … before `*`; `media:image`
   before `media:*`;
3. the runtime's type binding (code, per language, never serialized);
4. the kernel default: scalars, enums and nullables by §7a; a media
   value that is already a part passes through;
5. refuse `no-format`, naming the field and its shape.

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
 "read": "def read(span, f): …", "describe"?: "…", "sha256": "…",
 "authored_by": "…"}
```

Loading never runs a UDF. A runtime that will not place code refuses
`format-untrusted`; a tampered hash `udf-tampered`; source that reaches
into globals `format-not-self-contained`; a language the host cannot
place `udf-unplaceable`. Where it runs is the host's rule. A type with
no artifact entry uses the runtime binding or the kernel default, and
`plan.describe()` says which — this is the stated place where two
runtimes may legitimately spell the same type differently.

## 6. Strategies: how a meaning travels

```
Strategy = { when?: Predicate, requires?: [fact], visible?: bool = true,
             fragments?: {message role: text}, controls?: {…},
             placement?: {"@role": "controls.<key>" | "message:<role>"},
             routings?: [Routing] }
         | { choose: [{when: Predicate, use: Strategy}…, {else: Strategy}] }
Routing  = { from: "text" | "channel:<part type>",
             between?: [open, close] | pattern?: regex | line_prefixed?: prefix,
             to: "@role" | "@role.<sub>", consume?: bool }
Predicate = {capability} | {not} | {all} | {any}
```

Strategies are keyed by role in the artifact, as data, or referenced
`{"use": name, "options"?}` (vocabulary, `strategy/<name>`). A reference
is resolved at load, and what the factory returns is checked by the
kernel's own rules exactly as inline data (an empty `between`
delimiter, a bad predicate, an unrecoverable hidden field): a failing
factory or malformed result refuses `entry-malformed` naming the
reference's path. At bind, in
signature order: `choose` picks the first alternative whose `when`
holds (`capability-missing` if none and no `else`); `when`/`requires`
are checked against the declared capabilities (`capability-missing`
names role, strategy, fact); `@role` binds to the field bearing the
role, `@role.<sub>` to the field bearing role `<role>.<sub>`
(`role-ambiguous` if two fields share one); `{field}` in fragments binds
the name; `visible: false` hides the field from loops and the pattern;
`placement` writes the field's parts through its format into the request
patch (`controls.<key>`) or appends them to a message (`message:<role>`)
instead of a slot; fragments append to the named message (created if
absent, system first); controls deep-merge into the patch (§3;
`control-conflict` on a disagreeing leaf).
A field both visible and routed is `field-double-covered`.

Batch parse normalizes response parts before routing by the same logical-part
rule as streaming (§8): adjacent same-type text-bearing parts coalesce,
including empty text; a type change or a part without text ends the run.
Every response part is an object with a string `type`; `text`, when present,
is a string. Otherwise batch parse and part-delta `feed` refuse
`response-malformed`, without a `fix`. A bare string is valid as a text
response or text delta, but not as an element of a part list.
Metadata keys accumulate within a run; the last supplied value of each key
wins. Normalization does not change the caller's parts.

Routings run **before** the lens. `from: text` scans the reply text —
`between` (plain scan), `line_prefixed` (lines split on `\n`), `pattern`
(the artifact's declared `pattern/*` extension, §10: it defines the
syntax, what a match is, and what is captured) — each match becomes a
text part; `consume` removes the matches from the text the lens sees.
`between` and `line_prefixed` are core: plain scans, no regex engine.
`from: channel:<type>` collects the response parts of that lm15 part
type. The collected parts are the field's **span**; the field's format
reads it.
`span.text` is the stripped text parts joined by `\n`.

Two contracts, checked at bind: a routing's span kind must be one the
format's `read` accepts (`format-span-mismatch`); a placement's kind
must match what the format `emits` (`format-placement-mismatch`).

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
- **Rounding** — half-to-even in binary64: `roundeven(x·10ⁿ)/10ⁿ`.
- **Regex** — none in the core. A `pattern` routing's syntax and matching
  are the declared `pattern/*` extension's (§10); the kernel never
  interprets the string itself.

### 7b. Kernel default formats

Scalars, enums and nullables write and read by §7a; strings are one
text part, verbatim. A field whose shape is `{"media": type}` writes a
value that is already a part dict as that lm15 part (`{"type": type, …}`)
and reads the first part of that type from its span. Nothing structured
has a default.

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
`stream.finish()` marks end-of-stream
and returns `StreamResult(events, values)`: the final events caused by
EOF and the same typed values as batch `parse`. EOF can end a field and
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
close, tail, routing delimiter, or line; it emits only a prefix no
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

The derived marker lens streams incrementally. A vocabulary lens may
provide the optional streaming face
`lens.stream(field_names) → reducer`, where
`reducer.feed(text_delta) → {field: stable_raw_prefix}` and
`reducer.finish() → {field: final_raw}`. Calls receive the stable text
left by routings. Prefixes must only grow; `finish` checks them against
the batch lens and a disagreement is an implementation bug. A lens
without this face (the base method returns `None`) buffers and produces all events
at `finish`. In Go the same optional face is `StreamingLens.NewStream`
returning a `LensStream` with `Feed` and `Finish`. Routing behavior is:

- `between` emits a capture after its close arrives;
- `line_prefixed` emits a capture after its newline arrives (or at EOF);
- `from: channel:<type>` streams text from matching part deltas;
- `pattern` buffers its routed field until `finish` because a later byte
  can change a regex match;
- a consuming routing passes only stable, non-matching text to the next
  routing and the lens; routing stages compose in declaration order;
- when more than one routing writes one field, that field buffers until
  `finish`, because batch `span.text` concatenates by routing order,
  not response arrival order.

`plan.describe()["streaming"]` declares `mode` (`incremental`,
`hybrid`, or `buffered`), the lens mode, each routing's mode and reason,
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
(`unknown-format`, `unknown-strategy`, `unknown-parse-kind`).

The corpus (`corpus/cases/*.json`, `schema/case.schema.json`) is the
authority: an implementation is conformant when the harness passes every
case byte-exactly — rendered text and parts, parsed values, refusal
codes and their fixes. Case kinds: `render`, `parse`, `roundtrip`, `refuse`. A case
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
5. every construct that needs a family — today, a routing carrying
   `pattern` — has that family declared, else `extension-undeclared`
   naming the construct's path (fix `declare-extension`); a routing the
   artifact reaches through a named strategy counts, at the same path;
6. after that, the binding admits each construct it governs: a `pattern`
   the dialect rejects refuses `entry-malformed` at the routing's path,
   exactly as a malformed `between` does.

Declaring an extension the artifact does not use is allowed; it only
narrows where the artifact runs. `dump` writes `extensions` back
verbatim.

**The default tier.** The adapter *constructor* (`lmcc.adapter`,
`NewAdapter`) — never the loader — fills in the default when an inline
strategy carries `pattern` and no `pattern/*` is declared:
`pattern/legacy-re2` at the version the kernel binds natively. The line
is written into the adapter, so the dumped artifact says it; an explicit
`pattern/*` declaration is never overridden; a strategy reached by name
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
artifact has any `pattern` routing, add
`"extensions": {"pattern/legacy-re2": "0.1.0"}` — that contract is,
by definition, what 0.2 did (`spec/extensions/pattern-legacy-re2.md`),
so the meaning is preserved exactly; nothing is relabeled silently
because nothing is assumed: an undeclared `pattern` refuses.

## Deliberate gaps (0.3)

The `grammar` face of `skeleton()`, parse combinators (plan 02), turns
(plan 03), tools/citations strategy vocabularies (plan 04), and a
rigorously specified pattern dialect with library evidence (plan 10,
remaining items). Each lands as a versioned addition.

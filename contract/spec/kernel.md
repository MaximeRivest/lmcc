# The LMCC kernel — normative specification

**Version 0.2.0** (kernel). Status: the v3 design (`plans/08`), built with
two implementations (`python/lmcc`, `go/lmcc`) against the corpus. Where
this document and the corpus disagree, fix the corpus first, then both.

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
| `{"media": kind}` | a part of that kind (§5 defaults) |
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
and directives `{"directive": "demos" | "history"}`, with exactly three
constructs:

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

Messages are lm15-shaped: `{"role", "content": [part, …]}`; adjacent
text parts merge; empty messages drop. A response is a string or
`{"content": [part, …]}`. **Demos** are field dicts: the user templates
over the demo's inputs, then one assistant turn written by the lens over
the outputs the demo supplies (absent outputs are omitted). **History**
items are messages (verbatim) or `{"fields": {…}}` turns rendered like
demos; anything else refuses `value-invalid`.

`skeleton()` is what the derived lens knows the reply must contain:
`{"prefill": text before the first output hole, "stops": [the last
close or tail]}` (a `grammar` face is a stated gap). `prefix()` is the
rendered messages that do not depend on inputs (system, demos, history
turns before the first message with an input slot) — the cache-stable
bytes.

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
Routing  = { from: "text" | "channel:<part kind>",
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
absent, system first); controls merge into the patch (`control-conflict`).
A field both visible and routed is `field-double-covered`.

Batch parse normalizes response parts before routing by the same logical-part
rule as streaming (§8): adjacent same-kind text-bearing parts coalesce,
including empty text; a kind change or a part without text ends the run.
Metadata keys accumulate within a run; the last supplied value of each key
wins. Normalization does not change the caller's parts.

Routings run **before** the lens. `from: text` scans the reply text —
`between` (plain scan), `line_prefixed` (lines split on `\n`), `pattern`
(RE2, group 1, empty matches discarded) — each match becomes a text
part; `consume` removes the matches from the text the lens sees.
`from: channel:<kind>` collects the response parts of that kind. The
collected parts are the field's **span**; the field's format reads it.
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
  Written with the ECMAScript `Number::toString` algorithm (`3`, `0.5`,
  `1e-7`, `1e+21`); non-finite refuses `value-invalid`.
- **Booleans** — read `true|yes` / `false|no` after ASCII case-folding;
  written `true`/`false`.
- **Enum** — the stripped text equals a member's spelling.
- **Null** — nullable shapes only: written `null`, read `null` exactly.
- **Rounding** — half-to-even in binary64: `roundeven(x·10ⁿ)/10ⁿ`.
- **Regex** — RE2 syntax; lookaround, backreferences, named groups,
  atomic/possessive constructs refuse `entry-malformed`.

### 7b. Kernel default formats

Scalars, enums and nullables write and read by §7a; strings are one
text part, verbatim. A field whose shape is `{"media": kind}` writes a
value that is already a part dict as that part (`{"kind": kind, …}`)
and reads the first part of that kind from its span. Nothing structured
has a default.

## 8. Streaming parse (sans-I/O)

Streaming is a *refinement* of batch parse, never a second parser:

> Feed the same response in any chunking — the final values equal
> `parse()` of the concatenated response, exactly. Per field, the
> concatenation of emitted deltas equals the batch raw text.

`stream = plan.stream()` creates a pure state machine; it opens no
connection and owns no I/O. `stream.feed(delta)` accepts either a text
string or one lm15-shaped part delta `{"kind": string, ...}` and returns
zero or more structurally fixed events. `field_done.value` is the same
host-typed value as `parse()` (and therefore need not be JSON data).
`stream.finish()` marks end-of-stream
and returns `StreamResult(events, values)`: the final events caused by
EOF and the same typed values as batch `parse`. EOF can end a field and
release its held trailing whitespace, so final events cannot honestly
be returned by `feed`; this is why `finish` returns both. Calling
`feed` after `finish`, or `finish` twice, is host API misuse, not a
`Refusal`.

Text strings are deltas of the response's `text` channel. Adjacent
part deltas with the same `kind` and string `text` coalesce into one
logical part by concatenating `text`; a change of kind closes that
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
- `from: channel:<kind>` streams text from matching part deltas;
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
codes and their fixes. Case kinds: `render`, `parse`, `roundtrip`, `refuse`. A case may
declare `requires: ["udf:python"]`; a driver that cannot place that
language answers `{"ok": true, "unclaimed": "udf:python"}` and the
harness counts it apart — declared, never silent.

**The driver protocol.** `runner.py --driver CMD` starts one process and
streams JSON Lines: one case per line in, one `{"ok", "detail"?,
"unclaimed"?, "stream_trace"?}` per line out. Values compare by JSON
equality: objects unordered, arrays ordered, numbers by value. For
`parse` cases and `refuse` cases at `parse`, `stream_trace` is the §8
one-scalar event log — a list per feed of `[kind, field]` or
`[kind, field, text]` digests, then the EOF list or `{"refusal": code}`;
the harness compares it with the reference kernel's.

## Deliberate gaps (0.2)

The `grammar` face of `skeleton()`, parse combinators (plan 02), turns
(plan 03), and tools/citations strategy vocabularies (plan 04). Each
lands as a versioned addition.

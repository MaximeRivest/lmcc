# The LMCC kernel — normative specification

**Version 0.1.0** (kernel). Status: reference-proven — the Python
implementation in `python/lmcc` and this document were built together; where
they disagree, fix the corpus first, then both.

**One sentence.** LMCC is the language model calling convention: it maps a
declared I/O contract to model messages and maps the reply back to typed
values, as inspectable, shareable, versioned data.

**What the kernel is.** Mechanics only: the template engine, the lens, the
bake/render/parse pipeline, serde, the sockets, and the refusal taxonomy.
The kernel ships **zero codecs, zero strategies, zero host types**. Every
named codec/strategy is vocabulary (see `spec/vocab/`), registered through
sockets, certified by the corpus. The precedent is serde-without-serde_json.

---

## 1. SignatureCore (the neutral input)

```
SignatureCore = { instructions: str, fields: [Field] }
Field = { name, direction: "input"|"output", shape: JSONSchema,
          role: str = "plain", desc: str? }
```

The plain-data form is `schema/signature.schema.json`. Field names are
ASCII identifiers (`[A-Za-z_][A-Za-z0-9_]*`) and unique within a
signature; `direction` is `input` or `output`; `shape` is an object.
Anything else refuses `signature-malformed`, naming the field. Names are
restricted because they become template slots, lens markers, and JSON
member keys in every host language; a frontend that wants other names
maps them.

Shapes are JSON Schema, but the kernel **interprets only** these
keywords — every other keyword is carried untouched for codecs, lenses,
and request patches to read:

| shape | kernel meaning |
|---|---|
| `{"type": "string"}` | text, verbatim |
| `{"type": "integer"}` · `{"type": "number"}` · `{"type": "boolean"}` | kernel scalars (§7) |
| `{"enum": [...]}` (+ optional `type`) | membership; values are strings or integers |
| `{"type": "array", "items"?: shape}` · `{"type": "object", ...}` | structured: needs a codec (§7) |
| `{"media": "image" \| "document" \| ...}` | a message part, not text |
| **nullable** forms of a scalar/enum: `{"type": ["integer", "null"]}` or `{"anyOf": [S, {"type": "null"}]}` (either order) | the scalar, plus `null` (§7a) |
| anything else (`anyOf` of two real types, `$ref`, `{}`, no interpreted keyword) | **uninterpreted**: treated as structured — needs a codec (§7) |

The last row is the rule that makes the set closed: what the kernel does
not understand it never spells by itself. A frontend may lower any type
system's shape (a Union, a pydantic model with `$defs`, `Any`) and the
shape is carried whole; a codec, not the kernel, gives it text.

**Frontends.** Each language lowers its own signature syntax to this
form mechanically: Python type hints (`str`, `list[int]`,
`Literal[...]`, raw shape dicts), Go struct tags (`lmcc:"name,role=..."`),
JSON Schema documents, DSPy-style strings — all are frontends; none is
the contract. Foreign types resolve through the **host socket** or refuse
(`unmapped-type`, naming field and type). Host lowerings are
per-language code and are **never serialized**.

**The host socket** binds a native type once, per runtime:
`(shape, lower, lift?, codec?)` — its neutral shape, how a value lowers
to plain data and lifts back (both recurse through `list[X]`), and
optionally its **default codec**: the renderer that spells the type when
the entry binds none. Precedence at bake: the entry's per-field codec
binding wins; else the entry's **`@structured`** binding (a default for
every structured or uninterpreted shape — the way an adapter stays
signature-independent while still spelling `list[str]` or a model type);
else the type's registered default; else structured shapes refuse
(`no-codec`). Trade-off, stated: an entry-bound codec travels in the
artifact and is the byte-exact cross-runtime path; a host default is
per-runtime convenience code — two runtimes may legitimately spell the
same type differently unless the entry pins the codec.

A `shape` containing `"media"` (e.g. `{"media": "image"}`) is a media
shape: its value is a plain part-data dict and it renders as a message part
at its slot position, not as text.

## 2. The entry (the artifact)

See `schema/entry.schema.json`. An entry carries: `versions` (kernel +
per-vocabulary), `template`, `parse`, `strategies` (named refs or inline
data), `codecs` (named refs), `requires` (reserved: declared code sidecars).
The adapter is **signature-independent**: no entry ever contains a
signature. Loading is pure: names resolve only against the registry the
caller supplies; a data-only entry loads against an empty registry.

## 3. Template language

Three constructs; nothing else, ever:

- Slots `{path}`: `{instruction}`, `{format}` (the lens's reply
  skeleton, §4), `{input_field_name}`, `{var.attr}` inside loops.
  Attributes: `name`, `desc` ("" when absent), `schema` (codec's schema
  prose, else a mechanical hint), `role`, `value`. `instruction` and
  `format` are reserved and shadow same-named fields.
- Loops `{% for f in inputs %}…{% endfor %}` (also `outputs`). Loops
  iterate the **visible** fields of the baked plan, in signature order.
  In a **demo or history turn** (§8) an inputs loop iterates only the
  visible inputs the turn supplies, so an incomplete example renders
  its known fields and omits the rest; a bare slot with no value still
  refuses `missing-input` — omission is honest, invention is not.
- Escapes `{{` and `}}`. A bare brace anywhere else is `template-syntax`.

Bare slots may name **input** fields only; outputs are parsed, not
rendered. Message list entries are `{role, text}` or directives
`{"directive": "demos"|"history"}`.

## 4. The lens (parse spec)

A lens is one *document form* for the whole reply, with three faces on
one object — this triple use is normative for every lens:

- `split(text, field_names) → {name: raw}` reads the reply;
- `join(spelled) → text` writes gold outputs (demo assistant turns) in
  exactly the layout `split` reads;
- `format(placeholders) → text` writes the reply *skeleton* the prompt
  shows the model — the `{format}` template slot. Default (and the
  behavior of every 0.1 lens): `join` over the placeholder texts, so
  `{format}` renders e.g. `<answer>\nshort answer\n…` for `sections` and
  `{"answer": "short answer", …}` for a JSON lens.

Neither the skeleton nor the demos can ever drift from the parser.
The placeholder text per visible output field is one kernel rule:
`desc`, else the codec's schema prose, else the mechanical shape hint,
else `"..."`. The template still owns *whether* and *where* the skeleton
appears; the lens owns its spelling.

**Invertibility, stated exactly.** For the kernel lenses, `split(join(x))
== x` holds for every `x` whose spelled values are outer-whitespace-free
(§7a) and contain none of the lens's own markers. The second condition is
**enforced**: `join` refuses `value-collides` (naming the field and the
marker) when a spelled value contains any marker the lens reads — an
open/close/tail marker, or a derived anchor/close. The first condition is
a stated normalization, not a refusal: marker lenses trim what they read,
so outer whitespace of a value does not survive a round trip. Model
replies are read with the same rules; a reply that omits a close marker
*and* contains that marker inside the value is a double fault the reader
cannot detect — that is the one stated hole.

**The lens socket.** `parse.kind` names the lens. Two kinds are kernel
grammar — always available, never registered, never replaced: `derived`
and `sections`. Every other kind is vocabulary: it resolves through the registry
(`factory(parse_spec) → Lens`), refuses `unknown-parse-kind` when
unregistered (at load and at bake), and its version travels in the
artifact as `lens/<kind>` — exactly like codecs and strategies. A reply
that does not fit a lens's document form at all refuses
`lens-parse-error`; missing fields refuse `parse-missing-fields` with
recovered values in `.partial`. Routings run before the lens in either
case.

**Mode hooks.** A lens may declare `requires` (capability facts checked
at bake; `capability-missing` names the lens and the fact) and a `patch`
(request-side data computed from the visible output fields, merged into
the request patch; `control-conflict` on disagreement with strategies).
This is how a document form that is only honest under provider
enforcement — whole-object JSON — becomes a *mode*, never an
unconditional style.

**The primary kernel lens: `derived`** — the template read backwards.

```
{ "kind": "derived" }
```

The template must contain exactly one **output-pattern block**: an
outputs loop whose body contains `{f.value}`. That block is one
description read in three directions:

- **Prompt**: `{f.value}` renders as the field's placeholder (rule
  below) — the shape is *shown* to the model, never merely described.
- **Demos**: the block instantiated with gold values writes assistant
  turns.
- **Parser**: per visible output field, the literal text before the
  hole (instantiated) is its **anchor**; the literal after it is its
  close. Reading: anchors are found by their whitespace-stripped forms,
  first occurrence, any order; capture runs to the field's close, the
  next anchor, or end of text; result is whitespace-stripped. A close
  occurring more than once inside a field's capture region refuses
  `parse-ambiguous`, exactly like a repeated anchor.

Derivation refuses at bake (`not-lensable`, naming the defect) when:
there is no pattern block or more than one; a field's hole has no
literal before it; two fields' anchors coincide; a body nests loops or
holds two holes. **Ambiguity refuses at parse** (`parse-ambiguous`):
an anchor occurring more than once in a reply is never guessed at.
The placeholder rule (kernel-normative, one rule for `{f.value}` in
pattern blocks and for `{format}`): `desc`, else the codec's schema
prose, else the mechanical shape hint, else `"..."`.

**The declared kernel lens: `sections`.**

```
{ "kind": "sections", "open": "<{name}>", "close"?: str, "tail"?: str }
```

- **Reading**: each visible output field's marker is `open` with `{name}`
  substituted. First occurrence wins; a marker occurring more than once
  refuses `parse-ambiguous`; capture runs to the next marker, the
  `close` marker, the `tail`, or end of text; result is
  whitespace-stripped. The same rule guards every marker the lens
  reads: a `tail` occurring more than once in the reply, or a `close`
  occurring more than once inside a field's capture region, refuses
  `parse-ambiguous`.
- **Writing**: `marker \n value \n` per field (+ `close`), then `tail`.

Marker templates are data, so common marker dialects are spellings of
this one lens, not new lens kinds (pinned by corpus cases 20–21):

| dialect | spec |
|---|---|
| plain | `{"open": "<{name}>", "tail": "</done>"}` |
| XML-style | `{"open": "<{name}>", "close": "</{name}>"}` |
| DSPy chat adapter | `{"open": "[[ ## {name} ## ]]", "tail": "[[ ## completed ## ]]"}` |

JSON is **not** a marker dialect — it is a different document form, so it
is a different lens: `lens/json_object`, vocabulary provided by `lmcc_std`
(see `spec/vocab/lens-json_object.md`).

## 5. The extract algebra (kernel grammar)

Fixed set, versioned with the kernel — like template syntax, not like
vocabulary: `between {open, close}`, `pattern {regex}` (group 1 if
present), `line_prefixed {prefix}`, `parts {part}` (reads native response
parts by kind). Routings run **before** section splitting; a routing with
`strip: true` removes its matches from the visible text. `join` joins
the whitespace-stripped matches; `coerce` applies a registered coercion
by name.

Exact matching semantics, so two implementations cannot differ:

- `between`: scan left to right; find `open`, then the first `close`
  after it; the match is the whole span, the capture is the text
  between; continue after the `close`. An `open` with no later `close`
  ends the scan.
- `line_prefixed`: lines are split on `\n` (a trailing `\r` stays part
  of the line). A line beginning with `prefix` matches; the capture is
  the rest of the line; stripping removes the line's text and keeps its
  `\n`.
- `pattern`: the regex dialect is **RE2 syntax** — the portable core
  shared by Go, Python, JavaScript, Rust, and Java. Lookahead,
  lookbehind, backreferences, atomic groups, possessive quantifiers,
  and named groups (Python spells them `(?P<n>`, JavaScript `(?<n>`;
  neither is universal, and the algebra reads group 1 anyway) are
  outside the contract and refuse `entry-malformed` at construct and
  load. Matching is leftmost-first, non-overlapping, with `.` matching
  newlines. The capture is group 1 when the pattern has groups, else the
  whole match; stripping removes the whole match. Empty matches are
  discarded; a pattern that can match the empty string is outside the
  contract (implementations differ on how they advance past one).

## 6. Strategies

`Strategy = { predicate?: Predicate, requires: [fact],
fragments: {msg_role: text}, controls: {…}, routings: [Routing],
visible: bool }` — all data.

`Predicate = {"capability": fact} | {"not": P} | {"all": [P]} |
{"any": [P]}` — a boolean expression over the declared capability
facts (see `spec/vocab/capabilities.md`), so a strategy can say *"when
the model does NOT have native reasoning"*. `requires` is sugar for an
all-of.

At bake, per role in signature order: the predicate (and `requires`)
check against the declared capabilities dict (`capability-missing`
names role, strategy, and the failing fact or predicate); `@role` in routings and `{field}` in fragments bind to the role's
field; `visible: false` removes the field from loops and sections (its
routings must serve it — `entry-malformed` otherwise); fragments append to
the system message (created if absent); controls merge into the request
patch (`control-conflict` on disagreement). A role may bind one field
(`role-ambiguous`). A field both visible and routed is `field-double-covered`.

## 7. Codecs and kernel spelling

A codec spells one plain value: `render_schema(shape)`,
`render_value(value, shape)`, `parse_value(text, shape)`. The kernel itself
spells only scalars — strings verbatim, `integer`/`number`/`boolean` as
JSON literals, `enum` by membership. **Structured shapes (`object`/`array`)
with no codec bound refuse at bake** (`no-codec`). This line — scalars are
mechanics, everything else is vocabulary — is normative.

### 7a. Text rules (normative; every implementation, every vocabulary)

Byte-exact conformance across languages needs the primitive text
operations pinned. Vocabulary specs inherit these rules unless they say
otherwise.

- **Whitespace** — wherever this spec or a vocabulary spec says
  *strip*/*trim*, the set is exactly the six ASCII characters U+0009,
  U+000A, U+000B, U+000C, U+000D, U+0020. Unicode spaces (no-break
  space, ideographic space, …) are content and survive. Chosen because
  every language's built-in `strip`/`trim`/`TrimSpace` strips a
  *different* Unicode set; ASCII is the only set they all agree on.
- **Strings** — sequences of Unicode scalar values, never normalized;
  `\r\n` is not rewritten. Byte-exact means code-point-exact after JSON
  decoding.
- **Integer text** (reading) — after stripping, `-?[0-9]+`, ASCII digits
  only; anything else (`+5`, `1,000`, `1_000`, `٣`) refuses
  `value-invalid`. Writing: the decimal digits, `-` if negative.
  Implementations must carry at least the int64 range; the corpus never
  relies on wider integers.
- **Number text** (reading) — after stripping,
  `-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?`; `NaN`, `Infinity`, `.5`, `5.`
  refuse `value-invalid`. Values are IEEE-754 binary64.
- **Number spelling** (writing) — the ECMAScript `Number::toString`
  algorithm (ECMA-262 §6.1.6.1.20) over the shortest round-trip digits:
  `3` for `3.0`, `0.5`, `0.000001`, `1e-7`, `1e+21`,
  `123456789012345680000`. Chosen because it is the one number-to-text
  algorithm with a precise public specification and the widest
  deployment (every JSON.stringify; Go's encoding/json). Non-finite
  values refuse `value-invalid`.
- **Null** — for nullable shapes (§1) only: writing a missing value
  spells `null`; reading the stripped text `null` (exactly, lowercase)
  yields the null value; any other text reads through the underlying
  scalar rule. A nullable string therefore cannot carry the literal text
  `null` — stated, not hidden. Non-nullable shapes never accept `null`.
- **Booleans** — reading: after stripping and ASCII case-folding,
  `true`/`yes` → true, `false`/`no` → false, else `value-invalid`.
  Writing: `true` / `false`.
- **Enum** — reading: the stripped text equals the spelling of one
  member (integers by their decimal form); writing: that spelling.
- **Rounding** (for vocabulary that rounds) — round-half-to-even on the
  binary64 value: `round(x, n)` is `roundeven(x × 10ⁿ) / 10ⁿ` computed in
  binary64. This is IEEE's default and costs nothing in any language;
  it means `2.675` rounds to `2.67`, as its binary value dictates.

## 8. Bake, render, parse

```
bake(entry, signature, capabilities, registry) → Plan     (all refusals early)
render(plan, inputs, demos?, history?) → messages + patch  (pure)
parse(plan, response) → {field: value}                     (pure)
```

Render output messages are plain dicts, structurally lm15-shaped:
`{"role": r, "content": [{"kind": "text"|"image"|…, …}]}`. Adjacent text
parts merge; empty messages drop. `parse` accepts a bare string or a
response dict with a `content` part list. The kernel never performs I/O.

**Demos** are field dicts (inputs and outputs by name). Each renders as
the entry's user templates over the demo's inputs, then one assistant
turn written by the lens over the outputs the demo supplies; outputs
absent from the demo are omitted from that turn.

**History** items are either messages `{"role": "user"|"assistant",
"content": …}` (emitted verbatim) or **field turns** `{"fields": {…}}`
(rendered exactly like a demo, through the template and the lens). The
second form is how a conversation held as typed values — DSPy's
`History`, a tool loop's prior rounds — renders through the same
description as everything else, so history can never drift from the
format the model is asked to produce. Anything else refuses
`value-invalid`.

Bake checks input coverage: every visible input must be reachable from
some slot or input loop (`field-uncovered`, naming the fields).

## 9. Versioning

Kernel and each vocabulary entry version independently (semver; while
major = 0, minor is breaking). Entries declare what they need; loaders
refuse incompatibility naming both sides (`version-incompatible`). Unknown
names refuse (`unknown-codec` / `unknown-strategy` / `unknown-parse-kind`)
— never a silent skip.

## 10. Conformance

The corpus (`corpus/cases/*.json`) is the authority. An implementation is
conformant when the harness passes every case **byte-exactly** (rendered
text, parsed values, error codes). Case kinds: `render`, `parse`,
`roundtrip`, `refuse`; the case file format is `schema/case.schema.json`.

**The driver protocol** (language-neutral). The harness starts one
process (`runner.py --driver CMD`) and speaks JSON Lines on its
stdin/stdout: one case object per line in, one `{"ok": bool, "detail":
str}` per line out, in order, until EOF. The driver installs the packs a
case names in `vocab` into an otherwise empty registry, runs the case's
kind, and compares itself; the harness only counts. Values compare by
JSON equality: objects unordered, arrays ordered, numbers by value.

**Conformant implementations.** `python/` (the reference) and `go/`
(independent, stdlib only, `go/cmd/lmcc-conform`). Both run in `./check`.

## Deliberate gaps (0.1)

Streaming parse (same lens, incremental); the `requires` mechanism for
authored-code sidecars; tools/citations strategy vocabularies; per-strategy
media emission options. Each lands as its own versioned addition — never
silently. (The lens socket closed the "additional lens kinds" gap in
kernel 0.1: new document forms are now vocabulary, not kernel changes.)

# The a15 kernel — normative specification

**Version 0.1.0** (kernel). Status: reference-proven — the Python
implementation in `python/a15` and this document were built together; where
they disagree, fix the corpus first, then both.

**One sentence.** a15 owns typed signature ⇄ messages: how a declared I/O
contract renders into a prompt, and how the model's reply becomes typed
values again — as inspectable, shareable, versioned data.

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

Shapes are JSON Schema. Frontends lower their language's annotations to
shapes mechanically for the language's own constructs; foreign types resolve
through the **host socket** or refuse (`unmapped-type`, naming field and
type). Host lowerings are per-language code and are **never serialized**.

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

**The lens socket.** `parse.kind` names the lens. `sections` is kernel
grammar — always available, never registered, never replaced. Every other
kind is vocabulary: it resolves through the registry
(`factory(parse_spec) → Lens`), refuses `unknown-parse-kind` when
unregistered (at load and at bake), and its version travels in the
artifact as `lens/<kind>` — exactly like codecs and strategies. A reply
that does not fit a lens's document form at all refuses
`lens-parse-error`; missing fields refuse `parse-missing-fields` with
recovered values in `.partial`. Routings run before the lens in either
case.

**The kernel lens: `sections`.**

```
{ "kind": "sections", "open": "<{name}>", "close"?: str, "tail"?: str }
```

- **Reading**: each visible output field's marker is `open` with `{name}`
  substituted. First occurrence wins; capture runs to the next marker,
  the `close` marker, the `tail`, or end of text; result is
  whitespace-stripped.
- **Writing**: `marker \n value \n` per field (+ `close`), then `tail`.

Marker templates are data, so common marker dialects are spellings of
this one lens, not new lens kinds (pinned by corpus cases 20–21):

| dialect | spec |
|---|---|
| plain | `{"open": "<{name}>", "tail": "</done>"}` |
| XML-style | `{"open": "<{name}>", "close": "</{name}>"}` |
| DSPy chat adapter | `{"open": "[[ ## {name} ## ]]", "tail": "[[ ## completed ## ]]"}` |

JSON is **not** a marker dialect — it is a different document form, so it
is a different lens: `lens/json_object`, vocabulary provided by `a15_std`
(see `spec/vocab/lens-json_object.md`).

## 5. The extract algebra (kernel grammar)

Fixed set, versioned with the kernel — like template syntax, not like
vocabulary: `between {open, close}`, `pattern {regex}` (group 1 if
present), `line_prefixed {prefix}`, `parts {part}` (reads native response
parts by kind). Routings run **before** section splitting; a routing with
`strip: true` removes its matches from the visible text. `join` joins
stripped matches; `coerce` applies a registered coercion by name.

## 6. Strategies

`Strategy = { requires: [fact], fragments: {msg_role: text},
controls: {…}, routings: [Routing], visible: bool }` — all data.

At bake, per role in signature order: predicate facts check against the
declared capabilities dict (`capability-missing` names role, strategy,
fact); `@role` in routings and `{field}` in fragments bind to the role's
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
`roundtrip`, `refuse`. Non-Python implementations expose the same four
operations behind a JSON stdin/stdout driver: read one case object, write
`{"ok": bool, "detail": str}`.

## Deliberate gaps (0.1)

Streaming parse (same lens, incremental); the `requires` mechanism for
authored-code sidecars; tools/citations strategy vocabularies; per-strategy
media emission options. Each lands as its own versioned addition — never
silently. (The lens socket closed the "additional lens kinds" gap in
kernel 0.1: new document forms are now vocabulary, not kernel changes.)

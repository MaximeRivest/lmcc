# Reader: `json_object` — version 0.2.0

Provided by `lmcc_std`. The reply is **one JSON object**; each visible
output field is a member keyed by field name (the JSON-adapter style).

Spec: `{ "kind": "json_object", "probabilities"?: "off" | "if_available" | "required" }`.

**`probabilities`** (0.2.0) asks the provider to measure a distribution
over each judgment's declared answers: the reader's request settings
gain `config.probabilities` with that value (lm15 `ProbabilityPolicy`;
`required` makes a wire that cannot measure refuse before sending, lm15
MAP-14). Which fields are judgments is lm15's convention on the schema
this reader already sends: a boolean, a string enum, or an integer enum
`0..n-1`. The numbers come back on the reply's data part and are read by
the kernel into `plan.read(reply).probabilities` (kernel §3); the reader
itself is unchanged by them. Absent, nothing is asked. Any other key, or
another value, refuses `entry-malformed` (fix `edit-entry`, path
`reader`) at load — 0.1.0 accepted and ignored unknown keys, so an old
runtime would have read a 0.2.0 artifact without asking for what it
said. That is why this is a minor version: an artifact pinned at 0.1.0
refuses `version-incompatible` and moves by changing its pin.

**A data part reply.** On lm15 ≥ 1.0.1 a judgment answer arrives as an
lm15 `data` part, not text; the kernel reads it as its value's compact
JSON (kernel §3), so this reader reads it as it reads any document:
string members verbatim, others as their text in that spelling
(`{"score": 7.0}` feeds the integer rule `7`).

**This reader is a mode, not a template style.** A JSON object is a
meaning with many spellings, so the exchange form is only honest when
the provider enforces it. Therefore, normatively:

- baking **refuses** (`capability-missing`) unless the model declares
  `native_structured_output` (see `capabilities.md`);
- the reader patches the request with the enforcement control, built from
  the visible output fields at bake:

```json
{ "response_format": { "type": "json_schema", "schema": {
    "type": "object", "properties": { "<field>": <shape>, ... },
    "required": [ "<field>", ... ], "additionalProperties": false } } }
```

Without the capability, do not ask a model for JSON prose — use an
invertible marker template and put JSON *inside* typed fields via
formats.

A reader owns the *document form* only. Field values still go through the
field's format or the kernel scalar rules — this reader hands each of them a
raw string, exactly like `sections` does. Find rules (e.g. `<think>`
stripping) run before the reader, so transports compose unchanged.

## Reading (`split`)

1. **Locate the document.** Strip the text. If it starts with a markdown
   fence (```` ``` ````, any info string), the document is the fence body.
   Then: parse the whole document as strict JSON (`NaN`/`Infinity`,
   comments, trailing commas are not JSON); on failure, retry on the
   substring from the first `{` to the last `}`. If nothing parses, or the
   parsed value is not an object, refuse `reader-error`.
2. **Raw string per field.**
   - a string member → the decoded string, **verbatim**;
   - any other member → the member's **source text**, exactly as it
     appears in the document (outer whitespace trimmed) — no
     re-serialization, so digits, spacing, and member order are the
     model's own.
   So `{"rows": [1, 2]}` feeds a `json` format the text `[1, 2]` and
   `{"score": 9}` feeds the kernel integer rule `9` unchanged.
3. **Unknown members are ignored** (models add chatter keys). A field's
   key appearing **twice** in the document refuses `parse-ambiguous`
   (never last-wins). Missing fields refuse `parse-missing-fields`;
   `.partial` carries the recovered raw strings.

## Writing (`join` — assistant messages of earlier turns)

For each `(name, spelled_text)` in visible-output order:

- if `spelled_text` parses as JSON **and the result is not a string**,
  embed the parsed value (so a `json`-format field embeds as native JSON,
  and `9` / `true` embed as number / boolean);
- otherwise embed `spelled_text` as a JSON string.

The document is the object in the indented JSON layout of
`format-json.md` (two spaces), members in field order.

The non-string guard makes write∘read the identity on raw text: a spelled
string that happens to look like a quoted JSON string (e.g. `"hi"` with
the quotes) embeds as the string `"hi"` and reads back verbatim.

`format` (the `{format}` skeleton) is the kernel default: `join` over the
placeholder texts, so the prompt shows the object shape itself —
`{"answer": "short answer", "score": "(integer)"}` — pinned by corpus
case 28.
Whitespace inside embedded non-string values is **not** preserved
byte-for-byte across write∘read (write re-indents); formats must therefore
be whitespace-insensitive on read, which `format/json` is.

## Corpus

| case | pins |
|---|---|
| `22-std-json-reader-render` | `join` bytes: indent, embed rule, member order |
| `23-std-json-reader-parse` | fence stripping, native values, ignored members |
| `24-refuse-load-unknown-reader` | unregistered reader refuses at load |
| `25-refuse-json-reader-malformed` | non-JSON reply refuses `reader-error` |
| `26-roundtrip-json-reader` | `reader/json_object` version travels in the artifact |
| `28-std-json-reader-format` | `{format}` skeleton bytes (default `join` over placeholders) |
| `29-refuse-json-reader-needs-capability` | the mode gate: no declared `native_structured_output` refuses at bake |
| `46-refuse-json-reader-duplicate-key` | a field key appearing twice refuses `parse-ambiguous` |
| `202-parse-data-part-json-reader` | a data part reply: its value read as JSON, numbers by §7a, probabilities and `measured_by` |
| `206-render-json-reader-probabilities` | `probabilities` becomes `config.probabilities` beside `response_format` |
| `207-refuse-load-json-reader-option` | an unknown `probabilities` value refuses `entry-malformed` at load |

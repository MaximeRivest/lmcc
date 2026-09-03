# Lens: `json_object` — version 0.1.0

Provided by `lmcc_std`. The reply is **one JSON object**; each visible
output field is a member keyed by field name (the JSON-adapter style).

Spec: `{ "kind": "json_object" }`. No options in 0.1.0.

**This lens is a mode, not a template style.** A JSON object is a
meaning with many spellings, so the exchange form is only honest when
the provider enforces it. Therefore, normatively:

- baking **refuses** (`capability-missing`) unless the model declares
  `native_structured_output` (see `capabilities.md`);
- the lens patches the request with the enforcement control, built from
  the visible output fields at bake:

```json
{ "response_format": { "type": "json_schema", "schema": {
    "type": "object", "properties": { "<field>": <shape>, ... },
    "required": [ "<field>", ... ], "additionalProperties": false } } }
```

Without the capability, do not ask a model for JSON prose — use an
invertible marker template and put JSON *inside* typed fields via
codecs.

A lens owns the *document form* only. Field values still go through the
field's codec or the kernel scalar rules — this lens hands each of them a
raw string, exactly like `sections` does. Routings (e.g. `<think>`
stripping) run before the lens, so strategies compose unchanged.

## Reading (`split`)

1. **Locate the document.** Strip the text. If it starts with a markdown
   fence (```` ``` ````, any info string), the document is the fence body.
   Then: parse the whole document as strict JSON (`NaN`/`Infinity`,
   comments, trailing commas are not JSON); on failure, retry on the
   substring from the first `{` to the last `}`. If nothing parses, or the
   parsed value is not an object, refuse `lens-parse-error`.
2. **Raw string per field.**
   - a string member → the decoded string, **verbatim**;
   - any other member → the member's **source text**, exactly as it
     appears in the document (outer whitespace trimmed) — no
     re-serialization, so digits, spacing, and member order are the
     model's own.
   So `{"rows": [1, 2]}` feeds a `json` codec the text `[1, 2]` and
   `{"score": 9}` feeds the kernel integer rule `9` unchanged.
3. **Unknown members are ignored** (models add chatter keys). A field's
   key appearing **twice** in the document refuses `parse-ambiguous`
   (never last-wins). Missing fields refuse `parse-missing-fields`;
   `.partial` carries the recovered raw strings.

## Writing (`join` — demo assistant turns)

For each `(name, spelled_text)` in visible-output order:

- if `spelled_text` parses as JSON **and the result is not a string**,
  embed the parsed value (so a `json`-codec field embeds as native JSON,
  and `9` / `true` embed as number / boolean);
- otherwise embed `spelled_text` as a JSON string.

The document is the object in the indented JSON layout of
`codec-json.md` (two spaces), members in field order.

The non-string guard makes write∘read the identity on raw text: a spelled
string that happens to look like a quoted JSON string (e.g. `"hi"` with
the quotes) embeds as the string `"hi"` and reads back verbatim.

`format` (the `{format}` skeleton) is the kernel default: `join` over the
placeholder texts, so the prompt shows the object shape itself —
`{"answer": "short answer", "score": "(integer)"}` — pinned by corpus
case 28.
Whitespace inside embedded non-string values is **not** preserved
byte-for-byte across write∘read (write re-indents); codecs must therefore
be whitespace-insensitive on parse, which `codec/json` is.

## Corpus

| case | pins |
|---|---|
| `22-std-json-lens-render` | `join` bytes: indent, embed rule, member order |
| `23-std-json-lens-parse` | fence stripping, native values, ignored members |
| `24-refuse-load-unknown-lens` | unregistered lens refuses at load |
| `25-refuse-json-lens-malformed` | non-JSON reply refuses `lens-parse-error` |
| `26-roundtrip-json-lens` | `lens/json_object` version travels in the artifact |
| `28-std-json-lens-format` | `{format}` skeleton bytes (default `join` over placeholders) |
| `29-refuse-json-lens-needs-capability` | the mode gate: no declared `native_structured_output` refuses at bake |
| `46-refuse-json-lens-duplicate-key` | a field key appearing twice refuses `parse-ambiguous` |

# codec/json — 0.1.0

Spells any plain value as JSON.

**Options.** `indent`: integer or null (default 2).

**render_schema.** `"JSON matching this schema: "` + the shape serialized
as compact JSON (`ensure_ascii=false`).

**render_value.** Standard JSON serialization with the configured indent,
`ensure_ascii=false`.

**parse_value.** If the whole text (modulo surrounding whitespace) is a
single fenced code block (```` ``` ````, optional language tag), unwrap it
first. Then strict JSON parse. Any failure is a codec error → the kernel
wraps it as `codec-parse-error` naming the field.

**Corpus.** `16-std-json-codec.json`.

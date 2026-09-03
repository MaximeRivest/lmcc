# codec/json — 0.1.0

Spells any plain value as JSON.

**Options.** `indent`: integer or null (default 2).

**JSON writing (normative for this codec and `lens/json_object`).**
Strict RFC 8259 text; strings escaped minimally (`"`, `\`, and
U+0000–U+001F — the short forms `\n \r \t \b \f` where they exist, else
`\u00XX`), all other characters emitted raw (no `\uXXXX` for non-ASCII);
numbers by the kernel number spelling (`kernel.md` §7a); object members
in the value's own order. Two layouts:

- *indented* (`indent` = n): members and items one per line, nested
  blocks indented by n spaces, `"key": value`, items separated by `,` +
  newline; empty containers are `{}` / `[]`.
- *single-line* (`indent` = null): `, ` between members/items and `: `
  after keys — one line, spaces kept.

Both layouts coincide with ECMAScript `JSON.stringify` except that the
single-line form keeps its spaces (pinned by corpus case 28).

**render_schema.** `"JSON matching this schema: "` + the shape in the
single-line layout.

**render_value.** The value in the indented layout (or single-line when
`indent` is null).

**parse_value.** If the whole text (modulo surrounding whitespace) is a
single fenced code block (```` ``` ````, optional language tag), unwrap it
first. Then strict JSON parse: `NaN`/`Infinity`, trailing commas,
comments, and duplicate object members are errors. Any failure is a codec
error → the kernel wraps it as `codec-parse-error` naming the field.

**Corpus.** `16-std-json-codec.json`, `45-std-json-number-spelling.json`.

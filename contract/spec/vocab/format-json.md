# format/json — 0.1.0

Spells any plain value as JSON.

**Options.** `indent`: integer or null (default 2).

**Accepts** `*` — any shape; `read` receives the span's text.

**JSON writing (normative for this format and `lens/json_object`).**
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

**describe.** `"JSON matching this schema: "` + the shape in the
single-line layout.

**write.** The value in the indented layout (or single-line when
`indent` is null).

**read.** If the whole text (modulo surrounding whitespace) is a
single fenced code block (```` ``` ````, optional language tag), unwrap it
first. Then strict JSON parse: `NaN`/`Infinity`, trailing commas,
comments, and duplicate object members are errors. Any failure is a format
error → the kernel wraps it as `format-read-error` naming the field.

**Corpus.** `16-std-json-format.json`, `45-std-json-number-spelling.json`,
`48`–`49` (the `*` default), `55` (by type name).

**Python runtime note.** The Python `json` format also lowers dataclasses,
pydantic models and Enums on write and lifts them back through the
field's annotation on read — a language-home convenience (kernel §5,
step 3 is per runtime); the artifact never carries it.

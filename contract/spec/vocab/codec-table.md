# codec/table — 0.1.0

Spells a list of flat objects as a delimiter table. Exists because small
models often nail rows where they fumble JSON — a token-lean spelling worth
sharing, with its ugly cases legislated here so implementations cannot
drift.

**Options.** `columns`: list of property names, required — order is the
column order. `delimiter`: default `"|"`. `escape`: default `"\\"`.
`null`: the cell text meaning "no value", default `""`.

**render_schema.** `| col1 | col2 |  (one row per item)` using the
configured delimiter.

**render_value.** One line per item: `| cell | cell |` — a single space
after each opening and around each inner delimiter. Cell text: `null` →
the `null` string; strings verbatim; numbers and booleans by the kernel
spelling rules (`kernel.md` §7a: `3`, `0.5`, `true`); nested containers
are a codec error (→ `codec-render-error`). Then the escape character is
doubled and the delimiter prefixed with the escape.

**parse_value.** Consider only lines that (after trimming) start with the
delimiter. Split on unescaped delimiters; unescape; trim each cell. A row
whose cells equal `columns` is a header and is skipped. A row with the
wrong cell count is a codec error (→ `codec-parse-error`, naming the
field). A cell equal to `null` reads as null. Other cells read through
the item schema's property shape with the kernel scalar rules
(`integer`, `number`, `boolean`, `enum`; default string) — a cell that
fails its rule is a codec error, never a silent default.

**Corpus.** `17-std-table-codec-demo-lens.json` (render incl. escaping via
the demo lens), `18-std-table-codec-parse.json` (header skip + coercion),
`45-std-json-number-spelling.json` (number and boolean cells).

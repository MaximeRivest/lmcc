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
after each opening and around each inner delimiter. Cell text: `None` →
the `null` string; otherwise the string form of the value with the escape
character doubled, then the delimiter prefixed with the escape.

**parse_value.** Consider only lines that (after trimming) start with the
delimiter. Split on unescaped delimiters; unescape; trim each cell. A row
whose cells equal `columns` is a header and is skipped. A row with the
wrong cell count is a codec error (→ `codec-parse-error`, naming the
field). A cell equal to `null` reads as None. Other cells coerce through
the item schema's property type (`integer`, `number`, `boolean`; default
string).

**Corpus.** `17-std-table-codec-demo-lens.json` (render incl. escaping via
the demo lens), `18-std-table-codec-parse.json` (header skip + coercion).

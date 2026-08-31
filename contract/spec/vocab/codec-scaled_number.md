# codec/scaled_number — 0.1.0

Spells a number at a friendlier scale — canonically 0.78 ⇄ `78%`. Exists
because models write percentages more reliably than unit-interval decimals.

**Options.** `scale`: default 1. `suffix`: default `""`. `round`: decimal
places, default null (no rounding); `round: 0` renders an integer.

**render_schema.** `a number like 83%` (the example uses 83 when scale is
100, else 0.83, with the suffix).

**render_value.** `value * scale`, rounded per `round`, then the suffix.

**parse_value.** Trim; strip the suffix if present; float-parse; divide by
`scale`. Failure → `codec-parse-error` naming the field.

**Corpus.** `19-std-scaled-number.json`.

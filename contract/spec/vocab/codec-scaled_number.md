# codec/scaled_number — 0.1.0

Spells a number at a friendlier scale — canonically 0.78 ⇄ `78%`. Exists
because models write percentages more reliably than unit-interval decimals.

**Options.** `scale`: default 1. `suffix`: default `""`. `round`: decimal
places, default null (no rounding).

**render_schema.** `a number like 83%` (the example uses 83 when scale is
100, else 0.83, with the suffix).

**render_value.** `value × scale` in binary64, rounded per `round` with
the kernel rounding rule (`kernel.md` §7a, half-to-even), spelled with
the kernel number spelling (so `78.0` is `78`, and `round: 0` needs no
special case), then the suffix.

**parse_value.** Trim; strip the suffix if present; read with the kernel
number grammar; divide by `scale`. Failure → `codec-parse-error` naming
the field.

**Corpus.** `19-std-scaled-number.json`, `45-std-json-number-spelling.json`.

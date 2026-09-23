# format/scaled_number — 0.2.0

Spells a number at a friendlier scale — canonically 0.78 ⇄ `78%`. Exists
because models write percentages more reliably than unit-interval decimals.

**Accepts** `number`, `integer`.

**Options.** `scale`: default 1. `suffix`: default `""`. `round`: decimal
places, default null (no rounding).

**describe.** `a number like 83%` (the example uses 83 when scale is
100, else 0.83, with the suffix).

**write.** `value × scale` in binary64, rounded per `round` with
the kernel rounding rule (`kernel.md` §7a, half-to-even), spelled with
the kernel number spelling (so `78.0` is `78`, and `round: 0` needs no
special case), then the suffix.

**read.** Trim; strip the suffix if present; read with the kernel
number grammar; divide by `scale`. Failure → `format-read-error` naming
the field.

**Round trip.** With `round`, `round_trip` is **false**: `0.784` writes
`78%` and reads back `0.78`, so a rounded output cannot be written into
a past turn (`turn-not-renderable`); as an input it renders normally
(0.2.0, plan 09 G4). Without `round` it declares true; scaling in
binary64 can still move the last digit (`0.07 × 100 = 7.000000000000001`),
a stated limit of this format, not of the kernel.

**Corpus.** `19-std-scaled-number.json`, `45-std-json-number-spelling.json`.

# The corpus

These cases are the authority. If an implementation disagrees with a case,
the implementation is wrong; changing a case is a contract change and gets
reviewed like one.

**Provenance honesty.** The `expect` blocks of render/parse/roundtrip cases
were seeded once from the Python reference (`tools/bootstrap.py`) at
contract creation, then human-reviewed. From that moment the direction of
authority flipped: the files rule, the reference obeys. Do not re-run the
seeder over behavior changes — that would silently re-bless drift.
Cases added after creation (20+) are authored by hand first; the
implementation is then made to pass them — authority never flips back.
Cases 35–46 were authored while writing the Go implementation: each one
pins a rule the spec had left to the host language (number spelling,
whitespace, regex dialect, marker collisions, signature validity).

**Case format.** One JSON object per file:

- `kind`: `render` | `parse` | `roundtrip` | `refuse`
- `vocab`: packs the harness must install (e.g. `["std"]`); absent means
  the case must pass against an **empty registry**
- `entry`, `signature`, `capabilities`, `inputs`, `demos`, `history`,
  `response`: the scenario
- `expect`: exact `messages`+`patch`, exact `values`, exact `entry`, or
  `{code, at}` for refusals

Comparison is deep equality — byte-exact text, exact numbers, exact error
codes. Objects compare unordered, arrays ordered, numbers by value.

**Running another implementation.** `harness/runner.py --driver CMD`
starts CMD once and streams cases as JSON Lines (`spec/kernel.md` §10);
`go/cmd/lmcc-conform` is the Go driver. The case format itself is
`schema/case.schema.json`.

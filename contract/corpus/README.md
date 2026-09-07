# The corpus

**D-31 migration boundary.** These cases pin the existing 0.2 contract.
Passing its regex cases does not prove full RE2 equivalence. Future execution
extensions need separately declared requirements and scoped conformance cases
(see `../spec/portability.md`). Do not rewrite legacy expectations or count
unsupported extensions as passes.

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

**Second seeding (kernel 0.2, plan 08).** When the contract moved to the
v3 design, cases 01–54 were converted by a script (template list,
`codecs` → `formats` by structural key, the routing form, refusal codes)
and every `sections` template became a derived pattern. For the eleven
render cases whose bytes changed, the new expectation was regenerated
from the reference and each diff was reviewed by hand: every change is
the pattern loop rendering placeholders where a description loop used
to render `name  desc`. Cases 55–73 were hand-authored for what v3 adds.
Authority is frozen again from this point.

**Fix hints (plan 06).** Every refuse case that fires before render
gained an `expect.fix` (the exact payload both kernels must emit,
`schema/fix.schema.json`), authored by hand and reviewed against the
reference — one guess (case 56's field) was corrected by the harness
diff, in the reference's favor: the first offender in signature order.
Cases 74–79 were hand-authored to pin the actions no earlier case
reached (`edit-signature` with a role, `edit-entry` on `.visible` and
`.controls`, `install-vocabulary` for a strategy, `satisfy-predicate`,
`edit-template` for syntax).

**Anchor inside anchor (D-27).** Case 80 was hand-authored while making
streaming linear: a later anchor beginning inside an earlier anchor's
occurrence yields an empty capture (§4). It exposed a Go batch panic on
the negative slice, fixed to match; the reference already read it so.

**Vocabulary references (D-28).** Cases 81–82 were hand-authored after a
pack-built strategy with empty `between` delimiters hung batch parse in
both kernels: a reference's factory now runs at load, its failure is
`entry-malformed` at the reference's path, and a strategy it returns is
validated like inline data. Case 82 pins the same rule for a format
whose options the pack rejects.

**Streaming refinement (plan 01).** No streaming fixtures duplicate the
parse corpus. Both harness drivers replay every parse response whole,
one Unicode scalar at a time, at every scalar split, and at every split
inside a text-bearing part. They require the same typed values and the
same concatenated field deltas for every chunking. Parse-refusal cases
must finish with the complete same refusal (`code`, `hint`, `fix`, and
`partial`) as batch. Network byte decoding stays outside lmcc; clients
feed decoded text or part deltas.

**Case format.** One JSON object per file:

- `kind`: `render` | `parse` | `roundtrip` | `refuse` | `plan` (skeleton + prefix); every `parse` and refuse-at-parse case also drives streaming automatically
- `requires`: placements the case needs (`udf:python`); a driver without
  them answers `unclaimed` and the harness counts those apart
- `vocab`: packs the harness must install (e.g. `["std"]`); absent means
  the case must pass against an **empty registry**
- `entry`, `signature`, `capabilities`, `inputs`, `demos`, `history`,
  `response`: the scenario
- `expect`: exact `messages`+`patch`, exact `values`, exact `entry`, or
  `{code, fix?, at}` for refusals (`fix` is asserted exactly when present;
  every pre-render refuse case carries one)

Comparison is deep equality — byte-exact text, exact numbers, exact error
codes. Objects compare unordered, arrays ordered, numbers by value.

**Running another implementation.** `harness/runner.py --driver CMD`
starts CMD once and streams cases as JSON Lines (`spec/kernel.md` §10);
`go/cmd/lmcc-conform` is the Go driver. The case format itself is
`schema/case.schema.json`.

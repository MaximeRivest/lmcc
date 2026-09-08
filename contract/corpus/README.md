# The corpus

**Kernel 0.4 (D-35).** The wire is lm15: every render expectation is
`expect.request`, an lm15 request minus its model; responses are lm15
messages; parts carry `type`. The bytes of 01–95 were re-spelled by
script and reviewed through both harness drivers — no expectation
changed meaning; two were hand-edited to be *valid lm15* (66's tool item
became a `function` tool; 67's placement path a real control path).
Cases 96–98 pin what 0.4 adds: a control outside the pinned lm15 fields
refuses (96), a `developer` message renders and `system` folds (97), a
`system` message that does not lead refuses (98). Case 99 (D-36) pins
`config.stop` from the skeleton when `stop_sequences` is declared.

**Tools and citations (kernel 0.5, D-37).** Cases 100–112 were
hand-authored from `spec/vocab/strategy-tools.md` and
`strategy-citations.md`: native tools render (100), a call turn (101, the
answer is omitted, never refused), an answer turn (102, empty calls), lm15
history verbatim (103), the capability refusal (104); fenced tools render
with the catalog spelled `via` (105), a fenced call with an assigned id
(106), history spelled through `turns` (107), the probe refusing a
drifted spelling (108); inline citations render and parse (109–110),
native citations parse and render (111–112). Cases 113–114 pin the
whole-reply pattern (a single bare slot with no anchor, kernel §4),
which search-mode replies made necessary. Case 66's placement now
appends after a blank line, like a fragment — one deliberate byte change.

**Kernel 0.3 (D-33).** Every case pinned `kernel: 0.3.0`; the migration
changed no expectation's meaning. A case declares everything beyond the
core it needs in `requires` (`udf:python`, `pattern/legacy-re2`); drivers
bind exactly that, so a forgotten requirement refuses instead of passing,
and a driver lacking one answers `unclaimed` — counted apart, never a pass
(`../spec/portability.md`).

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

**Batch 1 safety fixes (plan 09).** Cases 83–90 remain active.
Cases 83–85 pin adjacent-part coalescing, kind changes, and empty text.
Cases 86–88 pin malformed-part refusals; 89–90 pin number overflow.
The experimental regex cases 91–95 were withdrawn with the custom matcher
before that branch merged; they never reached `master` and their numbers
are reused below. The withdrawn bytes remain on `batch/01` history and in
the review archive as candidate tests, not requirements.
The drivers retain malformed parts during replay and preserve part-list
context for bare strings. D-30 records the original experiment; D-32
records its withdrawal without discarding the safety fixes.

**Declared extensions (D-33, plan 10).** Cases 40 and 42 were migrated
by hand to declare `pattern/legacy-re2` 0.1.0 and to `requires` it; their
expectations are byte-identical. Cases 91–95 were hand-authored for the
mechanism of kernel §10: an undeclared `pattern` (91, fix names the
routing's path and the family to declare), a declared extension on a
core-only host (92, `bind-extension`), a version the host does not
provide (93, reusing `match-version` with the extension as `entry`), two
contracts of one family (94, `entry-malformed` at `extensions`, refused
before support is checked), and a roundtrip that preserves an unused
declaration verbatim (95).

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
- `requires`: everything beyond the core the case needs — UDF placements
  (`udf:python`) and extensions (`pattern/legacy-re2`); a driver binds
  exactly these and answers `unclaimed` for any it lacks; the harness
  counts those apart
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

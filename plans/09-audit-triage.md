# Plan 09 — audit triage: 114 findings from the clean-room TypeScript implementation and the docs review

**Current scope:** the custom regex engine and experimental cases 91–95
have been withdrawn. The mandatory-regex implementation instruction below
is historical, not current authority. The revised shared-core and declared-
extension design is being documented on master. Keep cases 83–90 and the
three non-regex safety fixes separate from any future backend choice.


## Motivation

The clean-room audit tests whether the published contract supports an independent implementation without reading another kernel.
It supplied 107 findings. The documentation review supplied seven more.
This queue keeps every input ID and merges duplicate work without merging away evidence.

The baseline is green: Python 82 passed; Go 76 passed and six unclaimed; `./check` reports ALL GREEN.
The 114 findings divide into **Bin 1: 20; Bin 2: 49; Bin 3: 32; Bin 4: 11; Bin 0: 2**.
The probes expose untested kernel differences, missing prose, and policy choices; green conformance does not settle those gaps.

| Bin | Input IDs | Merged work items |
|---|---:|---:|
| 4 — decision | 11 | 8 |
| 1 — defect | 20 | 15 |
| 2 — hole | 49 | 41 |
| 3 — accept | 32 | 24 |
| 0 — reject | 2 | 2 |

## Design and evidence rules

Follow spec → hand-authored corpus → both kernels → decision log.
This review changes no contract, corpus, kernel, or existing plan. It makes no commits.
Counts count input IDs, not merged rows. Each ID has exactly one bin below.
A policy gate may refer to a defect without moving that defect into a second bin.

`kernel.md`, `errors.md`, and `decisions.md` mean files under `contract/spec/`.
Bare Python filenames mean `python/lmcc/`; Go paths are explicit.
Case numbers mean `contract/corpus/cases/NN-*.json`, whose bytes remain authoritative.
`P<n>:name` means scenario `name` in `/tmp/probe/s<n>.py`, with output in `/tmp/probe/result<n>.log`.
`P3b` is the corrected rerun of selected `s3.py` scenarios in `result3b.log`.
Direct host probes live in `/tmp/probe/evidence.py`, `/tmp/probe/direct.go`, and `direct-results.log`.
The original reusable probes remain in `/home/maxime/Projects/.pi-worktrees/lmcc-triage-probe/`.

Driver mismatch output uses intentionally false expectations to reveal actual values; `ok: false` alone is not a defect.
Code agreement is evidence for a hole, not permission to generate corpus expectations from that code.
All proposed case bytes still need author review. Case ranges below reserve work, not ratified behavior.

## Bin 4 — maintainer decisions first

**Ratified 2026-09-07, all as recommended (D-29).**

### E7, DOC-1 — Does a dot match a newline?

Python and Go capture `a\nb`; TS finds no match (`P3b:E7-dotall`).
Option A: keep DOTALL. Existing reference behavior stays stable; greedy patterns can consume later sections.
Option B: exclude LF. RE2 defaults become familiar; existing Python and Go artifacts can change meaning.
Recommend A, with explicit flags and LF, CR, U+2028, and U+2029 cases.
Reject B unless a version change pays for changed extraction. Do not silently narrow the dialect.

### C1, B3 — Separate UDF admission from placement?

Without `requires`, case 60 gives `format-untrusted` in Python and Go; TS gives `udf-tampered` (`P1:C1`).
Option A: keep placement-first refusal. Non-placing hosts need no source-admission machinery; neutral hash tests remain unavailable.
Option B: verify hashes and declared facts first. More runtimes can test them; refusal precedence changes.
Recommend A for this queue. Specify hash bytes now; propose B as a versioned change.
B3's defaults also need ratification: Python defaults `accepts` to `['*']`, not `[key]` (`formats.py:265`).
Go cannot test materialized defaults. Add a non-placing facts API before claiming cross-runtime agreement.
Reject B as a mere removal of `requires`: cases 60, 61, and 68 would not reach their stated refusals.

### D5 — What happens to non-boolean capability values?

`instruct: 1` passes in Python and refuses in Go and TS (`P1:D5`).
The case schema forbids it (`contract/schema/case.schema.json:39–43`). This is outside the admitted case domain.
Option A: require booleans at the caller boundary. This preserves the schema but leaves host misuse outside conformance.
Option B: reject or coerce such values in every kernel. This adds a new boundary rule and possibly a refusal code.
Recommend A now; never call Python truthiness a portable fact declaration.
A maintainer must choose the invalid-input code and stage before B can become a corpus refusal.

### E5 — How large is the portable integer domain?

Python and TS write `10^21` as digits; Go refuses. Go also refuses `9223372036854775808` (`P3:E5`, `P12:E5-read`).
Section 7a requires at least int64, not unbounded integers. These probes exceed that minimum.
Option A: guarantee int64 only. Hosts may extend it; portable callers must stay inside the intersection.
Option B: require arbitrary precision. Byte portability improves; Go needs new number storage and operations.
Recommend A and pin both int64 endpoints. Keep decimal spelling mandatory for accepted integers.
Reject B as a clarification: it changes the minimum host requirement. Decide extension reporting before testing larger integers.

### E10 — Where must lone surrogates refuse?

Astral text survives all three runtimes (`P3b:E10`); lone-surrogate input does not (`P12:E10-sur`).
Python keeps the surrogate; the JSON driver paths produce U+FFFD. Section 7a permits only Unicode scalars.
Option A: reject invalid scalar data at transport decoding. This keeps the kernel domain small but excludes host misuse.
Option B: validate every kernel text boundary. This gives uniform errors but adds scans and stage rules.
Recommend A for transport, plus explicit host preconditions. Do not accept replacement as byte-exact parsing.
A direct host-API matrix, without JSON encoding, must settle B. The current probe cannot locate every replacement step.

### F25 — Validate history parts or keep them verbatim?

Python and Go retain a history part without `kind`; TS refuses `value-invalid` (`P7:F25`).
Section 3 calls history messages verbatim; it also requires lm15-shaped messages.
Option A: trust the history boundary. This preserves bytes but can carry invalid wire data.
Option B: validate first, then preserve valid parts. This catches bad history but adds rejection behavior.
Recommend B with `value-invalid` at render, without normalization of valid messages.
Reject A for new callers unless the API states an external validator precondition. Case 47 pins only valid history.

### H2, H3 — Who owns stream event timing?

D-27 and kernel §8 compare timing with the reference trace, not hand-authored fixtures.
Current traces start some fields before their first delta and interleave EOF work by field (`P5:G17`, `P5:G18`).
Option A: keep the reference oracle. Maintenance stays small; code gains authority over emission timing.
Option B: author event fixtures or a separate timing oracle. Corpus authority improves; fixtures or logic can duplicate rules.
Recommend B with small representative traces, plus existing all-split refinement tests.
Keep this unresolved for the maintainer. D-02 and D-27 state different authority costs.
The TS baseline reports zero compared traces. Its 74 passes do not prove timing agreement.

### DOC-7 — How can the harness install third-party packs?

The reference installs only `std`; Go rejects unknown pack names (`runner.py:48–53`, `go/conform/conform.go:87–99`).
Option A: keep pack-specific external drivers. This avoids a loading hook but needs a compatible reference for trace checks.
Option B: add an explicit pack-loader map. This supports neutral pack cases but adds trusted host configuration.
Recommend B as harness work, not artifact privilege. Unknown packs must never be silently ignored.
Reject automatic import by arbitrary artifact name. The maintainer must define the trusted loader interface first.

### R1 — repair gate for A4 (classification remains Bin 1)

Option A: coalesce adjacent same-kind text-bearing parts in batch before routing, as stream already does.
This preserves refinement and avoids provider part boundaries; it changes existing batch newline insertion.
Option B: preserve batch logical parts and add an explicit boundary signal to streaming.
This retains batch values but changes the feed protocol and every-split replay rules.
Recommend A, with explicit metadata handling and kind-change tests. Reject B without a real caller need for adjacent logical boundaries.
D-26 claimed unchanged old parse semantics; A requires a deliberate compatibility decision, not an invisible patch.

### R2 — repair gate for A6 (classification remains Bin 1)

Option A: open fact names and correct D-06's rule through a new decision entry.
This preserves case 78 and current kernels, but reduces vocabulary control.
Option B: retain closed names, deliberately repair case 78, and reject unknown names before bind.
This retains portable vocabulary control but changes accepted artifacts and requires a refusal rule.
Recommend B because D-06 explicitly chose portability over arbitrary facts. Reject A unless the maintainer now rejects that cost.
Corpus authority requires deliberate review of case 78; neither this review nor current code can overrule it.

## Bin 1 — contract defects

### A4, D4, H1, H6 — Batch and stream disagree on adjacent parts

**Contradiction.** The same part list returns different values, against kernel §8's refinement law.
**Evidence.** `P14:A4` and `direct-results.log`: Python and Go batch return `reasoning: "fo\nur"`; stream returns `"four"`.
**Wrong side.** The combined batch/stream contract is inconsistent; neither normalization can satisfy both current sentences.
**Case.** Parse adjacent thinking parts `fo`, `ur`; replay whole, scalar-split, empty-text, and kind-change variants.
**Spec sentence.** “Define one logical-part normalization for batch and stream before routing.” Ratify the rule in gate R1 above.
**Kernels.** Python and Go; TS already coalesces batch. Do not copy TS expectations before R1.
**Reserved cases:** 83–85.

### B5 — Malformed batch parts escape the refusal contract

**Contradiction.** Batch accepts or crashes on parts that `feed` must refuse as malformed under kernel §8.
**Evidence.** `P2:B5-textint` raises Python `TypeError`; Go reports `parse-missing-fields`; TS reports `response-malformed`.
`P2:B5-str` raises Python `AttributeError`; `P1:B5` silently ignores a missing kind in both reference kernels.
**Wrong side.** Batch normalization lacks the stream boundary checks; Python must not leak host errors for response data.
**Case.** Refuse at parse for a missing/string-invalid kind, a scalar part, and non-string text. Replay malformed deltas safely.
**Spec sentence.** “Each response part has a string kind; text, when present, is a string; otherwise refuse response-malformed.”
**Kernels.** Python and Go; TS already checks these shapes. Adjust malformed replay setup in both harness drivers.
**Reserved cases:** 86–88.

### E3 — Number overflow differs across kernels

**Contradiction.** Grammar-valid `1e400` becomes Infinity in Python but a refusal in Go.
**Evidence.** `P3:E3`: Python `values.n = Infinity`; Go and TS `parse-value`; `python/lmcc/core.py:97–103` uses unchecked `float`.
**Wrong side.** Python cannot return that result as portable JSON data. The spec only states the non-finite write refusal clearly.
**Case.** Refuse at parse for positive and negative overflow; add a finite boundary twin.
**Spec sentence.** “A number read whose binary64 result is not finite refuses parse-value.”
**Kernels.** Fix Python; pin and test Go. Test format wrappers separately because they use `format-read-error`.
**Reserved cases:** 89–90.

### E6 — RE2 admission and character classes differ

**Contradiction.** D-14 requires RE2 without named groups; host regex behavior narrows and broadens that language.
**Evidence.** `P4:RX-w`: Python captures `héllo`; Go and TS capture `h`. `P3:E6-Q`: Python refuses `\Q`, Go accepts.
`P3:E6-posix` gives different parses. `P4:RX-pL` shows all three falsely treating `\p{L}+` as a possessive quantifier.
**Wrong side.** Python's host semantics and the shared string-based lint violate RE2. TS's extra exclusions also violate D-14.
**Case.** Parse ASCII classes versus Unicode letters, POSIX classes, quoted literals, and inline flags; refuse forbidden constructs.
**Spec sentence.** “Admission and matching follow RE2 semantics, not the host regex engine; list explicit exceptions only.”
**Kernels.** Python and Go lint; Python matching; TS admission and matching. Keep the dot-policy gate separate.
**Reserved cases:** 91–95.

### F19 — Prefix returns an input-dependent message

**Contradiction.** `prefix()` returns a system message which an input placement later changes, against kernel §3's message-prefix law.
**Evidence.** `P13:F19-place` returns the system message without context; case 66 and `P14:F19-render` append `Ann is 41.`.
**Wrong side.** Python and Go stop only on template input slots, not input placements (`python/lmcc/plan.py:261–273`).
**Case.** Plan from case 66 must return `prefix: []`; a non-system placement must stop before its first target message.
**Spec sentence.** “A message written by an input placement depends on inputs and ends the cache-stable message prefix.”
**Kernels.** Python and Go; TS handles this dependency. Also pin vocabulary `skeleton: {}` separately; it is an omission, not this defect.
**Reserved cases:** 96–98.

### F14 — Placed inputs still render in explicit slots

**Contradiction.** A placed input also renders in its bare slot, although kernel §6 says placement acts instead of a slot.
**Evidence.** `P15:F14-bare`: Python and Go write `Ann is 41.` in both system placement and user slot; TS omits the slot value.
**Wrong side.** Python and Go remove placed inputs from loops, but not explicit slots. Case 66 did not exercise that combination.
**Case.** Render case 66 with `{q} {ctx}`; preserve placement and omit the placed input's slot value.
**Spec sentence.** “A placed input is absent from input loops and contributes nothing to explicit input slots.”
**Kernels.** Python and Go template environments; test TS. This removes duplicate wire content from existing explicit-slot templates.
**Reserved cases:** 99.

### G15 — A placement silently overwrites a control

**Contradiction.** Two request-control writers disagree, but the placement silently wins instead of refusing `control-conflict`.
**Evidence.** `P10:G15`: Python and Go return a tools part list over the declared control; TS refuses at bind.
`python/lmcc/plan.py:201–209` calls `_set_path` during render without a conflict gate.
**Wrong side.** Python and Go lose declared request data. `errors.md:27` requires refusal when request controls disagree.
**Case.** Refuse at bind for a placement and static control sharing a path; cover nested paths and reversed signature order.
**Spec sentence.** “A dynamic control placement cannot share an overlapping path with another control writer; refuse at bind.”
**Kernels.** Python and Go; test TS against the selected overlap rule. Reject all overlap before values exist, not during render.
**Reserved cases:** 100–101.

### G4 — A rounded format falsely declares lossless round trips

**Contradiction.** `round_trip` promises identity, but rounded scaled numbers remain demo-renderable in both reference packs.
**Evidence.** `P9:G4` writes a rounded demo; both packs inherit `round_trip = true` (`python/lmcc/formats.py:39`, `go/lmccstd/formats.go:24`).
`P15:G4-loss-write` and `P14:G4-loss` map `0.784` through `78%` to `0.78`; kernel §5 defines this as lossy. TS refuses the rounded demo.
**Wrong side.** The Python and Go pack declarations are false, not the demo gate.
**Case.** Refuse a rounded demo with `demo-not-renderable`; render the same value as an ordinary input and parse its rounded text.
**Spec sentence.** “scaled_number with rounding declares round_trip false; ordinary inputs remain renderable.”
**Kernels.** Python and Go standard packs. Audit unrounded binary64 scaling too; rounding-off alone does not prove exact identity.
**Reserved cases:** 102–103.

### G25 — Media defaults rewrite a wrong kind

**Contradiction.** A media value with kind audio becomes image, instead of passing through or refusing invalid media data.
**Evidence.** `P11:G25`: Python and Go rewrite the kind; TS refuses `value-invalid`. `python/lmcc/formats.py:127–140` also strips kind on read.
**Wrong side.** Silent kind replacement guesses the value's meaning. Kernel §7b says a part passes through and reads the first matching part.
**Case.** Refuse an explicit wrong kind; parse a matching part and pin whether kind survives. Retain case 66's missing-kind support deliberately.
**Spec sentence.** “Supply the field kind when absent; refuse a conflicting kind; reading returns the matching part as a whole.”
**Kernels.** Python and Go; test TS. The read rule changes current return values, so ratify that compatibility cost.
**Reserved cases:** 104–105.

### F23 — Empty demo messages do not drop

**Contradiction.** A demo with no outputs produces an empty assistant message, although kernel §3 says empty messages drop.
**Evidence.** `P7:F23`: Python and Go emit `content: [{kind: text, text: ""}]`; TS instead emits the tail alone.
**Wrong side.** Python and Go violate message cleanup. TS's tail-only choice is not required by the omission rule.
**Case.** Render a demo without outputs under a tail-bearing pattern; retain the user turn and omit the assistant turn.
**Spec sentence.** “If a demo supplies no outputs, emit no assistant message or pattern tail.”
**Kernels.** Python and Go cleanup; TS tail behavior. Case 53 covers only a partly supplied demo.
**Reserved cases:** 106.

### A1, J2 — The published resolution order puts wildcard too early

**Contradiction.** Kernel §5 step 2 places `*` before defaults; cases 48–49 require scalar defaults to win.
**Evidence.** `kernel.md:182–189`; case 48; `P1:A1` renders `true hi`, not JSON-quoted scalar text, in all three kernels.
**Wrong side.** The resolution prose is wrong against frozen corpus bytes. Do not move wildcard earlier in code.
**Case.** Render wildcard JSON with scalar and structured inputs; add a runtime type-binding precedence test in both kernels.
**Spec sentence.** “Resolve exact type, structural keys except wildcard, runtime binding, kernel default, wildcard, then no-format.”
**Kernels.** Verify Python and Go; TS matches the scalar example. A statement that wildcard always precedes runtime bindings would remain wrong.
**Reserved cases:** 107.

### A6 — The closed fact vocabulary contradicts case 78

**Contradiction.** D-06 and capabilities.md close the fact names, but case 78 uses undeclared `prefill` and expects capability-missing.
**Evidence.** `decisions.md:46–49`; `contract/corpus/cases/78-refuse-bind-choose-no-branch.json:47,116`; `P12:A6` accepts a true unknown fact.
**Wrong side.** The frozen case and both kernels contradict the closed-vocabulary prose. No code-only repair can resolve this.
**Case.** Pin an unknown name with true and absent values after gate R2; deliberately review case 78 if names remain closed.
**Spec sentence.** Choose “Fact names are open” or “Unknown fact names refuse at load”; do not publish both.
**Kernels.** Python and Go validation, or prose-only alignment if the maintainer opens names. TS currently uses open names.
**Reserved cases:** 108–109.

### B2, D1 — The conformance map has stale kinds and pointers

**Contradiction.** Kernel §9 excludes plan from its kind list, while the schema and case 72 use it; corpus/README points to absent §10.
**Evidence.** `kernel.md:411`; `contract/corpus/README.md:76`; case 72. The runner docstring already points to §9 (`runner.py:19`).
**Wrong side.** These prose locations are stale. D1 overstates the runner problem; do not change its correct pointer.
**Case.** Use the new F19 plan case plus case 72. Add a documentation check for the kind list and live section pointers.
**Spec sentence.** “Case kinds also include plan, which compares skeleton and prefix; the driver protocol is kernel §9.”
**Kernels.** No semantic edits; Python and Go harness/documentation checks. Preserve historical decision text as history.
**Reserved cases:** existing and harness-only.

### D2 — The harness does not assert the refusal stage

**Contradiction.** A case states a refusal stage, but the harness accepts the same code at another stage.
**Evidence.** `direct-results.log`: case 77 with `expect.at = bind` returns `ok: true` in Python despite load refusing.
`P15:D2-wrong-stage` also passes in Go. `runner.py:97–110` only uses at to select parse replay; `go/conform/conform.go:102–118` likewise lacks stage equality.
**Wrong side.** Both harness drivers fail to enforce stage promises from errors.md and the case schema.
**Case.** Harness negative tests must reject a correct code/fix at the wrong stage; ordinary load/bind cases supply positive fixtures.
**Spec sentence.** “A refusal case passes only when code, declared fix, and stage match its expectation.”
**Kernels.** Python and Go driver stage tracking. Their public Refusal types need not gain a stage field.
**Reserved cases:** existing and harness-only.

### D3 — Delta completeness has no independent harness assertion

**Contradiction.** Kernel §8 requires deltas to equal batch raw text; the local replay check proves only agreement between chunkings.
**Evidence.** `direct-results.log`: a fake reducer returning correct values and no events passes `_check_stream_success`.
`runner.py:152–171` compares deltas only with its first replay. External trace checks help, but omitted traces pass today.
**Wrong side.** The harness leaves a stated law unchecked; this is not evidence that current reducers lose ordinary deltas.
**Case.** Add negative driver tests for missing deltas and missing traces; use a parsed integer whose raw text differs from its value.
**Spec sentence.** “Each replay's deltas equal batch raw spans; a claimed parse case supplies every required trace.”
**Kernels.** Python and Go harness drivers; TS driver trace reporting. Keep trace authority subject to the H2/H3 decision.
**Reserved cases:** 110.

## Bin 2 — holes

Pin the stated current behavior unless a listed gate changes it.
“TS differs” reports the tested scenario, not a complete implementation equivalence claim.
The row sentence is the proposed normative addition. Evidence stays observational.

| IDs | One-line ambiguity | Proposed case: kind and pinned behavior | Spec sentence | Evidence | TS differs from | Cases |
|---|---|---|---|---|---|---|
| C2 | Dump may rewrite version metadata | roundtrip: omitted vocab versions become registered reference versions | Dump records current kernel and referenced vocabulary versions; it need not echo version metadata. | P1:C2 | Python + Go | 111 |
| E4 | Integer-valued float on integer write | refuse/render: 3.5 and JSON 3.0 refuse; integer token 3 writes 3 | Integer writes require an integer representation, not merely an integral floating value. | P3:E4/E4b | Python + Go | 112–113 |
| E9 | Empty capture versus empty full match | parse: DROP:() consumes DROP: and yields empty routed text | Discard zero-length full matches; retain empty captures from nonempty matches. | P14:E9-empty; parse.py:49–53 | Python + Go | 114 |
| F1, J3 | Demo boundary whitespace | render: strip boundary LF but preserve spaces and CR | Derived join removes only boundary LF characters, not all ASCII whitespace. | P7:F1b; parse.py:195 | Python + Go | 115 |
| F2 | Which messages a demo repeats | render: repeat slot-free user Go. but not other-role input messages | A demo repeats all user template messages, then writes its supplied outputs. | P6:F2; plan.py:234–239 | Python + Go | 116 |
| F5 | Fragments relative to placements | render: all fragments precede all placements, including across strategies | Append fragments in their collected order, then apply placements in signature order. | P6:F5; P15:F5-cross; plan.py:169–215 | Python + Go | 117 |
| F6 | Partial bare-slot demos | render: omitted answer removes its anchor/value/close, leaving the score section | Omit the absent output section in both loop and bare-slot patterns. | P6:F6; P7:F6-parse | Python + Go | 118 |
| F7 | Tail after a leading newline | parse/refuse: next nonempty literal line is the tail; duplicated tail refuses | Skip leading LF characters when locating the first tail line; retain those bytes when writing. | P6:F7; plan.py:521–541 | Python + Go | 119 |
| F13 | A hidden output in a bare slot | render: hidden reasoning still shows its placeholder but is not parsed there | Visibility excludes fields from loops and lens holes, not explicit slot placeholders. | P5:F13; P6:F13-parse2 | Python + Go | 120 |
| F26 | Unknown loop attribute depends on context | refuse/bind: input-loop attribute is unknown-slot; pattern attribute is not-lensable | Reject unknown input-loop attributes as unknown-slot; reject unsupported pattern slots as not-lensable. | P7:F26; P8:F26-in | Python + Go | 121–122 |
| G1 | Nullable structural resolution | render: number binding also handles nullable number 0.5 as 50% | Compute structural keys from the nullable base shape; an explicit format owns the whole value. | P9:G1 | Python + Go | 123 |
| G17, G18, G26 | No routing capture still reaches the format | parse/refuse: missing string route becomes empty; integer/media route refuses parse-value; unmatched open remains | Read an empty routed span through its format; an unclosed between capture consumes nothing. | P5:G17/G17-int/G18; P11:G26 | Python + Go | 124–126 |
| G19 | Consuming prefixed lines retain LF | parse: A, captured line, B leaves A\n\nB | Consume matching line characters, not the terminating LF. | P14:G19-newline | Python + Go | 127 |
| G22 | Patch versions and dump normalization | roundtrip: load 0.2.7 and dump current 0.2.0 | Compatibility ignores patch; dump records the current kernel version. | P11:G22-0.2.7; serde.py:32–38 | Python + Go | 128 |
| G23 | Only referenced vocabulary pins are checked | roundtrip/refuse: ignore unused version pin; reject incompatible referenced pin | Check vocabulary versions only when resolving referenced entries; dump only referenced versions. | P11:G23/G23b/G23c; serde.py:84,98,117 | Python + Go | 129–130 |
| I1 | Load refusal precedence | refuse/load: unknown format beats template syntax; kernel version beats unknown format | Check kernel version, resolve lens/strategy/format references in load order, then compile the template. | P12:I1/I1b; serde.py:63–139 | Python + Go | 131–132 |
| I2, I7 | Bind refusal precedence | refuse/bind: capability before no-format; format mismatch before double coverage; lens before uncovered input | Bind selects strategies, resolves formats, builds the lens, checks slots/input coverage, then checks double coverage. | P12:I2a/I2b/I7; plan.py bind path | Python + Go | 133–135 |
| I3, I6 | Structural checks and typed-read precedence | refuse/parse: duplicate beats missing; visible bad JSON beats earlier routed bad integer | Check lens structure first; read visible outputs in signature order, then routed fields in routing order. | P12:I3; P11:I6; P14:I3-reads; plan.py:293–306 | Python + Go | 136–138 |
| A5, DOC-2 | Stop precedence and stripping | plan: tail wins over close; whitespace-only close yields no stop | Use stripped tail, else stripped last close; omit an empty stop. | P1:A5; P12:DOC2b | none | 139 |
| B4 | Dotted role keys | parse: work.notes routes to its field | A strategy key is its complete role name, including dots. | P1:B4 | none | 140 |
| E8 | Pattern with no capture group | parse: Thought: [^\n]+ reads the full match | If a pattern has no capture group, use the full match. | P3b:E8 | none | 141 |
| F3 | Unused demos and history | render: arguments without directives have no effect | Demos and history render only at their respective directives. | P6:F3 | none | 142 |
| F4 | Where a missing fragment target appears | render: create system first and assistant last | Create missing system messages first; append other missing fragment targets. | P6:F4 | none | 143 |
| F8 | Duplicate tail region | refuse/parse: tail in preamble and ending is ambiguous | Search anchors and tail across all lens text; search each close inside its capture region. | P6:F8; cases 32/39 cover anchors/closes | none | 144 |
| F11, DOC-3 | Partial values are raw, not typed | refuse/parse: recover summary Great and stars string 5 while another field is absent | A missing-fields partial maps recovered fields to raw strings, before typed reads. | P15:F11-numeric; direct-results.log; parse.py:185; Go errors.go:19–37 | none | 145 |
| F15 | Absent strategy roles | render: unused role contributes no controls or fragments | Bind effects only for roles borne by signature fields; load still validates every entry reference. | P5:F15; D-28 | none | 146 |
| F17 | Kernel descriptions ignore host type names | render: type int with integer shape shows (integer) | Kernel scalar descriptions use mechanical hints; other formats without describe fall back to the type name. | P5:F17; formats.py:99–100 | none | 147 |
| F18 | Mechanical hints beyond existing examples | render: boolean, media, nullable enum, and string placeholders | Hints are (boolean), (kind), and one of: members; strings have no mechanical hint. | P5:F18; cases 01/04/35/47 cover other hints | none | 148 |
| F24 | Missing-pattern fix locator | refuse/bind: no pattern fixes template; defective hole fixes its message and field | Use template for a missing pattern; locate a defective hole at its template message. | P7:F24; case 33 covers defective anchor | none | 149 |
| G2 | Enum versus scalar structural keys | render: string binding skips enum; enum binding selects it | An enum resolves through enum, not its scalar type key. | P9:G2/G2b | none | 150 |
| G5 | Optional final table delimiter | parse: row without final delimiter still has two cells | Drop a trailing empty cell only when the row ends with the delimiter. | P9:G5/G5b | none | 151 |
| G6 | Missing table property | render: omitted score writes the configured null cell | A missing row property writes as null. | P9:G6 | none | 152 |
| G9 | Unclosed JSON fences | parse: lens accepts unclosed fence; format refuses it | The lens may recover a document without its closing fence; the JSON format requires both fences. | P11:G9-lens; P10:G9-fmt | none | 153–154 |
| G12 | Message placement accepts parts | render: image part appends to user message | Message placements accept text or parts; control placements require parts. | P10:G12; cases 66/67 cover text and control rejection | none | 155 |
| G13 | Dotted control paths | render: controls.tools.list creates nested objects | Each dot-separated control path component names one nested object key. | P10:G13 | none | 156 |
| G14 | Equal controls do not conflict | render: two equal temperature controls merge once | Static request controls conflict only when their values differ by JSON equality. | P11:G14; case 76 covers disagreement | none | 157 |
| G16 | Lens/control conflict repair side | refuse/bind: conflicting response_format fixes the strategy control | A lens/control conflict names the strategy control as the editable path. | P10:G16; errors.md fix policy | none | 158 |
| G20, I4 | when failure precedes requires | refuse/bind: both fail; fix carries satisfy-predicate for when | Check when before requires; use satisfy-predicate for when and declare-capability for requires. | P11:G20/I4; direct-results.log | none | 159 |
| G21 | Several missing required facts | refuse/bind: two declared vocabulary facts missing; fix names first listed | Check requires in list order and report the first missing fact. | P11:G21; direct-results.log; replace a/b after gate R2 | none | 160 |
| H4 | Text parts across other channels | parse: split answer marker across text, thinking, text | Concatenate all text-channel payloads in response order, regardless of intervening channels. | P12:H4; direct-results.log | none | 161 |
| J1 | UDF digest construction | roundtrip: known digest vector; unit vectors cover omitted read and changed describe | Hash UTF-8 name\0source\0 for each present write, read, describe face, in that order; use lowercase hex. | formats.py:193–198; existing hashes in cases 57–62/68; maintainer-established cross-kernel construction | none | 162 |

F19 also needs its non-defect skeleton rule in its reserved plan cases: a vocabulary lens without a skeleton face returns `{}`.
Both kernels do so (`P13:F19-json`); TS supplies empty prefill/stops instead. Add this sentence to the lens socket specification.
For F11, extend the refusal fixture and drivers to assert `expect.partial`; the current harness only compares it within replay.
For J1, pin known digest vectors independently of placement, but keep existing `requires` until the UDF decision changes admission.

## Bin 3 — accept as is

A citation can establish an implied rule without a dedicated edge fixture. The table says when a fixture does not exist.
Add clarifying prose if useful; do not claim adjacent cases pin untested edge bytes.

| IDs | Pinning or implying evidence |
|---|---|
| A2, J6 | Cases 71–72 pin hidden sub-role targets; case 75 pins visible/routed refusal. P1:A2 confirms the negative twin. Clarify “targeted fields”. |
| A3, J7 | Case 64 pins scalar reading of thinking text; case 68 pins declared UDF reads. P1:A3 gives parse-value for image-to-integer, not bind refusal. Do not infer every pack format accepts every kind. |
| B1, J5 | Case 16 pins list[string] resolution. The structural-key examples are incomplete, not an exclusion rule. P1:B1 and direct-results.log confirm fix key list[string]; add it to the examples. |
| C3, J4 | Cases 34 and 63 pin the exact double-LF fragment separator without trimming. No new case needed. |
| D6 | runner.py:90–96 requires inputs to exercise render in a refuse case. Case 38 shows it. Document inputs: {} when no input values are needed. |
| E1 | Kernel §7a gives the multiplication-first rounding formula. Cases 19/45 cover scaled spelling; P14:E1-input confirms 2.68% in all runtimes. No half-case exists; add a regression with G4, not a host-rounding policy. |
| E2 | Kernel §7a requires equality with the member spelling. Case 36 pins integer enum member 2; P3:E2 confirms 02 refuses. The integer grammar does not override enum membership. |
| F9, F10 | Kernel §4 explicitly uses positional boundaries and any anchor order. Cases 20 and 80 exercise boundary rules; P6:F9/F10 confirm the proposed missing-close and reversed-order examples. No new semantic rule. |
| F16 | Kernel §3 says empty messages drop. P5:F16 confirms ordinary templates. Case 66 pins preservation of non-text tool parts. F23 separately records the demo-path defect. |
| F20 | Kernel §4 defines format as the lens writing placeholders. Case 28 pins the vocabulary lens; P8:F20 confirms derived placeholders. The initial P7:F20 used an invalid q slot and supplies no evidence. |
| F21 | Kernel §4 rejects two patterns. Case 33 supplies a not-lensable baseline; P7:F21 confirms loop plus bare holes refuses. The mixed-form edge needs no policy choice. |
| G3 | Kernel §5 states accepts and format-shape-mismatch; case 56 pins it. P9:G3 confirms a scaled-number format rejects a list. Clarify structural-key matching only. |
| G7, G8 | format-table.md reading rules require cells equal columns and default unknown property shapes to string. Case 18 pins header/coercion behavior; P9:G7/G8 confirms case sensitivity and default strings. |
| G10 | lens-json_object.md reading step 3 limits duplicate refusal to field keys and ignores unknown members. Cases 23/46 pin each half; P11:G10 confirms duplicate chatter keys remain ignored. |
| G11 | lens-json_object.md reading step 1 explicitly retries first opening brace through last closing brace. Case 25 pins final failure; P11:G11 confirms successful prose recovery. This is already vocabulary behavior, not plan 02 work. |
| G24 | D-28 and case 82 settle option failures at load and the artifact-key fix path. Case 81 settles validation of pack-built strategies. TS failures reflect its earlier freeze, not an open contract question. |
| H5, H7, H8 | Kernel §8 defines strings as text-channel deltas, coalescing, and batch refinement. Existing parse/refusal replays enforce these laws; P12:H7 confirms the empty reply refusal. Add mixed-feed API tests, not a second parser rule. |
| H9 | Kernel §8 names cross-runtime code/fix/partial equality; errors.md allows hint wording changes. runner.py:174–185 compares hints only within one runtime. Existing parse-refusal replays do not require Python and Go hint text to match. |
| I5 | runner.py:65–73 loads before signature conversion; Go conform.go:133–146 agrees. Cases 43 and 77 exercise each stage separately. This is driver procedure, not a new public bind ordering law. |
| J8 | Cases 01, 04, 35, and 47 pin the listed integer, number, enum, empty-string, and fallback spellings. F18 covers additional unpinned hints; do not duplicate those existing fixtures. |
| J9 | Case 66 pins supplying kind for media data without kind. Kernel §9 compares objects unordered, so member order is immaterial. Do not use this to justify replacing a conflicting kind; G25 owns that defect. |
| DOC-4 | Kernel §6 Strategy grammar makes choose alternatives inline strategies. strategy.py:84–93 and P12:DOC4 reject nested named references. No corpus case pins this edge; the grammar already excludes it. This is a limitation, not a defect. |
| DOC-5 | Kernel §2 requires a mechanical hint, not an exhaustive nullable schema. Case 48 shows nullable scalar placeholders; P12:DOC5 confirms (number). Authors can state null in desc. |
| DOC-6 | python/tests/test_docs_howto.py:48–52 already checks module.__file__ before running dependency-marked guides. Baseline passes with two skips. No corpus case applies to pytest namespace-package discovery. |

## Bin 0 — reject

| IDs | Refuting evidence |
|---|---|
| F22 | Kernel §4 defines surroundings as literals instantiated from field attributes, not arbitrary slots. P7:F22a/F22b refuses instruction and q in both kernels (plan.py:498–516). Case 33 pins the anchor requirement, not this edge. The claimed instruction exception has no contract basis. |
| F12 | The proposed hidden, unserved field is invalid: kernel §6 names an unrecoverable hidden field as malformed; D-28 applies the same validation to packs. P5:F12 refuses entry-malformed in Python and Go. TS acceptance is wrong. |

## Acceptance criteria — six authoring batches, ordered by risk

Ratify the policy gates before the affected batch. Do not move an unresolved gate into implementation by assumption.
Every batch follows the accretion protocol, tests both kernels, and ends with `./check` green.
Do not infer acceptance from an external driver that omits required traces.

- [ ] **Batch 1 — safety fixes retained; regex work withdrawn.**
  Cases 83–85 cover adjacent parts; 86–88 cover malformed parts; 89–90 cover overflow.
  Keep both-kernel tests and every-split replay for these repairs.
  Cases 91–95 and the custom matcher are archived, not active requirements.
  Review the safety fixes separately before merging. Choose a declared pattern
  contract and evaluate mature libraries before resuming regex work.
- [ ] **Batch 2 — remaining defects and harness enforcement; cases 96–110; Python and Go kernels, packs, and drivers.**
  Cases 96–98 pin placement-aware prefix and vocabulary skeleton; 99 pins placed bare slots.
  Cases 100–101 pin control overlap; 102–103 pin rounded-demo refusal and ordinary rounded input spelling.
  Cases 104–105 pin media kind rules; 106 removes empty demo messages; 107 pins wildcard precedence.
  Ratify R2 before 108–109. Review case 78 deliberately if names remain closed.
  Case 110 uses typed integer input text to test raw-delta completeness.
  Add wrong-stage and missing-event/trace negative harness tests; do not add deliberately failing corpus fixtures.
  Correct B2/D1 prose and section-pointer checks. Add E1 half-even input regression tests to both packs.
- [ ] **Batch 3 — holes where TS differs; cases 111–138; Python and Go regression suites, TS behavior and driver.**
  Author every high-risk hole row in its reserved range, including version rewriting, whitespace, routing, and refusal order.
  Pin current Python/Go behavior only where the defect batches do not replace it.
  Verify exact fixes, not only refusal codes; include compound failures in both kernels.
  Test strict integer representation without routing large-number policy through host float coercion.
  Record any changed compatibility rule in a new decision entry.
- [ ] **Batch 4 — remaining holes; cases 139–162; Python and Go kernels, packs, and harness drivers.**
  Author the remaining table rows in their assigned ranges. Add each row's normative sentence.
  Extend refusal schemas, fixtures, and both drivers to compare partial raw strings from F11/DOC-3.
  Pin hash construction with reviewed vectors; add Go and Python digest unit tests independent of UDF placement.
  The J1 load/roundtrip fixture may require udf:python; Go must report unclaimed, never a false pass.
  Add positive and negative twins as unit tests when a row's single fixture cannot contain both outcomes.
- [ ] **Batch 5 — ratified policy cases only; reserve 163–171; Python and Go, with declared UDF placement limits.**
  Ratify all eight Bin 4 decisions. Publish the selected rule and its rejected alternative's cost.
  Reserve 163–164 for dot/newline rules; 165 for non-placing UDF precedence; 166 for declared UDF defaults.
  Reserve 167–168 for int64 endpoints; 169 for astral text and routing; 170 for history validation.
  Reserve 171 for the selected timing policy's representative empty/held-field trace.
  Test invalid capability and surrogate boundaries in host/schema tests if they remain outside the corpus domain.
  Test the trusted pack-loader interface with a fixture pack; do not grant artifacts an automatic import privilege.
  If a decision needs different fixtures, revise these reservations before authoring. Never fill them with guessed behavior.
- [ ] **Batch 6 — conformance and publication; verify cases 83–171 plus 01–82; Python and Go, and the TS driver.**
  Verify all 114 IDs occur in one classification each; keep duplicate merges visible.
  Run full schema, corpus, all-split stream, cross-driver trace, documentation, and DSPy checks.
  Keep unclaimed UDF cases explicit; require traces for every claimed parse case under the selected timing policy.
  Add the Bin 3 clarifications and F12 regression without changing their established rules.
  Update the plan index only in a later authorized change. Maintainer review before marking this plan done.

## Trade-offs and limits

- Counts use all 114 source IDs. Merged rows reduce work, not the number of findings.
- D-28 resolves pack admission and option errors. It does not settle every invalid option's detailed grammar.
- Out-of-schema capability values and non-scalar Unicode do not establish valid-input conformance defects.
- Int64 is the present minimum. Larger host integers remain a policy choice, not a Go defect by assertion.
- Frozen cases outrank implementations. A6 needs deliberate corpus review; A1 needs prose aligned to existing bytes.
- Coalescing batch parts changes old batch values. Preserving boundaries instead would change the streaming protocol.
- DOTALL preserves existing extraction but can consume later sections. Excluding LF requires a compatibility decision.
- Correct `round_trip` declarations can reject demos that currently render. Ordinary input formatting remains available.
- Media read repair can add kind to existing returned values. Wrong-kind refusal removes current silent conversion.
- Placed inputs lose explicit slot values under the repair. This removes duplicate wire content, not the placement itself.
- A prefix means complete messages, not a character prefix inside a changing message. Placements therefore reduce cacheable messages.
- Bare-slot demo omission can produce text that is not valid JSON. A derived marker lens does not promise a JSON document.
- Pinning integer representation, LF-only join trimming, and retained line newlines exposes current host-facing choices rather than smoothing them away.
- Harness defects need negative tests, not intentionally wrong corpus expectations. B2/D1 reuse the new plan fixtures.
- Refusal precedence tests constrain future implementation order. Test the stated collisions; do not claim every possible fault combination is pinned.
- Reference trace authority remains unresolved. TS passes without trace comparison do not supply timing evidence.
- Go does not place UDFs. Its unclaimed cases are not passes; Python-only default checks do not prove cross-runtime placement agreement.
- The direct Go probe must use LMCC JSON serialization for Object values. Initial output containing only Keys was a probe error.
- The initial E1 demo probe omitted the demos directive. P14:E1-input replaces it for rounding evidence.
- The first F14 bare-slot probe used role context instead of field ctx. P15:F14-bare now uses the correct field.
- The initial JSON probes retained extra case-23 fields. P11 supplies the corrected two-output scenarios.
- P6:F13-parse failed while requesting nonexistent describe keys. P6:F13-parse2 supplies the valid parse evidence.
- The first P3 run split output at Unicode line separators. P3b uses JSON Lines splitting and replaces that failed read.
- This is a review queue, not permission to change all kernels in one patch. Each batch requires maintainer review.

**Not in scope:** new recovery combinators (plan 02), a turns face (plan 03), and tools/citations vocabulary (plan 04).
Existing JSON recovery, history rendering, and generic placements stay in scope because the current contract already defines them.

## Reproduction commands

Run from this worktree unless the command changes directory.

```sh
./check > /tmp/lmcc-triage-check.log 2>&1
mkdir -p /tmp/probe
cp /home/maxime/Projects/.pi-worktrees/lmcc-triage-probe/*.py /tmp/probe/
for n in $(seq 1 13); do
  timeout 100 python3 /tmp/probe/multi.py /tmp/probe/s$n.py > /tmp/probe/result$n.log 2>&1
done
# Repair JSON Lines handling before the selected rerun.
python3 - <<'PYFIX'
from pathlib import Path
p = Path('/tmp/probe/multi.py')
p.write_text(p.read_text().replace('p.stdout.strip().splitlines()', 'p.stdout.strip().split("\\n")'))
PYFIX
python3 /tmp/probe/multi.py /tmp/probe/s3.py E7-dotall E7-2028 E8 E9 E10 > /tmp/probe/result3b.log
python3 /tmp/probe/multi.py /tmp/probe/s14.py > /tmp/probe/result14.log
python3 /tmp/probe/multi.py /tmp/probe/s15.py > /tmp/probe/result15.log
(cd go && go build -o /tmp/probe/direct /tmp/probe/direct.go)
python3 /tmp/probe/evidence.py > /tmp/probe/direct-results.log
python3 /home/maxime/Projects/.pi-worktrees/lmcc-triage-probe/probe.py /home/maxime/Projects/.pi-worktrees/lmcc-triage-probe/a4.json
python3 /home/maxime/Projects/.pi-worktrees/lmcc-triage-probe/probe.py /home/maxime/Projects/.pi-worktrees/lmcc-triage-probe/a4b.json
(cd /home/maxime/Projects/.pi-worktrees/lmcc-ts-branch/ts &&
 PYTHONPATH=../python python3 ../contract/harness/runner.py \
 --driver 'node --experimental-strip-types conform/main.ts' --cwd .)
```

The TS command returns 74 passed, two failed, six unclaimed, and zero compared stream traces.
Its two failures are cases 81–82, which D-28 added after its freeze.
Probe construction files under `/tmp/probe/` are review aids, not future corpus source generators.

## Proposed plans/README.md row

| `09-audit-triage.md` | classify 114 audit findings; ratify policy gates, then pin defects and missing contract rules | XL |


# Decision log (append-only)

Ratified choices and their reasons. Read before proposing a design
change; append after ratifying one. Each entry: the decision, the reason
that would survive cross-examination, and what it cost (trade-offs are
stated, never absorbed).

---

**D-01 · The kernel ships zero vocabulary.** No codecs, no strategies,
no vocabulary lenses in the kernel — everything with an opinion plugs
into sockets from packages. Precedent: serde ships without serde_json.
Reason: perfect symmetry (your codec and `json` have the same standing)
and a kernel that can freeze for years while vocabulary compounds.
Cost: hello-world needs a pack install (`lmcc_std`).

**D-02 · The corpus is the authority; authored bytes rule.** Cases 01–19
were seeded from the reference once, human-reviewed, then frozen; every
later case is hand-authored *first* and the implementation made to pass.
Reason: byte-exact fixtures are the only mechanism that makes
"identical in every language" a fact rather than a hope.
Cost: changing behavior means editing cases deliberately, like law.

**D-03 · Roles are intents; parts are transports.** A role names a
conversational function (reasoning, citing); a wire part names a
transport (thinking channel). Roles form an open, lmcc-owned vocabulary
aligned with — but never limited by — any provider's part kinds.
See `vocab/roles.md`. Cost: a small mapping table to maintain.

**D-04 · The template is the lens.** `parse: {"kind": "derived"}` reads
the output-pattern block backwards: prompt, demos, and parser are one
description. Non-invertible patterns refuse at bake (`not-lensable`);
anchors appearing twice in a reply refuse at parse (`parse-ambiguous`).
Reason: the drift bug becomes unwritable; refusal beats guessing.
Cost: sections stays as the declared alternative; two kernel lens kinds.

**D-05 · Invertible surroundings, semantic insides.** The exchange
layer separates fields by spelling; meanings (JSON etc.) live inside
typed fields via codecs. Whole-object JSON is a *mode*: `lens/json_object`
refuses to bake without declared `native_structured_output` and patches
the request with `response_format` + a schema built from the signature.
Reason: a JSON object is a meaning with many spellings — only honest
when the server enforces it. Cost: four corpus cases changed meaning
when this landed (reviewed as a contract change).

**D-06 · Capability facts are declared, never sniffed; closed
vocabulary.** `vocab/capabilities.md` lists the only words predicates
may use. Reason: portable predicates; refusals before money.
Cost: you cannot predicate on model names or context length.

**D-07 · Host types are per-runtime code bindings, never serialized.**
`register_host(type, shape, lower, lift, codec?)`; artifacts carry only
neutral shapes and codec names. Entry-bound codec wins over the type's
registered default. Reason: the Arrow/i64-vs-BigInt pattern — every
runtime materializes its native type. Cost: relying on a host *default*
codec means two runtimes may spell the same type differently unless the
entry pins it (stated in `kernel.md` §1).

**D-08 · `instruction` and `format` are reserved slots** and shadow
same-named fields. Cost: a field literally named `format` cannot be a
bare slot; accepted and documented.

**D-09 · Strategy predicates are a closed algebra.**
`capability | not | all | any` — enough to say "when the model does NOT
have native reasoning", small enough to analyze. `requires` stays as
all-of sugar.

**D-10 · Agent cockpit is part of the contract surface.** `AGENTS.md`
(map + protocol), `./check` (one verify command), `plans/` (work queue
with acceptance criteria), this log (memory), and data introspection
(`baked.describe()`, `registry.describe()`). Reason: the system's users
include agents; legibility and a closed verify loop are design
requirements, not conveniences.

**D-11 · The map is verified, not trusted.** Documentation claims are
cross-checked mechanically (`tests/test_coherence.py`): raised error
codes must be documented, the vocab index must be complete with real
spec files, corpus filenames must match their declared names, std
predicates may only name declared capability facts, and plans must
carry acceptance criteria. Reason: an agent can only rely on a map
whose claims fail tests when they rot — the corpus move, applied to the
docs themselves. Proof it was needed: the first run caught
`control-conflict` raised in the kernel but absent from `errors.md`.
Cost: adding vocabulary or codes now touches the index/table too —
which is the point.

**D-12 · The project and public package are named LMCC.** LMCC expands to
**Language Model Calling Convention**. LMCC maps a typed signature and
values onto model messages and maps the reply back into typed values.
`lm15` owns the model-neutral request and response shapes below that seam.
Reason: the name states the exact category, pairs with `lm15`, and does
not limit the contract to large or text-only models. Cost: this is a clean
pre-release rename from `a15`: Python imports become `lmcc` and `lmcc_std`,
and `A15Error` becomes `LMCCError`. No compatibility aliases remain.
Historical conversation keys keep the former name because changing those
keys would break durable links.

**D-13 · Text primitives are pinned to portable definitions (kernel
§7a).** Strip means the six ASCII whitespace characters; integer and
number text have explicit grammars; numbers are spelled with the
ECMAScript `Number::toString` algorithm; booleans are `true`/`false`;
rounding is half-to-even in binary64. Reason: every host language's
built-in `strip`, `int()`, `float()`, and float formatting differ in
some corner (Unicode spaces, `+5`, `1_000`, `1.0` vs `1`, `1e+20` vs
`100000000000000000000`), so "byte-exact across languages" was a hope
until each primitive had one definition. ECMAScript's algorithm was
chosen because it is the one number spelling with a precise public
specification and the widest deployment. Cost: `1.0` now renders as
`1`, `+5` refuses, a no-break space at a value's edge survives, and
the Python reference formats numbers itself instead of calling
`json.dumps`. Pinned by corpus cases 35–37, 44, 45.

**D-14 · The `pattern` extractor's dialect is RE2, minus named groups.**
Lookaround, backreferences, atomic groups, possessive quantifiers, and
named groups refuse `entry-malformed` at construct/load; empty matches
are discarded; `between` and `line_prefixed` are defined as plain scans
with no regex at all. Reason: Go, Python, JavaScript, Rust and Java
agree on the RE2 core and on nothing beyond it; named groups have two
incompatible spellings and buy nothing when the algebra reads group 1.
Cost: a handful of Python-only regex idioms are unavailable in
routings; the reference lints them syntactically rather than proving
RE2 conformance. Pinned by corpus cases 40–42.

**D-15 · Invertibility is stated exactly, and its write side is
enforced.** `join` refuses `value-collides` when a spelled demo value
contains any marker the lens reads; `split` refuses `parse-ambiguous`
when a close marker or tail occurs twice in its region, exactly as for
repeated anchors. The remaining normalization (outer whitespace of a
value does not survive a round trip) and the one undetectable double
fault (a reply that omits its close marker *and* contains it inside the
value) are written into kernel §4 instead of being implied away.
Reason: the README promised that demos and parser cannot drift; before
this a demo whose value contained `</answer>` would have been written
and then read back wrongly with no error. Escaping was rejected because
marker lenses have no escape syntax and inventing one changes what
models see. Cost: a demo value containing a marker must be rephrased.
Pinned by corpus cases 38–39.

**D-16 · Signatures are validated data with a schema.** Field names are
ASCII identifiers and unique; direction and shape are checked;
`signature-malformed` names the offender. `schema/signature.schema.json`
and `schema/case.schema.json` join the entry schema, and `./check`
validates every corpus case against all three. Reason: field names
become template slots, lens markers, and JSON member keys in every host
language (where integer-like keys reorder in JavaScript and Unicode
identifiers differ per language); the second implementation reads case
files and deserves a schema for them. Cost: Unicode field names are a
frontend's job to map. Pinned by corpus case 43.

**D-17 · `lens/json_object` hands over source text, not a
re-serialization.** A non-string member reaches the field's codec as the
exact characters the model wrote (outer whitespace trimmed); a field key
appearing twice refuses `parse-ambiguous`; parsing is strict RFC 8259.
Reason: re-serialization required every implementation to agree on a
compact serializer *and* lost information (digits, big integers in
JavaScript); source spans require only a JSON reader that reports member
offsets, which every language can write in a page. Cost: what a codec
receives now contains the model's own spacing, so codecs must be
whitespace-insensitive — `codec/json` already was. Pinned by corpus
cases 23 (unchanged bytes) and 46.

**D-18 · The second implementation is Go, stdlib only, and `./check`
runs it.** `go/` implements the kernel and the std pack from the
contract, exposes the corpus driver `cmd/lmcc-conform` (JSON Lines,
kernel §10), and adds a Go struct-tag signature frontend. Both kernels
must raise exactly the same set of error codes (`test_coherence.py`).
Reason: Go is the runtime most unlike Python — no ordered maps, no
dynamic JSON, RE2 regex, fixed-width integers — so every accidental
Python-ism in the spec surfaced while writing it (D-13 to D-17 are
that list). TypeScript would have shared too many defaults with the
rules chosen. Cost: an ordered-JSON type and a strict parser had to be
written by hand (encoding/json cannot preserve member order), the
kernel uses panic/recover internally behind an error-returning API (the
encoding/json precedent), and `./check` now needs a Go toolchain (falls
back to `nix shell nixpkgs#go`).

**D-19 · The kernel's shape set is closed; everything else is codec
territory.** A shape the kernel does not interpret (`anyOf` of two real
types, `$ref`, `{}`, no interpreted keyword) is *structured* for the
`no-codec` rule. Reason: the goal is to carry **any** frontend's
signature (a Union, a pydantic model with `$defs`, `Any`) as data
without the kernel ever spelling something it does not understand;
refusing at bake keeps rule 3. Cost: `Union[str, int]` needs a codec
even though its members are scalars — spelling and reading a union is a
codec's judgment, not the kernel's. Pinned by corpus 50.

**D-20 · Entries may bind a `@structured` default codec.** Precedence:
field-name binding, then `@structured`, then the host type's default,
then refuse. Reason: adapters are signature-independent, and before this
no adapter could spell `list[str]` for a signature it had never seen —
which made "one adapter for every signature" (the DSPy shape of use)
inexpressible. A single sigil key keeps the entry schema closed. Cost:
an entry that binds `@structured` decides the spelling of every
structured field at once; per-field bindings still win. Pinned by
corpus 48–49.

**D-21 · Nullable scalars read and write `null`.** Only the two bare
spellings (`{"type": [T, "null"]}`, `{"anyOf": [S, {"type": "null"}]}`)
are nullable; the text is exactly `null`. Reason: `Optional[X]` is the
most common non-scalar annotation in signatures and DSPy special-cases
it; one exact literal keeps reading unambiguous across languages. Cost:
a nullable *string* cannot carry the literal text `null`; `None`, `N/A`
and friends refuse — recovery is plan 02/06 data, never a kernel guess.
Pinned by corpus 51–52.

**D-22 · History turns may be field dicts; incomplete examples omit,
never invent.** A history item is a message (verbatim) or
`{"fields": {...}}`, rendered exactly like a demo through the template
and the lens; in demo/history turns an inputs loop iterates only the
supplied fields, while a bare slot with no value still refuses
`missing-input`; outputs absent from an example are omitted from its
assistant turn. Reason: a conversation held as typed values (DSPy
`History`, a tool loop) must render through the one description the
model is asked to follow, or it drifts; and DSPy's "Not supplied for
this particular example" placeholder was rejected because it puts text
in the model's mouth that no lens can read back. Cost: the `fields`
wrapper is one more shape in the history list; flat dicts refuse.
Pinned by corpus 53–54.

**D-23 · The DSPy frontend is a total lowering; what it drops is what
DSPy drops.** `python/lmcc_dspy` lowers any `dspy.Signature` to a
SignatureCore, carrying instructions, order, names, `desc`/`description`,
pydantic JSON schemas whole (constraints, `$defs`, `anyOf`), `Literal`
and `Enum` as enums, `Optional[X]` as nullable, media types as parts,
`Reasoning`/`Tool`/`ToolCalls`/`Citations` as roles, `dspy.Code` as a
string shape carrying its language, and `dspy.History` as history field
turns. It drops only `prefix`/`format`/`parser` (deprecated upstream:
"has no effect"), the type-undefined marker, and field defaults
(program-side values, never shown to a model); anything else it cannot
carry refuses `unmapped-type` by field. A `dspy.Tool` lowers to its
*declaration* (name, description, parameters) because the callable is
host code. Reason: the ratified goal is to write, save and render any
DSPy signature in LMCC and render/parse it LMCC's way — so the guarantee
is about information, checked by a catalog against a real DSPy
(`tests/dspy/test_catalog.py`, one row per feature, each rendered and
round-tripped through the DSPy-shaped entry), not about DSPy's prompt
bytes. Cost: `./check` builds a DSPy venv with uv on first run (network
once); `Optional[Model]` lifts to a dict, not a model (only bare model
types get host bindings); DSPy's lenient parsing is not reproduced.

**D-24 · The contract is the v3 design (kernel 0.2).** Formats replace
codecs and are keyed by **type name** or structural key, never by field
name; a format is `write(value) → parts`, `read(span) → value`,
optional `describe`, with declared `accepts`/`direction`/`emits`/
`round_trip`; the kernel keeps only its scalar/enum/null and media-part
defaults and refuses `no-format` for anything structured. A format may
be **shipped whole** (language, source, deps, sha256, author); `load`
never runs it; runtimes admit by hash and self-containment and refuse
by name when they will not or cannot place it. Strategies gain
`choose`, `placement`, and the `{from, to, consume}` routing form; the
`sections` lens is gone (every marker dialect is a derived pattern,
tails and bare output slots included); the lens socket stays for
document forms a signature-independent pattern cannot spell
(`json_object`). `@lmcc.fn`, `Role`, `One`, `Refusal(code, hint,
partial)`, `plan.skeleton()`/`prefix()` land. Reason: the 0.1 kernel had
narrowed v3 (codecs by field name, media as a kernel special case, no
parts, no UDFs) and D-20 was the symptom; the maintainer ratified v3 as
written, accepting that runtime type bindings are the stated
language-specific leak and that UDFs are the portable path when one
cares. Costs, each stated in `plans/08`: a second corpus seeding
(reviewed diff by diff), a second kernel rewrite, Go declares UDF cases
unclaimed and lacks `format-not-self-contained`, strict escapes remain
(`{{"answer": "{answer}"}}`), `reach` from the v2 pack-authors notes is
not adopted, and `parser()`/`grammar` stay gaps.

**D-25 · Refusals before render carry a `fix`; the vocabulary is closed
and corpus-pinned.** `Refusal` gains `fix: {"action", ...parameters}`
(Python) / `Error.Fix` (Go). Eleven actions, each with a fixed parameter
set of names a program can act on — a field, a role, a capability fact,
a vocabulary name, a version pair, a locator into the artifact — and a
`fix` column in the code table saying which action each code carries.
The rule: every refusal at construct, signature, load, or bind carries
one; render, parse, and registration refusals carry none. Reason: bind
is the gate, and a gate that names the next step as data is what makes
"refuse before money" usable by an agent; after render the cause is a
program value or model text, and what to do about it (retry, ask again)
is orchestration, which lmcc refuses to be — the `partial` face already
serves parse. Choices: one fix per refusal, the primary repair (prose
lists alternatives), because a list of fixes is a guess dressed as data;
`bind-format.key` is the type name, else the most specific structural
key, else `*`, so the fix is the artifact key to write; the first
offender in signature order is the one named; `satisfy-predicate`
carries the predicate itself (`{"any": [...]}` over a `choose`) rather
than a computed set of facts, because the predicate is the contract and
the caller may prefer an `else`. Costs, stated: ~110 call sites per
kernel now carry a fix, so adding a pre-render refusal is one more line
and the coherence test refuses a bare one; corpus refuse cases now pin
payloads, so a kernel that names a different offender is non-conformant
(case 56's hand-authored guess was corrected by the harness in the
reference's favor); `Fn.__call__` now raises `TypeError` instead of
`entry-malformed` — calling a signature is Python API misuse, not an
artifact defect, and it had no honest fix; the Go `FormatSpec.Read`
fallback error lost its `format-direction` code (it was never surfaced
as one: bind refuses `format-direction` first, and read errors wrap as
`format-read-error`). Pinned by corpus 09–14, 24, 29, 33, 42, 43, 50,
56, 59–61, 67, 68, 73–79; `schema/fix.schema.json`;
`tests/test_fix_hints.py`; `tests/test_coherence.py`.

**D-26 · Streaming refines batch; EOF returns events and final values.**
`plan.stream()` creates a pure sans-I/O reducer; `feed` accepts decoded
text or one lm15 part delta and emits `field_started` / stable raw
`field_delta`; `finish` returns `{events, values}` and is the only place
that emits typed `field_done`. The law is chunking-invariance: final
values or the complete refusal equal batch `parse`, and deltas join to
the exact raw spans batch captured. Reason: there must be one semantic
parser; a second set of final checks would drift, so stream EOF calls
the shared batch span/read path, while the incremental projection only
exposes prefixes future input cannot revise. Choices and costs: (1) the
plan sketch's `values = finish()` became `result = finish()` with both
EOF events and values — EOF can close an unclosed final field and
release held text, so an API that returns only values silently loses
required events; (2) typed done waits for EOF rather than firing at an
early close — a later duplicate anchor/close can make the reply
ambiguous, and an expert parser must not publish a typed value before
whole-document validation; the cost is less early typed data, while raw
deltas still stream; (3) the reducer retains the accumulated response
and reruns the shared batch path at EOF — formats can require complete
spans and global duplicate checks can invalidate early structure; the
cost is memory proportional to the reply and repeated projection work
per provider chunk (measured near 0.1 s for 100,000 ASCII characters in
1,000 chunks in the Python reference), accepted for exact refusal and
format order; (4) regex-routed fields buffer because a later scalar can
change an earlier RE2 match; a consuming regex buffers lens text too;
(5) two routings to one field buffer because batch joins spans by
routing declaration order, not arrival order; these costs are all
visible under `plan.describe()["streaming"]`; (6) adjacent text-bearing
part deltas of one kind coalesce, so providers need not invent part
boundaries, at the cost that two adjacent logical text parts of the same
kind must be separated by a kind change or sent as one; (7) harness
splits are Unicode-scalar, not raw-byte — UTF-8 decoding is transport
I/O and must happen incrementally before `feed`; testing invalid partial
Unicode as text would put transport policy into the calling convention.
Vocabulary lenses get one optional stream face with growing-prefix
semantics; absence buffers visibly. No artifact or kernel version bump:
the serialized entry and all old render/parse semantics are unchanged;
this is an additive runtime plan face. Implementing full-refusal equality
also exposed and fixed Go `Error.Describe`: `partial` is now an ordered
LMCC `Object`, not a host map. Pinned without duplicate fixtures: both
harness drivers replay every parse and parse-refusal corpus response
whole, one scalar at a time, at every scalar and text-part split;
`python/tests/test_streaming.py`; `go/lmcc/stream_test.go`.

**D-27 · Streaming is linear in the reply; marker overlap holds, never crashes.**
The §8 reducer no longer rescans the accumulated reply on every delta.
Markers are found by per-marker incremental scanners over a window one
byte shorter than the longest marker; each field keeps its emitted
pieces plus a short held tail; routings are chained transducers; the
whole reply is retained only for the batch parse at EOF. Reason: the
first implementation (D-26) was quadratic — 100,000 characters at
token-sized (4-character) deltas cost 4.9 s in Python and 0.9 s in Go,
and doubled reply length quadrupled the cost; D-26's "0.1 s in 1,000
chunks" figure hid this behind 100-character chunks. Now the same input
costs 0.36 s and about 20 ms, per-feed work is constant (≈17 µs Python),
and both kernels carry a scaling test. Emission timing is unchanged
(identical events on 3,000 random multi-chunk scenarios against the
D-26 reducer) except in one class of inputs the old reducer could not
handle: a marker beginning inside an earlier marker's occurrence
(`**Reasoning:**Answer:**` under `**Reasoning:**{r}**Answer:**{a}`).
Batch reads an empty reasoning capture (§4, corpus 80 — which also
exposed and fixed a Go batch panic on the negative slice); the old
reducer emitted `A` then raised `RuntimeError` on model text. The new
rule: a marker occurrence acts only once no boundary marker can still be
growing across it. This is exact (a prefix-table lookup bounded by the
longest marker), so ordinary templates lose no eagerness. Costs taken:
(1) the reducer is a state machine, about twice the code, in both
kernels — guarded by the EOF cross-check, the every-split harness, a
seeded random multi-chunk fuzz in each kernel over a shared plan set, and
the new cross-kernel stream trace; (2) event timing is now pinned across
kernels by the harness against the reference kernel's trace, not by
hand-authored corpus bytes — the §8 hold-back prose is the meaning and
the reference is its executable form; storing traces per case would
duplicate the parse corpus at every scalar; (3) a `between` routing with
both delimiters empty makes batch loop forever in both kernels (schema
allows it); the reducer breaks out instead of hanging, the batch bug is
left for its own fix. Memory stays proportional to the reply (D-26 (3)).

**D-28 · Vocabulary references resolve at load; a pack has no privilege.**
A `{"use": name, "options"}` reference (format or strategy) is resolved
when the artifact loads: the factory runs on the options, a failing
factory refuses `entry-malformed` at the reference's path, and what a
strategy factory returns is validated by the kernel's own rules exactly
as inline data. Reason: D-27 (3) recorded a hang — `reasoning_tags` with
`{"open": "", "close": ""}` built a `between` routing with empty
delimiters that the kernel refuses when written inline but accepted
from the pack, and batch parse looped forever in both kernels (corpus
81). Looking for the class rather than the instance found a second
member: `table` without `columns` raised a bare `ValueError` in Python
and refused at bind in Go with a fix path naming the format's name
instead of the artifact key (corpus 82) — two kernels, three behaviors,
no case. The tower says packs plug into sockets with zero privilege;
letting a factory's output skip validation was a privilege. Resolving
at load rather than bind keeps `errors.md` true (`entry-malformed`
fires at construct/load) and makes artifact validity independent of
any signature. Costs: (1) factories run at load and again at bind —
they are pure and cheap, and storing the built object would complicate
dump; (2) the fix path names the reference (`strategies['reasoning']`),
not the offending option, because the kernel cannot know which option
produced the bad data — the hint carries the pack's message; (3) in Go
a factory that panics with a non-`Error` is still a driver panic, not a
refusal: returning `error` is the factory contract, and a panic is a
bug to surface, not data to absorb.

**D-29 · Plan 09 policy gates, ratified as recommended.** The clean-room
TypeScript implementation (branch `ts/cleanroom`, written from
`contract/` alone) and the documentation review produced 114 findings;
plan 09 classified them and named the questions only the maintainer
could answer. Ratified 2026-09-07, each with the cost taken: (E7) `.`
in a `pattern` routing matches a newline, as both kernels do today —
greedy patterns can consume later sections; LF, CR, U+2028 and U+2029
get cases. (R1) Batch parse coalesces adjacent same-kind text-bearing
parts before routing, exactly as the reducer does — existing batch
values that joined such parts with `\n` change; it is the only reading
under which §8's refinement law holds. (R2) Capability fact names stay
closed (D-06); an unknown name refuses before bind, and case 78, which
predicated on an undeclared `prefill`, is repaired deliberately —
vocabulary control over convenience. (H2/H3) Stream event timing is
pinned by small hand-authored trace fixtures in the corpus, not by the
reference kernel's trace (revising D-27 (2)) — fixtures cost
maintenance; the reference regains no authority. (C1/B3) A non-placing
host refuses `format-untrusted` before verifying a hash; the hash
construction is specified as bytes; admission-before-placement is
proposed as a later versioned change. (E5) The portable integer domain
is int64, both endpoints pinned; larger host integers are an extension
a host may offer, never a portable claim. (F25) History parts are
validated at render (`value-invalid`), never normalized. (D5)
Non-boolean capability values are caller misuse outside conformance;
the case schema already forbids them. (E10) Lone surrogates refuse at
transport decoding; the kernel domain is Unicode scalars. (DOC-7) The
harness gains an explicit trusted pack-loader map; an artifact name
never triggers an import. Batches 1–6 of plan 09 implement these under
the accretion protocol; each batch that changes a rule appends its own
entry.

**D-30 · Batch 1: response safety and portable text (plan 09).**
Cases 83–95 were hand-authored after the spec sentences, before kernel
changes. No earlier case expectation changed. The batch implements the
R1 and E7 choices from D-29 and repairs B5, E3, and E6.

- Batch parse now coalesces adjacent same-kind text-bearing parts before
  routing, including empty text. A kind change or a textless part ends
  the run. Metadata keys accumulate; the last supplied value wins.
  Neither kernel changes the caller's parts. **Compatibility cost:**
  old batch `fo` + `ur` becomes `four`, not `fo\nur`. This deliberately
  corrects D-26's claim that all old batch values remain unchanged.
  The serialized entry stays at 0.2.0; this repairs its broken refinement
  law, not its data shape. Both reducers keep their event timing.
  All 30 saved pre-repair traces, including cases 83–85, remain identical.
- Batch and feed share each kernel's response-part validator. Every
  part needs a string `kind` and, when present, string `text`.
  Invalid parts refuse `response-malformed`, with no fix. Shared hints
  preserve full batch/feed refusal equality. **Boundary cost:** a bare
  string is a valid text delta but an invalid part-list element.
  The drivers preserve that distinction. They check a string element
  through the batch list boundary before feed can reinterpret it.
  Other malformed elements reach feed directly. Replay never converts
  malformed data into a valid part or skips a bad element.
- A binary64 read that overflows refuses `parse-value`. Python now checks
  finiteness; Go already did. Both suites pin the positive and negative
  finite endpoints. Standard format wrappers report overflow as
  `format-read-error`, not a leaked kernel error. **Cost:** Python callers
  can no longer receive infinity from grammar-valid decimal text.
- Pattern admission and matching use RE2 meanings, with DOTALL as the
  default. Go checks the parsed syntax tree instead of linting substrings.
  This admits quoted literals, POSIX classes, and quantified Unicode
  properties without admitting named groups or non-RE2 operators.
  Python lowers Perl/POSIX classes, Unicode categories/scripts, complements,
  quotes, octal/hex escapes, boundaries, and `i/m/s/U` flags into scalar
  matching instructions. ASCII word boundaries stay separate from Unicode
  simple folding. **Implementation cost:** simple translation into Python
  `re` was insufficient. For `(a*)+` against `aa`, its last empty loop
  iteration overwrote the capture with empty text; RE2 captures `aa`.
  Python therefore uses an ordered Thompson matcher for all pattern
  routings, not host response matching. This adds syntax/matcher code and
  trades the host's compiled matcher speed for explicit capture priority
  and linear search work. Patterns still buffer until EOF, as before.
- **Unicode cost:** Python bundles 129,560 bytes of Unicode 15.0.0 category,
  script, and simple-fold data from Go's standard-library tables.
  `go/lmcc/generate_re2_unicode.go` reproduces it. A version test requires
  review when Go upgrades Unicode. Python needs no external regex package
  or Go executable at runtime. The data is not vocabulary and grants no
  artifact code privilege. Compiled-pattern and property caches are bounded.
- **Limits, not new dialect rules:** named groups remain the only LMCC
  exclusion from RE2. Neither kernel implements RE2's byte escape `\C`;
  the existing Go scalar-text engine rejects it. This remains an inherited
  implementation gap, not a newly permitted exclusion from D-14.
  Recursive syntax construction still depends on host stack limits;
  this batch does not prove agreement at resource ceilings. The 1,018-pattern,
  seven-text differential check found no remaining difference in its tested
  domain. It supplements the authored cases; it does not define expectations
  or prove the whole RE2 language. Parent review must assess the larger
  Python matcher change rather than treating 95 green cases as that proof.

Validation: `./check` passes Python 95/95 and Go 89/95, with six declared
UDF cases unclaimed. All 95 cases pass schema validation; Go compares
39 stream traces. The unchanged TypeScript driver passes new cases
83–85 and 89–91. It fails 86–88 on batch/feed hint equality, 92–94 on
regex admission, and 95 on DOTALL. It reports no compared traces.
Parent review remains required; these results do not accept the batch.



**D-31 · Portability is a small shared core plus declared execution extensions.**
Ratified by the maintainer after reviewing the SQL comparison and the Batch 1
matcher expansion. Identical extraction across claimed implementations remains
mandatory. Universal RE2 support and a custom dependency-free matcher do not.
Artifacts declare named, versioned semantic requirements; hosts bind compatible
implementations or refuse before a usable plan and before model I/O. Frontends
may translate only when meaning is preserved. Host extension support stays
separate from model capability facts. Mature libraries are legitimate backends;
a library name or shared ancestry alone does not prove equivalent behavior.

This supersedes D-14's universal regex mandate and the corresponding implementation
instruction in D-29 and plan 09. DOTALL can belong to an explicitly named
legacy-compatible contract; it is not imposed on every extension. The unmerged
Batch 1 matcher is an experiment, not the selected architecture. Preserve its
findings and separate non-regex safety fixes from the backend decision.

Costs: more explicit compatibility metadata, hosts that support fewer artifacts,
and possible library or service dependencies. Benefits: a small implementable
core and no mandatory ownership of a regex engine. Silent dialect substitution
remains forbidden. `spec/portability.md` states the boundary; plan 10 gates the
core inventory, extension schema, discovery, binding, failures, and migration.
No identifier, backend, wire format, or new refusal code is approved here.
The existing 0.2 schemas, corpus bytes, and refusal stages remain unchanged until
that versioned migration. Historical decisions remain as history, not current
instructions to implement the superseded mandate.


**D-32 · Withdraw the custom regex engine; retain the safety fixes.**
The maintainer rejected mandatory ownership of a regex engine and authorized
removing the experiment. Reverse the regex implementation from bf822da,
including its Unicode tables, generator, integration changes, and tests.
Withdraw experimental corpus cases 91–95 before merging this branch.
Preserve their bytes and differential-review evidence outside the active corpus
for future library evaluation. Existing cases 01–82 are unchanged.

D-30 remains the historical record of the experiment, not approval of its
backend. Its regex support and completion claims no longer describe this branch.
Cases 83–90, response normalization, response validation, overflow refusal,
and their regression tests remain. Legacy regex behavior is restored with its
known limits; this is not a claim those limits are fixed. Backend and extension
contract selection must precede new regex implementation work.

Cost: the regex findings remain unresolved. Benefit: the branch no longer
carries an unapproved custom engine. The three safety fixes remain isolated
and reviewable without accepting that engine.


**D-33 · Kernel 0.3: extensions are declared on the artifact, bound by the
host, and refused by name; regex leaves the core.** Implements D-31's
direction as a mechanism (kernel §10, `portability.md`, `extensions/`).

- **Declaration.** A top-level `entry.extensions = {"<family>/<name>":
  version}`, must-understand, at most one contract per family. The model
  is JSON Schema's `$vocabulary`: the *keyword* (`pattern`) is interpreted
  by the declared contract. Rejected: reusing `versions.vocab` (those pin
  *referenced* entries and are optional — a loader ignores a missing pin;
  an extension must be understood or refused); a per-routing `dialect`
  field (a second copy of one fact, rule 1); overloading `requires`
  (already means capability facts on strategies and placements on cases).
- **Binding.** `Registry.extensions`: name → an `ExtensionBinding` with a
  version and a label (`python:re`, `go:regexp`). `Registry()` /
  `NewRegistry()` bind the kernel's natives — what the runtime's standard
  library can honestly do; `Registry(extensions=())` / `NewCoreRegistry()`
  bind nothing and are the core-only host. Discovery is
  `registry.describe()["extensions"]`, kept apart from model capabilities.
  A binding is a table entry: nothing runs, nothing starts.
- **Refusals.** `extension-undeclared` (fix `declare-extension {family,
  path}`) when a construct needs a family the artifact does not declare;
  `extension-unsupported` (fix `bind-extension {name, needs}`) when the
  host binds none; `version-incompatible` (existing, `match-version`)
  when versions disagree; `entry-malformed` at `extensions` for shape and
  ambiguity. Order: shape → one per family → support → version →
  undeclared use → admission. Rejected: folding "undeclared" into
  `entry-malformed` — the repair is adding a declaration, not editing the
  routing, and a fix names the real next action. Refusals fire at load
  and again at bind for adapters built in code; admission of each
  `pattern` string is the binding's job (kernel §10 rule 6), no longer
  the routing validator's — so a routing is structurally valid without a
  registry, and dialect errors carry the same code and path as before.
- **The first extension** is `pattern/legacy-re2` 0.1.0, defined as what
  kernel 0.2 required (RE2 subset, DOTALL, group 1, empty matches
  dropped) executed by the host engine, with its unspecified region
  stated in the spec. It is the migration bridge; the rigorous dialect
  plan 10 owes is a *different* contract, so this one never silently
  changes meaning.
- **Version 0.3.0**, not an additive 0.2.x: a bare `pattern` that loaded
  under 0.2 refuses under 0.3, and semver while major = 0 makes that a
  minor bump. Every corpus case's `kernel` pin moved; no expectation
  changed meaning. Migration is two edits (kernel §10).
- **Harness.** `requires` generalizes to `udf:<lang>` and
  `<family>/<name>`; a driver binds *exactly* what a case lists, so a case
  that forgets a requirement refuses instead of passing by accident, and a
  driver lacking one answers `unclaimed`. The Go claim is therefore "core
  + `pattern/legacy-re2`", byte-exact, with matching stream traces.
- **Not done, deliberately.** `udf:python` stays a placement, not an
  extension: unifying it would change the meaning of existing refusal
  codes without a corpus reason (portability.md notes it as follow-up).
  No new pattern dialect, no library comparison, no TypeScript update
  (it targets 0.2 and now refuses `version-incompatible`; plan 10 phase
  2). No migration tool: the two edits are documented, not automated.

Costs: 95 case files touched for a version string; artifacts using
`pattern` carry one more block; a routing's dialect error is found at
load/bind rather than at `Strategy` construction; `NewAdapter` grew a
parameter. Benefits: the core provably needs no regex engine (a core-only
registry passes every case that does not `requires` one); every
difference between hosts is a named contract or a named refusal; a
conformance claim is a list, not an adjective.


**D-34 · The default tier is declared by the constructor; exact tiers are
bound engines, added on demand; the authored-dialect task is withdrawn.**

- **Model: SQL dialects.** Engines legitimately diverge; what LMCC forbids
  is an artifact that does not say which engine it meant. So the tiers
  are: the host's native engine (`pattern/legacy-re2`, small stated
  divergence, no dependency — the common case, made easy); an exact
  single-language pin (a contract named for one engine at one version —
  identical wherever that runtime runs, refused elsewhere); an exact
  cross-language engine (RE2 bindings or Rust `regex` as WebAssembly, from
  a pack). All are rows of one table; the mechanism (D-33) never changes.
- **The constructor declares the default; the loader never does.**
  `lmcc.adapter` / `NewAdapter` write `pattern/legacy-re2` into the
  adapter when an inline strategy carries `pattern` and no `pattern/*` is
  declared, so the dumped artifact carries the line. `load` refuses an
  artifact without it (case 91 stands). Rejected: making a bare `pattern`
  *mean* legacy — then a default-tier artifact and a not-yet-declared one
  are indistinguishable on disk, and the day an exact tier exists nobody
  can tell which was meant. Explicit in the artifact, automatic in the
  tooling — a compiler writes the ABI into the binary without asking.
  Limit: named strategies are resolved at bind with a registry the
  constructor lacks; a pack that emits `pattern` is declared by hand (no
  std pack does). `declare_defaults=False` keeps the strict behavior for
  callers who want it.
- **Plan 10 phase 2 as written is withdrawn.** "Author a rigorous regex
  dialect with Unicode and capture cases; benchmark five libraries" was
  the residue of D-14's universal mandate, not a derivation from the one
  sentence. Regex is not in it; `between` and `line_prefixed` cover what
  adapters do; the corpus has one `pattern` parse case. Exact tiers are
  built when an adapter demands one, by binding an engine — never by
  authoring a grammar or a matcher (D-32 stands).

Cost: a code-built adapter now silently gets the default tier unless
`declare_defaults=False`; the trade is that the default is visible in
`dump()` and `plan.describe()`, and the artifact is what the loader
judges. Benefit: the common case costs zero keystrokes and stays honest;
the next agent inherits a demand-driven list, not a scheduled engine.


**D-35 · Kernel 0.4: the wire is lm15.** lmcc's messages were "lm15-shaped"
by intent and drifted in three places: parts said `kind` (lm15: `type`),
messages said `content` (lm15: `parts`), and `system` was a message
(lm15: a request field; message roles are `user|assistant|tool|developer`).
Since lm15 exists — or will — in every language lmcc does, the drift
bought nothing and cost a translation layer in every host. Ratified:

- **The wire layer *is* the lm15 contract** at the commit in
  `contract/LM15_CONTRACT_PIN`. `render()` produces an lm15 request minus
  its model (`{"system"?, "messages", "config"?, "tools"?}`); `parse()`
  takes text, an lm15 message, or an lm15 response; `feed()` takes lm15
  deltas as canonical JSON. lm15's own `request_from_dict` /
  `response_to_dict` are the whole typed bridge; nothing is renamed.
- **The kernel still imports no lm15.** The corpus is data, fed to a Go
  binary over stdin; if the kernel took lm15 *objects*, byte-exactness
  would be a claim about every language's serializer, and the kernel
  would be pinned to lm15's release cadence in every language at once. A
  contract commit changes deliberately and rarely; that is the pin. The
  typed face lives beside the kernel (`python/lmcc_lm15`, like
  `lmcc_dspy`), imports lm15, and is gated by `./check` step 7 against a
  venv built from a **git commit** — lm15 is not on PyPI; a version pin
  would be fiction. Bumping the commit is a reviewed edit.
- **Controls are a partial lm15 request**, deep-merged (`config.<field>`,
  `tools`), validated at the top two levels against the pinned `Config`
  field list, opaque below (lm15's own rule: provider knobs go under
  `config.extensions`). Rejected: no validation (the claim would be
  unenforced) and a full schema (lm15 duplicated in two kernels).
  `control-conflict` now means a disagreeing *leaf*; agreeing is fine.
  The lens patch nests under `config`. `native_reasoning` gained
  `controls.config.reasoning` (options `effort`, `thinking_budget`) — the
  live run had exposed that it only *read* thinking and left asking to
  the caller; a strategy does everything its meaning needs.
- **`system` messages lead the template** (else `entry-malformed`) and
  fold into the request field; mid-conversation instructions are lm15's
  `developer` role, now a template role, fragment target, and placement
  target. Rejected: keeping `system` as a message in `messages` (lm15
  would refuse the role) or moving a late `system` silently to the top
  (reorders what the author wrote).
- **`RenderResult.request(model)`** is one object — what a calling
  convention should pin. Rejected: keeping `messages` + a flat `patch`,
  the very shape lm15 could not consume.
- **lmcc's own stream events keep `kind`.** They are lmcc objects, not
  lm15's; renaming buys no compatibility and the corpus trace digests
  use them. Stated, not hidden.
- **Version 0.4.0.** Breaking on every axis above; every corpus case was
  re-spelled by script and reviewed through both drivers; cases 66 and 67
  were hand-edited to be *valid lm15* (a `function` tool item; a real
  control path) — their purpose unchanged, their bytes now something lm15
  accepts. Cases 96–98 pin the new rules. `lmcc_lm15` proves the loop
  offline (`tests/lm15`) and live (`python/integration/lm15_reasoning.py`:
  three strategies, two providers, batch and stream, the strategy asking
  for thinking itself).

Costs: 98 case files and every doc example changed spelling; adapter
authors write `controls.config.reasoning` instead of `controls.reasoning`;
a late `system` message that used to render now refuses; the lm15 pin is
a commit that must be bumped by hand. Benefits: no translation layer in
any language; `render().request(m)` is the call; a strategy's patch is a
valid partial request by construction; every wire word has one owner.


**D-36 · The plan asks the provider to stop at its tail.** `skeleton()`
already knew the reply's last close or tail; forwarding it as a stop
sequence was a chore left to the caller — the kind of gap the calling
convention exists to remove. Now, when the model declares the new
capability fact `stop_sequences` (vocabulary 0.2.0) and the lens's
skeleton has `stops`, bind merges `config.stop` into the patch as the
skeleton's control (`control-conflict` if a strategy set a different
list). Parsing is unchanged: providers omit the stop sequence from the
reply and the derived lens already reads a capture to its close *or end
of text*. Gated by a fact rather than assumed because the fact is real:
OpenAI's Responses API has no stop field and lm15 refuses to omit it
silently — the live run hit exactly that, so `stop_sequences` is
declared per model, like every other fact. Case 99 pins the bytes.
Cost: one more fact to declare; a caller who wants *no* stop on a model
that supports it leaves the fact out. `prefill` is the same story for
the other end of the reply and stays a stated gap until lm15 spells it.


**D-37 · Kernel 0.5: tools and citations are live roles; three kernel
mechanics they needed; the whole-reply pattern.** Plans 03 and 04, done
native-first and proven live (two providers, both tiers) before the
corpus was written. Every value shape is lm15's (`FunctionTool`,
`ToolCallPart`, `CitationPart`); lmcc invented none.

- **A call turn is a reply, not an error.** A routing may declare
  `suffices: true`; when it captures, outputs the lens cannot find are
  omitted instead of refusing `parse-missing-fields`. Rejected: making
  the caller read `.partial` (hostile), and nullable outputs (weakens
  every normal reply). Generic data on the routing; the kernel knows no
  role name.
- **`via`: a placement's own spelling** — the one stated exception to
  format-by-type, scoped to placement. A tool spec is an lm15 `function`
  tool in `Request.tools` and a line of text in a system prompt; one type,
  two transports, and a `choose` between them in one artifact must work.
  Rejected: two artifact-level formats for one type (impossible), a
  format with two `emits` (the kernel checks placement kinds by it).
- **`turns` + the probe** (plan 03). `turns.call`/`turns.result` spell
  `tool_call`/`tool_result` parts as text for models without a native
  channel; `tool` messages become `user`. At bind the kernel renders a
  synthetic call and reads it back through the strategy's own routing
  and format — `turns-drift` if they disagree: the lens law at strategy
  level. Native turns need no face: lm15 messages pass verbatim.
- **Text-tier ids are assigned** (`call_1`…) because the model has none
  to give and `Message.tool(id, …)` must still round-trip. Stated.
- **Native citations = what lm15 returns:** citation parts from provider
  search; the strategy adds the `web_search` built-in. lm15 exposes no
  per-document citation flag, so supplied sources
  (`citations.sources`, formerly reserved as `citable`) go live only
  through `inline_citations`. Different meaning, different program; not
  papered over.
- **The whole-reply pattern.** Search mode ignores reply patterns and
  answers in prose. "The whole reply is the answer" was inexpressible
  (a bare slot with no anchor refused `not-lensable`). Now a template
  whose only visible output is one bare anchorless slot captures the
  whole reply (§4); loops and multi-field patterns still need anchors
  (case 33 stands). Cases 113–114.
- **Placement into a message appends after a blank line**, like a
  fragment (case 66's bytes changed once, deliberately): the live run
  showed glued text.
- **Version 0.5.0**: the new strategy keys make 0.4 loaders refuse these
  artifacts. Cases 100–114; five formats, four strategies in both packs;
  `native_tools` and `fenced_tools` are the same program on gpt-4.1-mini
  and claude-sonnet-4-5 through a real tool loop; `inline_citations` and
  `native_citations` (web search) likewise.

Costs: three more strategy keys; a placement's format can differ from
its type's (visible in the artifact as `via`); a call turn's values lack
fields a caller might expect (they check `calls`); the template order
for a tool loop is `system, user, history` — the live run showed
`history` before the question invites a plain reply. Benefits: tools
and citations are conduct, not names; one program, any model; nothing on
the wire that lm15 did not define.

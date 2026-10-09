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


**D-38 · Formatted turns and representative samples; raw-code heredocs.**
A JSON `{input}` slot cannot spell raw code, and the universal sample
`probe({probe: true})` cannot test a single-tool code reader. Kernel 0.6
adds two declarations: `turns.input_format` (a named format reference) and
`turns.probe` (a representative `{name, input, id?}` call). No declaration
means the old JSON writer and sample, unchanged.

The format owns body spelling; the strategy owns the envelope. History and
the bind-time sample call the same bound writer. References in every choice
branch resolve at load; dump pins their vocabulary versions. A writer must
accept an object input and emit text. A sample write or read refusal becomes
`turns-drift` at bind; a real history write fails at render with its ordinary
format error or `value-collides`. Competing history writers in a formatted
plan refuse rather than silently choosing the first. Plan inspection names
the selected argument format and version.

Rejected: adding arbitrary expressions such as `{input.code}` to the
kernel template language (duplicates format work and couples syntax to
argument schemas); bypassing the probe for raw code (conceals drift); or
pretending that one synthetic sample proves all round trips. Equality
covers name and input, not transport-generated IDs. More samples and fuzz
cases belong in tests, not a claim that the bind-time sample proves all
programs.

The std pack ships `code_arguments`, `code_calls`, and `heredoc_tools`.
The calls reader delegates to the same raw-code argument format, using raw
captured text rather than the stripped `Span.text`. Indentation, CRLF,
Unicode, empty code and trailing newlines are preserved. Marker occurrence
anywhere in code is rejected on writing: this is deliberately more
restrictive than a real shell heredoc. The existing core `between` extractor
remains a literal scan, not a strict shell grammar or truncated-block
validator. The application must never execute unparsed reply text.

Costs: a breaking minor pin while major is zero (0.6), one configured tool
per shipped heredoc strategy, IDs unique only within a reply, conservative
marker exclusion, and two format references/options to keep aligned. The
probe catches configuration drift rather than guessing missing options.
A malformed/incomplete reply may remain prose; sandboxing, permissions,
call validation and loop limits remain with the application. The runnable
notebook uses simulated replies/results and does not execute generated code.

Evidence: corpus 116–127, Python and Go regression tests and every-split
stream replay. The previous Go serializer dropped inline `turns`; preserving
those declarations is now pinned by the nested-choice roundtrip case.

**D-39 · Kernel 0.7: one record, the turn, replaces demos and history.**
Examples, past exchanges and the exchange in progress are all turns: one
call of one signature, kept as values (inputs, steps, outputs), with each
model step's message as it came and a hash of the request it answered.
The plan writes turns with its own writers; the template places them in
named slots, as messages (`{"directive": "turns", "slot"?}`) or as text
(`{% for m in slot %}` with `m.role`/`m.kind`/`m.text`, and a
`{% if slot %}` guard). `demos`, `history`, lm15-message history items and
`render(demos=, history=)` are removed without aliases: there are no users
to migrate, and two ways to say one thing is the drift rule 1 forbids.

Why values, not messages: a conversation kept as messages freezes the
spelling it was recorded in, so switching adapters left old conventions in
the prompt, and hidden fields (reasoning, calls) had readers but no
writers. Why keep the message too: a reply holds more than its fields —
prose outside them, opaque provider parts (signed thinking, continuation
data). So the adapter chooses, as data (`replay`): `"recorded"` (default)
sends a recorded reply verbatim when this plan reads it back into the same
values, else writes it from values; `"values"` always writes from values,
replaying only parts no text can forge. Every hidden text-routed output
needs a writer — derived from `between`/`line_prefixed`, declared
(`turns.write`, `turns.position`) or dropped on purpose (`turns.write:
null`) — checked at bind (`turns-drift`); fields that read the calls' own
span are projections and are never written twice (a prototype shipped
that duplicate; case 148 now pins it). The current turn is a turn, so the
live input is written once. Tool results pair with calls in order
(`turn-invalid` otherwise); assigned ids written as native parts are
qualified per request (`s<k>_<id>`), provider ids never change; a tool's
non-text result parts follow its text on text transports (a 0.6 bug
dropped them). A turn carries its signature's fingerprint (instructions
excluded, so optimizing prose does not orphan recordings); a stored
request is its hash, so a stored conversation grows with its replies, not
quadratically. Placements and fragments now target only the template's
own messages (a 0.6 bug put the live sources into a past question).

Rejected: a `kind` on turns ("example" | "actual") and slot filters in the
kernel (presets; selection, windows and memory belong to the caller);
`env:` placement for RLM-style variables (control flow's concern, served
by a role + strategy + format in a pack); storing whole requests (quadratic
growth); byte-exact replay of whole requests as a kernel promise.

Costs: every 0.6 artifact refuses `version-incompatible`; the Go kernel
stays at 0.6 until ported — held to the `kernel-0.6` corpus with an exact,
declared code gap — and TypeScript is further behind. `replay: "values"`
loses a tool call's own continuation data (the calls format reads id,
name, input); the default keeps it. A text-form slot cannot hold native
parts and refuses rather than drops them. Id qualification and native
replay are unverified against live providers. Evidence: corpus 03, 47,
53, 54, 103, 107, 116, 122, 128–148 (each new rule caught by a deliberate
break of the kernel), `tests/test_turns.py`, howtos 11–13.

**D-40 · Kernel 0.7 vocabulary: one word, one meaning; named by what it does.**
The words are judged by how people learn: a few new ideas at a time,
recognition over recall, one meaning per word, familiar words over coined
ones, matching names for matching jobs. `docs/glossary.md` defines every
term in one sentence, in the order it is needed, and is the reference for
names. The renames, with their reason:

| 0.6 | 0.7 | why |
|---|---|---|
| strategy | transport | says what it is: how fields of one purpose travel |
| role (field), `Role[…]`, `@role` | purpose, `Purpose[…]`, `@purpose` | "role" is lm15's word for a message's speaker; one word, one meaning |
| lens, `parse: {kind}` | reader, `reader: {kind}` | "lens" is borrowed jargon; "parse" also names the verb |
| span | capture | the piece of reply found for a field; a word regex users know |
| `routings` / `placement` | `find` / `put` | a mirrored pair: where an output is found, where an input is put |
| `consume`, `suffices` | `remove`, `complete_reply` | say the effect |
| `fragments`, `controls` | `tell`, `request_settings` | text that tells the model; settings added to the request |
| `via`, `visible` | `written_as`, `in_template` | say what and where |
| `emits` | `writes` | pairs with `reads` |
| `channel:<type>`, `controls.<key>` | `part:<type>`, `request.<key>` | lm15's word "part"; the request is where the value goes |
| strategy `turns: {…, write}` | transport `spelling: {…, value}` | "turns" meant three things; now it means turns |
| patch (of a request) | request settings | one name for one thing |

Error codes follow: `unknown-reader`, `unknown-transport`, `reader-error`,
`not-readable`, `purpose-ambiguous`, `setting-conflict`,
`format-capture-mismatch`, `format-put-mismatch`, `spelling-drift`; fix
action `assign-purpose` (parameter `purpose`). The signature's JSON key
`role` became `purpose`, so the turn fingerprint changed (case 128).

Kept: signature, adapter, template, format, plan, bind, render, parse,
capabilities, turn, and lm15's words (message, role, part, request,
config). Kept "placement" only for placing shipped code in a runtime
(`place-udf`, `udf-unplaceable`), a different idea from `put`.

Costs: a second breaking change in 0.7, before any release (no pin
change: 0.7 was never published). Longer names in a few places
(`request_settings`, `complete_reply`). The Go kernel, pinned at 0.6,
keeps every old word until it is ported; its codes are mapped exactly in
`tests/test_coherence.py`. Not yet done: the check that someone new can
predict each setting from its name alone (plan 12, open item).

**D-41 · Python is the one implementation while the language is designed.**
The Go kernel is removed from the tree. It proved the contract portable up
to kernel 0.6 (a second, independent kernel passing the corpus byte for
byte, D-18 onward), and that code is kept whole at the git tag `kernel-0.6`,
with the corpus it passed. Kernel 0.7 changed the language twice (turns,
D-39; vocabulary, D-40), and more changes are expected from real use; a
second kernel frozen at 0.6 only added upkeep and old words. TypeScript
stays on its branch (`ts/cleanroom`). Other languages are rebuilt from the
contract when it settles.

What stays language-neutral: the spec, schemas and corpus; the ASCII text
rules; the harness's driver protocol, now exercised by a Python driver
(`contract/harness/python_driver.py`, `tests/test_driver_protocol.py`)
that runs the whole corpus through a subprocess and compares its stream
traces with the reference, and that a port copies.

Cost, stated: nothing now proves the contract implementable twice. The
cross-kernel code-set comparison is replaced by a one-sided pair of checks
(every documented code is raised; every raised code is documented), which
catches dead or undocumented codes but not a rule only Python can follow.
Host-language assumptions can creep in unnoticed until the next port; the
port is the test. Removed with Go: `./check`'s Go step, the `--cases`
harness option, the Go sections of the reference, and the `GO_AT_06`
declarations.

**D-42 · The derived reader repairs misspelled markers, reports every
tolerance, and refuses a cut reply (kernel 0.8, §4a).** Real models
misspell the layout they are shown (`<Answer>`, `**Answer:**`,
`[[## answer ##]]`), and 0.7 refused those replies while it silently
read a reply cut at the length limit as a finished answer. Both were
wrong in the direction that matters: brittle where the meaning was plain,
lenient where it was not.

Ratified with the maintainer on 2026-09-23. The choices:

- **In the kernel, on by default.** The repair is a reading rule of the
  derived reader, like the whitespace-stripped anchors it already had, not
  vocabulary: only the kernel can check it for ambiguity, keep the §8
  refinement law and report it. Most adapters are never configured, so
  the default decides how reliable LMCC is. `"markers": "exact"` turns
  it off.
- **One rule, not a list.** A marker matches ignoring ASCII case, spaces,
  and `*`, `_`, `#`, and its span widens over markdown decoration. It is
  general over signatures because it is stated over markers, never over
  field names. Line feeds are content, so a repair never joins lines.
- **The exact spelling wins.** A marker written exactly anywhere turns
  every loose spelling of it into content. So a reply 0.7 read keeps its
  values, and a model that mentions `answer:` in its reasoning does not
  make a correct reply ambiguous. Cost: a streamed reply holds from its
  first misspelled marker until `finish`, because a later exact marker can
  still undo the repair.
- **Never a guess.** Two repaired spans that overlap, or two repaired
  anchors of one field, refuse `parse-ambiguous`. No closest-match
  scoring, no second model call.
- **Everything reported.** `plan.read` returns the repairs with the
  values, including the tolerances 0.7 applied silently (`unclosed`,
  `ignored`), so a caller can count a model's slips, alert on them or
  refuse them. A missing close at the end of the text is not reported:
  a provider stop sequence produces exactly that.
- **Repaired replies replay from values** (§3a), so a conversation shows
  the model the layout, not its slip. `ignored` text does not trigger
  this: chatter around an answer is not a layout error.
- **Truncation is correctness, not a repair.** With `finish_reason:
  "length"`, an output that is missing or ran to the end of the text
  refuses `parse-truncated`; the caller decides whether to retry with more
  tokens. Only lm15 responses carry the reason; a bare text or message
  is read as before.

Costs, stated: one behavior change for replies 0.7 read (decoration
touching an exact marker is now removed from the neighboring captures,
and reported); a new refusal for cut replies that 0.7 accepted; a new
method (`read`) beside `parse`; the stream holds after a slip. Rejected:
a repair list shipped as vocabulary (a pack cannot keep the kernel's
guarantees, and the obvious repairs would be re-declared by every
adapter); per-field alternative spellings (they name fields, so an
adapter stops being general); repairing everywhere, exact or not (it
would make correct replies ambiguous). Not done in 0.8, as stated in
the kernel's gaps: find rule delimiters, provider parts, forgiving
default value reads.

**D-43 · Value slips and reasoning tags are repaired too; one `strict`
switch (kernel 0.8, before release).** Ratified with the maintainer on
2026-09-23, amending D-42 before 0.8 was published.

- **Values.** When the kernel's exact read of a scalar, enum or nullable
  refuses, a forgiving read tries: one pair of quotes or backticks off,
  one trailing period off, `null`/`none` in any case for a nullable, an
  enum member in another ASCII case when exactly one matches (§7a).
  Reported as `value` repairs. It runs only after the exact read failed,
  so no value 0.7 read changes; strings are never touched. `N/A` stays a
  refusal (it could be content), and so does `42.0` (a different
  spelling, not a slip). Only the kernel's default reads forgive; a
  format someone writes reads what they wrote it to.
- **Find rule delimiters opt in.** A `between` rule may declare
  `repair: true`; its delimiters are repaired by the §4a rule in a first
  pass over the reply, before the find rules. `reasoning_tags` opts in
  (0.3.0). Opt-in, not default, because a find rule can capture raw code
  (`heredoc_tools`), where a loose match inside the code would cut it.
  The reader's own pass runs after the find rules, so a tag named inside
  removed reasoning is never an exact marker for it.
- **One switch.** `strict: true` on the adapter turns every repair off.
  It replaces D-42's `reader.markers: "exact"`, which was never
  published: one plain word for "read exactly or refuse" is easier to
  learn than a per-kind option, and nobody asked for markers strict but
  values forgiving (a custom format still gives that).
- **Replay.** A recorded reply that needed a value repair is written back
  from its values, like one that needed a marker repair.

Found live the same day (`python/integration/lm15_repairs.py`, 9
models, 3 layouts): frontier models wrote every layout exactly;
`gpt-oss-20b` once put a label mid-line (`... experience. Sentiment:
negative`), so a marker's leading line feeds became optional (case 169);
small models (3B–12B) mostly abandoned the markers altogether, which
stays a refusal — reading bare values by their order would be a guess —
now with a hint that says so. A reasoning model that spent its tokens
thinking was cut off and refused `parse-truncated`, as intended.

Costs, stated: two passes and two holding stream stages; `describe()`
gains `strict` and the stream's `repairs` entry; `reasoning_tags` moves to
0.3.0, so artifacts pinning 0.2.0 refuse `version-incompatible`. Not done:
`line_prefixed` prefixes and provider parts (kernel gaps).

**D-44 · Plan 09's defects, rechecked against kernel 0.8 and closed.**
On 2026-09-23 every Bin 1 finding of the clean-room audit was re-run
against the Python kernel. Already fixed: A4, B5, E3 (batch 1), F23
(turns replaced demos), B2/D1 (pointers had been corrected). Withdrawn
with the custom regex work: E6 (D-31). Fixed now, each with a case:

- F19 — `prefix()` counts a message an input is `put` into as
  input-dependent, and has no stable prefix when the system text depends
  on inputs (170, 171).
- F14 — an input with a bare slot that is also `put` refuses
  `field-double-covered` (fix `edit-template`) instead of being sent
  twice (172). Refusing, not silently dropping the slot: the audit's
  proposal would have hidden an authoring mistake.
- G15 — a request `put` overlapping a fixed setting or another `put`
  refuses `setting-conflict` at bind (173).
- A6 — the capability vocabulary is closed, as D-06 and D-29 (R2, option
  B) ratified: a predicate or `requires` naming an unknown fact refuses
  `entry-malformed` at its exact path (174). Case 78's undeclared
  `prefill` became `stop_sequences`, a deliberate corpus repair; its
  expectation keeps its meaning (no branch applies). A `choose` branch's
  `when` is now validated at all. The caller's capability dict may still
  hold extra keys.
- G25 — a media value whose `type` contradicts the field's kind refuses
  `value-invalid` (175) instead of being relabeled.
- G4 — `scaled_number` with `round` declares `round_trip: false`
  (0.2.0); a rounded output cannot be written into a past turn (176).
- A1 — kernel §5's resolution list puts the artifact's `*` after the
  kernel default, as the code and cases 48, 49, 107 always did.
- D2 — the harness requires a refusal's stage to equal `expect.at`.
- D3 — the harness requires each field's streamed deltas to join to
  exactly the raw text batch captured, and tests prove it catches a
  stream that drops them (`tests/test_harness_checks.py`).

Costs, stated: artifacts naming private facts in predicates now refuse;
`scaled_number` moves to 0.2.0; templates that both slot and put one
input now refuse instead of sending it twice.

**D-45 · A guard may name an input (kernel 0.8).** `{% if context %} …
{% endif %}` renders its body when the input has a value (not null, `""`
or `[]`). Ratified with the maintainer on 2026-09-23 as the kernel half of
"leave bulky inputs out of past turns": the session layer decides what a
past turn keeps (the policy), the template says how a turn without that
input reads (the mechanism). Before this, a past turn without its
documents refused `missing-input`, so a conversation over retrieved
context could not trim old context at all.

Costs, stated: a guard naming neither a placed slot nor an input now
refuses `unknown-slot` at bind instead of `template-syntax` at construct,
because only bind knows the signature (no case pinned the old timing; one
unit test moved). A guarded input also makes its message input-dependent
for `prefix()`. The guard tests presence, not truth: a boolean input
`false` still renders the body. Rejected: an expression language
(`{% if x and not y %}`), and conditionals on outputs (the reply's shape
must not depend on values, §4).

**D-46 · The prefill: a template's last assistant message (kernel 0.8,
§3).** Ratified with the maintainer on 2026-09-23. Using a prefill is an
adapter author's choice, but 0.8 could not express it: a trailing
assistant message was sent, and the reply that continued it could not be
read (`parse-missing-fields`); nor could an adapter say which models
accept one (no fact). The language now owns exactly those two things.

- The template's last message, when `assistant`, is the prefill: literal
  text, sent last (after the current turn's steps), trailing whitespace
  never sent. Every read of the reply reads the prefill as sent plus the
  reply; a recorded step stores the whole message and is read whole.
- It is sent only under the new fact `assistant_prefill` (capabilities
  0.3.0), and otherwise simply not sent, with reading unchanged. Chosen
  over refusing at bind because a prefill changes no meaning — the reply
  is readable either way — exactly like `config.stop` under
  `stop_sequences` (D-36); refusing would force two adapters for one
  layout. `describe()["prefill"]` says whether it is sent.

Found live: Anthropic rejects a prefill ending in whitespace (HTTP 400),
hence the strip. Checked live on claude-haiku-4-5, llama-3.2-3b and
qwen-2.5-7b, with and without prefill. Costs, stated: a template that
ended with an assistant message for another purpose now means a prefill
(no such template in the corpus or the docs); on a model not declaring
the fact, the author's message is silently not sent — visible in
`describe()`, not in the request. Whether a prefill helps a given model is
the adapter author's question, not measured here.

**D-47 · Parts sit at positions in the reply; captures keep them
(kernel 0.8, §4b).** Ratified with the maintainer on 2026-09-23 as the
answer to "replies that interleave text with other parts". Before, the
reader read the text parts as one text and every other part was only
reachable by type (`part:<type>` find rules), so a template could not say
"the image goes here": an image output in the pattern refused
`parse-value`, and a past turn with one refused `turn-not-renderable`.

The rule: a part that is not text and that no `part:` rule reads is an
atom at its text position; positions follow every text edit; a field's
capture holds the atoms inside its section, in order, while its `.text`
stays exactly what it was. Writing is the mirror (a parts-writing output
is written at its hole), so one template describes both directions again.

Chosen over alternatives: a sentinel character in the text (it would
break the pinned rule that other parts are transparent to markers, plan
09 H4, and make streamed text depend on invisible characters); a new
reader kind for mixed replies (a second description of the same layout);
positional `part:` rules (they name positions, not meanings). No existing
value changes: text formats read the same `.text`; only replies that used
to refuse now read.

Found live (gemini-2.5-flash-image, three runs): once text, image and
text landed in the three fields; once the model drew no image (refused
`parse-value`); once it stopped after the image (refused
`parse-missing-fields`). The model is the unreliable part, not the
reading. Not covered, stated in §4b: atoms inside a find rule's match,
structured values made of several parts (vocabulary: a format that reads
a parts capture), stray text beside an image in a media field (the media
default reads the image and ignores the text, unreported), and streaming
events for atoms (they arrive with the values at `finish`).

**D-48 · `replay: "verbatim"` (kernel 0.8.2).** Ratified with the
maintainer on 2026-09-23 for training on lmfn programs through verifiers.
A trainer builds one token sequence per conversation path, and a path
holds only while each request extends the previous one exactly; the
default `recorded` replay rewrites a repaired reply in the template's
spelling (D-42) and writes nothing for a reply that could not be read,
so one episode would split into several sequences, and the model would
be trained on text it never wrote. `verbatim` writes every recorded
reply exactly as it came. A step from an unreadable reply is recorded
with empty `outputs` and its message; the other modes write nothing for
it, as before (case 190). Costs, stated: under `verbatim` the model sees
its own slips again, which is the point for training and the wrong
choice for serving; it is opt-in, and `recorded` stays the default.

**D-49 · `{% else %}`, and `false` is absent for an input guard (kernel
0.8.2).** Ratified with the maintainer on 2026-09-23. The alphabet-sort
port showed a task whose first turn is worded differently from the rest;
one function per task means the difference must be an input
(`first_turn: bool`), and the template must word both cases. D-45's guard
rendered its body for `false` (presence, not truth) and had no else, so
a boolean input could not choose between two wordings.

- An input guard is false when the value is absent, null, `false`, `""`
  or `[]`; `{% else %}` renders when the body does not. One else per
  guard, no `elif`, no expressions: a boolean or an optional input is
  the condition.
- An input named only by a guard counts as used (`field-uncovered` no
  longer fires): it shapes the prompt.
- In a past turn's user side, an input guard reads that turn's own
  inputs, so the message is written exactly as it was sent (training
  needs each request to extend the previous one). A turn-slot guard
  renders neither branch there, as before; a turn-slot guard inside a
  user message therefore re-renders differently once its turn is past,
  and breaks that exact extension — stated here, refused later if it
  proves a trap.

Costs, stated: changes the output of a published rule (D-45, 0.8.0) for a
`false` input, from body to nothing (no case pinned the old behavior);
templates that relied on a boolean `false` rendering the body now do not.

**D-50 · The forgiving read takes a period outside the quotes (kernel
0.8.3).** Ratified with the maintainer on 2026-09-26, from a review of the
banking77 work: models writing markdown answer `` `card_arrival`. `` — the
value in backticks, then the sentence's period. §7a removed the quotes
first and the period second, so the period outside the quotes blocked
both and the reply refused. The forgiving read now also tries the text
without one trailing period and then without one pair of quotes, after
the two texts it tried before, and folds enum case and `null`/`none` over
all three in that order. Case 194.

Costs, stated: only refusals change (they now read, reported as `value`
repairs); every text 0.8.2 read gives the same value, because the new
candidate is tried last. Still refused on purpose: text around the value
(`The answer is card_arrival.`) — that is a sentence, not a slip.

**D-51 · Descriptions: what the model is told about a type is data
(kernel 0.8.3).** Ratified with the maintainer on 2026-09-26, from the
banking77 review. The distilled student learned the 77 intents, so its
adapter tells it `Intent: <intent>` instead of the list. The only way to
say so was a code format (`make_format(write=..., read=..., describe=...)`)
that copied the kernel's read, with three consequences found live: the
adapter could not be dumped (a lambda cannot ship), the copied forgiving
read bypassed `strict`, and its repairs went unreported. The format's
`describe` was the one face that differed, and it is prose, not code.

A `formats` entry may now be a description `{"describe": text}`, and a
reference may carry `describe`. It replaces the chosen format's
`describe` and nothing else; a description alone chooses no format
(resolution continues), so the kernel default keeps its read, repairs
and `strict`. The applying text is the first of type name, then
structural keys, then `*` only for a format that came from `*` — a
wildcard never re-describes a scalar, as it never re-spells one (D-19).
A field's `desc` still wins: it is about this field, a description is
about a type. Cases 195–201; each order rule was broken on purpose and
caught by 199.

Chosen over: a std format `scalar` with a `describe` option (a pack
would have to claim the kernel's forgiving read, a privilege packs do
not have); making the forgiving read available to code formats (the
read is only honest where the kernel owns the grammar); a template
construct (four constructs, by design). Costs, stated: `describe` means
source code in a shipped UDF and text here — the same face in its two
forms, distinguished by `language`. A reference with a key other than
`use`, `options`, `describe` now refuses `entry-malformed`; it was
silently ignored before (the schema already forbade it).

**D-52 · A type bound at runtime lowers through its binding (Python
host, kernel 0.8.3).** Found in the lmfn analytics review (2026-09-23):
`annotation_to_shape` promised that foreign types "resolve through the
host socket", took a registry, and never asked it, so
`lmcc.format(pl.DataFrame, ...)` could not work — the signature refused
`unmapped-type` before any format was looked up. A type binding now
also says the shape the type lowers to (`shape=`, default `{}`); a
signature built without a registry consults the default one, as bind
does. The kernel's own constructs still lower mechanically first; the
binding is consulted only for what would otherwise refuse, and the hint
of that refusal now names `lmcc.format`. No contract bytes change: this
is the Python frontend; the artifact still names the type only.

Costs, stated: `{}` tells a JSON reader's schema nothing about the value
(any JSON); declare `shape=` when a schema matters. A list of a bound
type still needs its own format (§5: the kernel never nests formats).

**D-53 · lm15 1.0.1: data parts are read as text, and a reading carries
probabilities (kernel 0.8.3, `reader/json_object` 0.2.0).** Ratified with
the maintainer on 2026-09-26, from the banking77 review. Almost every
banking77 experiment needed a distribution over the 77 intents (soft
labels, confidence, escalation, Jev's answers), and all of it bypassed
lmcc: a reading held one value per field. lm15 added judgments on
2026-09-17 (`DataPart` with `probabilities` and `method`,
`Config.probabilities`, MAP-14), and lmcc refused `config.probabilities`
because its pinned `Config` list predated them. Worse, MAP-14 §3 makes
every wire answer a judgment request with a `data` part in place of the
text, so the JSON reader would have read nothing on any current lm15.

- The pin moves to lm15 1.0.1 (contract 3763eec). The pinned `Config`
  list gains `seed`, `frequency_penalty`, `presence_penalty`,
  `probabilities`, and `logprobs` (already in lm15 at the old pin;
  missing from lmcc's list by oversight).
- A reply's data part is text in its place: its value's compact JSON,
  numbers by §7a. One rule serves every reader, find rule, §4b and
  streaming, and it is lm15's own rule for a data part on a text wire
  (2026-09-19 D3), except numbers: `7.0` is `7`, so every implementation
  reads the same value — lm15's `json.dumps` spelling is Python's.
- `plan.read` and `stream.finish` return `probabilities` and
  `measured_by`, verbatim from the data parts, checked before reading.
  They are a measurement of the reply, not an output: the signature
  stays the task, and a model that cannot measure leaves them `{}`.
- `reader/json_object` 0.2.0 takes `probabilities` and asks for it with
  `config.probabilities`; it now refuses unknown spec keys at load
  (0.1.0 ignored them, so an old runtime would silently not ask). Every
  reader is now resolved at load, like formats and transports.

Chosen over: a signature field with a `probabilities` purpose (the
signature would change with the model's abilities, and one purpose
binds one field while the answer may hold several judgments); passing
parts to vocabulary readers (a second read path beside the text); token
logprobs (`Response.logprobs`) rebuilt into a distribution, as the
OpenRouter scripts did by hand — that is lm15's to measure (its vLLM
trie, MAP-14 D7), not the calling convention's to estimate. Cases
202–208; every rule was broken on purpose and caught (the hex case of
`\u00xx` only after case 203 gained U+001F).

Costs, stated: artifacts pinned at `reader/json_object` 0.1.0 refuse
`version-incompatible` until their pin moves (seven corpus cases moved,
nothing else changed in them). Probability keys stay lm15's strings
(`"true"`, `"0"`); a host that wants typed keys lifts them itself.
`measured_by` is per field although lm15's method is per part. Replies
with data parts were not valid at the old pin, so no reading changes.

Added the same day, within `reader/json_object` 0.2.0: a field's `desc`
is its property's `description` in the schema the reader sends. Found
when reproducing the banking77 Jev run through lmcc: lm15's judgment
convention takes the question from the description (MAP-14 D4), and the
reader dropped every desc, so the question could not be asked. It is
JSON Schema's own channel and every enforcing provider reads it. Cost,
stated: the request bytes of cases 22 and 28 changed (their fields have
descs); a desc now costs its tokens twice when the template also prints
`{format}`.

**D-54 · TypeScript joins as a second kernel; every JSON the kernel writes
spells numbers by §7a (kernel 0.8.4).** Ratified with the maintainer on
2026-09-26 ("we are ready to bring lmcc to typescript … make sure they
serialize to the same data"). Amends D-41: the language has settled enough
that a second implementation is the test it lacked.

- **The kernel.** `ts/` holds a TypeScript kernel (`ts/src`), the standard
  pack (`lmcc/std`) and the lm15 bridge (`lmcc/lm15`, on `@lm15/lm15`
  1.0.0-rc.2, whose contract pin fe5cdf9 descends from ours, 3763eec, with
  no change to the wire vocabulary lmcc reads). It is a port of the Python
  reference read against this spec, not a clean room: the reference is where
  the corpus's behavior lives. It imports nothing (no `node:` module either),
  so it runs in browsers and workers. `./check` step 7 holds it: types, unit
  tests, the corpus through the driver protocol with every stream trace
  compared to Python's (205 of 211 pass; the 6 that need `udf:python` are
  unclaimed), a differential check of everything both kernels serialize
  beyond the corpus (`plan.describe()`, `dump`, fingerprints, request
  hashes, readings, recorded steps and turns, prefixes, stream results,
  refusal data) on every case and 2,640 fuzzed replies, and the replay
  through Python of 19 recorded live exchanges with five providers.
- **The finding that changed the contract.** The canonical JSON behind the
  `signature` and `request` hashes (§3a) and a call's `{input}` (§6) were
  whatever Python's `json.dumps` wrote: `1.0`, `1e-07`. JavaScript cannot
  reproduce that (it has one number type), so a signature whose shape held
  such a number had a different fingerprint in each language, and a recorded
  turn could not cross. Both now spell numbers by §7a, like a data part
  already did (D-53): integers in decimal, other numbers by ECMAScript
  `Number::toString`; strings escape exactly as a data part's. §6 also said
  `{input}` was "canonical JSON" while the reference (and case 107) wrote
  insertion order with `, `/`: `; the text now says what the bytes are.
  Cases 209 (a shape with `0.0`, `1.0`, `1e-07`, fingerprint pinned by hand),
  210 (a fenced call input `1.0`, `1e-07`) and 211 (keys U+0061, U+FFFF,
  U+1F600: code-point order, not UTF-16 order, which a JavaScript `sort()`
  gives and no earlier case caught) were authored by hand; 209 and 210
  failed on the old Python, and 211 was written when a deliberately broken
  TypeScript sort passed every other case. Every expected hash was computed
  with `sha256sum` over hand-typed bytes. The harness computes fingerprints from the spec with its
  own writer, independent of both kernels.
- **Standard pack.** `format/citations` read a text marker with Python's
  Unicode `strip()`/`isdigit()` (`[\u00a05]` and `[٣]` were citations);
  the spec says a decimal integer, and model text is read by §7a: ASCII
  whitespace, ASCII digits. Python now does that; no case changed.

Host differences the TypeScript kernel takes, all inside what the contract
already leaves to hosts (`ts/README.md` states them): it places no UDF
language (a JavaScript format is a closure, not source with a checkable
boundary; `dump` of a code-built format refuses `format-not-self-contained`
rather than drop it); an integral `3.0` given to an integer field writes
`3` (one number type; the reference refuses it); integers beyond ±(2^53−1)
are read as `bigint` while `t.integer()`'s static type says `number`; the
frontend names no type unless told (types are erased at run time), so a
builder-made signature and a Python `@lmcc.fn` of the same function have
different fingerprints (`signatureFromDict` never differs); `pattern/legacy-re2`
binds ECMAScript `RegExp` (`s`, `u`), label `ecmascript:RegExp`; hints name
TypeScript APIs.

Costs, stated: kernel 0.8.4 changes the fingerprint of a signature whose
shape holds a non-integer-spelled or exponent-spelled number, and the
request hash of a request holding one (a temperature of `1.0`); turns
recorded under 0.8.3 with such a signature refuse `turn-invalid` until
re-recorded. No corpus byte before case 209 changed; ten cases moved only
the kernel version they record. Two implementations now carry every future
change; a rule only one can follow will fail `./check` instead of shipping.
The TypeScript package is build-ready (`npm run build`, `dist/` with
declarations, verified by installing the packed tarball into a clean
project) but not published.

**D-55 · A signature's instructions are text; lmcc objects cross copies
of one package (kernel 0.8.4, TypeScript API).** Ratified with the
maintainer on 2026-09-26, preparing functai-js on the TypeScript kernel.

- **Contract.** Neither kernel checked that `instructions` is text: Python
  crashed at render with a host `TypeError`, TypeScript would have sent
  `undefined` to the model. It now refuses `signature-malformed` with fix
  `edit-signature` (kernel §1, errors.md, case 212, authored first and
  failing on Python). Kernel 0.8.4 had not been released, so it is folded
  in without a version change. Absent in the plain-data form it stays `""`.
- **TypeScript surface for frontends.** `new Signature(instructions,
  fields)` validates (an invalid signature cannot exist) and deep-freezes
  its shapes, so a fingerprint cannot change after the fact; the Python
  `SignatureCore` does not freeze, a stated host difference.
  `turn.withMeta` and `turn.withScore` replace Python's
  `dataclasses.replace` and check JSON form at once. `sha256`,
  `sha256Hex`, `toJson`, `nullableBase`, `structuralKeys` and `isRefusal`
  are exported. Every JSON writer honors an object's own `toJSON` first,
  as `JSON.stringify` does (a plain object carrying `toJSON` was walked as
  data by three writers; found by a test of these exports).
- **Copies.** npm installs a package twice easily; `instanceof` then fails
  between copies, which wrapped a pack's refusals as `reader-error` and
  rejected its transports. Public classes carry a registered-symbol brand
  that `instanceof` checks, for the branded class only (subclasses keep
  JavaScript's rule). Brands carry the kernel's compatibility unit (0.8):
  across versions, turns and transports cross through their JSON (the
  versioned records), and a reader of another version is refused with a
  hint that says so. `Refusal` alone is unversioned: its shape is the stable
  one. Chosen over detecting duplicates and throwing (graphql-js), which
  breaks the common case of a pack and an app pinning one version twice.
- **Installing from a checkout.** `prepare` builds `dist/` for folder
  installs; the `lmcc-source` export condition runs the source with no
  build and cannot go stale.

Costs, stated: an object that fakes a brand symbol is trusted as that
class (brands are identity, not validation; transports are still
validated as data). npm 11 warns on folder and tarball installs that a
`prepare` script ran; registry installs do not (checked against `ky`,
which has the same script). A linked `dist/` goes stale when lmcc's
source changes unless the source condition is used. npm cannot install
from a subdirectory of a git repository, so before publication a checkout
is installed by path or as a packed tarball.

**D-56 · Julia and R kernels (kernel 0.8.4).** Asked by the maintainer on
2026-09-27 ("now do lmcc in both R and Julia, implement it all"). No
contract byte changed: the corpus, the spec and the Python kernel were
enough for two more languages, which is the evidence D-41 said only a port
could give.

- **What each is.** `julia/` (package `LMCC`) and `r/` (package `lmcc`):
  the kernel, the standard pack, the conformance driver, a differential
  probe, the lm15 bridge (LM15.jl as a package extension; lm15 for R as a
  suggested package) and a live script. Each passes 206 of 212 cases
  through the driver protocol with every one of the 72 stream traces equal
  to Python's; the six `udf:python` cases are unclaimed. The differential
  check, now in `contract/harness/differential.py --probe CMD` for every
  kernel, finds 0 differences on every case and 2,640 fuzzed replies
  (breaking a number spelling or an escape on purpose shows 20 and 190).
  Each ran 15 live scenarios on five providers through its own lm15, and
  Python replays the 19 recorded exchanges of each with 0 differences
  (`contract/harness/replay_live.py`). `./check` steps 8 and 9 hold them.
- **One string model for both.** Positions are UTF-8 byte offsets, not
  characters: R's character offsets are quadratic on non-ASCII text (lm15-r
  measured 83 s on a 445 KB reply) and Julia strings are byte-indexed.
  Every marker is a whole UTF-8 sequence, so a byte search never matches
  inside a character; holds are counted in characters and returned in
  bytes, so every cut lands on a boundary. The stream traces are the proof.
- **Dependencies.** Julia: stdlib plus OrderedCollections (key order is
  contract data; LM15.jl uses the same package, so the bridge passes lm15's
  dicts straight in). R: base R plus 150 lines of C, because base R cannot
  honor §7a: `as.numeric("1.00000000000000011102230246251565404236316680908203125")`
  is the next double up, not 1 (checked, R 4.6.1). The C calls the C
  library's `strtod` (correctly rounded on glibc, macOS and UCRT), finds
  shortest digits with `%.*e` checked by `strtod`, and computes SHA-256.
- **R's JSON.** Objects are named lists (an empty one keeps `names =
  character(0)`), arrays unnamed lists, null `NULL`; integers are 32-bit
  `integer`, whole doubles up to 2^53, and `lmcc_int` decimal text beyond.
  lm15 for R's classed values are read as the same data (`lm15_plain`).

Host differences, stated (both READMEs list them): neither places a UDF
language; Julia's frontend writes Julia type names and R's builders none,
so a signature from host types has a different fingerprint than Python's
(`signature_from_dict`/`signature_from_list` never differs); R accepts a
whole double for an integer field (`3` is R's usual literal) where Python
and Julia refuse a float; R strings cannot hold U+0000; R's `repr` of rare
non-ASCII characters in hints approximates Python's (hints are prose);
names Julia's `Base` or R's base use for something else are qualified
(`LMCC.parse`) or renamed (`parse_reply`, `record_step`, `describe_plan`);
the `pattern/legacy-re2` bindings are PCRE2 (`julia:PCRE2`, `r:PCRE2`).

Findings for other projects, not fixed here: lm15 for R 1.0.0's
`new_router()` rejects every API key from its default environment lookup,
because `Sys.getenv()` values keep the `Dlist` class its key check refuses
(the live script passes `env = unclass(Sys.getenv())`). Julia's
`parse(Float64, "1e400")` throws where C's `strtod` gives infinity; the
Julia kernel reads overflow and underflow as the reference does.

Costs, stated: four kernels carry every future change (`AGENTS.md`: a
kernel change is implemented in all four, and `./check` fails until it
is); `./check` takes about six minutes longer and needs Nix or local
Julia and R; the R package needs a C compiler to install (and a separate
wasm build for webR, which lm15 for R supports); neither package is
published (LMCC.jl is not in the General registry, lmcc is not on CRAN).

**D-57 · `reader/json_object` 0.2.1: every record in the requested
schema is closed.** Asked by the maintainer on 2026-09-27 ("go fix"),
after functai found it live: an output whose type is a record (a name
and an age), under a `json_object` reader, was refused with HTTP 400 by
OpenAI (`gpt-4.1-mini`, strict mode: "'additionalProperties' is required
to be supplied and to be false") and by Anthropic (`claude-haiku-4-5`:
"For 'object' type, 'additionalProperties' must be explicitly set to
false"), in Python and TypeScript alike. Gemini accepted it. The reader
closed only the outer object it builds.

- **Where the fix goes.** lm15 sends `schema` verbatim and never rewrites
  a keyword to make a request pass (lm15 MAP-8 4, INV-050). The schema is
  this reader's; so the reader writes one strict enforcement accepts.
- **The rule** (`vocab/reader-json_object.md`, "Every record is
  closed"): each record at any depth that does not say
  `additionalProperties` gains `additionalProperties: false`, and its
  `required` lists every property in property order. Records that say
  `additionalProperties`, maps and free objects are left as written.
  Field shapes, `describe()` and fingerprints are unchanged; only the
  request's `response_format` is.
- **Evidence.** Case 213 (a record in a record, a list of records, a
  nullable record, a map, an explicitly open record) was typed by hand
  from the rule and failed on the Python and TypeScript kernels first
  (Julia and R built the schema the same way). All four kernels
  (Python, TypeScript, Julia, R) implement it; case 26 moves only the
  version it records. Live after the fix: records in records, lists of
  records and a nullable record read through OpenAI, Anthropic and Gemini.
- **Version.** 0.2.1, a patch: loading ignores the patch (§9), so
  artifacts pinned at 0.2.0 (every functai `json` layout saved so far)
  get the fix without a change. The requested schema differs only where
  a field's shape holds a record.

- **The live replay compares versions as loading does.** A recorded
  exchange carries the artifact as its kernel dumped it, with the
  versions running then; `harness/replay_live.py` now compares dumps with
  vocabulary versions cut to MAJOR.MINOR (§9), so recordings made under
  0.2.0 stay evidence under 0.2.1 without being edited.

Costs, stated: an optional property of a record is now required, so a
strict provider always writes it (reading is unchanged); a map or free
object under this reader is still refused by strict providers, as
before; with Gemini, which enforced the open schema, a record now also
refuses keys it does not declare.

**D-58 · Names are data, and members keep their order (kernel 0.8.4;
the version is the maintainer's, see Contract).** Asked by the maintainer
on 2026-09-29 ("fix … so every kernel is held to it"), after functai's
TypeScript stage 1 found the first half, then again after two reviews of
that fix found the other two, a third time after two more reviews found
the same hazards in places the fixes had not reached, and a fourth time
after two reviews of the third pass found one more keyed lookup in R and
a grammar the kernels matched differently (the third and fourth passes
are the last items below). Four host hazards of one kind: a record keyed
by names that the host's own record type does not hold as data.

1. **TypeScript, `Object.prototype`.** The kernel kept records keyed by
   field names and JSON members in ordinary objects and read them with
   `name in obj` / `obj[name]` and wrote them with `obj[name] = v`. A name
   `Object.prototype` has was read from the prototype when absent, and
   `__proto__` was written into the prototype. Silent cases: an input
   named `__proto__` was sent as `{}`, a JSON input's `__proto__` member
   was dropped, an output named `__proto__` was read as nothing, and a
   reply missing an output named `toString` read it as `""` instead of
   refusing `parse-missing-fields`. Loud but wrong: a valid partial
   example refused `value-invalid`, and the json_object reader refused a
   correct reply `parse-ambiguous`.
2. **R, the empty name.** R reads `x[[""]]` as `NULL` and `x[[""]] <- v`
   appends: a JSON member named `""` (in an input, a turn's output, a
   shape's `properties`) was sent as `null` and written twice
   (`properties` with `""` twice, `required: ["", …, ""]`), a format key
   `""` refused at load, and the R driver's JSON equality called
   `{"": 1}` equal to `{"": 2}`.
3. **TypeScript, member order.** A JavaScript object enumerates
   integer-like names (`"10"`) first. `{"b": 1, "10": 2}` was written
   `{"10": 2, "b": 1}` by the json format, a written reply, a call's
   `{input}` and a data part's text, and a shape's `required` became
   `["1", "b"]` where Python writes `["b", "1"]`. `format-json.md` already
   said "in the value's own order"; D-16 had noted the reordering only
   for field names, which are identifiers and never integer-like.
4. **Julia, hash order.** A `Dict` iterates in hash order. The plan kept
   its formats, `written_as` and turn input formats in `Dict`s, so
   `describe()["versions"]["vocab"]` listed `format/tool_calls` before
   `format/function_tool` where the other three kernels list them in
   signature order. No check saw it: every comparison ignored member
   order.

- **Contract.** Kernel §1 says both rules: "Names are data" (format keys
  and member names are any string, `""` included) and "Members keep
  their order" (every JSON the kernel or a standard format writes, except
  canonical JSON, spells members in the value's order; `required` in
  property order). Nothing is newly allowed. Some inputs that loaded or
  rendered in 0.8.4 now refuse (the third and fourth passes list them):
  that is a change to when a code fires, breaking by the rule. It is
  classed here as a patch, for the maintainer to ratify with the release:
  every newly refused input was outside a grammar already published (the
  entry and signature schemas, §2's purposes, lm15's `ToolCallPart`),
  was accepted by only some of the four kernels, or keyed a transport no
  field could reach, so no artifact that worked the same everywhere
  changes. A minor version would make every artifact pinned to 0.8 be
  re-pinned for inputs none of them holds. Kernel 0.8.4 is already on
  npm with hazards 1 and 3; shipping the fix needs a new package version,
  and the package version is the kernel version, so that release is the
  maintainer's decision, not taken here; this branch moves no version. Cases
  214–222 pin hazard 1: inputs and a partial example (214), a guard,
  bare slots and a turn slot named `__proto__` (215), outputs read by
  the derived reader (216) and missing (217), outputs read by the
  json_object reader (218) and missing (219), JSON members through the
  json format, the reader's schema, its written reply and a turn
  fingerprint (220), artifact keys through load and dump (221), and a
  transport bound under the purpose `__proto__` (222). Cases 223–225
  and 230 pin hazard 2 (`""` in an input value, a turn output and a
  shape property, through the json format and the json_object reader;
  `""` members read from a reply; format keys `""` and `"10"` through
  load and dump); 226–229 pin hazard 3 (the json format, the reader's
  schema and written reply, a fenced call's `{input}` and a tool's
  parameters, a data part's text). All were typed from the spec; the
  corpus README states what failed where before the fixes.
- **TypeScript, names.** Records stay ordinary objects with ordinary
  prototypes, so no type or behaviour a caller sees changes except the
  bug: every read of a name-keyed record is an own-member read
  (`hasOwn`, `ownValue`) and every write goes through `setMember`; the
  three are exported for packs and callers. Null-prototype records were
  rejected: a caller's `values.hasOwnProperty(...)`, `String(values)`
  and Node's `assert.deepStrictEqual` against a literal would all break,
  and records callers build would still need own reads. Capabilities are
  now read own-only too: capabilities given as `Object.create(defaults)`
  or through getters on a prototype are no longer seen (no capability
  fact is an `Object.prototype` name, so this fixed no bug; it is the
  same rule, and `describe()` already listed own members only). The
  conformance driver, the differential probe and the streaming fuzz test
  had the same bug and are fixed. `ts/tests/names.test.ts` holds the
  paths the corpus does not reach.
- **TypeScript, order.** The larger fix, over stating a host
  difference: a JavaScript object cannot hold the order, so lmcc carries
  it: the list of its names under the registered symbol
  `lmcc.memberOrder`, not enumerable. The third pass put the list where
  names are added, not where objects are built: `setMember` appends a
  name the object does not hold (a replaced one keeps its place; one
  removed and set again comes last, as in a Python dict), starting the
  list the first time an integer-like name is added to an object with
  members. So an object is ordered whenever lmcc built it name by name,
  whatever built it. Five helpers are the only way `src/` touches a
  record's names (`memberNames`, `setMember`, `orderedObject`,
  `copyObject`, and `hasOwn`/`ownValue`), and a test fails on any
  `Object.keys`/`values`/`entries`/`fromEntries`/`assign`, object
  spread, `for ... in` or `in` with a data name outside `json.ts`
  (`names.test.ts`). Nothing is recorded while JavaScript's order is the
  value's, which is every object without an integer-like name. Rejected: `Map` values (a
  breaking change to every reading and input, and `values.o.b` would stop
  working), a `Map` only where order is at stake (a value's type would
  depend on the names a model wrote), a `Proxy` whose `ownKeys` returns
  the order (JavaScript's own writers would then agree, but
  `structuredClone` and `postMessage` throw on a proxy), and a
  module-level `WeakMap` (invisible to a second copy of lmcc, and to a
  debugger). `ts/tests/order.test.ts` holds the paths the corpus does
  not reach (a reading written back, a turn's JSON read back with
  `parseJson`, copies, a member added later).
- **R.** A name that comes from data and is not a validated identifier
  (a JSON member, a format key, a slot, a probabilities field, a
  registry or type-binding name, a request setting, a put or tell key)
  is found and written by position (`key_index`, `get_key`, `set_key`,
  `members_of` in `base.R`), never by `[[name]]`, and one object is
  updated by another with `merge_obj` (Python's `{**a, **b}`), never
  `c(a, b)`, which holds a name both have twice. `[[name]]` remains for
  names the kernel chose or validated first (field names, template
  slots, turn slots after the placed-slot check, purposes after load's
  check, loop variables, tell roles, request-setting paths checked
  against the pinned list) and for keys it builds itself with a prefix
  (`"k"`, `"channel\u0001"`); the first two passes had claimed "never by
  `[[name]]`" for all of them, which was not true, and the third pass
  missed the call-id map (fourth pass, below). R's other
  hazard of this kind, `$`'s partial matching on lists, is now checked on
  every run: the conformance driver and the differential probe set
  `warnPartialMatchDollar`, `warnPartialMatchArgs` and
  `warnPartialMatchAttr` and turn every warning into an error.
- **Julia** built its records as `OrderedDict`s but kept three plan
  tables in `Dict`s (hazard 4); the kernel now builds no `Dict` at all,
  and a unit test fails on one. Its exposure left is the caller's: a
  `Dict` a caller passes iterates in hash order, and lmcc writes it in
  that order (stated in its README).
- **Seeing order (third pass).** Every comparison ignored member order
  (Python's `==`, each driver's JSON equality, the differential's sorted
  walk, and the TypeScript probe wrote with `JSON.stringify`), so order
  was pinned only through rendered text, and the drift the reviews found
  passed `./check`. Now: a case marked `"ordered": true` compares member
  order too (kernel §9; cases 226–230, 234, 235 are); the differential
  compares every object's member order on everything it observes (the
  TypeScript probe writes with `jsonText`); and it adds, for each case
  whose data holds member names (shape properties, inputs, turns,
  replies, tool calls, probabilities, table columns), two variants with
  those names replaced by `""`, `"10"`, `"2"`, `"__proto__"`,
  `"toString"`, `"4294967295"`, `"NA"`, `"..."` and the like, in orders
  JavaScript would change. Rejected: ordering every corpus comparison,
  which would pin the order of members the kernel chooses itself (a
  reading's fields, an entry's top-level keys: eight cases differ there
  between their file and the reference, harmlessly) and so
  over-specify every future kernel.
- **Purposes (third pass).** A transport keyed by `""` loaded in Python,
  TypeScript and Julia and was dumped back; `a-b` loaded in all four;
  R refused `""` by accident ("must be an object"). A purpose is what a
  field declares, a name or dotted names, so load now refuses any other
  key `entry-malformed` with `fix: edit-entry` at `transports[...]`,
  before reading its value (kernel §2, cases 231, 232). The entry schema
  allowed `^[A-Za-z_][A-Za-z0-9_.]*$` (so `a.` and `a..b`), looser than
  the signature's purpose grammar; it now says the same grammar. This
  refuses artifacts that loaded before; each keyed a transport no field
  could reach, so no working artifact changes, but it is a change to
  when `entry-malformed` fires, stated here.
- **Also pinned (third pass).** A turn slot `""` refuses
  `turns-unplaced` (R dropped its turns silently; case 233, for which the
  case schema's `turns` now takes any slot name, as a caller can pass);
  probabilities keep the reply's order under any name, a name no output
  bears and `""` included, as §3's "verbatim" said (R refused
  `response-malformed`, TypeScript reordered the labels; case 234); a
  table row is read in column order (TypeScript reordered it; case 235);
  a table with a column `""` renders (case 236; a review of the second
  pass found R failing it before that pass); an artifact dumps its
  format keys in the order loaded (TypeScript reordered them; case 230,
  now ordered). TypeScript's
  `nullableBase` puts `type` last again, as the other kernels do (the
  second pass had moved it; no bytes differed).
- **Fourth pass.** Two reviews of the third pass found:
  - *R keyed the call-id map by a call id* (`ids[[id]]`), a value, not
    a member name, so no name fuzz reached it: a call whose id is `""`
    was written with no `id`, where the other kernels wrote `s0_`. The
    map is now two character vectors found with `match`. What a call id
    `""` means was open; it now refuses `turn-invalid` in all four
    kernels, native or spelled alike (kernel §3a, cases 237, 238),
    rather than being written `s<k>_`: lm15's `ToolCallPart` refuses an
    empty id, a tool step with id `""` already refused, so the call could
    never be answered, the heredoc calls format already required a
    non-empty id, and writing `s0_` would invent an id from nothing.
    Rejected: refusing a call's `name` `""` the same way, since
    `format/tool_calls` reads a fenced call's name verbatim and would
    then read values it cannot write back; a call named `""` written as
    a native part still reaches lm15, which refuses it when the request
    is built. Stated, not fixed here.
  - *A grammar matched differently.* Python and PCRE (Julia, R) let `$`
    match before a final `\n`, so `a\n` passed as a purpose, a field
    name or purpose, a turn slot, an extension name or version, a find
    rule's `from`/`to` or a put place in three kernels and refused in
    TypeScript; and Python's `\d`/`isdigit` and Julia's `\d` took other
    scripts' digits, so Python loaded an entry for kernel `0.٨.4` as
    0.8.4 (and raised `ValueError` on `0.8.²`). §7a now says every
    grammar matches the whole text, in ASCII; Python uses `fullmatch`,
    Julia and R `\A…\z`, digits are `[0-9]` (cases 239–249, 251).
  - *R wrote a member twice*: `reader/json_object` concatenated a
    field's description onto a shape that had one (case 250, ordered);
    every such `c(a, b)` is now `merge_obj` or `set_key`.
  - *The judges could not see it.* The differential decoded probe lines
    with plain `json.loads`, which keeps the last of two members, so a
    member written twice compared equal: it now fails the probe on any
    duplicate at any depth; it split lines with `str.splitlines`, which
    also splits at U+2028, and the TypeScript driver and probe read with
    `node:readline`, which does too (a case holding U+2028 crashed the
    TypeScript driver; case 251): all now split at `\n` only. A failed
    `ordered` comparison in the TypeScript driver names the path.
- **Pinned elsewhere.** A refusal's `partial` has no field in the case
  schema, so cases 217 and 219 do not pin it; the differential check
  compares every refusal's `partial` across the four kernels on every
  case and fuzzed reply, and `names.test.ts` checks TypeScript's.
  Case 222's `tell` is never rendered (a parse case) and pins nothing.

Costs, stated. A JavaScript caller who writes `{ __proto__: "x" }` as an
object literal sets the literal's prototype, not a member (the language
does that before lmcc sees it); such a value must be built with a
computed key, `JSON.parse`, `Object.fromEntries` or `setMember`. Records
lmcc returns (readings, turns, a refusal's `partial`, `describe()`) are
ordinary objects: `name in record` and an unguarded `record[name]` answer
from the prototype for a name the record lacks, `String(values)` throws
when an output is named `toString`, and `Object.assign({}, values)` drops
a `__proto__` member; `ts/README.md` says to use `Object.hasOwn`,
`ownValue`, `memberNames` and `setMember`. The recorded order is lmcc's,
not JavaScript's: `JSON.stringify` of a reading, and the request lm15
serializes, put integer-like names first (a `response_format` schema
reaches the provider that way; its `required` keeps the property order);
a tool call's `input` or a data part lm15 parsed arrives in JavaScript's
order; an object literal or a `JSON.parse` result has lost the order
before lmcc sees it (`orderedObject`, `parseJson`); a member added by
plain assignment (`obj[k] = v`) rather than `setMember` is listed after
the recorded ones in JavaScript's order, and one deleted and assigned
again goes back to its recorded place. A pack that builds its own
records with `obj[name] = v` can still lose a `__proto__` member or the
order of integer-like names; the kernel reads what it returns as own
members and writes it by `memberNames`. The order list grows by one
entry per name `setMember` adds and keeps names removed with `delete`
(they are skipped when read), so an object whose members are removed and
added many times holds a longer list than members. `lmcc.memberOrder`
is unversioned: two copies of lmcc at different versions share it, so
its meaning (a list of names, the last listing of a name wins, names
not held are skipped) is a small public protocol from now on. A Julia
caller's `Dict` and a JavaScript caller's literal keep their host's
order; an R caller reading a reading with `values[[""]]` gets `NULL`
and `values$na` may complete to another member (`r/README.md`).

**D-59 · lmcc's member order record is lm15's; the lm15 bridge sends it,
and big integers exactly (kernel 0.8.4; no version moves).** Asked by the
maintainer on 2026-09-29 ("the absolute best fix"), after a functai review
of TypeScript stage 1 found that D-58's record crashed every call through
lm15 (lm15's strict JSON check refused the symbol) and the workaround,
plain copies, sent a schema's integer-like properties first.

- **The record.** lm15-ts now keeps the order itself (lm15-contract
  `changes/2026-09-29-index-member-names.md`, lm15-ts `8358d49`): its
  `parseJson` records a member order JavaScript would change under the
  registered symbol `lm15.memberOrder`, its `stringifyJson` writes it, and
  its strict check accepts a well-formed record. The protocol is D-58's,
  unchanged (a list of names, the last listing of a name wins, names not
  held are skipped, a writer appends); only the symbol's name moves from
  `lmcc.memberOrder` to lm15's. So one record crosses both libraries in
  both directions: a schema, a tool's parameters or a call's input lmcc
  builds goes out in its order, and a tool call's input or a data part
  lm15 read arrives in lmcc in the provider's order. Two of D-58's stated
  costs are gone with an lm15 that keeps order ("the request lm15
  serializes put integer-like names first", "a tool call's `input` or a
  data part lm15 parsed arrives in JavaScript's order"). lmcc does not
  import lm15 for it: the symbol is registered. A record that breaks the
  protocol (not an array of strings) now throws `TypeError` where lmcc
  read it blindly.
  Rejected: stripping the record at the bridge (functai's workaround),
  which fixes the crash by sending JavaScript's order; a symbol owned by
  neither library (a third name in the global registry to agree on, for
  the same meaning); lmcc's name kept and lm15 taught two (two names for
  one protocol).
- **The bridge (`ts/src/lm15.ts`).** `request()` hands lm15 a copy in
  lm15's forms, of the plan's request and of the caller's `Config`: a
  `bigint` becomes lm15's `RawNumber` (its digits; lm15 refuses a
  `bigint`, so an int64 in a schema's `enum` or an input value used to
  throw), objects keep their record. The conversion is exported as
  `toLm15` for the other places lmcc data meets lm15 (a saved `Config`
  for `Config.fromJSON`, a stored reply for `Response.fromJSON`), so a
  frontend does not write its own; functai had (`lm15Data`). It detects the lm15 it runs
  with: `lm15KeepsOrder` is true when lm15 exports `MEMBER_ORDER` as the
  same symbol. With lm15 1.0.0-rc.2, the published one, which refuses any
  record, the copies are plain and the wire order is JavaScript's, as
  before; nothing throws. The merge with a caller's `Config` compares
  values as lmcc does: the plan's `bigint` and the same number as lm15's
  `RawNumber` are one value, where it used to raise `ConfigConflict` and
  then crash writing the message (`JSON.stringify` of a `bigint`); the
  message now prints both numbers. What is sent keeps each value's own
  form.
- **Checks.** `ts/tests/order.test.ts` holds the paths: the symbol, the
  schema's order and a big integer on the wire, a merged `Config`, a
  conflict between two big integers, a caller's `Config` built from lmcc
  data, a saved `Config` and a stored reply through `toLm15`, a malformed
  record. They were run against lm15 1.0.0-rc.2 (the fallback) and
  against lm15-ts `7169da2` (the order); `./check` runs them against the
  installed one.

Costs, stated. The order reaches the provider only with an lm15 that
exports `MEMBER_ORDER`: 1.0.0-rc.3 (published 2026-09-29), which
`package.json` now requires (`1.0.0-rc.3` for development, `^1.0.0-rc.3`
as the peer), so `./check` exercises the order. The fallback stays for an
install that holds an older lm15 anyway (the peer is optional): order
lost there as before, never a crash; the tests' fallback branch now runs
only by hand, with rc.2 installed. The symbol is unversioned, shared by every copy of lm15 and
lmcc in a process: its meaning is a public protocol of both from now on.

Ratified-by: Maxime Rivest, 2026-09-29 (in session): the record as a
permanent protocol of lm15 and lmcc, and the release of D-58 and D-59 as
kernel 0.8.5, the patch D-58 proposed. lm15 1.0.0-rc.3 was published the
same day; lmcc requires it.

**D-60 · A reply the provider stopped refuses `parse-filtered` (kernel
0.8.6, a patch).** GitHub issue #5, from a real extraction run
(2026-10-02): Claude stopped partway through toxicology papers; the
frontend saw `parse-missing-fields`, asked again with a hint, sent the
empty reply back (which Claude refuses), and the user was told the reply
"could not be read". The cause and the fix (another model) took a person
reading the log. Reproduced with lmcc 0.8.5 alone: an empty stopped reply
refused `parse-missing-fields`; a stopped reply whose text fit the pattern
was returned as the answer.

- **The rule (kernel §4a, Filtered).** lm15 gives two signals for one
  event, both in the pinned contract: the finish reason `content_filter`
  ("provider safety/refusal stop": Anthropic's `refusal`, Gemini's
  `SAFETY`, OpenAI's `content_filter`) and the `refusal` part (OpenAI's
  model declining in its own words, sent with finish reason `stop`).
  Either refuses `parse-filtered`, whether or not the text reads, before
  anything is read: before the reader, `parse-ambiguous`, truncation and
  every format. The issue named only the finish reason; the refusal part
  is included because without it OpenAI's declines keep the misdiagnosis
  the issue reports, and a message (no finish reason) could not be
  recognised at all.
- **Before ambiguity.** `parse-truncated` lets `parse-ambiguous` come
  first; this one does not: an ambiguous stopped reply reported as
  ambiguous invites the re-ask the issue is about.
- **`partial` is empty.** Nothing was read. A refusal part's text is
  quoted in the hint; the caller holds the response for anything else.
- **The name** is the issue's (`parse-filtered`, after lm15's
  `content_filter`); functai 1.3 (unreleased) already raises it in four
  languages, and drops its own check now.

Costs, stated. **A new code under a patch number.** `errors.md` says
adding a code is a minor change, and while the major is 0 a minor is
breaking: every 0.8 artifact would refuse `version-incompatible`. No
artifact changes meaning here, only replies that were never answers read
differently, so the release is 0.8.6, as 0.8.5 made some inputs refuse
under a patch; the rule in `errors.md` is unchanged and this is a stated
exception. A frontend that switches on codes meets one it did not know;
it was getting the wrong one before. Not covered: lm15's `error` finish
reason (a stream that ended in error), which is also not an answer and
is still read like any other reply; it needs its own code and is left
for a decision.

Ratified-by: Maxime Rivest, 2026-10-07 (in session): issues #3, #4 and #5
as recommended (#5 as a kernel rule; #4's list fix and JSON hooks on the
type binding, runtime only; #3 in the lm15 bridge). The choices made while
building them and not in the recommendation are stated here and in D-61
for review: the refusal part, the order before `parse-ambiguous`, the
patch number, the names `to_json`/`from_json`, binding on import.

**D-61 · A host type's JSON form is part of its binding; lm15's media
parts are bound by the bridge (Python; no kernel change).** GitHub issues
#4 and #3.

- **#4, the bug.** `lmcc.turn.lift` called `model_validate` only for an
  object or a text, so a list-like type (or a number-like one) came back
  as plain JSON when a turn was loaded, and the format bound to it
  received a `Pages` live and a list of base64 dicts on replay. `lift`
  now rebuilds from any JSON; `lmcc_std`'s copy of `lift` is the kernel's.
- **#4, the hook.** `lmcc.format(T, ..., to_json=, from_json=)`: the
  type's JSON form, both ways, on the binding that already holds its
  format and shape, never serialized (D-07). This is the 2026-09-02
  answer to "lower/lift feel like what codecs is trying to be" (conversation
  `01a061fe`): a type's local materialization belongs to its binding, not
  to a layer of its own. A turn writes it (`to_json`, by `isinstance`),
  `plan.load_turn` rebuilds with it (`lift`), and **the format bound to
  the type receives the type itself, live or replayed; every other
  format (the artifact's, the kernel's defaults) receives the JSON form.**
  Without hooks, dataclasses and pydantic models cross as before. The
  issue's names `dump`/`load` were not taken: lmcc's `dump`/`load` are
  the artifact's.
- **Binding refinements.** A binding with neither `write` nor `use` binds
  no format, only a shape and a JSON form (the type crosses by its
  shape's format); a declared `shape` now wins over the mechanical
  lowering of a dataclass (it was silently ignored); binding the same
  type again replaces its binding (the second one was silently dead).
- **#3.** `import lmcc_lm15` binds `ImagePart`, `AudioPart`, `VideoPart`,
  `DocumentPart`, `BinaryPart` in the default registry (`install(registry)`
  for another): shape `{"media": kind}`, no format (the kernel's media
  default or the artifact's), JSON form lm15's own `part_to_dict`, `type`
  included so a part of another kind refuses `value-invalid`. A part given
  by `path` keeps its path; lm15 reads the file when it sends. lmcc never
  touches the file system. The kernel never imports lm15 (it only names
  the bridge in an `unmapped-type` hint).

Costs, stated. `to_json`, `Turn.to_dict` and `lift` look in the default
registry unless given one: a program with its own registry passes it
(`turn.to_dict(registry=...)`); `plan.load_turn` passes the plan's; the
standard formats, which see no registry, use the default. The bridge
binds on import (a side effect on the default registry); a later
`lmcc.format(ImagePart, ...)` replaces it. A hooked value nested inside
another value reaches an artifact's format as its JSON form only through
`to_json` or `lmcc_std.lower`; a pack that walks values its own way does
not see the hook. TypeScript, Julia and R have the same gaps, each in its
own form (TypeScript cannot recognise an lm15 part by its value; it
writes an lm15-ts image with `mediaType`, which lm15 refuses only at
send), and none rebuilds host types from a turn: plan 14. No corpus case:
host types are not data.

**D-62 · A type's JSON form and lm15's media parts in TypeScript, Julia
and R (plan 14; no kernel change).** Asked by the maintainer on
2026-10-07 ("fix in all languages") after D-61 did Python. The rule is
D-61's in every kernel: a type binding may carry the type's JSON form both
ways; the format bound to the type receives the value itself, live or
replayed; every other format receives the JSON form; `load_turn` rebuilds
it. One call is new in all four: **`plan.dump_turn(turn)`** (`dumpTurn` in
TypeScript), the counterpart of `load_turn`, which writes each value by its
binding.

- **Finding the binding.** Python and Julia find it by the value (class,
  `isa`), so `to_json`, `turn.to_dict()` and `turn_to_dict` apply it
  without a plan. TypeScript and R find it by the field's type name, as
  they already found format bindings: a plain object carries no class
  (lm15-ts's parts are plain objects), and R binds by name. There a turn
  must be saved with `dump_turn`; `turn.toJSON()`/`turn_to_list()` write
  values as they are. Each README states it.
- **The surfaces.** TypeScript: `registry.format(type, {toJson, fromJson,
  shape?})`, overloaded so a binding with a format still returns a
  `Format`. Julia: `bind_type!(reg, T; to_json, from_json, name)`; `name`
  is new because `string(T)` reads `LM15.ImagePart` or `ImagePart`
  depending on the caller's imports, and the type name is in a
  signature's fingerprint and in an artifact's format keys. R:
  `bind_type(reg, type, to_json =, from_json =)`; R has no type lowering,
  so no `shape`. In all three, binding a name again replaces it (R
  already did) and a binding with only a JSON form binds no format.
- **The bridges.** TypeScript: `media.image()` (`audio`, `video`,
  `document`, `binary`) are fields typed `ImagePart`, …; the JSON form is
  lm15's `Part.toJSON` (lm15-ts's camelCase `mediaType` becomes
  `media_type`), and part data given as it is passes through. Importing
  `lmcc/lm15` binds them in `defaultRegistry`, so `package.json`'s
  `sideEffects` now names that module instead of `false`. Julia: loading
  the extension binds `LM15.ImagePart`, … (`lm15_install!`), JSON form
  `LM15.to_dict` with `type` first as the other kernels write it, names
  Python's. R: `lm15_media(kind)` fields; the default registry has the
  bindings (`lm15_install()` for another), which call lm15 only when they
  meet an lm15 value. Every bridge keeps a `path` for lm15 to read.
- **Checks.** Each kernel has a unit test of the rule (Python
  `test_host_json.py`, TypeScript `host_json.test.ts`, Julia's testset, R
  `test-host-json.R`) and a bridge test against a real lm15, offline:
  Python's against its pinned release; TypeScript's against the installed
  `@lm15/lm15`; Julia's (`julia/bridge/test.jl`) against LM15.jl at commit
  `34c1167` (1.0.0, not in the General registry); R's
  (`r/bridge/test-lm15.R`) against lm15 for R `v1.1.0` (not on CRAN). The
  last two also check `parse-filtered` through lm15 objects. `./check`
  installs both once (network the first time), like Python's.

Costs, stated. In TypeScript and R a media field declared without the
bridge's type (`t.media("image")`, `shape_media("image")`) does not see
the binding: given an lm15-ts part, TypeScript still writes `mediaType`,
which lm15 refuses when the request is built; given an lm15 R part, R
writes it with lm15's empty members (`"url": null`, …), which lm15
accepts but which makes a request differ from the typed field's. Use the
bridge's fields. A kernel rule refusing unknown members in a media value
would close both everywhere; it is a contract change and is left for a
decision. `./check` now downloads LM15.jl and lm15 for R once.

**D-63 · A media value is written as lm15 serializes the part; a reply
ended in error refuses `parse-interrupted`; R gets the helpers (kernel
0.8.6, before its release).** Asked by the maintainer on 2026-10-07
("go") after D-62 left two kernel gaps and a parity gap.

- **Media members (§7b).** For lm15's five media part kinds the kernel
  writes exactly lm15's part: members from the pinned contract's
  `spec/types.md` (`media_type`, `data`, `url`, `file_id`, `path`,
  `continuation`, `detail` for images), anything else refuses
  `value-invalid` naming it, and a member lm15 omits when empty (`null`,
  `""`, `[]`, `{}`) is left out, `media_type` excepted. This closes
  D-62's stated gaps in every kernel: an lm15-ts part in an untyped field
  refuses before the wire naming `mediaType` (lm15 refused it late and
  obscurely), and an lm15 R part writes the same bytes as through the
  typed field (its empty members are gone). It extends the precedent of
  the pinned `Config` field list (D-35): lm15's names are pinned, a new
  lm15 member is a deliberate pin bump. lm15's invariants (a non-empty
  `media_type`, exactly one source) stay lm15's to check; it refuses them
  before sending. Other kinds (`function`, used by puts into
  `request.tools`) are written as given: they are not lm15 media parts.
  Cases 257–259. Cases 184, 185 and 187 used an Anthropic-shaped image
  (`source`) that lm15 never delivers and would refuse to send; they now
  hold lm15's (`corpus/README.md`).
- **Interrupted (§4a).** lm15's finish reason `error` is read as a cut
  reply, with its own code, `parse-interrupted`, because the remedy
  differs from `parse-truncated`'s (send again, not more tokens). Same
  rule otherwise: refused when an output may be cut, read when every
  output ended first. Cases 260–262. This closes the gap D-60 stated.
- **R helpers (plan 13).** `find_between`, `find_lines`, `find_pattern`,
  `find_part`, `put_system`/`developer`/`user`/`request`, `when_has`/
  `lacks`/`all`/`any`, and `choose_transport`: the data Python's helpers
  return, byte for byte (`tests/testthat/test-helpers.R` pins Python's
  JSON). The choice is `choose_transport` because R's `choose()` is the
  binomial coefficient and an exported `choose` would mask it.

Costs, stated. A media value with a member lm15 does not know used to be
sent (and lm15 dropped it, or refused late); it now refuses at render, a
behaviour change for anyone passing extra keys (`alt`, `mime`; lmcc's own
test passed `mime`). `value-invalid` fires in a new place and
`parse-interrupted` is a new code, both under 0.8.6 for D-60's reason; 0.8.6
is not yet released, so no published version reads differently twice. A
frontend reading `parse-truncated` to mean any cut now also meets
`parse-interrupted`.

Ratified-by: Maxime Rivest, 2026-10-07 (in session): "go" on the media
rule, the `error` finish reason and the R helpers as recommended.

**D-64 · Pictures are never written as text by a key written for every
value; a list of one media kind and a nullable media value have kernel
defaults (kernel 0.8.7, a patch).** GitHub issue #7, reproduced with lmcc
0.8.6 and lm15 1.1.0 through FunctAI's `xml` layout: a field
`list[ImagePart]` (`{"type": "array", "items": {"media": "image"}}`) had
no default, so an artifact's `{"*": {"use": "json"}}`, which most real
artifacts carry, caught it and wrote the pictures into the prompt as
base64 inside a JSON array. The call succeeded and the model guessed.
`Optional[ImagePart]` and a record with a picture member (`{"properties":
{"photo": {"media": "image"}}}`) failed the same way.

- **Kernel defaults (§7b).** A list whose items are exactly a media shape
  writes its items' parts at the hole, in order, each as one media value
  (D-63's member rule, the refusal naming the index), and reads every part
  of that kind in its capture, in order; `[]` writes nothing and reads
  back. It round-trips, so it writes turns. The nullable form of a media
  shape (only `anyOf`: a media shape has no `type`) writes `null` as the
  text `null`, as a nullable scalar is written, and reads `null` when its
  capture holds no part of its kind. Its structural keys are its base's;
  a list of media answers to `list[media:<type>]`, `list[media:*]` before
  `list[*]`, the issue's proposal.
- **The catch-all rule (§5).** For a field whose shape holds media (any
  JSON Schema subschema of a value: `items`, `prefixItems`,
  `additionalProperties`, `properties`, `patternProperties`, `$defs`,
  `anyOf`, `oneOf`, `allOf`), a format that writes text is passed over
  when it comes from `*` or from a structural key that does not hold
  `media:`. Resolution goes on; a record holding a picture that nothing
  writing parts catches refuses `no-format` at bind, the hint naming the
  media. Whether a format writes text is its declared `writes`, read
  without running it (a shipped entry without one writes text), so every
  kernel decides alike whether or not it places the code.
- **Why a kernel rule rather than the issue's second proposal** (`json`
  refusing a value holding media, `format-write-error`). That refusal
  would fire at render, from a fact known at bind (the shape); it would
  cover one format of one pack, not `table` or another pack's text
  formats; and an artifact carrying `{"list[*]": json}` could never reach
  the list default: no artifact entry names the kernel's format, so the
  refusal would be permanent. Passing over a catch-all mirrors resolution
  step 5's existing rule, a wildcard never overrides a scalar default. A
  format bound by the field's type name, by a key naming media, or at
  runtime is the author's choice and is taken, text or not: writing an
  image as its caption or its address for a model that reads no images is
  legitimate (case 272). So `format/json` is unchanged (still 0.1.0).
- **Bridges.** Python and Julia find a binding by the value, so
  `list[ImagePart]` (`Vector{LM15.ImagePart}`) and `Optional[ImagePart]`
  (`Union{LM15.ImagePart, Nothing}`) take lm15 parts as they are: the
  list default receives each bound item's JSON form, as D-61 gives the
  kernel's defaults a bound value's. Julia's `lift`, which only applied
  the annotation's own hook, now rebuilds `Union{T, Nothing}` as `T` and a
  `Vector{T}` item by item, as Python's does, so `load_turn` rebuilds the
  parts. TypeScript and R find bindings by type name (D-62), so the
  bridges bind `list[ImagePart]` and `Optional[ImagePart]` (Python's
  spellings, so one artifact's format keys hold in every language), item
  by item, and give fields for them: `media.list(media.image())`,
  `media.nullable(media.image())`; `lm15_media("image", list = TRUE)`,
  `lm15_media("image", nullable = TRUE)`.

Costs, stated. **Behaviour changes under a patch number**, for D-60's
reason: no artifact changes meaning for a field that holds no media, and
every 0.8 artifact loads; what reads differently are fields that were
being sent wrongly. A list of pictures under `*` or `list[*]` that wrote
JSON text now sends parts; an `Optional` picture given `null` used to
write the text `null` through `json`, and still does through the default.
A record holding a picture under `*` or `object` used to render (as
base64 text) and now refuses at bind: a program that "worked" stops, by
design. **Not covered, stated:** a list of nullable media, a nullable list
of media, a list of lists of media and a record holding media have no
default (the first cannot tell an item `null` from one left out; the
others need a layout that is vocabulary): each refuses `no-format` unless
a format is bound for it. A value holding media under a shape that does
not say so is not seen: Python's frontend lowers `dict[str, ImagePart]`
to `{"type": "object"}` (changing that would change fingerprints), and
`lmcc_dspy` lowers `list[dspy.Image]` and `Optional[dspy.Image]` through
pydantic, as an object with a `url`, so `json` under `*` still writes
those as text; the DSPy frontend's media types are a separate piece of
work (its single `Image` already writes no `media_type`, which lm15
needs). A format written for every value that writes parts and was not
written for media is taken, as before. In Julia a `Vector{LM15.ImagePart}`
field is still named by `string(T)`, which depends on the caller's
imports, as every unbound Julia name is (D-62 gave bound types a `name`).
FunctAI's warning for media below a function's top level (its stopgap for
this issue) can drop the list and optional cases on lmcc 0.8.7.

Ratified-by: Maxime Rivest, 2026-10-09 (in session): "fix issue 7 fully
and excellently, publish a new version". The choice of the kernel rule
over the issue's `json` refusal, the nullable default and the bridge
spellings were made while building it and are stated here for review.

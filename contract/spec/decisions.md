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

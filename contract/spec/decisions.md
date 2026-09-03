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

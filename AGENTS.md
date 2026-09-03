# LMCC — agent operating manual

You are an agent working in this repository. This file is your cockpit:
the map, the physics, the controls, and the protocol. Read it first;
verify it second (`./check`); trust it only after it runs green.

**One sentence.** LMCC is the calling convention for calling a model:
where each argument goes, how the result comes back, how each type
crosses — as inspectable, versioned, cross-language data. The design is
`research/ideal-readme-v3.md` (local); `contract/spec/kernel.md` is its
normative form.

## The tower (read bottom-up; authority flows up)

```
  L5  programs            your code: @lmcc.fn signatures + values in, values out
  L4  vocabulary packs    python/lmcc_std, go/lmccstd (+ anyone's): formats,
                          strategies, lenses — plugged into sockets, zero privilege
      frontends           python/lmcc_dspy (any dspy.Signature), Go struct tags,
                          @lmcc.fn; any syntax lowers, none is the contract
  L3  the plan            bind(adapter × signature × capabilities) → Plan
                          all refusals fire HERE, before any money is spent
  L2  the artifact        template + parse + strategies by role + formats by
                          type — never a field name (schema/entry.schema.json);
                          a shipped format is the one place it carries code,
                          declared (language, deps, sha256, author)
  L1  kernel mechanics    python/lmcc/ (reference) and go/lmcc/ (independent)
                          — core (signature, shapes, text rules, parts, spans),
                          template (3 constructs), lens (derived), formats
                          (defaults, resolution, UDF admission), strategy,
                          plan (bind/render/parse/skeleton/prefix), serde
  L0  the contract        contract/ — spec (meaning), schema (form),
                          corpus (byte-exact truth), harness (the judge)
```

L0 outranks everything. If code and corpus disagree, the code is wrong.
If spec and corpus disagree, fix the corpus first, deliberately, then both.

## The three generative rules

Every design answer in this repo derives from three rules. When you face
a decision, derive from these before inventing anything:

1. **One description, many directions.** The template's output pattern
   renders the prompt, writes the demos and history turns, and derives
   the parser — one object, drift unrepresentable. Any feature that
   would create a second copy of a contract is wrong by construction.
2. **Data over code at every seam; code declared where it must exist.**
   Artifacts, plans, strategies, predicates, anchors: plain data. The
   one place an artifact carries code is a shipped format, and it says
   so on the entry; loading never runs it. Type → format decides *how* a
   value is spelled; role → strategy decides *where* it travels; the
   template decides where visible things sit (v3 §6b).
3. **Refuse loudly, before money.** Bake is the gate. Every failure has
   a stable code (`contract/spec/errors.md`), names its exact offender,
   and says what to do next. Ambiguity refuses (`parse-ambiguous`);
   guessing is the one forbidden behavior.

## Invariants — verify, do not trust

| invariant | enforced by |
|---|---|
| corpus is byte-exact authority | `contract/harness/runner.py` (73 cases; 6 need `udf:python`) |
| the contract is portable: an independent Go kernel passes every claimable case byte-exactly, and both kernels raise the same refusal-code set (minus the declared placement-only code) | `./check` step 5 (`runner.py --driver go/bin/lmcc-conform`), `tests/test_coherence.py` |
| text primitives are portable: ASCII strip, explicit integer/number grammars, ECMAScript number spelling, RE2 regex (kernel §7a, §5) | corpus 35–37, 40–42, 44, 45; `tests/test_text_rules.py`; `go/lmcc/text_test.go` |
| `split(join(x)) == x` for marker-free, trimmed `x`; `join` refuses collisions (`value-collides`) | `tests/test_kernel.py`, `test_text_rules.py`; corpus 38 |
| the artifact never names a field: strategies by role, formats by type/structural key | `schema/entry.schema.json`; corpus 55 |
| resolution order: artifact type → structural key → runtime binding → kernel default → `*` → `no-format` | `tests/test_formats.py`; corpus 48–50, 55–56 |
| shipped formats are admitted (hash, self-containment, placement) and never run by `load` | `tests/test_formats.py`; corpus 57–62; Go answers `unclaimed` |
| all refusals fire at bind, never mid-render | refuse-corpus cases (`at: bind`) |
| data-only entries load with zero registrations | corpus case 08 + empty-registry harness default |
| kernel imports stdlib only, ships zero vocabulary | `tests/test_agent_surface.py` |
| artifacts never contain signatures | `schema/entry.schema.json` |
| duplicated anchors, closes, tails, and JSON keys refuse, never guess | corpus cases 32, 39, 46 |
| signatures and cases are schema-valid data | `./check` step 3 (`schema/signature.schema.json`, `schema/case.schema.json`); corpus 43 |
| any DSPy signature lowers (losing only DSPy's declared no-ops), bakes, renders and parses | `./check` step 6 (`tests/dspy/test_catalog.py` against real DSPy); D-23 |
| the kernel's shape set is closed: uninterpreted shapes need a codec; `@structured` gives one per entry | corpus 48–50; D-19, D-20 |
| plans and registries are JSON-serializable data | `tests/test_agent_surface.py` |
| docs cannot drift from code: every raised error code is in `spec/errors.md`, every registered vocab entry is indexed with a real spec file, case files match their declared names, std predicates only name declared facts, plans carry acceptance criteria | `tests/test_coherence.py` |

## Sense — how to see the system state

- `plan.describe()` → the whole plan as a plain dict (lens, anchors,
  visible/hidden fields, each field's format and *what resolved it*,
  routings, placements, fragments, patch, skeleton, `versions`).
  `plan.explain()` is its pretty-printer. Read plans, not code.
- `plan.skeleton()` (prefill, stops) and `plan.prefix()` (cache-stable
  messages) — what the plan knows about the reply and the prompt.
- `registry.describe()` → every named format, type binding, strategy,
  lens, and whether this runtime places UDFs.
- `adapter.dump()` → the artifact. Diff two of them to see any change.
- Every `Refusal` has `.code` (stable, in `spec/errors.md`), `.hint`
  (names the offender), and `.partial` (what parsing recovered).
- `render(...)` is pure: preview exact bytes without spending anything.

## Act — the accretion protocol (data first, always)

The order is the point: meaning, then truth, then code.

1. **Spec.** Write or amend the vocabulary/spec file. Behavior including
   the ugly cases (escaping, fences, nulls) must be written down.
2. **Corpus.** Hand-author the case bytes *first* (`corpus/README.md`).
   The harness diff is your reviewer: run it, read the mismatch, decide
   which side is right. Authority never flips back to code.
3. **Code.** Implement until `./check` is green.
4. **Memory.** If a rule changed or a trade-off was taken, append one
   entry to `contract/spec/decisions.md`. Never absorb a trade-off.

Checklists:

- **new format/strategy/lens**: spec file in `contract/spec/vocab/` →
  corpus cases (`"vocab": ["std"]` or your pack) → register through the
  socket in a pack (never the kernel) → row in `spec/vocab/README.md`.
  A format declares `accepts`, `direction`, `emits`, `round_trip`.
- **new capability fact**: row in `spec/vocab/capabilities.md` (minor
  version bump) → a corpus case that predicates on it.
- **new error code**: row in `spec/errors.md` → a refuse-corpus case
  asserting it → raised in **both** kernels (the coherence test
  requires identical code sets). Changing *when* a code fires is
  breaking.
- **kernel change**: touches `spec/kernel.md` first; expect corpus
  changes to be reviewed as contract changes; implement in `python/`
  and `go/` — the corpus will not pass until both agree.
- **anything that touches model text**: use the §7a primitives
  (`core.strip`, `read_integer`, `format_number` / `lmcc.Strip`,
  `ReadInteger`, `FormatNumber`), never the host language's own
  `strip`/`int`/`float`/`repr`. That is where cross-language drift hides.
- **a case that ships a UDF**: declare `"requires": ["udf:python"]`; a
  driver without that placement answers `unclaimed`, never a false pass.

## Verify — one command

```
./check     # python tests + harness + schemas + README-verbatim
            # + go/check + the Go binary through the harness
            # + the DSPy catalog against a real DSPy; green = holds
```

Run it before you start (baseline), after every meaningful change, and
before every commit. It is cheap (~seconds). Never commit red.

## Plans — the work queue

`plans/` holds the ratified next steps, each with motivation, design,
and **acceptance criteria** (what corpus cases and tests must exist for
it to be done). Pick one, execute the accretion protocol, check it off.
Add new plans the same shape; a plan without acceptance criteria is a
wish, not a plan.

## Decisions — the memory

`contract/spec/decisions.md` is the append-only log of ratified choices
and their reasons. Read it before proposing a design change — most
"why not X?" questions are answered there. Append after ratifying.

## Conventions

- Commit messages: plain, factual, no AI mentions, no signatures.
- Corpus provenance: cases 01–19 were seeded once then frozen; every
  later case is authored by hand first (see `corpus/README.md`).
- Versions: semver per vocabulary entry; while major = 0, minor is
  breaking. Artifacts pin what they need; loaders refuse mismatches.
- Research lineage (adapter RFCs, conversation maps, the ideal-README
  drafts) is kept locally in `research/`, which is git-ignored and not
  published; `decisions.md` cites it where relevant. Ask the maintainer
  for it before proposing a design change.
# a15 — agent operating manual

You are an agent working in this repository. This file is your cockpit:
the map, the physics, the controls, and the protocol. Read it first;
verify it second (`./check`); trust it only after it runs green.

**One sentence.** a15 owns typed signature ⇄ messages: how a declared
I/O contract renders into a prompt and how the reply becomes typed
values again — as inspectable, versioned, cross-language data.

## The tower (read bottom-up; authority flows up)

```
  L5  programs            your code: signatures + values in, values out
  L4  vocabulary packs    python/a15_std (+ anyone's): codecs, strategies,
                          lenses, hosts — plugged into sockets, zero privilege
  L3  the plan            bake(entry × signature × capabilities) → Baked
                          all refusals fire HERE, before any money is spent
  L2  the entry           the artifact: template + parse + strategies +
                          codecs, pure data (schema/entry.schema.json)
  L1  kernel mechanics    python/a15/ — core (shapes, scalars, messages),
                          template (3 constructs), parse (lens + extract
                          algebra), plan (bake/render/parse), serde, registry
  L0  the contract        contract/ — spec (meaning), schema (form),
                          corpus (byte-exact truth), harness (the judge)
```

L0 outranks everything. If code and corpus disagree, the code is wrong.
If spec and corpus disagree, fix the corpus first, deliberately, then both.

## The three generative rules

Every design answer in this repo derives from three rules. When you face
a decision, derive from these before inventing anything:

1. **One description, many directions.** The template's output-pattern
   block renders the prompt, writes the demos, and derives the parser —
   one object, drift unrepresentable. Any feature that would create a
   second copy of a contract (a format instruction apart from its
   parser, a demo apart from its reader) is wrong by construction.
2. **Data over code at every seam.** Entries, plans, strategies,
   predicates, anchors: plain data — diffable, serializable,
   cross-language, optimizable, and safe to accept from anyone
   (analysis replaces trust). Code survives only at the host boundary
   (native types) and inside registered vocabulary, behind sockets.
3. **Refuse loudly, before money.** Bake is the gate. Every failure has
   a stable code (`contract/spec/errors.md`), names its exact offender,
   and says what to do next. Ambiguity refuses (`parse-ambiguous`);
   guessing is the one forbidden behavior.

## Invariants — verify, do not trust

| invariant | enforced by |
|---|---|
| corpus is byte-exact authority | `contract/harness/runner.py` (34+ cases) |
| `parse(join(x)) == x` for every lens | `tests/test_kernel.py`, `test_derived.py`, `test_lenses.py` |
| all refusals fire at bake, never mid-render | refuse-corpus cases (`at: bake`) |
| data-only entries load with zero registrations | corpus case 08 + empty-registry harness default |
| kernel imports stdlib only, ships zero vocabulary | `tests/test_agent_surface.py` |
| entries never contain signatures | `schema/entry.schema.json` |
| duplicated anchors refuse, never guess | corpus case 32 |
| plans and registries are JSON-serializable data | `tests/test_agent_surface.py` |
| docs cannot drift from code: every raised error code is in `spec/errors.md`, every registered vocab entry is indexed with a real spec file, case files match their declared names, std predicates only name declared facts, plans carry acceptance criteria | `tests/test_coherence.py` |

## Sense — how to see the system state

- `baked.describe()` → the whole plan as a plain dict (lens, anchors,
  visible/hidden fields, routings, fragments, patch, codecs, strategies,
  and `versions` — the exact vocabulary versions the plan stands on).
  `baked.explain()` is its pretty-printer. Read plans, not code.
- `registry.describe()` → every registered codec/strategy/lens/coercion/
  host with versions. One call answers "what vocabulary exists here?"
- `adapter.dump()` → the artifact. Diff two of them to see any change.
- Every `A15Error` has `.code` (stable, in `spec/errors.md`), `.detail`
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

- **new codec/strategy/lens**: spec file in `contract/spec/vocab/` →
  corpus cases (`"vocab": ["std"]` or your pack) → register through the
  socket in a pack (never the kernel) → row in `spec/vocab/README.md`.
- **new capability fact**: row in `spec/vocab/capabilities.md` (minor
  version bump) → a corpus case that predicates on it.
- **new error code**: row in `spec/errors.md` → a refuse-corpus case
  asserting it. Changing *when* a code fires is breaking.
- **kernel change**: touches `spec/kernel.md` first; expect corpus
  changes to be reviewed as contract changes.

## Verify — one command

```
./check     # tests + harness + schema + README-verbatim; green = holds
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
- Research lineage lives outside this repo (`~/Projects/adapter-rfc`,
  dspy roadmap docs); `decisions.md` cites it where relevant. The map to
  all of it is `research/` (sources by tier, research axes, ranked
  conversations). Read `research/axes.md` before proposing a design.

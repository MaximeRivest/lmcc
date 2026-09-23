# LMCC — agent operating manual

You are an agent working in this repository. This file is your cockpit:
the map, the physics, the request_settings, and the protocol. Read it first;
verify it second (`./check`); trust it only after it runs green.

**One sentence.** LMCC is the calling convention for calling a model:
where each argument goes, how the result comes back, how each type
crosses — as inspectable, versioned, cross-language data. The design is
`research/ideal-readme-v3.md` (local); `contract/spec/kernel.md` is its
normative form.

## The tower (read bottom-up; authority flows up)

```
  L5  programs            your code: @lmcc.fn signatures + values in, values out
  L4  vocabulary packs    python/lmcc_std (+ anyone's): formats,
                          transports, readers — plugged into sockets, zero privilege
      frontends           python/lmcc_dspy (any dspy.Signature), @lmcc.fn;
                          any syntax lowers, none is the contract
  L3  the plan            bind(adapter × signature × capabilities) → Plan
                          all refusals fire HERE, before any money is spent
  L2  the artifact        template + reader + transports by purpose + formats by
                          type — never a field name (schema/entry.schema.json);
                          renders to an lm15 request minus model, parses an
                          lm15 message/response (contract/LM15_CONTRACT_PIN);
                          a shipped format is the one place it carries code,
                          declared (language, deps, sha256, author)
  L1  kernel mechanics    python/lmcc/ (the one implementation, while the
                          language is designed; others are rebuilt from L0)
                          — core (signature, shapes, text rules, parts, captures),
                          template (4 constructs), reader (derived), formats
                          (defaults, resolution, UDF admission), transport,
                          plan (bind/render/parse/skeleton/prefix), serde
  L0  the contract        contract/ — spec (meaning), schema (form),
                          corpus (byte-exact truth), harness (the judge)
```

L0 outranks everything. If code and corpus disagree, the code is wrong.
If spec and corpus disagree, fix the corpus first, deliberately, then the code.

## Portability: core + declared extensions (D-31, D-33)

Read `contract/spec/portability.md` (the boundary and the core inventory),
kernel §10 (the mechanism) and `contract/spec/extensions/README.md` (the
index) before touching anything outside the core. The core is exact and
mandatory; everything else is a named, versioned extension the artifact
declares (`entry.extensions`) and the host binds (`Registry.extensions`)
or refuses — `extension-undeclared` / `extension-unsupported` /
`version-incompatible`, each with a fix, before any plan. Host support and
model capabilities are separate vocabularies; never overload one for the
other. Regex is not core: `pattern/legacy-re2` is the migration bridge
(what 0.2 did, limits stated), not a rigorously specified dialect. Do not
build a regex engine to be conformant; `plans/10` lists what is still open.

## The three generative rules

Every design answer in this repo derives from three rules. When you face
a decision, derive from these before inventing anything:

1. **One description, many directions.** The template's output pattern
   renders the prompt, writes earlier turns (examples and conversations), and derives
   the parser — one object, drift unrepresentable. Any feature that
   would create a second copy of a contract is wrong by construction.
2. **Data over code at every seam; code declared where it must exist.**
   Artifacts, plans, transports, predicates, anchors: plain data. The
   one place an artifact carries code is a shipped format, and it says
   so on the entry; loading never runs it. Type → format decides *how* a
   value is spelled; purpose → transport decides *where* it travels; the
   template decides where visible things sit (v3 §6b).
3. **Refuse loudly, before money.** Bake is the gate. Every failure has
   a stable code (`contract/spec/errors.md`), names its exact offender,
   and says what to do next — before render, as data: a `fix` from the
   closed action vocabulary. Ambiguity refuses (`parse-ambiguous`);
   guessing is the one forbidden behavior.

## Invariants — verify, do not trust

| invariant | enforced by |
|---|---|
| corpus is byte-exact authority | `contract/harness/runner.py` (178 cases; 6 need `udf:python`, 9 need `pattern/legacy-re2`) |
| one record, the turn, replaces demos and history (kernel §3a): examples, past exchanges and the exchange in progress are written by the plan's own writers; a recorded reply this plan reads back without a marker repair is replayed verbatim; hidden fields have derived or declared writers checked at bind; call ids stay unique; a tool's images survive text transports | corpus 03, 53, 54, 103, 107, 116, 122, 128–148; `tests/test_turns.py` |
| formatted turns use the same argument writer for past calls and the representative bind probe; raw-code whitespace is preserved and marker collisions refuse | corpus 116–127; `tests/test_heredoc_turns.py`; notebook `docs/howto/12-conversational-heredoc-tools.md` |
| tools and citations are live purposes: the same program runs native (lm15 `tool_call`/`citation` parts, `Request.tools`) and as text (`fenced_tools`, `inline_citations`); a call turn is a reply (`complete_reply`); a text spelling of a past call must read back through its own find rule (`turns` probe, `spelling-drift`) | corpus 100–112; `tests/test_tools_citations.py`; `python/integration/lm15_tools_citations.py` (live, by hand) |
| the wire is lm15: parts `type`, messages `parts`, `system` a request field, request_settings a partial lm15 request validated at `config.<field>`/`tools`; `render().request(model)` feeds lm15's `request_from_dict` unchanged | every render case's `expect.request`; cases 96–98; `tests/lm15/test_bridge.py` through a real lm15 at the pinned commit (`./check` step 6) |
| the contract is portable and one implementation holds it: the Python kernel passes every claimable case byte-exactly in process *and* through the language-neutral driver protocol, stream traces included; every documented code is raised and every raised code documented. Other languages are rebuilt from the contract later; the Go kernel that passed 0.6 is at the tag `kernel-0.6` (D-41) | `./check` steps 1–2, `tests/test_driver_protocol.py`, `tests/test_coherence.py` |
| the derived reader repairs misspelled markers by one rule (ASCII case, spaces, `*`/`_`/`#`, never across a line), opted-in find rule delimiters and value slips too (`strict` turns all off), the exact spelling wins, overlapping repairs refuse, every repair and tolerance is reported in a fixed order, and a reply cut at its length limit never reads as finished (kernel §4a) | corpus 149–169; `tests/test_repairs.py` (including a streaming fuzz of misspelled replies against batch) |
| text primitives are portable: ASCII strip, explicit integer/number grammars, ECMAScript number spelling (kernel §7a) | corpus 35–37, 44, 45; `tests/test_text_rules.py` |
| the core needs no regex: a `pattern` find rule requires a declared `pattern/*` extension; a core-only host refuses before model I/O; every native binding has an indexed spec | corpus 40, 42, 91–95; `tests/test_extensions.py`; `tests/test_coherence.py` |
| `split(join(x)) == x` for marker-free, trimmed `x`; `join` refuses collisions (`value-collides`) | `tests/test_kernel.py`, `test_text_rules.py`; corpus 38 |
| the artifact never names a field: transports by purpose, formats by type/structural key | `schema/entry.schema.json`; corpus 55 |
| resolution order: artifact type → structural key → runtime binding → kernel default → `*` → `no-format` | `tests/test_formats.py`; corpus 48–50, 55–56 |
| shipped formats are admitted (hash, self-containment, put) and never run by `load` | `tests/test_formats.py`; corpus 57–62 |
| streaming refines batch: every text/part split has identical final values or full refusal; field deltas concatenate independently of chunking; the one-scalar event trace is pinned through the driver protocol; per-feed work does not grow with the reply | corpus harness replays every parse and parse-refusal case whole, one scalar at a time, and at every split, and compares the stream trace sent through the driver protocol with the reference; seeded random multi-chunk fuzz, marker-overlap and scaling tests in `tests/test_streaming.py` |
| all refusals fire at bind, never mid-render | refuse-corpus cases (`at: bind`) |
| every refusal before render carries a `fix` from the closed action vocabulary; the corpus pins which one; render/parse refusals carry none | `spec/errors.md` (code → fix column, action table), `schema/fix.schema.json`, every pre-render refuse case pins `expect.fix`, `tests/test_coherence.py` (call-site rule), `tests/test_fix_hints.py` |
| data-only entries load with zero registrations | corpus case 08 + empty-registry harness default |
| kernel imports stdlib only, ships zero vocabulary | `tests/test_agent_surface.py` |
| artifacts never contain signatures | `schema/entry.schema.json` |
| duplicated anchors, closes, tails, and JSON keys refuse, never guess | corpus cases 32, 39, 46 |
| signatures and cases are schema-valid data | `./check` step 3 (`schema/signature.schema.json`, `schema/case.schema.json`); corpus 43 |
| any DSPy signature lowers (losing only DSPy's declared no-ops), bakes, renders and parses | `./check` step 5 (`tests/dspy/test_catalog.py` against real DSPy); D-23 |
| the kernel's shape set is closed: uninterpreted shapes need a codec; `@structured` gives one per entry | corpus 48–50; D-19, D-20 |
| plans and registries are JSON-serializable data | `tests/test_agent_surface.py` |
| docs cannot drift from code: every raised error code is in `spec/errors.md`, every registered vocab entry is indexed with a real spec file, case files match their declared names, std predicates only name declared facts, plans carry acceptance criteria | `tests/test_coherence.py` |

## Sense — how to see the system state

- `plan.describe()` → the whole plan as a plain dict (reader, anchors,
  visible/hidden fields, each field's format and *what resolved it*,
  find rules, puts, tell, request settings, skeleton, `versions`).
  `plan.explain()` is its pretty-printer. Read plans, not code.
- `plan.skeleton()` (prefill, stops) and `plan.prefix()` (cache-stable
  messages) — what the plan knows about the reply and the prompt.
- `stream = plan.stream()` → `stream.feed(delta)` emits started/raw-delta
  events; `stream.finish()` returns EOF events + typed values. Read
  `plan.describe()["streaming"]` before assuming a route/reader streams.
- `registry.describe()` → every named format, type binding, transport,
  reader, and whether this runtime places UDFs.
- `adapter.dump()` → the artifact. Diff two of them to see any change.
- Every `Refusal` has `.code` (stable, in `spec/errors.md`), `.hint`
  (names the offender), `.fix` (the next action as data, on every
  refusal before render), and `.partial` (what parsing recovered);
  `.describe()` is all four as a dict.
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

- **new format/transport/reader**: spec file in `contract/spec/vocab/` →
  corpus cases (`"vocab": ["std"]` or your pack) → register through the
  socket in a pack (never the kernel) → row in `spec/vocab/README.md`.
  A format declares `accepts`, `direction`, `writes`, `round_trip`.
- **new capability fact**: row in `spec/vocab/capabilities.md` (minor
  version bump) → a corpus case that predicates on it.
- **new error code**: row in `spec/errors.md` (with its fix action, or
  `—` if it fires at render/parse) → a refuse-corpus case asserting it
  and, before render, its `fix` → raised in the kernel (the coherence
  test requires every documented code to be raised, every raised code to
  be documented, and every call site to carry a fix exactly when the
  table says so). Changing *when* a
  code fires is breaking.
- **new fix action**: row in the action table of `spec/errors.md` →
  branch in `schema/fix.schema.json` → a corpus case pinning it → the kernel
  writes it. Renaming an action or a parameter is breaking.
- **kernel change**: touches `spec/kernel.md` first; expect corpus
  changes to be reviewed as contract changes; implement in `python/` —
  the corpus decides; code never rewrites a case to match itself.
- **anything that touches streaming**: preserve the §8 refinement law;
  add every-split tests (the harness replays every split); never write a prefix a
  later delta can revise; make every forced buffer visible in
  `plan.describe()["streaming"]`.
- **anything that touches the wire** (a part, a message, a request field):
  the word is lm15's, never a synonym; a new lm15 field the request settings may
  set goes into the pinned `Config` list in the kernel *and* the spec,
  with the contract pin bumped deliberately. lmcc's own objects (events,
  refusals, plans) stay in lmcc's words.
- **anything that touches model text**: use the §7a primitives
  (`core.strip`, `read_integer`, `format_number`), never the host language's own
  `strip`/`int`/`float`/`repr`. That is where cross-language drift hides.
- **a case that needs anything beyond the core**: declare it in
  `requires` (`udf:python`, `pattern/legacy-re2`); drivers bind exactly
  that, so a forgotten requirement refuses; a driver lacking it answers
  `unclaimed`, never a false pass.
- **new extension**: spec file in `contract/spec/extensions/` pinning
  every observable outcome and its limits → row in the index → corpus
  cases that `requires` it → a binding in the kernel
  (`native_extensions()`; the coherence test checks it is indexed at its
  version) → one decision entry.

## Notebooks and REPLs

`./dev-venv` builds `.venv` (lmcc editable + `lmcc_std` + `lmcc_lm15` with
the pinned lm15 + IPython) and registers the rat runtime `py@lmcc` on it,
so every `docs/howto/*.md` runs as an mrmd notebook. `lmcc` is not on PyPI
yet (checked 2026-09-23; the name is free); install it editable from
`python/`. The package version equals the kernel version.

## Verify — one command

```
./check     # python tests + harness (in process and via the driver
            # protocol) + schemas + README-verbatim + the DSPy catalog
            # against a real DSPy + the lm15 bridge; green = holds
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
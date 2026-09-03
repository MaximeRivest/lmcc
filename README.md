# LMCC — the language model calling convention

LMCC makes a language model callable like a typed function. It turns a
declared I/O contract into lm15-shaped messages and request controls. It
then turns the model reply back into typed values. LMCC never sends the
request; any model client can do that.

The knowledge of how to talk to models — which layouts, spellings, and
reasoning formats work per model family — is folklore today. It lives in
prompt strings and dies in codebases. LMCC makes that knowledge an
inspectable, shareable, versioned artifact that can accumulate and travel.

## The shape of the thing

```
contract/          the authority (no code)
  spec/            kernel spec + per-entry vocabulary specs
  schema/          the artifact file format (JSON Schema)
  corpus/          fixture cases — byte-exact, the real source of truth
  harness/         runs any implementation against the corpus
python/
  lmcc/             the reference kernel: mechanics only (template engine,
                   lens, bake/render/parse, serde, sockets, refusals)
  lmcc_std/         the standard vocabulary pack — a separate package,
                   registered through the same sockets as yours
  lmcc_dspy/        the DSPy frontend: any dspy.Signature → SignatureCore
  tests/           kernel tests + the corpus, as pytest; tests/dspy is
                   the DSPy catalog (needs dspy; ./check builds a venv)
go/
  lmcc/, lmccstd/  an independent Go implementation of both, stdlib only
  cmd/lmcc-conform the corpus driver the harness runs it through
```

**The kernel ships zero codecs, zero strategies, zero host types.** Every
named thing is vocabulary: a spec file, corpus cases, and a package that
registers through the sockets. `codec/json` has exactly the standing your
lab's codec has. (Precedent: serde ships without serde_json.)

## Quickstart

```python
import lmcc, lmcc_std
lmcc_std.install()

sig = lmcc.signature(
    "Answer the question.",
    inputs={"question": str},
    outputs={"reasoning": lmcc.field(str, role="reasoning"),
             "answer": str, "score": int},
)

adapter = lmcc.adapter(
    template=lmcc.template([
        lmcc.message("system",
            "{instruction}\n\nAnswer in exactly this form:\n"
            "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        lmcc.directive("demos"),
        lmcc.message("user",
            "{% for f in inputs %}== {f.name} ==\n{f.value}\n{% endfor %}"),
    ]),
    parse={"kind": "derived"},   # the parser is deduced from the template
    strategies={"reasoning": "reasoning_tags"},   # swap: "native_reasoning"
)

baked = adapter.bake(sig, {"instruct": True})     # all refusals fire here
request = baked.render(inputs={"question": "Why is the sky blue?"})
# → plain lm15-shaped messages + request patch; send with any client

values = baked.parse("<answer>\nRayleigh<think>blue scatters</think> scattering.\n"
                     "</answer>\n<score>\n9\n</score>")
# {'reasoning': 'blue scatters', 'answer': 'Rayleigh scattering.', 'score': 9}

entry = adapter.dump()        # the artifact: pure data, versioned
adapter2 = lmcc.load(entry)    # loads with zero ambient state
```

Same signature, same program: bind `"native_reasoning"` instead and the
reasoning field leaves the token stream entirely, served by the model's
thinking channel. That swap costing one word is the point of the library.

## Design rules (each one is load-bearing)

1. **Adapters are signature-independent.** An entry never contains a
   signature; the two meet only at `bake`.
2. **The template is the lens.** One description, two directions: the
   output-pattern block in the template renders the prompt, writes the
   demo turns, and *derives the parser* — none of the three can drift.
   Patterns that cannot invert refuse at bake (`not-lensable`); replies
   that read two ways refuse at parse (`parse-ambiguous`) — never a
   silent guess.
3. **Invertible surroundings, semantic insides.** The exchange layer
   separates fields by spelling; meanings (JSON and friends) live inside
   typed fields, via codecs. Whole-object JSON is a *mode*, gated on the
   declared `native_structured_output` capability, with the request
   patched to enforce the schema — never an unconditional style.
4. **Scalars are mechanics; structure is vocabulary.** The kernel spells
   strings and JSON literals; anything structured requires a codec, or it
   refuses.
5. **Strategies are data with a predicate.** A boolean expression over
   declared capability facts (`{"not": {"capability":
   "native_reasoning"}}`), checked at bake, refused by name — before any
   money is spent.
6. **Loud refusal, stable codes.** `contract/spec/errors.md`; asserted by
   the corpus. Silent wrong rendering is the one forbidden bug.
7. **The corpus is the authority.** An implementation is conformant when
   the harness passes byte-exactly — not before. Two do today: the
   Python reference and an independent Go kernel (`go/`), both run by
   `./check`. The primitives that make "byte-exact" meaningful across
   languages — whitespace, number grammars and spelling, the regex
   dialect — are pinned in `kernel.md` §5 and §7a rather than left to
   each host language's `strip`, `float`, and `re`.
8. **Signatures are neutral data; syntaxes are frontends.** Python type
   hints, Go struct tags, JSON Schema, or any signature DSL lower to
   the same `SignatureCore` (`schema/signature.schema.json`). The kernel
   never sees the syntax you wrote. `python/lmcc_dspy` lowers **any
   `dspy.Signature`** — pydantic models, `Optional`, `Literal`, enums,
   images, `History`, `Reasoning`, tools — and a 16-row catalog run
   against a real DSPy proves each one bakes, renders and parses
   (`plans/07-dspy-parity.md`). LMCC renders its own way; it does not
   imitate DSPy's prompt bytes.

## What "portable" means here, exactly

- The **artifact** (the entry) is plain data and travels anywhere.
- The **kernel** is portable: the corpus proves two independent
  implementations produce the same bytes and the same refusals.
- **Vocabulary** (codecs, strategies, lenses) is code, per language.
  An artifact that names `codec/json` runs in a runtime only if that
  runtime has a pack claiming `codec/json` at a compatible version;
  otherwise it refuses by name (`unknown-codec`). Byte-exactness across
  runtimes holds when both packs pass the entry's corpus cases.
- **Host types** never travel; each runtime binds its own.

So an artifact is portable data whose executable meaning is supplied,
verified, and versioned per runtime — not code that runs everywhere by
itself. That trade-off is deliberate and stated, not hidden.

## For agents (and fast-moving humans)

`AGENTS.md` is the cockpit: the system map, the invariants and the
tests that enforce them, the accretion protocol (spec → corpus → code),
and the introspection surface (`baked.describe()`,
`registry.describe()`). `plans/` is the work queue with acceptance
criteria; `contract/spec/decisions.md` is the append-only memory of why
things are the way they are. One command verifies everything:

```
./check
```

## Learning the kernel

`GUIDE.md` is the kernel-only walkthrough (no std pack): signatures,
the derived lens, refusals, inline strategies, host types, your own
codecs, and the artifact. Every code block in it is executed by the
test suite — the guide cannot drift from the kernel.

## Running the checks

```
./check                                            # everything, both languages
cd python && PYTHONPATH=. pytest tests/            # python kernel + corpus
PYTHONPATH=python python contract/harness/runner.py  # harness, python reference
cd go && ./check                                   # go kernel + corpus
PYTHONPATH=python python contract/harness/runner.py --driver go/bin/lmcc-conform
```

## Rename

The project previously used the working name `a15`. The public Python
packages are now `lmcc` and `lmcc_std`. The refusal type is `LMCCError`.
There are no legacy import aliases because this is a pre-release contract.
Historical conversation links keep the old name so those links still work.

## Status (0.1.0) — deliberate gaps

Streaming parse, the `requires` declaration for authored-code sidecars,
tools/citations strategy vocabularies, and media emission options are
out, on purpose, and listed in `contract/spec/kernel.md`. Each lands as
a versioned addition. Known, stated holes in what *is* in: marker
lenses trim outer whitespace of values (a round trip normalizes it),
and a reply that omits its close marker while containing that marker
inside the value cannot be detected (`kernel.md` §4).

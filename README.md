# a15 — the adapter kernel

a15 owns one seam of the LLM stack: **typed signature ⇄ messages**. It
turns a declared I/O contract into a prompt, and a model's reply back into
typed values — and it makes the *how* of that conversation a first-class,
inspectable, shareable, versioned artifact.

The knowledge of how to talk to models — which layouts, spellings, and
reasoning formats actually work per model family — is folklore today: it
lives in prompt strings and dies in codebases. a15's job is to make that
knowledge accumulate and travel. Everything in this repo is derivable from
that sentence; anything that isn't gets cut.

## The shape of the thing

```
contract/          the authority (no code)
  spec/            kernel spec + per-entry vocabulary specs
  schema/          the artifact file format (JSON Schema)
  corpus/          fixture cases — byte-exact, the real source of truth
  harness/         runs any implementation against the corpus
python/
  a15/             the kernel: mechanics only (template engine, lens,
                   bake/render/parse, serde, sockets, refusals)
  a15_std/         the standard vocabulary pack — a separate package,
                   registered through the same sockets as yours
  tests/           kernel tests + the corpus, as pytest
```

**The kernel ships zero codecs, zero strategies, zero host types.** Every
named thing is vocabulary: a spec file, corpus cases, and a package that
registers through the sockets. `codec/json` has exactly the standing your
lab's codec has. (Precedent: serde ships without serde_json.)

## Quickstart

```python
import a15, a15_std
a15_std.install()

sig = a15.signature(
    "Answer the question.",
    inputs={"question": str},
    outputs={"reasoning": a15.field(str, role="reasoning"),
             "answer": str, "score": int},
)

adapter = a15.adapter(
    template=a15.template([
        a15.message("system",
            "{instruction}\n\nAnswer in exactly this form:\n"
            "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        a15.directive("demos"),
        a15.message("user",
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
adapter2 = a15.load(entry)    # loads with zero ambient state
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
7. **The corpus is the authority.** A second implementation (Go, TS) is
   conformant when the harness passes byte-exactly — not before.

## Running the checks

```
cd python && PYTHONPATH=. pytest tests/            # kernel + corpus
PYTHONPATH=python python contract/harness/runner.py  # harness alone
```

## Status (0.1.0) — deliberate gaps

Streaming parse, the `requires` declaration for authored-code sidecars,
tools/citations strategy vocabularies, media emission options, and non-Python
implementations are all out, on purpose, and listed in
`contract/spec/kernel.md`. Each lands as a versioned addition.

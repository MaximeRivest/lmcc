# lmcc — the calling convention for calling a model

When your program calls a function in another language, a **calling
convention** says where each argument goes, how the result comes back,
and how each type crosses the boundary. A model is another language.
lmcc is its calling convention.

```
signature (your typed function)
        │  write: each value → its place on the wire
        ▼
   the wire: messages, parts, request controls        ← the adapter lays this out
        │  read: the reply → each typed value
        ▼
your typed return value
```

lmcc never touches the network. It lays out the call and reads the
return. You send. Every code block below runs in the test suite; every
claim is a corpus case that two independent implementations (Python,
Go) pass byte for byte.

## 1. A signature

```python
import lmcc

@lmcc.fn
def answer(question: str) -> str:
    """Answer the question in one sentence."""
```

Inputs from the parameters, outputs from the return type, instructions
from the docstring. Nothing else is inferred. Several outputs: return a
dataclass. One structured value: `-> lmcc.One[Person]`.

## 2. An adapter is a template

```python
xml = lmcc.adapter(messages=[
    lmcc.system(
        "{instruction}\n\n"
        "Reply with exactly this pattern:\n"
        "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.demos(),
    lmcc.user("{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
])
```

An adapter never knows your field names — that is what lets one adapter
serve every signature. The template has three constructs and nothing
else:

| construct | example | meaning |
|---|---|---|
| slot | `{instruction}`, `{question}`, `{f.name}`, `{f.value}` | a value goes here |
| loop | `{% for f in inputs %} … {% endfor %}` (also `outputs`) | once per field |
| escape | `{{`, `}}` | a literal brace |

`lmcc.demos()` marks where worked examples go. Read the template top to
bottom and you know the prompt. If a byte is not in the template or in a
format you registered, it is not in the prompt.

## 3. Bind, render, parse

```python
plan = answer.bind(xml, capabilities={"instruct": True})

request = plan.render(question="Why is the sky blue?")
assert request.messages[1]["content"][0]["text"] == "<question>\nWhy is the sky blue?\n</question>\n"
assert request.patch == {}

assert plan.parse("<answer>\nRayleigh scattering.\n</answer>") == {"answer": "Rayleigh scattering."}
```

- `bind` joins a signature, an adapter, and what the model declares it
  can do. **Every refusal fires here**, before any call.
- `render` and `parse` are pure. Look at a million prompts for free.
- The rendered form is plain messages with parts plus a request patch.
  Hand it to any client.

## 4. The template is the parser

You wrote no parser for `xml`. lmcc read the output pattern backwards:
the literal before each output hole is its anchor, the literal after it
its close. Rename `<answer>` to `<reply>` and the prompt *and* the parser
change in the same edit. Demos are written through the same pattern the
model is asked to follow.

```python
assert plan.describe()["lens"]["anchors"] == [["answer", "<answer>\n", "\n</answer>\n"]]
demo = plan.render(question="q", demos=[{"question": "d", "answer": "a"}]).messages[2]
assert plan.parse(demo["content"][0]["text"]) == {"answer": "a"}
```

Two rules keep it honest: a pattern that cannot be read backwards
refuses at bind (`not-lensable`, naming the field); a reply that reads
two ways refuses at parse (`parse-ambiguous`). lmcc never guesses.

**The JSON rule.** "Reply with a JSON object" names a format, not a
pattern, so it cannot be read backwards. Spell the pattern — it reads
back:

```python
spelled = lmcc.adapter(messages=[
    lmcc.system('Reply exactly like this:\n{{"answer": "{answer}", "score": {score}}}'),
    lmcc.user("{question}")])
qa = lmcc.signature("Answer.", inputs={"question": str}, outputs={"answer": str, "score": int})
assert spelled.bind(qa).parse('{"answer": "Paris", "score": 9}') == {"answer": "Paris", "score": 9}
```

Or ask the server to enforce a schema: `lens/json_object` in the std
pack is that mode, gated on the `native_structured_output` capability.
Meanings go *inside* fields, through formats (§5). Surroundings stay
invertible.

## 5. Formats: how a type is written and read

A **format** is how one type crosses: `write` (value → what the model
sees) and `read` (the captured span → value). It is the only mechanism
for values. Scalars, enums and `Optional[...]` have kernel defaults;
anything with structure needs a format or refuses `no-format` — never a
silent `str()`.

```python
import dataclasses, json

@dataclasses.dataclass
class Person:
    name: str
    age: int

registry = lmcc.Registry()
registry.format(Person,
    write=lambda p: json.dumps(p.__dict__),
    read=lambda span: Person(**json.loads(span.text)),
    describe=lambda: "name and age, as JSON")

@lmcc.fn
def extract(text: str) -> lmcc.One[Person]:
    """Extract the person mentioned."""

plan = extract.bind(xml, registry=registry)
assert plan.parse('<extract>\n{"name": "Ann", "age": 41}\n</extract>') == {"extract": Person("Ann", 41)}
```

Three rules:

- **A format owns the whole value.** Resolution is by the type's name
  first (`Person`), then by structural shape (`list[object]`, `object`,
  `*`), then the runtime's binding, then the kernel default. The plan
  says which won: `plan.describe()["outputs"][0]["resolved_by"]`.
- **A format is a UDF, and the artifact can hold it whole** — `write`,
  `read`, `describe` as source, with language, deps, a hash, and who
  wrote them. Loading never runs it: a runtime that will not place code
  refuses `format-untrusted`; a tampered hash `udf-tampered`; source
  that reaches into globals `format-not-self-contained`. Where it runs
  is the host's rule.
- **`describe` is the optional third face** — what the model is told
  when it must reply with one. Default: the type's name.

`write` returns **parts** — text, or an image, or several. `read`
receives the **span** lmcc captured. An image format writes an image
part at the field's slot; a text-only format just reads `span.text`.

## 6. Strategies: how a meaning travels

Some fields are not just values. Reasoning, tools, citations, history:
for those the question is **how they travel** — in the text, or through
the model's own channel. That choice is a **strategy**: data, attached
to a role.

```python
@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Role["reasoning", str]
    answer: int

@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve it."""

tags = lmcc.Strategy(
    fragments={"system": "Think inside <think>…</think> before you answer."},
    routings=[{"from": "text", "between": ["<think>", "</think>"], "to": "@role", "consume": True}],
    visible=False)

native = lmcc.Strategy(
    requires=["native_reasoning"],
    visible=False,
    controls={"reasoning": {"effort": "medium"}},
    routings=[{"from": "channel:thinking", "to": "@role"}])

auto = lmcc.Strategy(choose=[
    {"when": {"capability": "native_reasoning"}, "use": native},
    {"else": tags},
])

adapter = lmcc.adapter(messages=xml.template, strategies={"reasoning": auto})
p1 = solve.bind(adapter, capabilities={"instruct": True})
p2 = solve.bind(adapter, capabilities={"instruct": True, "native_reasoning": True})
assert p1.parse("<think>4</think><answer>\n4\n</answer>") == {"answer": 4, "reasoning": "4"}
assert p2.render(problem="2+2").patch == {"reasoning": {"effort": "medium"}}
assert p2.parse({"content": [{"kind": "thinking", "text": "4"}, {"kind": "text", "text": "<answer>\n4\n</answer>"}]}) == {"answer": 4, "reasoning": "4"}
```

Same signature, same template, two inference behaviors — chosen by the
model's declared facts, never by editing the program. A strategy may add
text (`fragments`), hide its field (`visible`), read it back from a place
in the reply (`routings`), put its parts in the request or a message
(`placement`), and patch the request (`controls`).

## 7. Capabilities: refuse before you pay

```python
try:
    solve.bind(lmcc.adapter(messages=xml.template, strategies={"reasoning": native}),
               capabilities={"instruct": True})
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "capability-missing"
```

Capabilities are a closed, versioned vocabulary of facts, declared by
whoever knows the model. Nothing is sniffed.

## 8. What the plan knows

```python
assert p1.skeleton() == {"prefill": "<answer>\n", "stops": ["</answer>"]}
assert [m["role"] for m in p1.prefix()] == ["system"]
```

`skeleton` is what a client uses for assistant prefill and stop
sequences; `prefix` is the cache-stable bytes. `plan.describe()` is the
whole plan as data.

## 9. When the model gets it wrong

```python
try:
    p1.parse("<think>hmm</think>\n<answer>\nnine\n</answer>")
except lmcc.Refusal as r:
    assert r.code == "parse-value" and "nine" in r.hint
```

lmcc gives the hint. Retrying is not its job — a plan is one call.

## 10. The artifact

```python
entry = adapter.dump()
assert entry["template"] == xml.template and entry["parse"] == {"kind": "derived"}
assert list(entry["strategies"]) == ["reasoning"] and "formats" not in entry
again = lmcc.load(entry, registry=lmcc.Registry())
assert again.dump() == entry
```

One JSON file: template, parse rule, **strategies by role**, **formats
by type**. No signature, no field names, no hidden code — a shipped
format says so on its entry (language, deps, hash, author).
`lmcc.load(entry)` needs nothing ambient. Another implementation that
loads it lays out the same bytes.

## 11. Where things live

```
contract/          the authority (no code)
  spec/            kernel.md (the convention), errors.md, vocab/ specs
  schema/          entry, signature, case — JSON Schema
  corpus/          73 byte-exact cases — the real source of truth
  harness/         runs any implementation against the corpus
python/
  lmcc/            the reference kernel, stdlib only
  lmcc_std/        formats json/table/scaled_number, lens json_object,
                   reasoning strategies — a pack like anyone's
  lmcc_dspy/       any dspy.Signature → a signature (16-row catalog)
go/
  lmcc/, lmccstd/  an independent Go implementation of both
  cmd/lmcc-conform the corpus driver the harness runs it through
```

`./check` runs everything: Python tests, the corpus through both
kernels, the schemas, this README verbatim, and the DSPy catalog. What
"portable" means here, exactly: the artifact is data and travels
anywhere; the layout is byte-exact across implementations; a named
format is byte-exact where both runtimes ship the name; a shipped UDF
runs where its language can be placed and is declared *unclaimed* where
it cannot. That boundary is the contract's, not an accident.

## 12. What lmcc refuses to be

- **Not a client.** It lays out and reads. You send.
- **Not an orchestrator.** One plan, one call.
- **Not a runtime for other people's code.** A format travels whole with
  its language declared; where it runs is the host's rule.
- **Not a guesser.** Ambiguity, missing capabilities, non-invertible
  templates, unknown names: refuse, loudly, with a stable code.
- **Not batteries.** The kernel ships scalar defaults and nothing else.

`AGENTS.md` is the cockpit for agents; `GUIDE.md` is the longer
walkthrough; `contract/spec/decisions.md` is the memory of why.

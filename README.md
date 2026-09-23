# lmcc — the calling convention for calling a model

When your program calls a function in another language, a **calling
convention** says where each argument goes, how the result comes back,
and how each type crosses the boundary. A model is another language.
lmcc is its calling convention.

```
signature (your typed function)
        │  write: each value → its place on the wire
        ▼
   the wire: messages, parts, request request_settings        ← the adapter lays this out
        │  read: the reply → each typed value
        ▼
your typed return value
```

lmcc never touches the network. It lays out the call and reads the
return. You send. Every code block below runs in the test suite; every
claim is a corpus case the Python implementation passes byte for byte.
The contract is written so other languages can pass the same cases; for
now Python is the one implementation, while the language is designed.

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
    lmcc.turns(),
    lmcc.user("{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
])
```

An adapter never knows your field names — that is what lets one adapter
serve every signature. The template has four constructs and nothing
else:

| construct | example | meaning |
|---|---|---|
| slot | `{instruction}`, `{question}`, `{f.name}`, `{f.value}` | a value goes here |
| loop | `{% for f in inputs %} … {% endfor %}` (also `outputs`, or a turn slot) | once per field (or per earlier message) |
| guard | `{% if examples %} … {% endif %}` | only when that turn slot has turns |
| escape | `{{`, `}}` | a literal brace |

`lmcc.turns()` marks where earlier turns go — worked examples and the
conversation so far (§4). Read the template top to bottom and you know
the prompt. If a byte is not in the template or in a
format you registered, it is not in the prompt.

## 3. Bind, render, parse

```python
plan = answer.bind(xml, capabilities={"instruct": True})

request = plan.render(question="Why is the sky blue?")
assert request.messages[0]["parts"][0]["text"] == "<question>\nWhy is the sky blue?\n</question>\n"
assert request.request_settings == {}

assert plan.parse("<answer>\nRayleigh scattering.\n</answer>") == {"answer": "Rayleigh scattering."}

# Or read the same reply as the client receives it.
stream = plan.stream()
events = stream.feed("<answer>\nRayleigh")
assert events == [
    {"kind": "field_started", "field": "answer"},
    {"kind": "field_delta", "field": "answer", "text": "Rayleigh"},
]
events += stream.feed(" scattering.\n</answer>")
end = stream.finish()              # EOF can release final events
assert end.values == {"answer": "Rayleigh scattering."}
assert end.events == [
    {"kind": "field_done", "field": "answer", "value": "Rayleigh scattering."},
]
```

- `bind` joins a signature, an adapter, and what the model declares it
  can do. **Every refusal fires here**, before any call.
- `render`, `parse`, and `stream` are pure. Look at a million prompts for free.
- Streaming is a refinement: any chunking finishes with exactly the same
  values or refusal as `parse`; field deltas join to the batch raw text.
- `feed` accepts text or one part delta. `finish` returns EOF events and
  final values. Typed `field_done` events wait for full validation.
- The rendered form is plain messages with parts plus request settings.
  Hand it to any client.

## 4. The template is the parser

You wrote no parser for `xml`. lmcc read the output pattern backwards:
the literal before each output hole is its anchor, the literal after it
its close. Rename `<answer>` to `<reply>` and the prompt *and* the parser
change in the same edit. Earlier turns are written through the same
pattern the model is asked to follow.

```python
assert plan.describe()["reader"]["anchors"] == [["answer", "<answer>\n", "\n</answer>\n"]]
example = plan.example({"question": "q"}, {"answer": "a"})
written = plan.render(question="d", turns=[example]).messages[1]
assert plan.parse(written["parts"][0]["text"]) == {"answer": "a"}
```

Two rules keep it honest: a pattern that cannot be read backwards
refuses at bind (`not-readable`, naming the field); a reply that reads
two ways refuses at parse (`parse-ambiguous`). lmcc never guesses.

Models misspell layouts, so the reader forgives the obvious slips, by one
rule and out loud: `<Answer>` or `**answer**` reads as `<answer>`, and
`plan.read` says so. A reply the provider cut at its length limit is
never read as a finished answer (`parse-truncated`).

```python
reading = plan.read("<Answer>\nRayleigh scattering.\n</Answer>")
assert reading.values == {"answer": "Rayleigh scattering."}
assert [r["saw"] for r in reading.repairs] == ["<Answer>", "</Answer>"]
```

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

Or ask the server to enforce a schema: `reader/json_object` in the std
pack is that mode, gated on the `native_structured_output` capability.
Meanings go *inside* fields, through formats (§5). Surroundings stay
invertible.

### Turns: one record for examples and conversations

A **turn** is one call of one signature, kept as values: the inputs, the
steps (each model reply, each tool result), the outputs. An example is a
turn that did not happen here; the conversation is the turns that did;
the call in progress is a turn too. The plan writes all of them with its
own writers, so a past answer always matches the current adapter — even
after you switch it.

```python
now = plan.turn(question="Why is the sky blue?")
rendered = plan.render(now)                                       # a request, as before
done = rendered.step("<answer>\nRayleigh scattering.\n</answer>").finish()
assert done.outputs == {"answer": "Rayleigh scattering."}

nxt = plan.render(question="And sunsets?", turns=[done])          # the conversation so far
assert [m["role"] for m in nxt.messages] == ["user", "assistant", "user"]
```

A turn is JSON (`done.to_dict()`, `plan.load_turn(...)`), tied to its
signature by a fingerprint. A tool call and its result are steps of the
same turn: `rendered.step(reply)` records the call, `turn.tool(id,
output)` its result. Choosing *which* turns to pass — a window, a
summary, a memory — is the caller's job; lmcc writes exactly what it is
given. Kernel §3a has the whole contract.

## 5. Formats: how a type is written and read

A **format** is how one type crosses: `write` (value → what the model
sees) and `read` (the captured capture → value). It is the only mechanism
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
    read=lambda capture: Person(**json.loads(capture.text)),
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
receives the **capture** lmcc captured. An image format writes an image
part at the field's slot; a text-only format just reads `capture.text`.

## 6. Transports: how a meaning travels

Some fields are not just values. Reasoning, tools, citations:
for those the question is **how they travel** — in the text, or through
the model's own channel. That choice is a **transport**: data, attached
to a purpose.

```python
@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Purpose["reasoning", str]
    answer: int

@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve it."""

tags = lmcc.Transport(
    tell={"system": "Think inside <think>…</think> before you answer."},
    find=[{"from": "text", "between": ["<think>", "</think>"], "to": "@purpose", "remove": True}],
    in_template=False)

native = lmcc.Transport(
    requires=["native_reasoning"],
    in_template=False,
    request_settings={"config": {"reasoning": {"effort": "medium"}}},   # a partial lm15 request
    find=[{"from": "part:thinking", "to": "@purpose"}])

auto = lmcc.Transport(choose=[
    {"when": {"capability": "native_reasoning"}, "use": native},
    {"else": tags},
])

adapter = lmcc.adapter(messages=xml.template, transports={"reasoning": auto})
p1 = solve.bind(adapter, capabilities={"instruct": True})
p2 = solve.bind(adapter, capabilities={"instruct": True, "native_reasoning": True})
assert p1.parse("<think>4</think><answer>\n4\n</answer>") == {"answer": 4, "reasoning": "4"}
assert p2.render(problem="2+2").request_settings == {"config": {"reasoning": {"effort": "medium"}}}
assert p2.parse({"role": "assistant", "parts": [{"type": "thinking", "text": "4"}, {"type": "text", "text": "<answer>\n4\n</answer>"}]}) == {"answer": 4, "reasoning": "4"}
```

Same signature, same template, two inference behaviors — chosen by the
model's declared facts, never by editing the program. A transport may add
text (`tell`), take its field out of the template (`in_template: False`),
find it in the reply (`find`), put an input in the request or a message
(`put`), and add request settings (`request_settings`).

## 7. Capabilities: refuse before you pay

```python
try:
    solve.bind(lmcc.adapter(messages=xml.template, transports={"reasoning": native}),
               capabilities={"instruct": True})
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "capability-missing"
    assert r.fix == {"action": "declare-capability", "fact": "native_reasoning"}
```

Capabilities are a closed, versioned vocabulary of facts, declared by
whoever knows the model. Nothing is sniffed. Every refusal that fires
before render carries a `fix`: the one next action, as data from a
closed vocabulary (`spec/errors.md`), naming the exact field, purpose,
fact, name, or artifact path to act on. A program can repair without
reading English.

## 8. What the plan knows

```python
assert p1.skeleton() == {"prefill": "<answer>\n", "stops": ["</answer>"]}
assert p1.prefix() == {"system": p1.render(problem="x").system, "messages": []}
assert p1.describe()["streaming"]["mode"] == "incremental"
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
    assert r.fix is None
```

lmcc gives the hint. Retrying is not its job — a plan is one call — so
refusals about model text or program values carry no `fix`.

## 10. The artifact

```python
entry = adapter.dump()
assert entry["template"] == xml.template and entry["reader"] == {"kind": "derived"}
assert list(entry["transports"]) == ["reasoning"] and "formats" not in entry
again = lmcc.load(entry, registry=lmcc.Registry())
assert again.dump() == entry
```

One JSON file: template, reader, **transports by purpose**, **formats
by type**. No signature, no field names, no hidden code — a shipped
format says so on its entry (language, deps, hash, author).
`lmcc.load(entry)` needs nothing ambient. Another implementation that
loads it lays out the same bytes.

## 11. Where things live

```
contract/          the authority (no code)
  spec/            kernel.md (the convention), errors.md, vocab/ specs
  schema/          entry, signature, case — JSON Schema
  corpus/          176 byte-exact cases — the real source of truth
  LM15_CONTRACT_PIN the lm15 contract commit the wire layer is
  harness/         runs any implementation against the corpus (a driver
                   in any language speaks JSON Lines; python_driver.py
                   is the template)
python/
  lmcc/            the reference kernel, stdlib only
  lmcc_std/        formats json/table/scaled_number, reader json_object,
                   reasoning transports — a pack like anyone's
  lmcc_dspy/       any dspy.Signature → a signature (16-row catalog)
  lmcc_lm15/       typed face over the shared wire: lm15 Request in, Response out
```

`./check` runs everything: Python tests, the corpus (in process and
through the driver protocol), the schemas, this README verbatim, the DSPy catalog, and the
lm15 bridge against a pinned lm15. What
"portable" is designed to mean, exactly: the artifact is data and
travels anywhere; the layout is byte-exact in every implementation that
passes the corpus; a named format is byte-exact where the runtime ships
the name; a shipped UDF
runs where its language can be placed and is declared *unclaimed* where
it cannot. That boundary is the contract's, not an accident.

## The wire is lm15

lmcc never touches the network; what it renders is an **lm15 request
minus its model** — `{"system", "messages": [{"role", "parts"}], "config",
"tools"}` in lm15's canonical JSON, pinned to the lm15 contract commit in
`contract/LM15_CONTRACT_PIN` — and what it parses is an lm15 message or
response. No translation layer: `plan.render(...).request(model)` is the
dict lm15's `request_from_dict` takes, in every language lm15 exists in.
A transport's `request_settings` are a partial lm15 request too (`config.reasoning`,
`config.response_format`, `tools`), so a transport does everything its
meaning needs — asks for thinking *and* reads it back. The typed face
(`python/lmcc_lm15`) is a few lines over lm15's own serde:

```python
# import lmcc_lm15, lm15
# req = lmcc_lm15.request(plan.render(problem="2+2"), model="claude-sonnet-4-5",
#                         config=lm15.Config(max_tokens=400))   # an lm15.Request
# values = lmcc_lm15.parse(plan, lm.complete(req))               # typed values
# events, result = lmcc_lm15.stream(plan, lm.stream(req))        # sans-I/O stream, fed
```

## Portability: shared meaning, declared support

Implementations need not use the same execution engine. They must preserve
meaning for every contract they claim to support.

Kernel 0.3 separates a small mandatory core from named, versioned
**extensions**. An artifact declares what it needs
(`"extensions": {"pattern/legacy-re2": "0.1.0"}`); the host binds a
compatible implementation or refuses — by name, with a fix — before any
model request. Regex execution is the first such extension: no host has
to build a regex engine to be conformant, and a "core only" claim is a
complete one. `registry.describe()["extensions"]` says what a host binds;
`plan.describe()["extensions"]` says what a plan resolved. Model
capabilities and host execution support stay separate vocabularies. See
[portability](contract/spec/portability.md), kernel §10, and
[the extension index](contract/spec/extensions/README.md).

Raw-code tool calls are covered in the runnable
[conversational heredoc notebook](docs/howto/12-conversational-heredoc-tools.md).
`heredoc_tools` supplies the envelope and the spelling of past calls;
`code_arguments` writes the body without escaping or trimming; `code_calls`
reads it back. `spelling.input_format` and `spelling.probe` let custom transports
use the same writer for past calls and a representative bind-time
round-trip check. No code is executed by binding or by the notebook.

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

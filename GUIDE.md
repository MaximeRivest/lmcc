# Using a15 — the kernel guide

This guide uses **only the kernel**: `import a15`, nothing else. No
`a15_std`, no packs. Everything here runs against an empty registry —
except the last sections, where you register *your own* vocabulary
through the sockets, which is the point of them.

Every code block in this file is executed, in order, by
`tests/test_guide.py`. If the guide drifts from the code, `./check`
goes red. Read it as a program.

## 1. One idea before any code

You describe a typed contract (the **signature**) and a conversation
shape (the **adapter**). The kernel turns them into exact messages, and
turns the model's reply back into typed values. One description does
both directions — the parts that could disagree are derived from each
other, so they cannot. When something cannot be done honestly, a15
refuses with a named error **before** any model is called. It never
guesses.

## 2. The signature: what goes in, what comes out

```python
import a15

sig = a15.signature(
    "Extract the book facts from the sentence.",
    inputs={"text": str},
    outputs={"title": a15.field(str, desc="the book title"),
             "year": int,
             "confident": bool},
)
```

Values in `inputs`/`outputs` are your language's own type hints. The
kernel maps `str`, `int`, `float`, `bool`, `list[...]`,
`typing.Literal[...]` mechanically; you may also pass a raw JSON-Schema
dict. `a15.field(...)` adds a description or a role. Anything the
kernel cannot map refuses by name (`unmapped-type`) — see §8 for how
native types plug in.

## 3. The adapter: how the conversation looks

An adapter never knows a signature. It is a template (data), a parse
spec (data), and optional bindings. The template language has exactly
three constructs — slots, loops, escapes — nothing else, ever:

```python
adapter = a15.adapter(
    template=a15.template([
        a15.message("system",
            "{instruction}\n\nAnswer in exactly this form:\n"
            "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        a15.directive("demos"),
        a15.message("user", "{text}"),
    ]),
    parse={"kind": "derived"},
)
```

The outputs loop containing `{f.value}` is the **output-pattern
block**. With `parse: {"kind": "derived"}`, that one block is read
three ways: it renders the prompt's skeleton, it writes example
answers, and **the parser is derived from it** — the literal text
around each `{f.value}` hole becomes the anchors the parser looks for.
You never write a parser.

## 4. Bake, render, parse

`bake` is where adapter, signature, and the model's declared facts
meet. Every refusal fires here — before any money is spent. `render`
and `parse` are pure functions: no network, no clock, no state.

```python
baked = adapter.bake(sig, {})   # {} = no declared capabilities; fine here

request = baked.render(
    inputs={"text": "Dune came out in 1965."},
    demos=[{"text": "1984 was published in 1949.",
            "title": "1984", "year": 1949, "confident": True}])

roles = [m["role"] for m in request.messages]
assert roles == ["system", "user", "assistant", "user"]
```

The demo's assistant turn was written by the derived lens — the same
object that parses. Send `request.messages` (plus `request.patch`) with
any client you like; the kernel never performs I/O. Then:

```python
values = baked.parse(
    "Sure!\n<title>\nDune\n</title>\n<year>\n1965\n</year>\n"
    "<confident>\ntrue\n</confident>\nHope this helps!")
assert values == {"title": "Dune", "year": 1965, "confident": True}
```

Typed values: `1965` is an `int`, `True` is a `bool` — kernel scalar
rules (strings verbatim; integer/number/boolean as JSON literals; enums
by membership). Surrounding chatter falls away because the anchors are
found *inside* the reply.

The lens law, checkable in one line — what the lens wrote as a demo,
the lens reads back identically:

```python
demo_turn = request.messages[2]["content"][0]["text"]
assert baked.parse(demo_turn) == {"title": "1984", "year": 1949,
                                  "confident": True}
```

## 5. Refusal is the interface

Every failure has a stable code (`contract/spec/errors.md`), names its
exact offender, and carries whatever was recovered:

```python
try:
    baked.parse("<title>\nDune\n</title>")
    raise AssertionError("should have refused")
except a15.A15Error as err:
    assert err.code == "parse-missing-fields"
    assert err.partial == {"title": "Dune"}     # what was recovered

try:
    baked.parse("I quote <title> here.\n<title>\nDune\n</title>\n"
                "<year>\n1965\n</year>\n<confident>\nyes\n</confident>")
    raise AssertionError("should have refused")
except a15.A15Error as err:
    assert err.code == "parse-ambiguous"        # never guesses which one
```

Non-invertible templates refuse at bake, naming the defect:

```python
bad = a15.adapter(
    template=a15.template([
        a15.message("system", "{% for f in outputs %}{f.value}\n{% endfor %}"),
        a15.message("user", "{text}")]),
    parse={"kind": "derived"})
try:
    bad.bake(sig, {})
    raise AssertionError("should have refused")
except a15.A15Error as err:
    assert err.code == "not-lensable"           # no anchor before the hole
```

## 6. The declared lens: `sections` and `{format}`

When you prefer declaring markers over deriving them, use the
`sections` lens. Marker dialects are pure data — the DSPy chat style
and XML style are spellings, not features. The reserved `{format}` slot
asks the lens to render its own skeleton:

```python
dspy_style = a15.adapter(
    template=a15.template([
        a15.message("system", "{instruction}\nAnswer like this:\n{format}"),
        a15.message("user", "{text}")]),
    parse={"kind": "sections", "open": "[[ ## {name} ## ]]",
           "tail": "[[ ## completed ## ]]"})

b = dspy_style.bake(sig, {})
assert b.parse("[[ ## title ## ]]\nDune\n[[ ## year ## ]]\n1965\n"
               "[[ ## confident ## ]]\ntrue\n[[ ## completed ## ]]"
               ) == {"title": "Dune", "year": 1965, "confident": True}
```

## 7. Strategies: per-role conduct, as inline data

Mark a field with a role; bind a strategy to the role. A strategy is
plain data: a predicate over declared capability facts, prompt
fragments, request controls, and routings that recover the value from
wherever it actually arrives. No registration needed for inline ones:

```python
think_aloud = a15.Strategy(
    predicate={"not": {"capability": "native_reasoning"}},
    fragments={"system": "Wrap every thought in <think>...</think>."},
    routings=[{"extract": {"kind": "between",
                           "open": "<think>", "close": "</think>"},
               "field": "@role", "strip": True, "join": "\n"}],
    visible=False)          # the field leaves the token stream entirely

cot_sig = a15.signature(
    "Answer the question.",
    inputs={"question": str},
    outputs={"reasoning": a15.field(str, role="reasoning"),
             "answer": str})

cot = a15.adapter(
    template=a15.template([
        a15.message("system",
            "{instruction}\n\nAnswer in exactly this form:\n"
            "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        a15.message("user", "{question}"),
    ]),
    parse={"kind": "derived"},
    strategies={"reasoning": think_aloud})

cb = cot.bake(cot_sig, {})   # predicate "not native_reasoning" holds
prompt = cb.render(inputs={"question": "Capital of France?"})
system_text = prompt.messages[0]["content"][0]["text"]
assert "<reasoning>" not in system_text          # hidden from the pattern
assert "Wrap every thought" in system_text       # fragment landed

values = cb.parse("<think>easy one</think><answer>\nParis\n</answer>")
assert values == {"reasoning": "easy one", "answer": "Paris"}
```

Same signature on a native-reasoning model? Bind a different strategy
whose predicate is `{"capability": "native_reasoning"}` with a
`{"kind": "parts", "part": "thinking"}` routing — the program does not
change. The capability dict you pass to `bake` is **declared, never
sniffed**; its legal words live in `contract/spec/vocab/capabilities.md`.

## 8. Native types: the host socket

Your language's types cross the boundary through per-runtime bindings:
a neutral shape, a `lower` to plain data, a `lift` back, and optionally
the codec that spells it. Bindings are code and are never serialized —
artifacts stay cross-language.

```python
class Photo:                       # stands in for PIL.Image
    def __init__(self, b64): self.b64 = b64

registry = a15.Registry()
registry.register_host(Photo, shape={"media": "image"},
                       lower=lambda p: {"data": p.b64, "mime": "image/png"})

vision_sig = a15.signature(
    "Describe the photo.",
    inputs={"photo": Photo}, outputs={"caption": str}, registry=registry)

vision = a15.adapter(
    template=a15.template([
        a15.message("system", "{instruction}\n"
            "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        a15.message("user", "{photo}"),
    ]),
    parse={"kind": "derived"})

vp = vision.bake(vision_sig, {"image_input": True}, registry=registry)
msg = vp.render(inputs={"photo": Photo("b64bytes")}).messages[1]
assert {"kind": "image", "data": "b64bytes", "mime": "image/png"} in msg["content"]
```

A media-shaped value renders as a real message part at its slot
position — never as text.

## 9. Structured values: bring a codec

The kernel spells **scalars only**. A structured shape with no codec
refuses at bake — that line is the contract's mechanics/vocabulary
boundary:

```python
rows_sig = a15.signature("List them.", inputs={"text": str},
                         outputs={"rows": list[int]})
try:
    adapter.bake(rows_sig, {})
    raise AssertionError("should have refused")
except a15.A15Error as err:
    assert err.code == "no-codec"
```

A codec is ~10 lines against the socket. It owns one value's spelling,
both directions; the template owns position; the lens owns layout:

```python
class CommaList(a15.Codec):
    def render_schema(self, shape): return "comma-separated integers"
    def render_value(self, value, shape): return ", ".join(map(str, value))
    def parse_value(self, text, shape):
        return [int(p.strip()) for p in text.split(",")]

registry.register_codec("comma_list", lambda options: CommaList(),
                        version="0.1.0")

lists = a15.adapter(
    template=a15.template([
        a15.message("system", "{instruction}\n"
            "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        a15.message("user", "{text}"),
    ]),
    parse={"kind": "derived"},
    codecs={"rows": "comma_list"})

lb = lists.bake(rows_sig, {}, registry=registry)
assert lb.parse("<rows>\n3, 5, 8\n</rows>") == {"rows": [3, 5, 8]}
```

(You can also attach a codec to a host type once —
`register_host(..., codec="comma_list")` — so every signature using
that type spells it without per-adapter bindings. The entry's own
binding always wins.)

## 10. The artifact: dump, load, travel

An adapter serializes to pure data — the entry. A data-only entry
(inline strategies, no named refs) loads against an **empty** registry;
named vocabulary loads only where it is registered, with versions
checked, refusing loudly otherwise:

```python
import json

entry = cot.dump()                       # inline strategy travels inside
wire = json.dumps(entry)                 # it is just JSON
again = a15.load(json.loads(wire), registry=a15.Registry())
rebaked = again.bake(cot_sig, {})
assert rebaked.parse("<think>hm</think><answer>\nParis\n</answer>"
                     ) == {"reasoning": "hm", "answer": "Paris"}
```

Diff two dumps to see exactly what changed between two adapters. The
file format is `contract/schema/entry.schema.json`.

## 11. Seeing what you built

Never step through code to understand a plan — read it as data:

```python
plan = cb.describe()                     # JSON-serializable, all of it
assert plan["lens"]["kind"] == "derived"
assert plan["hidden"] == ["reasoning"]
assert plan["strategies"] == {"reasoning": "(inline)"}
json.dumps(plan)                         # proves it is data

print(cb.explain())                      # the same, pretty-printed
print(registry.describe())               # what this runtime speaks
```

`render` is pure, so previewing exact prompt bytes costs nothing.

## 12. Where to go next

- `contract/spec/kernel.md` — the normative rules behind everything here
- `contract/spec/errors.md` — every refusal code, and when it fires
- `contract/spec/vocab/` — how shared vocabulary (codecs, strategies,
  lenses, roles, capabilities) is specified and certified
- `a15_std` — the standard pack: the *exemplar* of everything §7–§9
  showed you how to build yourself
- `AGENTS.md` — the repo's cockpit: verify loop, work queue, decisions

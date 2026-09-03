# Using lmcc — the kernel guide

This guide uses **only the kernel**: `import lmcc`, nothing else. No
`lmcc_std`, no packs. Everything here runs against an empty registry —
except the last sections, where you register *your own* formats through
the sockets, which is the point of them.

Every code block in this file is executed, in order, by
`tests/test_guide.py`. If the guide drifts from the code, `./check`
goes red. Read it as a program.

## 1. One idea before any code

You describe a typed contract (the **signature**) and a conversation
shape (the **adapter**). The kernel binds them into a **plan** that
turns values into exact messages, and the model's reply back into typed
values. One description does both directions — the parts that could
disagree are derived from each other, so they cannot. When something
cannot be done honestly, lmcc refuses with a named `Refusal` **before**
any model is called. It never guesses.

## 2. The signature: what goes in, what comes out

```python
import dataclasses
import lmcc

@dataclasses.dataclass
class Facts:
    title: str
    year: int
    confident: bool

@lmcc.fn
def book(text: str) -> Facts:
    """Extract the book facts from the sentence."""

assert [f.name for f in book.signature.inputs] == ["text"]
assert [(f.name, f.type) for f in book.signature.outputs] == [("title", "str"), ("year", "int"), ("confident", "bool")]
```

Parameters are inputs, the return type is the output, a dataclass return
is several outputs, the docstring is the instruction. The same signature
as plain data — what every frontend lowers to — is
`lmcc.signature_to_dict(book.signature)`; it has a JSON Schema
(`contract/schema/signature.schema.json`). Descriptions and roles:
`lmcc.signature("...", inputs={"text": str}, outputs={"title": lmcc.field(str, desc="the book title")})`.

## 3. The adapter: how the conversation looks

An adapter never knows a signature. It is a template, a parse rule,
strategies by role, formats by type — never a field name. The template
has exactly three constructs — slots, loops, escapes:

```python
adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nAnswer in exactly this form:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.demos(),
    lmcc.user("{text}"),
])
```

The outputs loop containing `{f.value}` is the **output pattern**. It
renders the prompt's skeleton, it writes example answers, and **the
parser is derived from it** — the literal text around each hole becomes
the anchors the parser looks for. You never write a parser.

## 4. Bind, render, parse

`bind` is where adapter, signature, and the model's declared facts meet.
Every refusal fires here — before any money is spent. `render` and
`parse` are pure: no network, no clock, no state.

```python
plan = book.bind(adapter)

request = plan.render(text="Dune came out in 1965.",
                      demos=[{"text": "1984 was published in 1949.",
                              "title": "1984", "year": 1949, "confident": True}])
assert [m["role"] for m in request.messages] == ["system", "user", "assistant", "user"]

values = plan.parse("Sure!\n<title>\nDune\n</title>\n<year>\n1965\n</year>\n"
                    "<confident>\ntrue\n</confident>\nHope this helps!")
assert values == {"title": "Dune", "year": 1965, "confident": True}
```

Typed values: `1965` is an `int`, `True` is a `bool` — the kernel's
scalar rules, pinned to the character (`kernel.md` §7a): `+5` is not an
integer, `Yes` is a boolean, only ASCII whitespace is trimmed, `3.0` is
spelled `3`. Surrounding chatter falls away because anchors are found
*inside* the reply.

The lens law, checkable in one line — what the lens wrote as a demo, the
lens reads back identically:

```python
demo_turn = request.messages[2]["content"][0]["text"]
assert plan.parse(demo_turn) == {"title": "1984", "year": 1949, "confident": True}
```

The law holds for every demo the lens agrees to write. A demo value that
contains one of the lens's own markers could not be read back as
written — so the lens refuses to write it (`value-collides`):

```python
try:
    plan.render(text="x", demos=[{"text": "y", "title": "Dune </title> II", "year": 1, "confident": True}])
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "value-collides"
```

## 5. Refusal is the interface

Every failure has a stable code (`contract/spec/errors.md`), a hint that
names the exact offender, and whatever was recovered:

```python
try:
    plan.parse("<title>\nDune\n</title>")
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "parse-missing-fields"
    assert err.partial == {"title": "Dune"}

try:
    plan.parse("I quote <title> here.\n<title>\nDune\n</title>\n<year>\n1965\n</year>\n<confident>\nyes\n</confident>")
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "parse-ambiguous"        # never guesses which one

bad = lmcc.adapter(messages=[lmcc.system("{% for f in outputs %}{f.value}\n{% endfor %}"), lmcc.user("{text}")])
try:
    book.bind(bad)
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "not-lensable"           # no anchor before the hole
```

## 6. Bare output slots — spell any pattern

The pattern need not be a loop. Any line holding output slots is read
backwards the same way — so a spelled JSON object is a pattern:

```python
spelled = lmcc.adapter(messages=[
    lmcc.system('{instruction}\nReply exactly like this:\n{{"title": "{title}", "year": {year}, "confident": {confident}}}'),
    lmcc.user("{text}")])
p = book.bind(spelled)
assert p.parse('{"title": "Dune", "year": 1965, "confident": true}') == {"title": "Dune", "year": 1965, "confident": True}
assert p.skeleton() == {"prefill": '{"title": "', "stops": ["}"]}
```

## 7. Strategies: how a meaning travels, as data

Mark a field with a role; bind a strategy to the role. A strategy is
plain data: a predicate over declared capability facts, prompt
fragments, request controls, routings that recover the value from where
it actually arrives, and a `choose` list to pick among alternatives:

```python
@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Role["reasoning", str]
    answer: str

@lmcc.fn
def cot(question: str) -> Solution:
    """Answer the question."""

think_aloud = lmcc.Strategy(
    when={"not": {"capability": "native_reasoning"}},
    fragments={"system": "Wrap every thought in <think>...</think>."},
    routings=[{"from": "text", "between": ["<think>", "</think>"], "to": "@role", "consume": True}],
    visible=False)          # the field leaves the token stream entirely

cot_adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nAnswer in exactly this form:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{question}")], strategies={"reasoning": think_aloud})

cp = cot.bind(cot_adapter)
system_text = cp.render(question="Capital of France?").messages[0]["content"][0]["text"]
assert "<reasoning>" not in system_text          # hidden from the pattern
assert "Wrap every thought" in system_text       # fragment landed
assert cp.parse("<think>easy one</think><answer>\nParis\n</answer>") == {"reasoning": "easy one", "answer": "Paris"}
```

Same signature on a native-reasoning model? A strategy with
`requires=["native_reasoning"]` and a routing `{"from": "channel:thinking",
"to": "@role"}` — the program does not change. The capability dict you
pass to `bind` is **declared, never sniffed**; its legal words live in
`contract/spec/vocab/capabilities.md`.

## 8. History: typed turns through the same description

History items are messages, or **field turns** rendered exactly like
demos — through the template and the lens, so history can never drift
from the format the model is asked to produce:

```python
chat = lmcc.adapter(messages=[adapter.template[0], lmcc.history(), lmcc.user("{text}")])
hp = book.bind(chat)
req = hp.render(text="third", history=[
    {"fields": {"text": "first", "title": "A", "year": 1, "confident": False}},
    {"role": "assistant", "content": "a raw turn"}])
assert [m["role"] for m in req.messages] == ["system", "user", "assistant", "assistant", "user"]
```

## 9. Formats: your types, your spelling

The kernel spells **scalars only**. A structured value with no format
refuses at bind — that line is the contract's mechanics/vocabulary
boundary:

```python
@lmcc.fn
def rows(text: str) -> list[int]:
    """List them."""

try:
    rows.bind(adapter, registry=lmcc.Registry())
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "no-format"
```

A format is a few lines. It owns one type's spelling, both directions;
the template owns position; the lens owns layout:

```python
registry = lmcc.Registry()
registry.format(list[int],
    write=lambda v: ", ".join(map(str, v)),
    read=lambda span: [int(p.strip()) for p in span.text.split(",")],
    describe=lambda: "comma-separated integers")

rp = rows.bind(adapter, registry=registry)
assert rp.describe()["outputs"][0]["resolved_by"] == "runtime:list[int]"
assert rp.parse("<rows>\n3, 5, 8\n</rows>") == {"rows": [3, 5, 8]}
```

That binding is per runtime — code, never serialized. An artifact can
name a format for a type (`"formats": {"list[int]": {"use": "csv"}}`) or
carry one **whole** (source, language, deps, hash, author):

```python
def write(v, f):
    return ", ".join(str(x) for x in v)

def read(span, f):
    return [int(p.strip()) for p in span.text.split(",")]

shipped = lmcc.adapter(messages=adapter.template,
                       formats={"list[int]": lmcc.make_format(write=write, read=read)})
entry = shipped.dump(registry=lmcc.Registry())
assert entry["formats"]["list[int]"]["language"] == "python"

try:
    lmcc.load(entry, registry=lmcc.Registry())          # a runtime that places no code
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "format-untrusted"

placed = lmcc.load(entry, registry=lmcc.Registry(allow_udf=True))
assert placed.bind(rows.signature, registry=lmcc.Registry(allow_udf=True)).parse("<rows>\n1, 2\n</rows>") == {"rows": [1, 2]}
```

Loading never runs the code; the receiving runtime decides. A tampered
hash refuses `udf-tampered`; a function that reaches into globals refuses
`format-not-self-contained` at ship time.

## 10. The artifact: dump, load, travel

```python
import json
entry = cot_adapter.dump()
wire = json.dumps(entry)                                  # it is just JSON
again = lmcc.load(json.loads(wire), registry=lmcc.Registry())
assert again.bind(cot.signature).parse("<think>hm</think><answer>\nParis\n</answer>") == {"reasoning": "hm", "answer": "Paris"}
```

Diff two dumps to see exactly what changed. The file format is
`contract/schema/entry.schema.json`: template, parse, strategies by
role, formats by type. No signature, no field names.

## 11. Seeing what you built

```python
d = cp.describe()                        # JSON-serializable, all of it
assert d["lens"]["kind"] == "derived" and d["hidden"] == ["reasoning"]
assert d["strategies"] == {"reasoning": "(inline)"}
assert d["skeleton"] == {"prefill": "<answer>\n", "stops": ["</answer>"]}
json.dumps(d)
print(cp.explain())
print(registry.describe())
```

`render` is pure, so previewing exact prompt bytes costs nothing.

## 12. Where to go next

- `contract/spec/kernel.md` — the normative rules behind everything here
- `contract/spec/errors.md` — every refusal code, and when it fires
- `contract/spec/vocab/` — how shared vocabulary is specified and certified
- `lmcc_std` — the standard pack: the *exemplar* of §7–§9
- `lmcc_dspy` — any DSPy signature, lowered
- `AGENTS.md` — the repo's cockpit: verify loop, work queue, decisions

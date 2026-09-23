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
import json
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
(`contract/schema/signature.schema.json`). Descriptions and purposes:
`lmcc.signature("...", inputs={"text": str}, outputs={"title": lmcc.field(str, desc="the book title")})`.

## 3. The adapter: how the conversation looks

An adapter never knows a signature. It is a template, a reader,
transports by purpose, formats by type — never a field name. The template
has four constructs — slots, loops, guards, escapes — and one directive,
`lmcc.turns()`, the place where earlier exchanges go (§8):

```python
adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nAnswer in exactly this form:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.turns(),
    lmcc.user("{text}"),
])
```

The outputs loop containing `{f.value}` is the **output pattern**. It
renders the prompt's skeleton, it writes earlier answers, and **the
parser is derived from it** — the literal text around each hole becomes
the anchors the parser looks for. You never write a parser.

## 4. Bind, render, parse

`bind` is where adapter, signature, and the model's declared facts meet.
Every refusal fires here — before any money is spent. `render` and
`parse` are pure: no network, no clock, no state.

```python
plan = book.bind(adapter)

example = plan.example({"text": "1984 was published in 1949."},
                       {"title": "1984", "year": 1949, "confident": True})
request = plan.render(text="Dune came out in 1965.", turns=[example])
assert request.system and [m["role"] for m in request.messages] == ["user", "assistant", "user"]

values = plan.parse("Sure!\n<title>\nDune\n</title>\n<year>\n1965\n</year>\n"
                    "<confident>\ntrue\n</confident>\nHope this helps!")
assert values == {"title": "Dune", "year": 1965, "confident": True}
```

Typed values: `1965` is an `int`, `True` is a `bool` — the kernel's
scalar rules, pinned to the character (`kernel.md` §7a): `+5` is not an
integer, `Yes` is a boolean, only ASCII whitespace is trimmed, `3.0` is
spelled `3`. Surrounding chatter falls away because anchors are found
*inside* the reply.

The reader law, checkable in one line — what the reader wrote for the
example, the reader reads back identically:

```python
written = request.messages[1]["parts"][0]["text"]
assert plan.parse(written) == {"title": "1984", "year": 1949, "confident": True}
```

The law holds for every turn the reader agrees to write. A value that
contains one of the reader's own markers could not be read back as
written — so the reader refuses to write it (`value-collides`):

```python
try:
    bad = plan.example({"text": "y"}, {"title": "Dune </title> II", "year": 1, "confident": True})
    plan.render(text="x", turns=[bad])
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "value-collides"
```

### Read a reply as it arrives

`parse()` reads a complete reply. `stream()` reads the same reply in
pieces, without owning a network connection:

```python
stream = plan.stream()
events = stream.feed("<title>\nDu")
events += stream.feed("ne\n</title>\n<year>\n1965\n</year>\n<confident>\nyes\n</confident>")
end = stream.finish()
assert end.values == {"title": "Dune", "year": 1965, "confident": True}
assert "".join(e["text"] for e in events + end.events
               if e["kind"] == "field_delta" and e["field"] == "title") == "Dune"
```

`feed` accepts a text delta or one part delta such as
`{"type": "thinking", "text": "…"}` — an lm15 delta). It emits `field_started` and
safe `field_delta` events. It holds trailing spaces and partial markers
because later text can change their meaning. `finish` returns the final
events and values. It emits typed `field_done` events only after the
whole reply passes the same checks as `parse()`.

The rule is strict: every way to split one reply gives the same final
values or refusal, and each field's deltas join to the raw text that
batch parsing captured. Regex find rules and readers without a streaming
face buffer until EOF; `plan.describe()["streaming"]` states every such
choice and its reason.

### Replies that are almost right

Models misspell the layout they were shown. lmcc reads the reply the
model actually wrote and says what it repaired. `read` gives the values
and the repairs; `parse` gives the values alone:

```python
reading = plan.read("**<Title>**\nDune\n</TITLE>\n<year>\n1965\n</year>\n<confident>\nyes\n</confident>")
assert reading.values == {"title": "Dune", "year": 1965, "confident": True}
assert reading.repairs == [
    {"repair": "marker", "marker": "<title>", "saw": "**<Title>**"},
    {"repair": "marker", "marker": "</title>", "saw": "</TITLE>"}]
```

The rule is one sentence: a marker matches ignoring letter case, spaces,
and markdown's `*`, `_` and `#`, but never across a line. It holds for
any signature, because it is about the markers, not about field names.
It never guesses: if the exact marker appears anywhere, the misspelled
one is just text, and two readings refuse `parse-ambiguous`. Turn it off
with `reader={"kind": "derived", "markers": "exact"}`.

One thing is never repaired: a reply the provider cut at its length
limit. Pass the lm15 response (not just its text) and an answer that may
have been cut refuses `parse-truncated`, instead of reading as finished:

```python
cut = {"message": {"role": "assistant", "parts": [{"type": "text", "text": "<title>\nDune Mess"}]},
       "finish_reason": "length"}
try:
    plan.parse(cut)
    raise AssertionError("should have refused")
except lmcc.Refusal as err:
    assert err.code == "parse-truncated"
```

The whole story, streaming included, is
[how-to 14](docs/howto/14-read-imperfect-replies.md).

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
    assert err.code == "not-readable"           # no anchor before the hole
    assert err.fix == {"action": "edit-template", "path": "template[0]", "field": "title"}
```

The last one shows the fourth face of a refusal. Every refusal that
fires *before render* — at signature, load, or bind — carries a `fix`:
the one next action as plain data, from a closed vocabulary
(`contract/spec/errors.md`, "Fix actions"). Its parameters are names a
program can act on (a field, a purpose, a capability fact, a vocabulary
name, a path into the artifact), never prose. `err.describe()` is the
whole refusal as a dict. Render and parse refusals carry `fix: None`:
what to do about a bad value or a bad reply is orchestration.

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

## 7. Transports: how a meaning travels, as data

Mark a field with a purpose; bind a transport to the purpose. A transport is
plain data: a predicate over declared capability facts, prompt
tell, request request_settings, find rules that recover the value from where
it actually arrives, and a `choose` list to pick among alternatives:

```python
@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Purpose["reasoning", str]
    answer: str

@lmcc.fn
def cot(question: str) -> Solution:
    """Answer the question."""

think_aloud = lmcc.Transport(
    when={"not": {"capability": "native_reasoning"}},
    tell={"system": "Wrap every thought in <think>...</think>."},
    find=[{"from": "text", "between": ["<think>", "</think>"], "to": "@purpose", "remove": True}],
    in_template=False)          # the field leaves the token stream entirely

cot_adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nAnswer in exactly this form:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{question}")], transports={"reasoning": think_aloud})

cp = cot.bind(cot_adapter)
system_text = cp.render(question="Capital of France?").system
assert "<reasoning>" not in system_text          # hidden from the pattern
assert "Wrap every thought" in system_text       # the tell text landed
assert cp.parse("<think>easy one</think><answer>\nParis\n</answer>") == {"reasoning": "easy one", "answer": "Paris"}
```

Same signature on a native-reasoning model? A transport with
`requires=["native_reasoning"]` and a find rule `{"from": "part:thinking",
"to": "@purpose"}` — the program does not change. The capability dict you
pass to `bind` is **declared, never sniffed**; its legal words live in
`contract/spec/vocab/capabilities.md`.

## 8. Turns: examples and conversations through the same description

A **turn** is one call of one signature, kept as values: what went in,
the steps (model replies, tool results), what came out. An example is a
turn that did not happen here; a conversation is the turns that did.
Both are written by the plan's own template and reader, so a past answer
can never drift from the format the model is asked to produce — even
after you switch adapters.

```python
current = plan.turn(text="first")
rendered = plan.render(current)
first = rendered.step("<title>\nA\n</title>\n<year>\n1\n</year>\n<confident>\nfalse\n</confident>").finish()
assert first.outputs == {"title": "A", "year": 1, "confident": False}

req = plan.render(text="second", turns=[example, first])
assert [m["role"] for m in req.messages] == ["user", "assistant", "user", "assistant", "user"]
assert json.loads(json.dumps(first.to_dict()))["signature"] == first.signature   # a turn is JSON
```

Templates may name their turn slots and place them as messages or as
text (`{% for m in examples %}[{m.role}] {m.text}{% endfor %}`, behind
`{% if examples %}`); the kernel renders exactly the turns it is given.
Choosing which turns to give — windows, summaries, memory — belongs above
lmcc (`kernel.md` §3a).

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
the template owns position; the reader owns layout:

```python
registry = lmcc.Registry()
registry.format(list[int],
    write=lambda v: ", ".join(map(str, v)),
    read=lambda capture: [int(p.strip()) for p in capture.text.split(",")],
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

def read(capture, f):
    return [int(p.strip()) for p in capture.text.split(",")]

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
`contract/schema/entry.schema.json`: template, parse, transports by
purpose, formats by type. No signature, no field names.

## 11. Seeing what you built

```python
d = cp.describe()                        # JSON-serializable, all of it
assert d["reader"]["kind"] == "derived" and d["hidden"] == ["reasoning"]
assert d["transports"] == {"reasoning": "(inline)"}
assert d["skeleton"] == {"prefill": "<answer>\n", "stops": ["</answer>"]}
json.dumps(d)
print(cp.explain())
print(registry.describe())
```

`render` is pure, so previewing exact prompt bytes costs nothing.

## Portability and execution requirements

Portability means identical behavior within a declared feature set, not
support for every extension on every host. The kernel is a small core;
regex is not in it. A `pattern` find rule runs under a declared extension —
like SQL dialects: divergence between engines is normal, *undeclared*
divergence is the sin. The constructor declares the default tier for you
(the host's own engine, `pattern/legacy-re2`); the artifact carries the
line; a loaded artifact without it refuses:

```python
regex = lmcc.Transport(in_template=False, find=[
    {"from": "text", "pattern": "Thought: ([^\\n]+)", "to": "@purpose", "remove": True}])
xml = lmcc.adapter(messages=cot_adapter.template, transports={"reasoning": regex})
assert xml.dump()["extensions"] == {"pattern/legacy-re2": "0.1.0"}      # written for you
assert cot.bind(xml).describe()["extensions"] == {
    "pattern/legacy-re2": {"needs": "0.1.0", "provides": "0.1.0", "binding": "python:re"}}
try:
    cot.bind(xml, registry=lmcc.Registry(extensions=()))   # a core-only host
except lmcc.Refusal as r:
    assert r.code == "extension-unsupported"
bare = xml.dump(); del bare["extensions"]
try:
    lmcc.load(bare)                                        # an artifact must speak for itself
except lmcc.Refusal as r:
    assert r.code == "extension-undeclared"
    assert r.fix == {"action": "declare-extension", "family": "pattern",
                     "path": "transports['reasoning'].find[0]"}
```

Three tiers exist or can: the default (native engine, small stated
divergence, no dependency), an exact single-language pin (a contract
named for one engine and version), and an exact cross-language engine
(one shared library). All are rows in the
[extension index](contract/spec/extensions/README.md); only the first
exists today, the others are added when an adapter demands them. The host
binds (`Registry()` binds what the standard library can honestly do;
`register_extension` binds yours) or refuses before a model request. A
frontend must never silently translate a pattern into another dialect.

## 12. Where to go next

- `contract/spec/kernel.md` — the normative rules behind everything here
- `contract/spec/errors.md` — every refusal code, and when it fires
- `contract/spec/vocab/` — how shared vocabulary is specified and certified
- `lmcc_std` — the standard pack: the *exemplar* of §7–§9
- `lmcc_dspy` — any DSPy signature, lowered
- `AGENTS.md` — the repo's cockpit: verify loop, work queue, decisions

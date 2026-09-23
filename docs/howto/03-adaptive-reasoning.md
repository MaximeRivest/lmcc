# Add reasoning that adapts to the model

**Goal.** Give a signature a reasoning field. Serve it through prompt
tags on a plain instruct model, and through the native thinking channel
on a model that has one. Change nothing in the program between the two.

A purpose names what a field is for. A transport says how that meaning
travels. `choose` picks one transport from the model's declared
capabilities at bind.

## 1. A field with a purpose

```python
import dataclasses

import lmcc

@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Purpose["reasoning", str]
    answer: int

@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve the arithmetic problem."""

assert solve.signature.field_named("reasoning").purpose == "reasoning"
```

## 2. Two transports and a chooser

```python
tags = lmcc.Transport(
    tell={"system": "Think inside <think>...</think> before you answer."},
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

adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{problem}"),
], transports={"reasoning": auto})
```

Both transports take the field out of the template (`in_template=False`). It leaves the output
pattern. A find rule brings its value back from where it arrives.

Note: an alternative inside `choose` holds inline transport data. It
cannot hold a `{"use": name}` reference; only a top-level purpose binding
can (kernel.md §6).

## 3. Bind for an instruct model: the tags branch

```python
p1 = solve.bind(adapter, capabilities={"instruct": True})
d1 = p1.describe()
assert d1["hidden"] == ["reasoning"]
assert d1["find"] == [{"field": "reasoning", "from": "text", "between": ["<think>", "</think>"], "remove": True}]
assert d1["request_settings"] == {}

system_text = p1.render(problem="2+2").system
assert system_text == (
    "Solve the arithmetic problem.\n\nReply with exactly this pattern:\n"
    "<answer>\n(integer)\n</answer>\n\n\n"
    "Think inside <think>...</think> before you answer.")

assert p1.parse("<think>2 and 2</think><answer>\n4\n</answer>") == {"answer": 4, "reasoning": "2 and 2"}
```

The `tell` text is appended to the system message after two newlines. The
`<think>` capture is routed to `reasoning` and removed from the text the
reader reads (`remove`).

## 4. Bind for a native-reasoning model: the native branch

```python
p2 = solve.bind(adapter, capabilities={"instruct": True, "native_reasoning": True})
d2 = p2.describe()
assert d2["find"] == [{"field": "reasoning", "from": "part:thinking"}]
assert d2["tell"] == {}
assert p2.render(problem="2+2").request_settings == {"config": {"reasoning": {"effort": "medium"}}}

reply = {"role": "assistant", "parts": [{"type": "thinking", "text": "2 and 2"},
                                        {"type": "text", "text": "<answer>\n4\n</answer>"}]}
assert p2.parse(reply) == {"answer": 4, "reasoning": "2 and 2"}
```

No `tell` text, no tags. The request settings carry the switch. The value
comes from the `thinking` parts of the reply.

## 5. The chooser is data

```python
entry = adapter.dump()
alts = entry["transports"]["reasoning"]["choose"]
assert alts[0]["when"] == {"capability": "native_reasoning"}
assert alts[0]["use"]["requires"] == ["native_reasoning"]
assert "else" in alts[1]
```

## 6. No branch matches

Without an `else`, a model that declares neither fact refuses at bind.
The fix names the predicate to satisfy.

```python
strict = lmcc.Transport(choose=[{"when": {"capability": "native_reasoning"}, "use": native}])
try:
    solve.bind(lmcc.adapter(messages=adapter.template, transports={"reasoning": strict}),
               capabilities={"instruct": True})
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "capability-missing"
    assert r.fix == {"action": "satisfy-predicate", "purpose": "reasoning",
                     "predicate": {"any": [{"capability": "native_reasoning"}]}}
```

The std pack ships the same three ideas as named transports:
`prefix_cot`, `reasoning_tags`, `native_reasoning`
([transport-reasoning.md](../../contract/spec/vocab/transport-reasoning.md)).

## What can refuse here

| code | when |
|---|---|
| `capability-missing` | at bind: `requires` or `when` fails, or no `choose` branch holds and there is no `else` |
| `purpose-ambiguous` | at bind: two fields carry the purpose `reasoning` |
| `field-double-covered` | at bind: the field is found by a transport but still in the template |
| `format-capture-mismatch` | at bind: the find rule delivers a part kind the field's format cannot read |
| `setting-conflict` | at bind: two transports set the same request control to different values |
| `unknown-slot` | at bind: a find rule targets `@purpose.sub` and no field has that purpose |
| `entry-malformed` | at construct: a find rule without a source, a bad predicate, an unknown key |

Codes and fixes: [contract/spec/errors.md](../../contract/spec/errors.md).
Capability facts: [capabilities.md](../../contract/spec/vocab/capabilities.md).

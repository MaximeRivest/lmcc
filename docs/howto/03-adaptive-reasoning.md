# Add reasoning that adapts to the model

**Goal.** Give a signature a reasoning field. Serve it through prompt
tags on a plain instruct model, and through the native thinking channel
on a model that has one. Change nothing in the program between the two.

A role names what a field means. A strategy says how that meaning
travels. `choose` picks one strategy from the model's declared
capabilities at bind.

## 1. A field with a role

```python
import dataclasses

import lmcc

@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Role["reasoning", str]
    answer: int

@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve the arithmetic problem."""

assert solve.signature.field_named("reasoning").role == "reasoning"
```

## 2. Two strategies and a chooser

```python
tags = lmcc.Strategy(
    fragments={"system": "Think inside <think>...</think> before you answer."},
    routings=[{"from": "text", "between": ["<think>", "</think>"], "to": "@role", "consume": True}],
    visible=False)

native = lmcc.Strategy(
    requires=["native_reasoning"],
    visible=False,
    controls={"config": {"reasoning": {"effort": "medium"}}},   # a partial lm15 request
    routings=[{"from": "channel:thinking", "to": "@role"}])

auto = lmcc.Strategy(choose=[
    {"when": {"capability": "native_reasoning"}, "use": native},
    {"else": tags},
])

adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{problem}"),
], strategies={"reasoning": auto})
```

Both strategies hide the field (`visible=False`). It leaves the output
pattern. A routing brings its value back from where it arrives.

Note: an alternative inside `choose` holds inline strategy data. It
cannot hold a `{"use": name}` reference; only a top-level role binding
can (kernel.md §6).

## 3. Bind for an instruct model: the tags branch

```python
p1 = solve.bind(adapter, capabilities={"instruct": True})
d1 = p1.describe()
assert d1["hidden"] == ["reasoning"]
assert d1["routings"] == [{"field": "reasoning", "from": "text", "between": ["<think>", "</think>"], "consume": True}]
assert d1["patch"] == {}

system_text = p1.render(problem="2+2").system
assert system_text == (
    "Solve the arithmetic problem.\n\nReply with exactly this pattern:\n"
    "<answer>\n(integer)\n</answer>\n\n\n"
    "Think inside <think>...</think> before you answer.")

assert p1.parse("<think>2 and 2</think><answer>\n4\n</answer>") == {"answer": 4, "reasoning": "2 and 2"}
```

The fragment is appended to the system message after two newlines. The
`<think>` span is routed to `reasoning` and removed from the text the
lens reads (`consume`).

## 4. Bind for a native-reasoning model: the native branch

```python
p2 = solve.bind(adapter, capabilities={"instruct": True, "native_reasoning": True})
d2 = p2.describe()
assert d2["routings"] == [{"field": "reasoning", "from": "channel:thinking"}]
assert d2["fragments"] == {}
assert p2.render(problem="2+2").patch == {"config": {"reasoning": {"effort": "medium"}}}

reply = {"role": "assistant", "parts": [{"type": "thinking", "text": "2 and 2"},
                                        {"type": "text", "text": "<answer>\n4\n</answer>"}]}
assert p2.parse(reply) == {"answer": 4, "reasoning": "2 and 2"}
```

No fragment, no tags. The request patch carries the control. The value
comes from the `thinking` parts of the reply.

## 5. The chooser is data

```python
entry = adapter.dump()
alts = entry["strategies"]["reasoning"]["choose"]
assert alts[0]["when"] == {"capability": "native_reasoning"}
assert alts[0]["use"]["requires"] == ["native_reasoning"]
assert "else" in alts[1]
```

## 6. No branch matches

Without an `else`, a model that declares neither fact refuses at bind.
The fix names the predicate to satisfy.

```python
strict = lmcc.Strategy(choose=[{"when": {"capability": "native_reasoning"}, "use": native}])
try:
    solve.bind(lmcc.adapter(messages=adapter.template, strategies={"reasoning": strict}),
               capabilities={"instruct": True})
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "capability-missing"
    assert r.fix == {"action": "satisfy-predicate", "role": "reasoning",
                     "predicate": {"any": [{"capability": "native_reasoning"}]}}
```

The std pack ships the same three ideas as named strategies:
`prefix_cot`, `reasoning_tags`, `native_reasoning`
([strategy-reasoning.md](../../contract/spec/vocab/strategy-reasoning.md)).

## What can refuse here

| code | when |
|---|---|
| `capability-missing` | at bind: `requires` or `when` fails, or no `choose` branch holds and there is no `else` |
| `role-ambiguous` | at bind: two fields carry the role `reasoning` |
| `field-double-covered` | at bind: the field is routed but still visible in the pattern |
| `format-span-mismatch` | at bind: the routing delivers a part kind the field's format cannot read |
| `control-conflict` | at bind: two strategies set the same request control to different values |
| `unknown-slot` | at bind: a routing targets `@role.sub` and no field has that role |
| `entry-malformed` | at construct: a routing without a source, a bad predicate, an unknown key |

Codes and fixes: [contract/spec/errors.md](../../contract/spec/errors.md).
Capability facts: [capabilities.md](../../contract/spec/vocab/capabilities.md).

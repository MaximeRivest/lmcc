# Extract one structured value

**Goal.** Return one dataclass from a model call. Spell it with a format.
Read it back as the dataclass.

The kernel spells scalars only. A dataclass is a structured shape. It
needs a format, or `bind` refuses `no-format`. This guide shows both
ways to give it one: a runtime binding, and an artifact entry.

## 1. The signature

`lmcc.One[Person]` means: one output field, whose value is a `Person`.
Without `One`, a dataclass return means several outputs (see
[02-return-several-outputs.md](02-return-several-outputs.md)).

```python
import dataclasses
import json

import lmcc

@dataclasses.dataclass
class Person:
    name: str
    age: int

@lmcc.fn
def extract(text: str) -> lmcc.One[Person]:
    """Extract the person mentioned in the text."""

out = extract.signature.outputs[0]
assert (out.name, out.type) == ("extract", "Person")
assert out.shape["type"] == "object"
```

The output field takes the function's name. Its `type` is the name the
frontend spelled: `Person`. Formats resolve by that name first.

## 2. Bind without a format: the refusal

```python
adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.demos(),
    lmcc.user("{text}"),
])

try:
    extract.bind(adapter, registry=lmcc.Registry())
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "no-format"
    assert r.fix == {"action": "bind-format", "field": "extract", "key": "Person"}
```

The `fix` names the field and the key to bind under.

## 3. Way one: a runtime binding

Register a format for the type in a registry. This is code, per runtime.
It is never written into the artifact.

```python
registry = lmcc.Registry()
registry.format(Person,
    write=lambda p: json.dumps(p.__dict__),
    read=lambda span: Person(**json.loads(span.text)),
    describe=lambda: 'a JSON object {"name": ..., "age": ...}')

plan = extract.bind(adapter, registry=registry)
assert plan.describe()["outputs"][0]["resolved_by"] == "runtime:Person"

system_text = plan.render(text="Ann is 41.").messages[0]["content"][0]["text"]
assert system_text == (
    "Extract the person mentioned in the text.\n\n"
    "Reply with exactly this pattern:\n"
    '<extract>\na JSON object {"name": ..., "age": ...}\n</extract>\n')

assert plan.parse('<extract>\n{"name": "Ann", "age": 41}\n</extract>') == {"extract": Person("Ann", 41)}
```

`describe` is what the model sees in the output slot. `read` gets the
captured span; `span.text` is the stripped text between the markers.

## 4. Way two: a format in the artifact

Install the std pack. Name the `json` format under the type name. This
choice travels with the adapter as data.

```python
import lmcc_std

std = lmcc.Registry()
lmcc_std.install(std)

shared = lmcc.adapter(messages=adapter.template, formats={"Person": "json"})
plan2 = extract.bind(shared, registry=std)
assert plan2.describe()["outputs"][0]["resolved_by"] == "artifact:Person"

assert plan2.parse('<extract>\n{"name": "Ann", "age": 41}\n</extract>') == {"extract": Person("Ann", 41)}
fence = "`" * 3
fenced = f'<extract>\n{fence}json\n{{"name": "Ann", "age": 41}}\n{fence}\n</extract>'
assert plan2.parse(fenced) == {"extract": Person("Ann", 41)}

demo = plan2.render(text="x", demos=[{"text": "Bo is 7.", "extract": Person("Bo", 7)}]).messages[2]
assert demo["content"][0]["text"] == '<extract>\n{\n  "name": "Bo",\n  "age": 7\n}\n</extract>'
assert shared.dump(registry=std)["formats"] == {"Person": {"use": "json"}}
```

The std `json` format lifts the parsed object back into the dataclass
through the field's annotation. It also accepts a fenced reply.

## 5. When the reply is not valid JSON

```python
try:
    plan2.parse('<extract>\n{"name": "Ann"\n</extract>')
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "format-read-error"
    assert r.fix is None
```

A parse refusal carries no `fix`. What to do about a bad reply is your
program's decision.

## What can refuse here

| code | when |
|---|---|
| `no-format` | at bind: the structured type has no format anywhere in the resolution order |
| `format-shape-mismatch` | at bind: the bound format does not accept the field's type or shape |
| `format-direction` | at bind: an input-only format on the output field |
| `unknown-format` | at load or dump: `{"use": "json"}` names a format the registry lacks |
| `format-read-error` | at parse: the format's `read` raised |
| `format-write-error` | at render: the format's `write` raised |
| `parse-missing-fields` | at parse: the reply has no `<extract>` section |

Codes and fixes: [contract/spec/errors.md](../../contract/spec/errors.md).
Resolution order: kernel.md §5.

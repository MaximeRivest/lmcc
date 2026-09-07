# Return several outputs

**Goal.** Get several typed values from one call: a string, an integer,
an enum member, and an optional number. Use a dataclass return without
`One`.

Every field of the dataclass becomes one output field. Each output gets
its own section in the reply. The kernel reads scalars, enums, and
nullable scalars with no format at all.

## 1. The signature

```python
import dataclasses
import enum
import typing

import lmcc

class Mood(enum.Enum):
    HAPPY = "happy"
    SAD = "sad"

@dataclasses.dataclass
class Review:
    summary: str
    stars: int
    mood: Mood
    price: typing.Optional[float]

@lmcc.fn
def review(text: str) -> Review:
    """Summarize the review."""

assert [(f.name, f.type) for f in review.signature.outputs] == [
    ("summary", "str"), ("stars", "int"), ("mood", "Mood"), ("price", "Optional[float]")]
assert review.signature.field_named("mood").shape == {"enum": ["happy", "sad"], "type": "string"}
```

The enum lowers to an `enum` shape. `Optional[float]` lowers to a
nullable number. Both have kernel defaults, so no registry is needed.

## 2. A line-per-field pattern

The output pattern can be any spelling with a literal before each hole.
Here each field is one line: `name: value`.

```python
adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern:\n"
                "{% for f in outputs %}{f.name}: {f.value}\n{% endfor %}"),
    lmcc.demos(),
    lmcc.user("{text}"),
])
plan = review.bind(adapter)

assert plan.render(text="t").messages[0]["content"][0]["text"] == (
    "Summarize the review.\n\nReply with exactly this pattern:\n"
    "summary: ...\nstars: (integer)\nmood: one of: happy, sad\nprice: (number)\n")
assert plan.describe()["lens"]["anchors"] == [
    ["summary", "summary: ", "\n"], ["stars", "stars: ", "\n"],
    ["mood", "mood: ", "\n"], ["price", "price: ", "\n"]]
```

Each output slot renders the field's placeholder: its `desc`, else the
format's `describe`, else the mechanical hint. The anchors are the
literal text before each hole; the close is the newline after it.

Note: the placeholder for `price` shows `(number)`, not that null is
allowed. Give the field a `desc` if the model must know.

## 3. Parse typed values

```python
values = plan.parse("summary: Great\nstars: 5\nmood: happy\nprice: null")
assert values == {"summary": "Great", "stars": 5, "mood": Mood.HAPPY, "price": None}
assert plan.parse("summary: Great\nstars: 5\nmood: happy\nprice: 12.50")["price"] == 12.5
```

`5` is an `int`. `happy` becomes `Mood.HAPPY`. `null` reads as `None`
only because the shape is nullable.

## 4. Demos go through the same pattern

A demo may supply a subset of the outputs. The lens writes only the
fields the demo supplies.

```python
full = plan.render(text="x", demos=[{"text": "d", "summary": "s", "stars": 3, "mood": Mood.SAD, "price": None}])
assert full.messages[2]["content"][0]["text"] == "summary: s\nstars: 3\nmood: sad\nprice: null"
assert plan.parse(full.messages[2]["content"][0]["text"]) == {"summary": "s", "stars": 3, "mood": Mood.SAD, "price": None}

part = plan.render(text="x", demos=[{"text": "d", "summary": "s", "stars": 3}])
assert part.messages[2]["content"][0]["text"] == "summary: s\nstars: 3"
```

## 5. Two ways a reply fails

```python
try:
    plan.parse("summary: Great\nstars: five\nmood: happy\nprice: null")
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "parse-value" and "five" in r.hint

try:
    plan.parse("summary: Great\nstars: 5")
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "parse-missing-fields"
    assert r.partial == {"summary": "Great", "stars": "5"}
```

`partial` holds the raw text of each section that was found, before any
typed read. `"5"` is a string here.

## 6. The skeleton

```python
assert plan.skeleton() == {"prefill": "summary: ", "stops": []}
```

The first anchor is the prefill. The last close is a bare newline, which
is whitespace, so there is no stop sequence. Use a marker such as
`</done>` after the loop if your client needs one.

## What can refuse here

| code | when |
|---|---|
| `unmapped-type` | at signature: a dataclass field has a type the frontend cannot lower |
| `no-format` | at bind: a dataclass field has a structured type and no format |
| `not-lensable` | at bind: the pattern has a hole with no literal before it, or two fields share one anchor |
| `parse-value` | at parse: text the kernel scalar rules cannot read (`five`, `+5`, `maybe`) |
| `parse-missing-fields` | at parse: a section is absent; `partial` carries the raw sections found |
| `parse-ambiguous` | at parse: an anchor appears twice |
| `value-invalid` | at render: a demo value the kernel cannot spell (a non-finite number, null where not nullable) |

Codes and fixes: [contract/spec/errors.md](../../contract/spec/errors.md).
Scalar text rules: kernel.md §7a.

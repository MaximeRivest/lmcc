# Preview cost and cache before you send

**Goal.** See the exact bytes a call will send, the bytes that stay
stable across calls, and what the reply must contain. Spend nothing.

`render`, `prefix`, and `skeleton` are pure. They touch no network and
no clock. Call them as often as you like.

## 1. A plan with demos

```python
import dataclasses

import lmcc

@dataclasses.dataclass
class Out:
    answer: str
    score: int

@lmcc.fn
def qa(context: str, question: str) -> Out:
    """Answer from the context."""

adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}</done>"),
    lmcc.demos(),
    lmcc.user("<context>\n{context}\n</context>"),
    lmcc.user("{question}"),
])
plan = qa.bind(adapter)
demos = [{"context": "Paris is in France.", "question": "Where is Paris?",
          "answer": "France", "score": 9}]
```

## 2. `prefix()`: the cache-stable messages

`prefix` renders every message before the first one that depends on an
input. That is the system message and the demo turns here.

```python
pre = plan.prefix(demos=demos)
assert [m["role"] for m in pre] == ["system", "user", "user", "assistant"]
assert pre[0]["content"][0]["text"] == (
    "Answer from the context.\n\nReply with exactly this pattern:\n"
    "<answer>\n...\n</answer>\n<score>\n(integer)\n</score>\n</done>")
assert pre[3]["content"][0]["text"] == "<answer>\nFrance\n</answer>\n<score>\n9\n</score>\n</done>"

stable_chars = sum(len(p["text"]) for m in pre for p in m["content"])
assert stable_chars == 223
```

Count characters, or run your tokenizer over `pre`, to know what a
provider's prompt cache can hold.

## 3. `render()` is pure and starts with the prefix

```python
req = plan.render(context="c", question="q", demos=demos)
assert req.messages[:4] == pre
assert [m["role"] for m in req.messages] == ["system", "user", "user", "assistant", "user", "user"]
assert req.patch == {}
assert req.request() == {"messages": req.messages}

again = plan.render(context="c", question="q", demos=demos)
assert again == req
```

Two renders with the same values are equal. `request()` merges the
messages and the patch into one dict for a client.

The user messages carry the inputs. Change one input, and only its
message changes:

```python
a = plan.render(context="c", question="q")
b = plan.render(context="c", question="other")
assert a.messages[:-1] == b.messages[:-1]
assert b.messages[-1]["content"][0]["text"] == "other"
```

## 4. `skeleton()`: what the reply must contain

```python
assert plan.skeleton() == {"prefill": "<answer>\n", "stops": ["</done>"]}
```

`prefill` is the text before the first output hole. Hand it to a client
as the assistant prefill. `stops` is the marker that ends the pattern.
Hand it to the client as a stop sequence. Both come from the template;
neither is a guess.

## 5. A missing input refuses at render

```python
try:
    plan.render(context="c")
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "missing-input" and "question" in r.hint
    assert r.fix is None
```

Render refusals carry no `fix`: the cause is a program value.

## What can refuse here

| code | when |
|---|---|
| `missing-input` | at render: no value for a rendered input field |
| `value-invalid` | at render: a kernel default cannot spell the value (wrong kind, non-finite number, bad history item) |
| `format-write-error` | at render: a format's `write` raised |
| `value-collides` | at render: a demo value contains a marker the lens reads |
| `demo-not-renderable` | at render: a demo goes through a format that does not round-trip |

None of these carries a `fix`. Every bind-time refusal has already fired
before you reach `render`. Codes: [errors.md](../../contract/spec/errors.md).
`prefix` and `skeleton`: kernel.md §3.

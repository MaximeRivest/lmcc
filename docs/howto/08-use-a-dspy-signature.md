# Use a DSPy signature

**Goal.** Take a `dspy.Signature` you already have. Lower it to an lmcc
signature. Bind, render, and parse through the DSPy-shaped adapter.

`lmcc_dspy` is a frontend. It lowers any DSPy signature to the same
plain form every other frontend produces. It also ships one adapter
whose template spells DSPy's `[[ ## name ## ]]` markers.

Every block in this guide needs `dspy`. The test skips the guide when
`dspy` does not import. Run it with `python/lmcc_dspy/check`'s venv:
`.venv-dspy/bin/python -m pytest tests/test_docs_howto.py`.

## 1. Lower a class-based signature

```python
# requires: dspy
import dspy

import lmcc
import lmcc_dspy

class Summarize(dspy.Signature):
    """Summarize the passage in one sentence."""
    passage: str = dspy.InputField()
    summary: str = dspy.OutputField(desc="one sentence")
    keywords: list[str] = dspy.OutputField()

registry = lmcc.Registry()
lowered = lmcc_dspy.lower(Summarize, registry=registry)
sig = lowered.signature
assert sig.instructions == "Summarize the passage in one sentence."
assert [(f.name, f.direction, f.type) for f in sig.fields] == [
    ("passage", "input", "str"), ("summary", "output", "str"), ("keywords", "output", "list[str]")]
assert sig.field_named("summary").desc == "one sentence"
assert sig.field_named("keywords").shape == {"items": {"type": "string"}, "type": "array"}
```

`lower` drops only what DSPy declares a no-op: `prefix`, `format`,
`parser`, and field defaults. A type it cannot carry refuses
`unmapped-type`, naming the field.

## 2. Bind through the DSPy-shaped adapter

```python
adapter = lmcc_dspy.adapter(registry)
plan = adapter.bind(sig, {}, registry=registry)
assert [(o["name"], o["format"], o["resolved_by"]) for o in plan.describe()["outputs"]] == [
    ("summary", "kernel-scalar", "kernel"), ("keywords", "json", "artifact:*")]
assert adapter.dump(registry=registry)["formats"] == {"*": {"use": "json", "options": {"indent": None}}}
```

The adapter binds `json` under `*`. Scalars keep the kernel defaults;
every structured shape goes through `json`.

## 3. Render and parse

```python
req = plan.render(passage="Rain fell all day.")
assert req.messages[1]["content"][0]["text"] == (
    "[[ ## passage ## ]]\nRain fell all day.\n\n"
    "Respond with the corresponding output fields, then end with the marker for `[[ ## completed ## ]]`.")
assert plan.skeleton() == {"prefill": "[[ ## summary ## ]]\n", "stops": ["[[ ## completed ## ]]"]}

reply = '[[ ## summary ## ]]\nIt rained.\n\n[[ ## keywords ## ]]\n["rain"]\n\n[[ ## completed ## ]]'
assert plan.parse(reply) == {"summary": "It rained.", "keywords": ["rain"]}
```

The parser is derived from the template. `[[ ## completed ## ]]` is the
tail, so it is also the stop sequence.

## 4. A string signature

```python
short = lmcc_dspy.lower("question -> answer", registry=registry)
assert short.signature.instructions == "Given the fields `question`, produce the fields `answer`."
assert [f.name for f in short.signature.fields] == ["question", "answer"]
```

## 5. `dspy.History` becomes history turns

The history input leaves the signature. `split_inputs` turns its
messages into field turns that the adapter's `history` directive
renders through the same pattern.

```python
class Chat(dspy.Signature):
    """Chat."""
    history: dspy.History = dspy.InputField()
    question: str = dspy.InputField()
    answer: str = dspy.OutputField()

chat = lmcc_dspy.lower(Chat, registry=registry)
assert chat.history_field == "history"
inputs, turns = chat.split_inputs({
    "history": dspy.History(messages=[{"question": "hi", "answer": "hello"}]),
    "question": "how are you?"})
assert inputs == {"question": "how are you?"}
assert turns == [{"fields": {"question": "hi", "answer": "hello"}}]

cp = adapter.bind(chat.signature, {}, registry=registry)
req = cp.render(inputs=inputs, history=turns)
assert [m["role"] for m in req.messages] == ["system", "user", "assistant", "user"]
assert req.messages[2]["content"][0]["text"] == "[[ ## answer ## ]]\nhello\n\n[[ ## completed ## ]]"
```

## 6. `dspy.Reasoning` carries the role

```python
class Solve(dspy.Signature):
    q: str = dspy.InputField()
    reasoning: dspy.Reasoning = dspy.OutputField()
    a: str = dspy.OutputField()

assert [(f.name, f.role) for f in lmcc_dspy.lower(Solve, registry=registry).signature.fields] == [
    ("q", "plain"), ("reasoning", "reasoning"), ("a", "plain")]
```

Bind a strategy to the `reasoning` role to change how it travels
([03-adaptive-reasoning.md](03-adaptive-reasoning.md)).

## What can refuse here

| code | when |
|---|---|
| `unmapped-type` | at lower: an annotation the frontend cannot carry, or a `dspy.History` that is not an input |
| `signature-malformed` | at lower: a field that is neither `InputField` nor `OutputField` |
| `unknown-format` | at load: `json` is not in the registry (`lmcc_dspy.adapter` installs `lmcc_std`) |
| `parse-missing-fields`, `parse-ambiguous` | at parse: a marker is absent or occurs twice |
| `format-read-error` | at parse: a structured field's text is not valid JSON |

Not claimed: DSPy's exact prompt bytes and lenient JSON repair. The
catalog of claimed features is `python/tests/dspy/test_catalog.py`.
Codes: [errors.md](../../contract/spec/errors.md).

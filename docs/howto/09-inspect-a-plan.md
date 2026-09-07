# Inspect a plan: the debugging how-to

**Goal.** Find out why a prompt looks the way it does, which format
spells a field, where a hidden field went, and what streams. Read the
plan, not the code.

`plan.describe()` is the whole plan as a JSON-serializable dict.
`plan.explain()` prints the short form. `registry.describe()` shows what
the runtime registered.

## 1. A plan with a named strategy and a named format

```python
import dataclasses
import json

import lmcc
import lmcc_std

@dataclasses.dataclass
class Out:
    reasoning: lmcc.Role["reasoning", str]
    answer: str
    tags: list[str]

@lmcc.fn
def classify(text: str) -> Out:
    """Classify."""

registry = lmcc.Registry()
lmcc_std.install(registry)
adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}</done>"),
    lmcc.demos(),
    lmcc.user("{text}")],
    strategies={"reasoning": "reasoning_tags"},
    formats={"list[string]": "json"},
    name="tagger")
plan = classify.bind(adapter, capabilities={"instruct": True}, registry=registry)
d = plan.describe()
json.dumps(d)                       # all of it is plain data
```

## 2. Which fields are visible, and what spells them

```python
assert [(f["name"], f["format"], f["resolved_by"]) for f in d["outputs"]] == [
    ("answer", "kernel-scalar", "kernel"),
    ("tags", "json", "artifact:list[string]")]
assert d["inputs"] == [{"name": "text", "type": "str", "shape": {"type": "string"},
                        "format": "kernel-scalar", "resolved_by": "kernel"}]
assert d["hidden"] == ["reasoning"]
```

`resolved_by` names the step of the resolution order that won:
`artifact:<key>`, `runtime:<type>`, or `kernel`. A field in `hidden`
is served by a strategy, not by the pattern.

## 3. Where the hidden field went

```python
assert d["strategies"] == {"reasoning": "reasoning_tags"}
assert d["routings"] == [{"field": "reasoning", "from": "text",
                          "between": ["<think>", "</think>"], "consume": True}]
assert d["fragments"] == {
    "system": "After every sentence of output, add your thinking inside <think>...</think> tags."}
assert d["placements"] == [] and d["patch"] == {}
```

The strategy added a fragment to the system message. It reads the field
back from `<think>` spans and removes them before the lens runs.

## 4. What the parser looks for

```python
assert d["lens"] == {
    "kind": "derived",
    "anchors": [["answer", "<answer>\n", "\n</answer>\n"], ["tags", "<tags>\n", "\n</tags>\n"]],
    "tail": "</done>"}
assert d["skeleton"] == {"prefill": "<answer>\n", "stops": ["</done>"]}
```

Each anchor is `[field, before, after]`. The tail ends the pattern. If
a reply does not parse, compare its bytes with these.

## 5. What streams, and what versions are pinned

```python
assert d["streaming"] == {
    "mode": "incremental", "lens": {"mode": "incremental"},
    "routings": [{"field": "reasoning", "from": "text", "mode": "incremental"}],
    "field_done": "finish"}
assert d["versions"] == {"kernel": "0.3.0",
                         "vocab": {"format/json": "0.1.0", "strategy/reasoning_tags": "0.1.0"}}
assert d["capabilities"] == {"instruct": True}
```

## 6. The short form

```python
assert plan.explain() == "\n".join([
    "adapter: tagger",
    "lens: derived",
    "input  text                 kernel-scalar (kernel)",
    "output answer               kernel-scalar (kernel)",
    "output tags                 json (artifact:list[string])",
    "hidden reasoning            served by strategy/placement",
])
```

## 7. What the runtime registered

```python
assert registry.describe() == {
    "formats": {"json": "0.1.0", "scaled_number": "0.1.0", "table": "0.1.0"},
    "type_bindings": [],
    "strategies": {"native_reasoning": "0.1.0", "prefix_cot": "0.1.0", "reasoning_tags": "0.1.0"},
    "lenses": {"derived": "kernel", "json_object": "0.1.0"},
    "allow_udf": False,
    "extensions": {"pattern/legacy-re2": {"version": "0.1.0", "binding": "python:re"}}}
```

`type_bindings` lists runtime `registry.format(T, ...)` calls. They are
never in the artifact; two runtimes may differ here. `extensions` is
what this host binds beyond the core (kernel §10) — a fact about the
process, kept apart from the model's capabilities; an artifact that
declares one this list lacks refuses `extension-unsupported` at load.

## 8. Two more views

- `adapter.dump()` is the artifact. Diff two dumps to see what changed.
- `plan.render(...)` is pure. Print the messages to see exact bytes.
- `refusal.describe()` is `{code, hint, fix, partial}` as a dict.

## What can refuse here

`describe()`, `explain()`, and `registry.describe()` never refuse. Every
refusal fired at `bind`. When `bind` refuses, read `r.fix` first
([06-repair-from-a-fix.md](06-repair-from-a-fix.md)). When `bind`
succeeds but the prompt or the parse surprises you, read `describe()`
before you read code.

# Inspect a plan: the debugging how-to

**Goal.** Find out why a prompt looks the way it does, which format
spells a field, where a hidden field went, and what streams. Read the
plan, not the code.

`plan.describe()` is the whole plan as a JSON-serializable dict.
`plan.explain()` prints the short form. `registry.describe()` shows what
the runtime registered.

## 1. A plan with a named transport and a named format

```python
import dataclasses
import json

import lmcc
import lmcc_std

@dataclasses.dataclass
class Out:
    reasoning: lmcc.Purpose["reasoning", str]
    answer: str
    tags: list[str]

@lmcc.fn
def classify(text: str) -> Out:
    """Classify."""

registry = lmcc.Registry()
lmcc_std.install(registry)
adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}</done>"),
    lmcc.turns(),
    lmcc.user("{text}")],
    transports={"reasoning": "reasoning_tags"},
    formats={"list[string]": "json"},
    name="tagger")
plan = classify.bind(adapter, capabilities={"instruct": True}, registry=registry)
d = plan.describe()
json.dumps(d)                       # all of it is plain data
```

## 2. Which fields are in the template, and what spells them

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
is served by a transport, not by the pattern.

## 3. Where the hidden field went

```python
assert d["transports"] == {"reasoning": "reasoning_tags"}
assert d["find"] == [{"field": "reasoning", "from": "text",
                          "between": ["<think>", "</think>"], "remove": True, "repair": True}]
assert d["tell"] == {
    "system": "After every sentence of output, add your thinking inside <think>...</think> tags."}
assert d["puts"] == [] and d["request_settings"] == {} and d["strict"] is False
```

The transport added `tell` text to the system message. It reads the field
back from `<think>` captures and removes them before the reader runs.

## 4. What the parser looks for

```python
assert d["reader"] == {
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
    "mode": "incremental", "reader": {"mode": "incremental"},
    "find": [{"field": "reasoning", "from": "text", "mode": "incremental"}],
    "field_done": "finish",
    "repairs": {"mode": "forgiving",
                "reason": "from the first misspelled marker the rest of the reply waits for finish"}}
assert d["versions"] == {"kernel": "0.8.3",
                         "vocab": {"format/json": "0.1.0", "transport/reasoning_tags": "0.3.0"}}
assert d["capabilities"] == {"instruct": True}
```

## 6. How earlier turns will be written

One slot, `turns`, placed as messages. The current turn's steps would
follow the template. Reasoning has a writer derived from its own find rule
(the same `<think>` markers it is read with), placed before the answer.
Nothing is dropped, and nothing depends on a recorded provider part.

```python
assert d["turns"] == {
    "slots": [{"name": "turns", "form": "messages"}],
    "steps": "after the template",
    "replay": "recorded",
    "writers": {"reasoning": {"by": "derived:between", "between": ["<think>", "</think>"],
                              "position": "before"}},
    "projections": {}, "replayed": [], "input_formats": {}}
```

## 7. The short form

```python
assert plan.explain() == "\n".join([
    "adapter: tagger",
    "reader: derived",
    "input  text                 kernel-scalar (kernel)",
    "output answer               kernel-scalar (kernel)",
    "output tags                 json (artifact:list[string])",
    "hidden reasoning            served by transport/put",
])
```

## 8. What the runtime registered

```python
d = registry.describe()
assert d["formats"] == {"code_arguments": "0.1.0", "code_calls": "0.1.0",
                        "citations": "0.1.0", "function_tool": "0.1.0", "json": "0.1.0", "scaled_number": "0.2.0",
                        "source_list": "0.1.0", "table": "0.2.0", "tool_calls": "0.1.0", "tool_catalog": "0.1.0"}
assert d["transports"] == {"heredoc_tools": "0.1.0",
                           "fenced_tools": "0.1.0", "inline_citations": "0.1.0", "native_citations": "0.1.0",
                           "native_reasoning": "0.1.0", "native_tools": "0.1.0", "prefix_cot": "0.1.0",
                           "reasoning_tags": "0.3.0"}
assert d["readers"] == {"derived": "kernel", "json_object": "0.1.0"} and d["allow_udf"] is False
assert d["extensions"] == {"pattern/legacy-re2": {"version": "0.1.0", "binding": "python:re"}}
assert [b["type"] for b in d["type_bindings"]] == ["list[Tool]", "list[ToolCall]", "list[Citation]", "list[Source]"]
```

`type_bindings` lists runtime `registry.format(T, ...)` calls. They are
never in the artifact; two runtimes may differ here. `extensions` is
what this host binds beyond the core (kernel §10) — a fact about the
process, kept apart from the model's capabilities; an artifact that
declares one this list lacks refuses `extension-unsupported` at load.

## 9. Two more views

- `adapter.dump()` is the artifact. Diff two dumps to see what changed.
- `plan.render(...)` is pure. Print the messages to see exact bytes.
- `refusal.describe()` is `{code, hint, fix, partial}` as a dict.

## What can refuse here

`describe()`, `explain()`, and `registry.describe()` never refuse. Every
refusal fired at `bind`. When `bind` refuses, read `r.fix` first
([06-repair-from-a-fix.md](06-repair-from-a-fix.md)). When `bind`
succeeds but the prompt or the parse surprises you, read `describe()`
before you read code.

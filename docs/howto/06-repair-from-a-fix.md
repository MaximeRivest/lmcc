# Read a refusal's `fix` and repair in code

**Goal.** Catch a refusal before render. Read its `fix`. Apply the named
action without reading the English hint. Try again.

Every refusal that fires at construct, signature, load, or bind carries
a `fix`: `{"action": ..., ...parameters}`. The action vocabulary is
closed ([errors.md, "Fix actions"](../../contract/spec/errors.md)).
Parameters are names: a field, a role, a fact, a vocabulary name, a
path into the artifact.

## 1. An artifact that needs two repairs

This entry references the `json` format and a strategy that needs a
capability. Load it with an empty registry and no declared facts.

```python
import dataclasses
import json

import lmcc

@dataclasses.dataclass
class Person:
    name: str
    age: int

@dataclasses.dataclass
class Out:
    reasoning: lmcc.Role["reasoning", str]
    person: Person

@lmcc.fn
def extract(text: str) -> Out:
    """Extract the person."""

entry = {
    "name": "x", "versions": {"kernel": "0.2.0", "vocab": {}},
    "template": [
        {"role": "system", "text": "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"},
        {"role": "user", "text": "{text}"}],
    "parse": {"kind": "derived"},
    "strategies": {"reasoning": {"requires": ["native_reasoning"], "visible": False,
                                 "routings": [{"from": "channel:thinking", "to": "@role"}]}},
    "formats": {"Person": {"use": "json"}},
}
```

## 2. A repair loop over `fix["action"]`

```python
registry = lmcc.Registry()
capabilities = {}
log = []

def attempt():
    adapter = lmcc.load(entry, registry=registry)
    return extract.bind(adapter, capabilities=capabilities, registry=registry)

plan = None
for _ in range(5):
    try:
        plan = attempt()
        break
    except lmcc.Refusal as r:
        log.append((r.code, r.fix))
        if r.fix["action"] == "install-vocabulary":
            import lmcc_std
            lmcc_std.install(registry)          # provides format 'json'
        elif r.fix["action"] == "declare-capability":
            capabilities[r.fix["fact"]] = True  # the model does have it
        else:
            raise

assert log == [
    ("unknown-format", {"action": "install-vocabulary", "kind": "format", "name": "json"}),
    ("capability-missing", {"action": "declare-capability", "fact": "native_reasoning"}),
]
assert plan.describe()["hidden"] == ["reasoning"]
```

The loop never reads `r.hint`. Each action names what to touch. Declare
a capability only when the model truly has it; the fix reports what the
artifact needs, not what the model can do.

## 3. Fixes that point into the artifact

Some fixes name a path. `edit-template` names the message and the
field. A program can show the exact spot, or rewrite it.

```python
uncovered = dict(entry, template=[entry["template"][0], {"role": "user", "text": "go"}])
try:
    extract.bind(lmcc.load(uncovered, registry=registry), capabilities=capabilities, registry=registry)
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "field-uncovered"
    assert r.fix == {"action": "edit-template", "path": "template", "field": "text"}

no_anchor = dict(entry, template=[{"role": "system", "text": "{% for f in outputs %}{f.value}\n{% endfor %}"},
                                  entry["template"][1]])
try:
    extract.bind(lmcc.load(no_anchor, registry=registry), capabilities=capabilities, registry=registry)
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "not-lensable"
    assert r.fix == {"action": "edit-template", "path": "template[0]", "field": "person"}
```

## 4. A version mismatch names both sides

```python
newer = json.loads(json.dumps(entry))
newer["versions"]["kernel"] = "0.9.0"
try:
    lmcc.load(newer, registry=registry)
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.describe() == {
        "code": "version-incompatible",
        "hint": "kernel: artifact needs 0.9.0, this implementation provides 0.2.0",
        "fix": {"action": "match-version", "entry": "kernel", "needs": "0.9.0", "provides": "0.2.0"},
        "partial": None}
```

`describe()` is the whole refusal as a dict. Log it as JSON.

## What can refuse here

Every code that fires before render carries a `fix`. The full table is
in [errors.md](../../contract/spec/errors.md). The actions this guide
met:

| action | parameters | seen with |
|---|---|---|
| `install-vocabulary` | `kind`, `name` | `unknown-format`, `unknown-strategy`, `unknown-parse-kind` |
| `declare-capability` | `fact` | `capability-missing` |
| `edit-template` | `path`, `slot`?, `field`? | `field-uncovered`, `not-lensable`, `unknown-slot` |
| `match-version` | `entry`, `needs`, `provides` | `version-incompatible` |

Refusals at render and parse carry `fix: None`. What to do about a bad
value or a bad reply is your program's decision.

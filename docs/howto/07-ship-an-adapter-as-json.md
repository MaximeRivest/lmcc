# Ship an adapter as JSON and load it elsewhere

**Goal.** Write an adapter to one JSON file. Load it elsewhere. Ship a
format's code inside the file when a name is not enough, and load that
with `allow_udf`.

## 1. A data-only artifact

A format reference `{"use": "json"}` is data. The loader needs only a
registry that provides the name.

```python
import json

import lmcc
import lmcc_std

@lmcc.fn
def rows(text: str) -> list[int]:
    """List the integers."""

template = [
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{text}")]

std = lmcc.Registry()
lmcc_std.install(std)
adapter = lmcc.adapter(messages=template, formats={"list[integer]": "json"}, name="rows_v1")
entry = adapter.dump(registry=std)
assert entry == {
    "name": "rows_v1",
    "versions": {"kernel": "0.3.0", "vocab": {"format/json": "0.1.0"}},
    "template": [
        {"role": "system", "text": "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"},
        {"role": "user", "text": "{text}"}],
    "parse": {"kind": "derived"},
    "formats": {"list[integer]": {"use": "json"}},
}
wire = json.dumps(entry)
```

`versions` pins the kernel and every named vocabulary entry used. The
key `list[integer]` is a structural key; the type name `list[int]` would
also work and would win over it.

## 2. Load it elsewhere

```python
elsewhere = lmcc.Registry()
lmcc_std.install(elsewhere)
again = lmcc.load(json.loads(wire), registry=elsewhere)
assert again.dump(registry=elsewhere) == entry
assert rows.bind(again, registry=elsewhere).parse("<rows>\n[1, 2]\n</rows>") == {"rows": [1, 2]}

try:
    lmcc.load(json.loads(wire), registry=lmcc.Registry())
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "unknown-format"
    assert r.fix == {"action": "install-vocabulary", "kind": "format", "name": "json"}
```

An empty registry refuses by name; nothing ambient is consulted.

## 3. Ship the format's code inside the artifact

Ship the functions when the receiver may lack your pack. Each must be a
named `def` (not a lambda) that reaches no global.

```python
def write(v, f):
    return ", ".join(str(x) for x in v)

def read(span, f):
    return [int(p.strip()) for p in span.text.split(",")]

def describe(f):
    return "comma-separated integers"

csv = lmcc.make_format(write=write, read=read, describe=describe)
shipped_entry = lmcc.ship(csv, authored_by="docs")
assert shipped_entry["language"] == "python" and shipped_entry["deps"] == []
assert shipped_entry["write"] == 'def write(v, f):\n    return ", ".join(str(x) for x in v)'
assert len(shipped_entry["sha256"]) == 64

shipped = lmcc.adapter(messages=template, formats={"list[integer]": shipped_entry}, name="rows_v2")
entry2 = shipped.dump(registry=lmcc.Registry())
assert entry2["formats"]["list[integer]"] == shipped_entry
```

## 4. Load with and without placement

```python
try:
    lmcc.load(entry2, registry=lmcc.Registry())
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "format-untrusted"
    assert r.fix == {"action": "place-udf", "language": "python", "path": "formats['list[integer]']"}

placing = lmcc.Registry(allow_udf=True)
placed = lmcc.load(entry2, registry=placing)
plan = rows.bind(placed, registry=placing)
assert plan.describe()["outputs"][0]["resolved_by"] == "artifact:list[integer]"
assert plan.parse("<rows>\n1, 2, 3\n</rows>") == {"rows": [1, 2, 3]}
assert placed.dump(registry=placing) == entry2
```

Loading never runs the code. Admission checks the hash and the
self-containment. `allow_udf` is the host's decision.

## 5. What admission refuses

```python
tampered = json.loads(json.dumps(entry2))
tampered["formats"]["list[integer]"]["read"] = "def read(span, f):\n    return []"
try:
    lmcc.load(tampered, registry=placing)
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "udf-tampered"
    assert r.fix == {"action": "reship-udf", "path": "formats['list[integer]']"}

LIMIT = 3
def capped(v, f):
    return ", ".join(str(x) for x in v[:LIMIT])

try:
    lmcc.ship(lmcc.make_format(write=capped, read=read))
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "format-not-self-contained" and "LIMIT" in r.hint
    assert r.fix == {"action": "reship-udf", "path": "write"}
```

## What can refuse here

| code | when |
|---|---|
| `unknown-format`, `unknown-strategy`, `unknown-parse-kind` | at load or dump: a `{"use": name}` names nothing in the registry |
| `version-incompatible` | at load: the artifact pins a version this runtime cannot honor |
| `entry-malformed` | at load: a structural defect; the hint names the path |
| `format-untrusted` | at load: the artifact ships a UDF and `allow_udf` is false |
| `udf-tampered` | at load: the `sha256` does not match the source |
| `format-not-self-contained` | at ship or load: a function reaches a free variable or a global |
| `udf-unplaceable` | at load: the UDF's language has no placement in this host |

Codes and fixes: [errors.md](../../contract/spec/errors.md). The file
format: [entry.schema.json](../../contract/schema/entry.schema.json).

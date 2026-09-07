# Write a vocabulary pack

**Version scope.** These examples use kernel 0.2. The [next-version portability design](../../contract/spec/portability.md)
makes execution extensions explicit and optional. Its requirements and binding
API are not implemented yet. Do not infer general regex portability from these examples.

**Goal.** Register a named format and a named strategy through the
sockets. Reference them from an artifact by name. Pin their behavior
with a corpus-style case. A pack has no privilege; `lmcc_std` uses the
same calls.

## 1. A format factory

A named format is a factory `options -> Format`. Raise on a bad
option; the loader reports `entry-malformed` at the reference's path.

```python
import lmcc

ASCII_WS = " \t\n\r\f\v"          # the six characters kernel.md §7a strips

class CsvFormat(lmcc.Format):
    accepts = ("list[string]",)      # the keys this format may bind under

    def __init__(self, options):
        self.sep = options.get("sep", ",")
        if not isinstance(self.sep, str) or not self.sep.strip(ASCII_WS):
            raise ValueError("sep must be a non-blank string")

    def describe(self, field):
        return f"values separated by {self.sep!r}"
    def write(self, value, field):
        return f"{self.sep} ".join(value)
    def read(self, span, field):
        return [p.strip(ASCII_WS) for p in span.text.split(self.sep)] if span.text else []

def csv_factory(options):
    return CsvFormat(options)
```

## 2. A strategy factory

A named strategy is a factory `options -> Strategy`. The kernel checks
its result like inline data.

```python
def scratchpad(options):
    prefix = options.get("prefix", "NOTE:")
    return lmcc.Strategy(
        requires=["instruct"],
        fragments={"system": f"Write your notes on lines starting with {prefix!r}."},
        routings=[{"from": "text", "line_prefixed": prefix, "to": "@role", "consume": True}],
        visible=False)
```

## 3. Install through the sockets

```python
def install(registry, *, exist_ok=True):
    registry.register_format("csv", csv_factory, version="0.1.0", exist_ok=exist_ok)
    registry.register_strategy("scratchpad", scratchpad, version="0.1.0", exist_ok=exist_ok)

registry = lmcc.Registry()
install(registry)
assert registry.describe()["formats"] == {"csv": "0.1.0"}
```

## 4. A corpus-style case

Author the case as data first. Then make the pack pass it.

```python
case = {
    "name": "mypack-csv-scratchpad", "kind": "parse", "vocab": ["mypack"],
    "entry": {
        "name": "notes_v1",
        "versions": {"kernel": "0.3.0", "vocab": {"format/csv": "0.1.0", "strategy/scratchpad": "0.1.0"}},
        "template": [
            {"role": "system", "text": "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"},
            {"role": "user", "text": "{text}"}],
        "parse": {"kind": "derived"},
        "strategies": {"reasoning": {"use": "scratchpad", "options": {"prefix": "NOTE:"}}},
        "formats": {"list[string]": {"use": "csv", "options": {"sep": ";"}}}},
    "signature": {"instructions": "Find the names.", "fields": [
        {"name": "text", "direction": "input", "shape": {"type": "string"}},
        {"name": "reasoning", "direction": "output", "shape": {"type": "string"}, "role": "reasoning"},
        {"name": "names", "direction": "output", "shape": {"type": "array", "items": {"type": "string"}}}]},
    "capabilities": {"instruct": True},
    "response": "NOTE: two names\n<names>\nAnn; Bo\n</names>\nNOTE: done",
    "expect": {"values": {"names": ["Ann", "Bo"], "reasoning": "two names\ndone"}},
}

def run_parse_case(case, registry):
    adapter = lmcc.load(case["entry"], registry=registry)
    signature = lmcc.signature_from_dict(case["signature"])
    plan = adapter.bind(signature, case.get("capabilities", {}), registry=registry)
    values = plan.parse(case["response"])
    assert values == case["expect"]["values"], values
    text = case["response"]
    for i in range(len(text) + 1):             # every split gives the same values
        stream = plan.stream()
        stream.feed(text[:i])
        stream.feed(text[i:])
        assert stream.finish().values == values
    return plan

plan = run_parse_case(case, registry)
assert plan.render(text="t").messages[0]["content"][0]["text"].endswith(
    "<names>\nvalues separated by ';'\n</names>\n\n\nWrite your notes on lines starting with 'NOTE:'.")
```

The real harness (`contract/harness/runner.py`) installs only `std`
today; run a pack's own cases through a loop like this one.

## 5. What the sockets refuse

```python
try:
    lmcc.load(case["entry"], registry=lmcc.Registry())
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "unknown-strategy"
    assert r.fix == {"action": "install-vocabulary", "kind": "strategy", "name": "scratchpad"}

bad = dict(case["entry"], formats={"list[string]": {"use": "csv", "options": {"sep": " "}}})
try:
    lmcc.load(bad, registry=registry)
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "entry-malformed"
    assert r.fix == {"action": "edit-entry", "path": "formats['list[string]']"}

try:
    install(registry, exist_ok=False)
except lmcc.Refusal as r:
    assert r.code == "already-registered" and r.fix is None
```

To graduate the pack: write a spec file in `contract/spec/vocab/`, add
corpus cases with `"vocab": ["mypack"]`, add a row to
`contract/spec/vocab/README.md`.

## What can refuse here

| code | when |
|---|---|
| `already-registered` | at registration: the name exists and `exist_ok` is false; no `fix` |
| `unknown-format`, `unknown-strategy` | at load or dump: the registry lacks the name |
| `entry-malformed` | at load: the factory raised, or returned malformed data |
| `version-incompatible` | at load: the artifact pins a version the pack does not provide |
| `format-shape-mismatch` | at bind: the format's `accepts` does not cover the field |

Codes: [errors.md](../../contract/spec/errors.md). Exemplar: `python/lmcc_std/`.

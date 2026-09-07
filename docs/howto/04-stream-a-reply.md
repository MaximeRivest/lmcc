# Stream a reply

**Version scope.** These examples use kernel 0.2. The [next-version portability design](../../contract/spec/portability.md)
makes execution extensions explicit and optional. Its requirements and binding
API are not implemented yet. Do not infer general regex portability from these examples.

**Goal.** Read a reply as it arrives. Get the same typed values, or the
same refusal, as `parse()`.

`plan.stream()` is a pure reducer with no connection. Hand each network
delta to `feed`. At end of stream, call `finish`.

## 1. A plan and its streaming mode

```python
import dataclasses

import lmcc

@dataclasses.dataclass
class Book:
    title: str
    year: int

@lmcc.fn
def book(text: str) -> Book:
    """Extract the book."""

adapter = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{% for f in inputs %}{f.value}{% endfor %}"),
])
plan = book.bind(adapter)
assert plan.describe()["streaming"] == {
    "mode": "incremental", "lens": {"mode": "incremental"}, "routings": [], "field_done": "finish"}
```

`incremental`: field text is released as it arrives. `buffered`: it
waits for EOF, and the reason is stated.

## 2. Feed text deltas, consume events

```python
stream = plan.stream()
log = []
for delta in ["Sure! <ti", "tle>\nDu", "ne ", "Messiah", "\n</title>\n<year>\n19", "69\n</year>\nDone."]:
    log.append(stream.feed(delta))

assert log == [
    [],
    [{"kind": "field_started", "field": "title"}, {"kind": "field_delta", "field": "title", "text": "Du"}],
    [{"kind": "field_delta", "field": "title", "text": "ne"}],
    [{"kind": "field_delta", "field": "title", "text": " Messiah"}],
    [{"kind": "field_started", "field": "year"}, {"kind": "field_delta", "field": "year", "text": "19"}],
    [{"kind": "field_delta", "field": "year", "text": "69"}],
]

end = stream.finish()
assert end.events == [{"kind": "field_done", "field": "title", "value": "Dune Messiah"},
                      {"kind": "field_done", "field": "year", "value": 1969}]
assert end.values == {"title": "Dune Messiah", "year": 1969}
assert end.values == plan.parse("Sure! <title>\nDune Messiah\n</title>\n<year>\n1969\n</year>\nDone.")
```

`<ti` emits nothing: it may start a marker. The space after `ne` is held
until the next delta. `field_done` comes only from `finish`, after the
same checks as `parse`. A field's deltas join to its raw text, for every
way to split the reply.

## 3. Feed part deltas

Adjacent part deltas of the same kind join into one part.

```python
@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Role["reasoning", str]
    answer: int

@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve."""

native = lmcc.Strategy(requires=["native_reasoning"], visible=False,
                       routings=[{"from": "channel:thinking", "to": "@role"}])
p2 = solve.bind(lmcc.adapter(messages=adapter.template, strategies={"reasoning": native}),
                capabilities={"native_reasoning": True})
s = p2.stream()
assert s.feed({"kind": "thinking", "text": "two and "}) == [
    {"kind": "field_started", "field": "reasoning"},
    {"kind": "field_delta", "field": "reasoning", "text": "two and"}]
assert s.feed({"kind": "thinking", "text": "two"}) == [{"kind": "field_delta", "field": "reasoning", "text": " two"}]
assert s.feed({"kind": "text", "text": "<answer>\n4"}) == [
    {"kind": "field_started", "field": "answer"}, {"kind": "field_delta", "field": "answer", "text": "4"}]
assert s.feed("\n</answer>") == []
assert s.finish().values == {"answer": 4, "reasoning": "two and two"}
```

## 4. A refusal at `finish`

`feed` never refuses on content. `finish` raises what `parse` would.
Events emitted before the refusal are observations, not a result.

```python
s = plan.stream()
seen = s.feed("<title>\nDune\n</title>\n<year>\nlater\n</year>")
assert [e["kind"] for e in seen] == ["field_started", "field_delta", "field_started", "field_delta"]
try:
    s.finish()
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "parse-value" and "later" in r.hint

s = plan.stream()
s.feed("<title>\nDune\n</title>")
try:
    s.finish()
except lmcc.Refusal as r:
    assert r.code == "parse-missing-fields" and r.partial == {"title": "Dune"}
```

## 5. When a routing buffers

```python
regex = lmcc.Strategy(visible=False, routings=[
    {"from": "text", "pattern": "THOUGHT: ([^\\n]*)\\n", "to": "@role", "consume": True}])
p3 = solve.bind(lmcc.adapter(messages=adapter.template, strategies={"reasoning": regex},
                             extensions={"pattern/legacy-re2": "0.1.0"}))
assert p3.describe()["streaming"] == {
    "mode": "buffered",
    "lens": {"mode": "buffered", "reason": "a consuming pattern routing can revise lens text"},
    "routings": [{"field": "reasoning", "from": "text", "mode": "buffered",
                  "reason": "pattern routing waits for EOF"}],
    "field_done": "finish"}
s = p3.stream()
assert s.feed("THOUGHT: hm\n<answer>\n4\n</answer>") == []
assert s.finish().values == {"answer": 4, "reasoning": "hm"}
```

A `pattern` routing is not core: the adapter must declare which
dialect the string is in (`extensions`, kernel §10). `pattern/legacy-re2`
is the host's own regex engine with `.` matching newlines and group 1 as
the capture — exactly what kernel 0.2 did. Without the declaration, bind
refuses `extension-undeclared`; on a host that binds no regex at all it
refuses `extension-unsupported`. Both fire before anything is sent, and
`p3.describe()["extensions"]` shows what resolved.

## What can refuse here

| code | when |
|---|---|
| `response-malformed` | at `feed`: a delta is neither text nor a part with a string `kind` |
| `parse-value` | at `finish`: a section's text is not a valid scalar |
| `parse-missing-fields` | at `finish`: a section is absent; `partial` carries the raw sections found |
| `parse-ambiguous` | at `finish`: an anchor, close, or tail occurs twice |
| `format-read-error`, `lens-parse-error` | at `finish`: a format's `read` raised; a vocabulary lens cannot read the document |

`feed` after `finish`, or `finish` twice, is host API misuse, not a
`Refusal`. Codes: [errors.md](../../contract/spec/errors.md). The
refinement law: kernel.md §8.

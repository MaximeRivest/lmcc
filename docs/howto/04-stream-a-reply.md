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
    "mode": "incremental", "reader": {"mode": "incremental"}, "find": [], "field_done": "finish",
    "repairs": {"mode": "forgiving",
                "reason": "from the first misspelled marker the rest of the reply waits for finish"}}
```

`incremental`: field text is released as it arrives. `buffered`: it
waits for EOF, and the reason is stated. `repairs` says what a misspelled
marker does to streaming: a reply written as the template says streams
as it arrives; from a slip such as `<Answer>` on, the rest waits for
`finish`, where it is repaired ([how-to 14](14-read-imperfect-replies.md)).

## 2. Feed text deltas, read the events

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
    reasoning: lmcc.Purpose["reasoning", str]
    answer: int

@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve."""

native = lmcc.Transport(requires=["native_reasoning"], in_template=False,
                       find=[{"from": "part:thinking", "to": "@purpose"}])
p2 = solve.bind(lmcc.adapter(messages=adapter.template, transports={"reasoning": native}),
                capabilities={"native_reasoning": True})
s = p2.stream()
assert s.feed({"type": "thinking", "text": "two and "}) == [
    {"kind": "field_started", "field": "reasoning"},
    {"kind": "field_delta", "field": "reasoning", "text": "two and"}]
assert s.feed({"type": "thinking", "text": "two"}) == [{"kind": "field_delta", "field": "reasoning", "text": " two"}]
assert s.feed({"type": "text", "text": "<answer>\n4"}) == [
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

## 5. When a find rule buffers

```python
regex = lmcc.Transport(in_template=False, find=[
    {"from": "text", "pattern": "THOUGHT: ([^\\n]*)\\n", "to": "@purpose", "remove": True}])
p3 = solve.bind(lmcc.adapter(messages=adapter.template, transports={"reasoning": regex}))
assert p3.describe()["extensions"] == {
    "pattern/legacy-re2": {"needs": "0.1.0", "provides": "0.1.0", "binding": "python:re"}}
assert p3.describe()["streaming"] == {
    "mode": "buffered",
    "reader": {"mode": "buffered", "reason": "a removing pattern find rule can revise the reader's text"},
    "find": [{"field": "reasoning", "from": "text", "mode": "buffered",
                  "reason": "a pattern find rule waits for EOF"}],
    "field_done": "finish",
    "repairs": {"mode": "forgiving",
                "reason": "from the first misspelled marker the rest of the reply waits for finish"}}
s = p3.stream()
assert s.feed("THOUGHT: hm\n<answer>\n4\n</answer>") == []
assert s.finish().values == {"answer": 4, "reasoning": "hm"}
```

A `pattern` find rule is not core: the artifact declares which dialect
the string is in (`extensions`, kernel §10), and the constructor writes
the default tier for you — `pattern/legacy-re2`, the host's own regex
engine with `.` matching newlines and group 1 as the capture, exactly
what kernel 0.2 did. A loaded artifact without the line refuses
`extension-undeclared`; a host that binds no regex at all refuses
`extension-unsupported`. Both fire before anything is sent.

## What can refuse here

| code | when |
|---|---|
| `response-malformed` | at `feed`: a delta is neither text nor a part with a string `kind` |
| `parse-value` | at `finish`: a section's text is not a valid scalar |
| `parse-missing-fields` | at `finish`: a section is absent; `partial` carries the raw sections found |
| `parse-ambiguous` | at `finish`: an anchor, close, or tail occurs twice |
| `format-read-error`, `reader-error` | at `finish`: a format's `read` raised; a vocabulary reader cannot read the document |

`feed` after `finish`, or `finish` twice, is host API misuse, not a
`Refusal`. Codes: [errors.md](../../contract/spec/errors.md). The
refinement law: kernel.md §8.

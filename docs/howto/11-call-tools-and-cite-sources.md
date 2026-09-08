# Call tools and cite sources — one program, native or text

**Goal.** Write one function that may call a tool and one that cites
its sources. Run each on a model with native support *and* on a plain
instruct model, changing nothing in the program. Along the way, meet
the five kernel mechanics that make this honest: a **call turn**
(`suffices`), a placement's own spelling (`via`), spelling the past
(`turns`) with its **probe**, the **whole-reply** pattern, and how
placed text joins a message.

Every block below runs as-is (`python/tests/test_docs_howto.py`); no
network is touched — the model's replies are written out by hand so you
can see exactly what lmcc reads. The live version, against real
providers, is `python/integration/lm15_tools_citations.py`.

## 1. The program

Two roles from the vocabulary: `tools` (an **input**: what the model may
call) and `tools.calls` (an **output**: what it asked for). The value
types are the std pack's — they are lm15's shapes with Python names, and
formats resolve by *type*, so `tools` and `calls` must be different
types.

```python
import dataclasses

import lmcc
import lmcc_std
from lmcc_std.tools import Tool, ToolCall

registry = lmcc.Registry()
lmcc_std.install(registry)

@dataclasses.dataclass
class Out:
    calls: lmcc.Role["tools.calls", list[ToolCall]]
    answer: str

@lmcc.fn
def ask(question: str, tools: lmcc.Role["tools", list[Tool]]) -> Out:
    """Answer the question, using a tool when needed."""

weather = Tool("get_weather", "Weather for a city.",
               {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})
```

## 2. One adapter, two strategies, chosen by declared facts

The template puts `history` *after* the user's question: in a tool loop
the conversation continues after the user's turn, and the model should
see the question, its own call, the result — in that order.

```python
template = [
    lmcc.system("{instruction}\nReply with exactly one line:\nAnswer: {answer}"),
    lmcc.user("{question}"),
    lmcc.history(),
]
tools_auto = lmcc.Strategy(choose=[
    {"when": {"capability": "native_function_calling"}, "use": lmcc_std.tools.native_tools({})},
    {"else": lmcc_std.tools.fenced_tools({})},
])
adapter = lmcc.adapter(messages=template, strategies={"tools": tools_auto})

native = ask.bind(adapter, capabilities={"native_function_calling": True}, registry=registry)
fenced = ask.bind(adapter, capabilities={"instruct": True}, registry=registry)

assert native.describe()["hidden"] == fenced.describe()["hidden"] == ["tools", "calls"]
```

Both plans hide `tools` and `calls` from the template: those fields
travel by strategy, not by slot.

## 3. Where the tools go — `via`, a placement's own spelling

Same field, same type `list[Tool]`. On the native plan it becomes an
lm15 `function` tool in `Request.tools`; on the fenced plan it becomes a
line of text in the system prompt.

```python
rn = native.render(question="Weather in Paris?", tools=[weather])
rf = fenced.render(question="Weather in Paris?", tools=[weather])

assert rn.patch["tools"] == [{"type": "function", "name": "get_weather", "description": "Weather for a city.",
                              "parameters": weather.parameters}]
assert rf.patch == {}
assert rf.system.endswith(
    "and nothing else; you will be given the result and asked again.\n\n"
    '- get_weather({"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}): Weather for a city.')
```

Formats resolve by type (kernel §5), and one type cannot have two
formats in one artifact. So the fenced strategy says, for its own
placement, *spell this through `tool_catalog` instead*:

```python
assert lmcc_std.tools.fenced_tools({}).to_dict()["placement"] == {"@role": "message:system"}
assert lmcc_std.tools.fenced_tools({}).to_dict()["via"] == {"@role": "tool_catalog"}
```

`via` is the one exception to format-by-type, scoped to placements —
how a placed value is spelled is inseparable from where it is placed.
Notice the blank line before `- get_weather`: placed text joins a
message after a blank line, exactly like a strategy's fragment does.

## 4. Reading the reply — a call turn is a reply, not an error

A model that calls a tool does not write `Answer:`. The routing that
reads calls declares `suffices: true`: a capture on it completes the
reply, and outputs the lens cannot find are omitted, never refused.

```python
assert native.describe()["routings"] == [{"field": "calls", "from": "channel:tool_call", "suffices": True}]

call_turn = {"role": "assistant", "parts": [
    {"type": "tool_call", "id": "call_9", "name": "get_weather", "input": {"city": "Paris"}}]}
assert native.parse(call_turn) == {"calls": [ToolCall("call_9", "get_weather", {"city": "Paris"})]}
assert native.parse("Answer: Sunny.") == {"answer": "Sunny.", "calls": []}

FENCE = "`" * 3                     # this guide's own code fences would end here, so build the model's from parts
assert fenced.parse(FENCE + 'tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n' + FENCE) == {
    "calls": [ToolCall("call_1", "get_weather", {"city": "Paris"})]}
```

The fenced call has an *assigned* id (`call_1`, in reply order): the
model gave none, and the result you send back must name one. A reply
with neither a call nor an answer is still a refusal — nothing was
captured, so `suffices` did not apply:

```python
try:
    native.parse("I have no idea.")
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "parse-missing-fields"
```

## 5. The second call — `turns` spell the past

You run the tool. The next prompt must show the call and its result.
History items are lm15 messages, verbatim: on the native plan they pass
through untouched; on the fenced plan the strategy's `turns` spell the
protocol parts as text and the `tool` message becomes a `user` one.

```python
history = [
    {"role": "assistant", "parts": [{"type": "tool_call", "id": "call_9", "name": "get_weather", "input": {"city": "Paris"}}]},
    {"role": "tool", "parts": [{"type": "tool_result", "id": "call_9", "name": "get_weather",
                                "content": [{"type": "text", "text": "Sunny, 22C"}]}]},
]
n = native.render(question="Weather in Paris?", tools=[weather], history=history).messages
assert [m["role"] for m in n] == ["user", "assistant", "tool"] and n[1]["parts"][0]["type"] == "tool_call"

f = fenced.render(question="Weather in Paris?", tools=[weather], history=history).messages
assert f[1] == {"role": "assistant", "parts": [{"type": "text",
                "text": FENCE + 'tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n' + FENCE}]}
assert f[2] == {"role": "user", "parts": [{"type": "text", "text": "Result of get_weather (call_9):\nSunny, 22C"}]}
```

The spelling of a *past* call and the routing that reads a *new* one
are two copies of one contract, and copies drift. So at bind the kernel
runs a **probe**: it spells a fake call through `turns.call`, reads it
back through the strategy's own routing and format, and refuses if the
two disagree — the "template is the lens" law at strategy level.

```python
drifted = lmcc_std.tools.fenced_tools({})
drifted.turns["call"] = "CALL {name} WITH {input}"      # the fenced routing cannot read this
try:
    ask.bind(lmcc.adapter(messages=template, strategies={"tools": drifted}),
             capabilities={"instruct": True}, registry=registry)
    raise AssertionError("should have refused")
except lmcc.Refusal as r:
    assert r.code == "turns-drift"
    assert r.fix == {"action": "edit-entry", "path": "strategies['tools'].turns"}
```

## 6. Citations: numbered sources, or the provider's own

Two programs, because they mean different things: one cites *sources
you supply* (spelled into the prompt, markers read back); one cites
*what the provider found* (a search tool the strategy asks for,
`citation` parts read back). lm15 has no per-document citation flag
yet, so supplied sources have no native tier — that is stated, not
papered over.

```python
from lmcc_std.tools import Citation, Source

@dataclasses.dataclass
class Grounded:
    answer: str
    citations: lmcc.Role["citations", list[Citation]]

@lmcc.fn
def grounded(question: str, sources: lmcc.Role["citations.sources", list[Source]]) -> Grounded:
    """Answer from the sources only."""

inline = grounded.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\nAnswer: {answer}"), lmcc.user("{question}")],
                                    strategies={"citations": "inline_citations"}),
                       capabilities={"instruct": True}, registry=registry)
r = inline.render(question="When was the tower built?",
                  sources=[Source("Completed in 1889.", title="Encyclopedia"), Source("330 m tall.", title="Almanac")])
assert r.messages[0]["parts"][0]["text"] == (
    "When was the tower built?\n\n[1] Encyclopedia: Completed in 1889.\n[2] Almanac: 330 m tall.")
v = inline.parse("Answer: In 1889 [1], and it is 330 m [2] [1] [see].")
assert v["citations"] == [Citation(source=1), Citation(source=2)]        # distinct, in order; prose skipped
assert v["answer"] == "In 1889 [1], and it is 330 m [2] [1] [see]."      # markers stay in the prose
```

## 7. The whole-reply pattern

Provider search mode answers in prose and ignores reply patterns. "The
whole reply is the answer" — the simplest adapter there is — needed a
rule: one visible output, a bare slot, nothing after it in its message.

```python
@lmcc.fn
def searched(question: str) -> Grounded:
    """Answer in one sentence, citing a web source."""

native_cite = searched.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\n{answer}"), lmcc.user("{question}")],
                                         strategies={"citations": "native_citations"}),
                            capabilities={"native_citations": True}, registry=registry)
assert native_cite.render(question="q").patch == {"tools": [{"type": "builtin", "name": "web_search"}]}
assert native_cite.describe()["lens"]["anchors"] == [["answer", "", ""]]

reply = {"role": "assistant", "parts": [
    {"type": "text", "text": "The 2028 Games will be held in Los Angeles.  "},
    {"type": "citation", "url": "https://example.org/la2028", "title": "LA 2028", "text": "Los Angeles"}]}
assert native_cite.parse(reply) == {
    "answer": "The 2028 Games will be held in Los Angeles.",
    "citations": [Citation(url="https://example.org/la2028", title="LA 2028", text="Los Angeles")]}
```

The rule is deliberately narrow. Anything else without an anchor still
refuses — including a slot with prose after it, which is *not* "the
whole reply":

```python
for bad in ("{instruction}\n<answer>\n{answer}\n</answer>",     # prose after the slot
            "{instruction}\n{% for f in outputs %}{f.value}\n{% endfor %}"):   # a loop, no anchor
    try:
        lmcc.adapter(messages=[lmcc.system(bad), lmcc.user("{question}")]).bind(
            lmcc.signature("x", inputs={"question": str}, outputs={"answer": str}))
        raise AssertionError("should have refused")
    except lmcc.Refusal as r:
        assert r.code == "not-lensable"
```

## 8. The loop is yours

lmcc lays out one call and reads one reply. Running the tool and
calling again is the caller's — with lm15 it is four lines:

```python
# request  = lmcc_lm15.request(plan.render(question=q, tools=[weather], history=history), model=...)
# response = lm.complete(request)
# values   = lmcc_lm15.parse(plan, response)
# if values.get("calls"): run them, then
#     history += [lmcc_lm15.message_to_history(response.message),
#                 lmcc_lm15.message_to_history(lm15.Message.tool(call.id, result))]
```

## What can refuse here

| code | when |
|---|---|
| `capability-missing` | `native_tools` on a model that does not declare `native_function_calling` |
| `turns-drift` | a `turns.call` spelling the strategy's own routing/format cannot read back |
| `unknown-format` | `via` names a format the registry does not have |
| `format-read-error` | a fenced call that is not `{"name", "input"}` JSON |
| `parse-missing-fields` | no answer *and* no call — `suffices` needs a capture |
| `not-lensable` | an anchorless slot that is not the whole reply |

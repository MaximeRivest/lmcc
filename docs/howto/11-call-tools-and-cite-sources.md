# Call tools and cite sources — one program, native or text

**Goal.** Write one function that may call a tool and one that cites
its sources. Run each on a model with native support *and* on a plain
instruct model, changing nothing in the program. Along the way, meet
the five kernel mechanics that make this honest: a **call turn**
(`suffices`), a placement's own spelling (`via`), spelling the past
(`turns`) with its **probe**, the **whole-reply** pattern, and how
placed text joins a message.

This guide is a notebook: run the cells in order and read what they
print. No network is touched — the model's replies are written by hand
so you see exactly what lmcc reads. The live version, against real
providers, is `python/integration/lm15_tools_citations.py`.

## 0. Setup

```python
import dataclasses, json

import lmcc, lmcc_std
from lmcc_std.tools import Tool, ToolCall, Citation, Source

registry = lmcc.Registry()
lmcc_std.install(registry)

def show(x):
    """Pretty-print plain data (parts, patches, values); dataclasses as dicts."""
    print(json.dumps(x, indent=2, default=lambda o: dataclasses.asdict(o) if dataclasses.is_dataclass(o) else str(o)))

def refuses(thunk):
    """Run something that should refuse; print the refusal like a REPL would."""
    try:
        thunk()
        print("(did not refuse)")
    except lmcc.Refusal as r:
        print(f"Refusal[{r.code}]  fix={r.fix}\n  {r.hint[:120]}")

print("std vocabulary:", *sorted(registry.describe()["strategies"]))
```

## 1. The program

Two roles from the vocabulary: `tools` (an **input**: what the model may
call) and `tools.calls` (an **output**: what it asked for). The value
types are the std pack's — lm15's shapes with Python names. Formats
resolve by *type*, so `tools` and `calls` must be different types.

```python
@dataclasses.dataclass
class Out:
    calls: lmcc.Role["tools.calls", list[ToolCall]]
    answer: str

@lmcc.fn
def ask(question: str, tools: lmcc.Role["tools", list[Tool]]) -> Out:
    """Answer the question, using a tool when needed."""

weather = Tool("get_weather", "Weather for a city.",
               {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})

for f in ask.signature.fields:
    print(f"{f.direction:<6} {f.name:<9} role={f.role:<12} type={f.type}")
```

## 2. One adapter, two strategies, chosen by declared facts

The template puts `history` *after* the user's question: in a tool loop
the conversation continues after the user's turn — question, the
model's call, the result, in that order.

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

for name, plan in ("native", native), ("fenced", fenced):
    d = plan.describe()
    print(f"{name}: hidden={d['hidden']}  routings={d['routings']}  placements={d['placements']}")
```

Both plans hide `tools` and `calls` from the template: those fields
travel by strategy, not by slot. Same routing target, different source.

## 3. Where the tools go — `via`, a placement's own spelling

Same field, same type `list[Tool]`. Render both and compare where the
tool ended up.

```python
rn = native.render(question="Weather in Paris?", tools=[weather])
rf = fenced.render(question="Weather in Paris?", tools=[weather])

print("native → request.tools:"); show(rn.patch)
print("\nfenced → request.tools:", rf.patch)
print("fenced → end of the system prompt:\n" + rf.system[-260:])
```

Formats resolve by type (kernel §5), and one type cannot have two
formats in one artifact. So the fenced strategy says, for its own
placement, *spell this through `tool_catalog` instead*:

```python
show({k: v for k, v in lmcc_std.tools.fenced_tools({}).to_dict().items() if k in ("placement", "via")})
```

`via` is the one exception to format-by-type, scoped to placements —
how a placed value is spelled is inseparable from where it is placed.
Notice the blank line before `- get_weather` above: placed text joins a
message after a blank line, exactly like a strategy's fragment does.

## 4. Reading the reply — a call turn is a reply, not an error

A model that calls a tool does not write `Answer:`. The routing that
reads calls declares `suffices: true`: a capture on it completes the
reply, and outputs the lens cannot find are omitted, never refused.
Three replies, three outcomes:

```python
call_turn = {"role": "assistant", "parts": [
    {"type": "tool_call", "id": "call_9", "name": "get_weather", "input": {"city": "Paris"}}]}

print("call turn   →", native.parse(call_turn))
print("answer turn →", native.parse("Answer: Sunny."))
print("neither     →", end=" "); refuses(lambda: native.parse("I have no idea."))
```

The fenced tier reads the same thing from text. Its call has an
*assigned* id (`call_1`, in reply order): the model gave none, and the
result you send back must name one.

```python
FENCE = "`" * 3   # this guide's own code fences would end here, so build the model's from parts
fenced_reply = FENCE + 'tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n' + FENCE
print(fenced_reply)
print("→", fenced.parse(fenced_reply))
```

## 5. The second call — `turns` spell the past

You run the tool. The next prompt must show the call and its result.
History items are lm15 messages, verbatim. Watch what each plan does
with the same two messages:

```python
history = [
    {"role": "assistant", "parts": [{"type": "tool_call", "id": "call_9", "name": "get_weather", "input": {"city": "Paris"}}]},
    {"role": "tool", "parts": [{"type": "tool_result", "id": "call_9", "name": "get_weather",
                                "content": [{"type": "text", "text": "Sunny, 22C"}]}]},
]
for name, plan in ("native", native), ("fenced", fenced):
    print(f"\n{name}:")
    for m in plan.render(question="Weather in Paris?", tools=[weather], history=history).messages:
        p = m["parts"][0]
        print(f"  {m['role']:<9} {p['type']:<10} {p.get('text', p.get('name'))!r}")
```

Native passes the protocol parts through untouched. The fenced strategy
has `turns` — a spelling for a past call and a past result — and the
`tool` message becomes a `user` one:

```python
show(lmcc_std.tools.fenced_tools({}).turns)
```

The spelling of a *past* call and the routing that reads a *new* one
are two copies of one contract, and copies drift. So at bind the kernel
runs a **probe**: it spells a fake call through `turns.call`, reads it
back through the strategy's own routing and format, and refuses if the
two disagree — the "template is the lens" law at strategy level.

```python
drifted = lmcc_std.tools.fenced_tools({})
drifted.turns["call"] = "CALL {name} WITH {input}"      # the fenced routing cannot read this back

refuses(lambda: ask.bind(lmcc.adapter(messages=template, strategies={"tools": drifted}),
                         capabilities={"instruct": True}, registry=registry))
```

## 6. Citations: numbered sources, or the provider's own

Two programs, because they mean different things: one cites *sources
you supply* (spelled into the prompt, markers read back); one cites
*what the provider found* (a search tool the strategy asks for,
`citation` parts read back). lm15 has no per-document citation flag
yet, so supplied sources have no native tier — stated, not papered over.

```python
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
print(r.system, "\n---")
print(r.messages[0]["parts"][0]["text"])
```

The markers stay in the prose (`consume: false`); `citations` reads them —
distinct, in order, bracketed prose skipped:

```python
show(inline.parse("Answer: In 1889 [1], and it is 330 m [2] [1] [see]."))
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

print("asks the provider for:", native_cite.render(question="q").patch)
print("lens anchors:", native_cite.describe()["lens"]["anchors"], " skeleton:", native_cite.skeleton())

reply = {"role": "assistant", "parts": [
    {"type": "text", "text": "The 2028 Games will be held in Los Angeles.  "},
    {"type": "citation", "url": "https://example.org/la2028", "title": "LA 2028", "text": "Los Angeles"}]}
show(native_cite.parse(reply))
```

The rule is deliberately narrow. Anything else without an anchor still
refuses — including a slot with prose after it, which is *not* "the
whole reply":

```python
sig = lmcc.signature("x", inputs={"question": str}, outputs={"answer": str})
for bad in ("{instruction}\n<answer>\n{answer}\n</answer>",                    # prose after the slot
            "{instruction}\n{% for f in outputs %}{f.value}\n{% endfor %}"):   # a loop, no anchor
    print(repr(bad), "→", end=" ")
    refuses(lambda: lmcc.adapter(messages=[lmcc.system(bad), lmcc.user("{question}")]).bind(sig))
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
print("see python/integration/lm15_tools_citations.py for the live loop on two providers")
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

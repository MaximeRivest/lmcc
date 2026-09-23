# Call tools and cite sources — one program, native or text

**Goal.** Write one function that may call a tool and one that cites its sources. Run each on a model with native support *and* on a plain instruct model, changing nothing in the program. Along the way, meet the five kernel mechanics that make this honest: a **call turn** (`complete_reply`), a put's own spelling (`written_as`), spelling the past (`turns`) with its **probe**, the **whole-reply** pattern, and how placed text joins a message.

This guide is a notebook: run the cells in order and read what they print. No network is touched — the model's replies are written by hand so you see exactly what lmcc reads. The live version, against real providers, is `python/integration/lm15_tools_citations.py`.

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

print("std vocabulary:", *sorted(registry.describe()["transports"]))
```

```output
std vocabulary: fenced_tools heredoc_tools inline_citations native_citations native_reasoning native_tools prefix_cot reasoning_tags
```

## 1. The program

Two purposes from the vocabulary: `tools` (an **input**: what the model may call) and `tools.calls` (an **output**: what it asked for). The value types are the std pack's — lm15's shapes with Python names. Formats resolve by *type*, so `tools` and `calls` must be different types.

```python
@dataclasses.dataclass
class Out:
    calls: lmcc.Purpose["tools.calls", list[ToolCall]]
    answer: str

@lmcc.fn
def ask(question: str, tools: lmcc.Purpose["tools", list[Tool]]) -> Out:
    """Answer the question, using a tool when needed."""

weather = Tool("get_weather", "Weather for a city.",
               {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})

for f in ask.signature.fields:
    print(f"{f.direction:<6} {f.name:<9} purpose={f.purpose:<12} type={f.type}")
```

```output
input  question  purpose=plain        type=str
input  tools     purpose=tools        type=list[Tool]
output calls     purpose=tools.calls  type=list[ToolCall]
output answer    purpose=plain        type=str
```

## 2. One adapter, two transports, chosen by declared facts

`lmcc.turns()` marks where earlier turns go: before the question. The call in progress needs no marker — its own steps (the model's call, the tool's result) follow the question, in that order.

```python
template = [
    lmcc.system("{instruction}\nReply with exactly one line:\nAnswer: {answer}"),
    lmcc.turns(),
    lmcc.user("{question}"),
]
tools_auto = lmcc.Transport(choose=[
    {"when": {"capability": "native_function_calling"}, "use": lmcc_std.tools.native_tools({})},
    {"else": lmcc_std.tools.fenced_tools({})},
])
adapter = lmcc.adapter(messages=template, transports={"tools": tools_auto})

native = ask.bind(adapter, capabilities={"native_function_calling": True}, registry=registry)
fenced = ask.bind(adapter, capabilities={"instruct": True}, registry=registry)

for name, plan in ("native", native), ("fenced", fenced):
    d = plan.describe()
    print(f"{name}: hidden={d['hidden']}  find={d['find']}  puts={d['puts']}")
```

```output
native: hidden=['tools', 'calls']  find=[{'field': 'calls', 'from': 'part:tool_call', 'complete_reply': True}]  puts=[{'field': 'tools', 'at': 'request.tools'}]
fenced: hidden=['tools', 'calls']  find=[{'field': 'calls', 'from': 'text', 'between': ['```tool\n', '\n```'], 'remove': True, 'complete_reply': True}]  puts=[{'field': 'tools', 'at': 'message:system'}]
```

Both plans hide `tools` and `calls` from the template: those fields travel by transport, not by slot. Same find rule target, different source.

## 3. Where the tools go — `written_as`, a put's own spelling

Same field, same type `list[Tool]`. Render both and compare where the tool ended up.

```python
rn = native.render(question="Weather in Paris?", tools=[weather])
rf = fenced.render(question="Weather in Paris?", tools=[weather])

print("native → request.tools:"); show(rn.request_settings)
print("\nfenced → request.tools:", rf.request_settings)
print("fenced → end of the system prompt:\n" + rf.system[-260:])
```

```output
native → request.tools:
{
  "tools": [
    {
      "type": "function",
      "name": "get_weather",
      "description": "Weather for a city.",
      "parameters": {
        "type": "object",
        "properties": {
          "city": {
            "type": "string"
          }
        },
        "required": [
          "city"
        ]
      }
    }
  ]
}

fenced → request.tools: {}
fenced → end of the system prompt:
h exactly one fenced block:
 ```tool
{"name": "<tool>", "input": {...}}
 ```
and nothing else; you will be given the result and asked again.

- get_weather({"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}): Weather for a city.
```
and nothing else; you will be given the result and asked again.

- get_weather({"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}): Weather for a city.
```

Formats resolve by type (kernel §5), and one type cannot have two
formats in one artifact. So the fenced transport says, for its own
put, *spell this through `tool_catalog` instead*:

```python
show({k: v for k, v in lmcc_std.tools.fenced_tools({}).to_dict().items() if k in ("put", "written_as")})
```

```output
{
  "put": {
    "@purpose": "message:system"
  },
  "written_as": {
    "@purpose": "tool_catalog"
  }
}
```

`written_as` is the one exception to format-by-type, scoped to `put` — how a value is spelled is inseparable from where it is put. Notice the blank line before `- get_weather` above: text that is put into a message joins it after a blank line, exactly like a transport's `tell` text does.

## 4. Reading the reply — a call turn is a reply, not an error

A model that calls a tool does not write `Answer:`. The rule that reads calls declares `complete_reply: true`: a capture on it completes the reply, and outputs the reader cannot find are omitted, never refused. Three replies, three outcomes:

```python
call_turn = {"role": "assistant", "parts": [
    {"type": "tool_call", "id": "call_9", "name": "get_weather", "input": {"city": "Paris"}}]}

print("call turn   →", native.parse(call_turn))
print("answer turn →", native.parse("Answer: Sunny."))
print("neither     →", end=" "); refuses(lambda: native.parse("I have no idea."))
```

```output
call turn   → {'calls': [ToolCall(id='call_9', name='get_weather', input={'city': 'Paris'})]}
answer turn → {'answer': 'Sunny.', 'calls': []}
neither     → Refusal[parse-missing-fields]  fix=None
  reply is missing pattern section(s): 'answer'
```

The fenced tier reads the same thing from text. Its call has an *assigned* id (`call_1`, in reply order): the model gave none, and the result you send back must name one.

```python
FENCE = "`" * 3   # this guide's own code fences would end here, so build the model's from parts
fenced_reply = FENCE + 'tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n' + FENCE
print(fenced_reply)
print("→", fenced.parse(fenced_reply))
```

```output
 ```tool
{"name": "get_weather", "input": {"city": "Paris"}}
 ```
→ {'calls': [ToolCall(id='call_1', name='get_weather', input={'city': 'Paris'})]}
```
→ {'calls': [ToolCall(id='call_1', name='get_weather', input={'city': 'Paris'})]}
```

## 5. The second call — one turn, two steps

You run the tool. The next prompt must show the call and its result.
Both are **steps of one turn**: `rendered.step(reply)` records the
model's reply (its values and the message exactly as it came), and
`turn.tool(id, output)` records the result. Record once — here from a
native reply — and give the *same* turn to each plan:

```python
turn = native.turn(question="Weather in Paris?", tools=[weather])
rendered = native.render(turn)
turn = rendered.step({"role": "assistant", "parts": [
    {"type": "tool_call", "id": "call_9", "name": "get_weather", "input": {"city": "Paris"}}]})
turn = turn.tool("call_9", "Sunny, 22C")

for name, plan in ("native", native), ("fenced", fenced):
    print(f"\n{name}:")
    for m in plan.render(turn).messages:
        p = m["parts"][0]
        print(f"  {m['role']:<9} {p['type']:<10} {p.get('text', p.get('name'))!r}")
```

```output
native:
  user      text       'Weather in Paris?'
  assistant tool_call  'get_weather'
  tool      tool_result 'get_weather'

fenced:
  user      text       'Weather in Paris?'
  assistant text       '```tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n```'
  user      text       'Result of get_weather (call_9):\nSunny, 22C'
```

The native plan reads the recorded reply back into the same values, so it sends it exactly as it came. The fenced plan cannot read a native part, so it writes the step again from its values, with its `turns` — a spelling for a past call and a past result — and the result becomes a `user` message:

```python
show(lmcc_std.tools.fenced_tools({}).spelling)
```

```output
{
  "call": "```tool\n{\"name\": \"{name}\", \"input\": {input}}\n```",
  "result": "Result of {name} ({id}):\n{output}"
}
```

The spelling of a *past* call and the find rule that reads a *new* one are two copies of one contract, and copies drift. So at bind the kernel runs a **probe**: it spells a fake call through `spelling.call`, reads it back through the transport's own find rule and format, and refuses if the two disagree — the "template is the reader" law at transport level.

```python
drifted = lmcc_std.tools.fenced_tools({})
drifted.spelling["call"] = "CALL {name} WITH {input}"      # the fenced rule cannot read this back

refuses(lambda: ask.bind(lmcc.adapter(messages=template, transports={"tools": drifted}),
                         capabilities={"instruct": True}, registry=registry))
```

```output
Refusal[spelling-drift]  fix={'action': 'edit-entry', 'path': "transports['tools'].spelling"}
  purpose 'tools': transport '(inline)': spelling.call spells a call as 'CALL probe WITH {"probe": true}', and its own fin
```

## 6. Citations: numbered sources, or the provider's own

Two programs, because they mean different things: one cites *sources you supply* (spelled into the prompt, markers read back); one cites *what the provider found* (a search tool the transport asks for, `citation` parts read back). lm15 has no per-document citation flag yet, so supplied sources have no native tier — stated, not papered over.

```python
@dataclasses.dataclass
class Grounded:
    answer: str
    citations: lmcc.Purpose["citations", list[Citation]]

@lmcc.fn
def grounded(question: str, sources: lmcc.Purpose["citations.sources", list[Source]]) -> Grounded:
    """Answer from the sources only."""

inline = grounded.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\nAnswer: {answer}"), lmcc.user("{question}")],
                                    transports={"citations": "inline_citations"}),
                       capabilities={"instruct": True}, registry=registry)

r = inline.render(question="When was the tower built?",
                  sources=[Source("Completed in 1889.", title="Encyclopedia"), Source("330 m tall.", title="Almanac")])
print(r.system, "\n---")
print(r.messages[0]["parts"][0]["text"])
```

```output
Answer from the sources only.
Answer: ...

Cite the numbered sources inline as [n] after each claim they support. 
---
When was the tower built?

[1] Encyclopedia: Completed in 1889.
[2] Almanac: 330 m tall.
```

The markers stay in the prose (`remove: false`); `citations` reads them — distinct, in order, bracketed prose skipped:

```python
show(inline.parse("Answer: In 1889 [1], and it is 330 m [2] [1] [see]."))
```

```output
{
  "answer": "In 1889 [1], and it is 330 m [2] [1] [see].",
  "citations": [
    {
      "url": null,
      "title": null,
      "text": null,
      "source": 1
    },
    {
      "url": null,
      "title": null,
      "text": null,
      "source": 2
    }
  ]
}
```

## 7. The whole-reply pattern

Provider search mode answers in prose and ignores reply patterns. "The whole reply is the answer" — the simplest adapter there is — needed a rule: one visible output, a bare slot, nothing after it in its message.

```python
@lmcc.fn
def searched(question: str) -> Grounded:
    """Answer in one sentence, citing a web source."""

native_cite = searched.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\n{answer}"), lmcc.user("{question}")],
                                         transports={"citations": "native_citations"}),
                            capabilities={"native_citations": True}, registry=registry)

print("asks the provider for:", native_cite.render(question="q").request_settings)
print("reader anchors:", native_cite.describe()["reader"]["anchors"], " skeleton:", native_cite.skeleton())

reply = {"role": "assistant", "parts": [
    {"type": "text", "text": "The 2028 Games will be held in Los Angeles.  "},
    {"type": "citation", "url": "https://example.org/la2028", "title": "LA 2028", "text": "Los Angeles"}]}
show(native_cite.parse(reply))
```

```output
asks the provider for: {'tools': [{'type': 'builtin', 'name': 'web_search'}]}
reader anchors: [['answer', '', '']]  skeleton: {'prefill': '', 'stops': []}
{
  "answer": "The 2028 Games will be held in Los Angeles.",
  "citations": [
    {
      "url": "https://example.org/la2028",
      "title": "LA 2028",
      "text": "Los Angeles",
      "source": null
    }
  ]
}
```

The rule is deliberately narrow. Anything else without an anchor still refuses — including a slot with prose after it, which is *not* "the whole reply":

```python
sig = lmcc.signature("x", inputs={"question": str}, outputs={"answer": str})
for bad in ("{instruction}\n<answer>\n{answer}\n</answer>",                    # prose after the slot
            "{instruction}\n{% for f in outputs %}{f.value}\n{% endfor %}"):   # a loop, no anchor
    print(repr(bad), "→", end=" ")
    refuses(lambda: lmcc.adapter(messages=[lmcc.system(bad), lmcc.user("{question}")]).bind(sig))
```

```output
'{instruction}\n<answer>\n{answer}\n</answer>' → Refusal[not-readable]  fix={'action': 'edit-template', 'path': 'template[0]', 'field': 'answer'}
  field 'answer': no literal text before its hole — nothing anchors the parser; put the field's marker before the hole, on
'{instruction}\n{% for f in outputs %}{f.value}\n{% endfor %}' → Refusal[not-readable]  fix={'action': 'edit-template', 'path': 'template[0]', 'field': 'answer'}
  field 'answer': no literal text before its hole — nothing anchors the parser; put the field's marker before the hole
```

## 8. The loop is yours

lmcc lays out one call and reads one reply. Running the tool and calling again is the caller's — with lm15 it is a few lines:

```python
# turn = plan.turn(question=q, tools=[weather])
# while True:
#     rendered = plan.render(turn)
#     turn = lmcc_lm15.step(rendered, lm.complete(lmcc_lm15.request(rendered, model=...)))
#     calls = turn.pending_calls()
#     if not calls: break
#     for call in calls: turn = turn.tool(call.id, run(call))
# turn = turn.finish()        # one record: the question, every step, the answer
print("see python/integration/lm15_tools_citations.py for the live loop on two providers")
```

```output
see python/integration/lm15_tools_citations.py for the live loop on two providers
```

## What can refuse here

| code | when |
|---|---|
| `capability-missing` | `native_tools` on a model that does not declare `native_function_calling` |
| `spelling-drift` | a `spelling.call` spelling the transport's own find rule/format cannot read back |
| `unknown-format` | `written_as` names a format the registry does not have |
| `format-read-error` | a fenced call that is not `{"name", "input"}` JSON |
| `parse-missing-fields` | no answer *and* no call — `complete_reply` needs a capture |
| `not-readable` | an anchorless slot that is not the whole reply |

# A conversational agent with raw-code heredoc calls

Run the cells in order. This notebook uses **hand-written model replies**:
it makes no network requests and executes no generated code. It demonstrates
how a model reply becomes values, and how those values are written back into
the next model call. `./dev-venv` prepares the project notebook environment.

We will use three independent components of a reply: a conversational reply,
optional reasoning, and a request to run Python. A reply may contain more than
one component. The application, not LMCC, decides what to do with them.

## 1. Setup and the program

```python
import dataclasses
import json
import lmcc
import lmcc_std
from lmcc_std.tools import Tool, ToolCall

registry = lmcc.Registry()
lmcc_std.install(registry)

def show(value):
    print(json.dumps(value, indent=2, ensure_ascii=False,
                     default=lambda x: dataclasses.asdict(x) if dataclasses.is_dataclass(x) else str(x)))

@dataclasses.dataclass
class Reply:
    reply: str
    reasoning: lmcc.Purpose["reasoning", str]
    calls: lmcc.Purpose["tools.calls", list[ToolCall]]

@lmcc.fn
def agent(message: str, tools: lmcc.Purpose["tools", list[Tool]]) -> Reply:
    """Talk with the user and help with programming.
    You may request Python execution when useful.
    A request is not execution: wait for the result before claiming success.
    """

python_tool = Tool(
    "run_python", "Request Python execution in the application's sandbox.",
    {"type": "object", "properties": {"code": {"type": "string"}},
     "required": ["code"], "additionalProperties": False},
)
print("Kernel:", lmcc.__version__)
```

## 2. The adapter: prose plus two hidden channels

The ordinary reply is whatever remains after find rule. Reasoning is removed
from the prose, and a heredoc becomes a structured call. There is no shell
execution here: `run_python <<'PY_END'` is a literal message spelling.

```python
reasoning = lmcc.Transport(
    in_template=False,
    tell={"system": "If you include analysis, put it inside <think>...</think>."},
    find=[{"from": "text", "between": ["<think>", "</think>"],
               "to": "@purpose", "remove": True}],
    spelling={"position": "before"},   # when a past reply is written from values: reasoning first
)

adapter = lmcc.adapter(
    messages=[
        lmcc.system("{instruction}\n{reply}"),
        lmcc.turns(),
        lmcc.user("{message}"),
    ],
    formats={
        "list[Tool]": lmcc.use("function_tool"),
        "list[ToolCall]": lmcc.use("code_calls"),
    },
    transports={"reasoning": reasoning, "tools": lmcc.use("heredoc_tools")},
)
plan = agent.bind(adapter, capabilities={"instruct": True}, registry=registry)
question = "Could you calculate 6 times 7?"
rendered = plan.render(message=question, tools=[python_tool])
print(rendered.system)
print("\nUser:", rendered.messages[0]["parts"][0]["text"])
```

The reasoning transport reads `<think>` blocks; the same markers write past
reasoning back when a reply must be rebuilt from its values, and `position`
puts it before the reply. The tools transport writes the catalog as text
(`written_as: tool_catalog`). Its
`spelling.input_format` is **code_arguments**: it writes `{"code": ...}` as raw
code, without JSON quotes, escape sequences or trimming.

## 3. Three possible replies

These are example replies, not calls to a model. Watch the parsed values.
An empty `reply` is normal on a reasoning-only or tool-only turn.

```python
print("Conversation:")
show(plan.parse("Yes! I can help with that."))

print("\nReasoning only:")
show(plan.parse("<think>I should check the calculation.</think>"))

model_reply = "<think>Let's calculate.</think>\nrun_python <<'PY_END'\nprint(6 * 7)\nPY_END"
print("\nTool request:")
print(model_reply)
values = plan.parse(model_reply)
show(values)
```

## 4. One turn: the question, the call, the result, the answer

A **turn** records one call of the agent as values: its inputs, its steps
(each model reply, each tool result) and, once finished, its outputs.
`rendered.step(reply)` parses a reply and records it with the message exactly
as it came; `turn.tool(id, output)` records a result for a pending call.

Suppose the application approved the call and its sandbox returned `42`.
We **supply that result as a fixture**; this notebook does not run the code.

```python
turn = plan.turn(message=question, tools=[python_tool])
turn = plan.render(turn).step(model_reply)
call = turn.pending_calls()[0]
print("Pending:", call)
turn = turn.tool(call.id, "42")

next_request = plan.render(turn)
for message in next_request.messages:
    print(f"\n{message['role']}:")
    for part in message["parts"]:
        print(part.get("text", part))
```

You built no message by hand. The question is written once; the model's reply
is sent back exactly as it came (this plan reads it into the same values);
the result becomes a user message through the transport's `spelling.result`.

The model answers, and the turn closes. The finished turn is the conversation
so far: the next question passes it as an earlier turn.

```python
turn = plan.render(turn).step("The result is 42.").finish()
show(turn.outputs)

follow_up = plan.render(message="And 8 times 9?", tools=[python_tool], turns=[turn])
print([m["role"] for m in follow_up.messages])
```

The first turn is written before the new question, with its call and result.
Which earlier turns to pass (all, the last few, a summary) is the
application's choice; LMCC writes exactly what it is given.

## 5. Code whitespace is data

The reader uses the raw captured parts, **not** the trimmed `capture.text` view.
Here the code contains indentation, Unicode, CRLF and a trailing newline.
The envelope adds its own newline before `PY_END`; that newline is not code.

A step can also be built from values alone, for example one loaded from
storage with no recorded message. Then the plan's own writer spells it:

```python
def called(code):
    step = lmcc.ModelStep({"calls": [ToolCall("example", "run_python", {"code": code})]},
                          calls_field="calls")
    return plan.turn(message=question, tools=[python_tool]).with_step(step).tool("example", "ok")

exact_code = '    # café\r\n    print(6 * 7)\r\n'
request_with_code = plan.render(called(exact_code))
heredoc = request_with_code.messages[1]["parts"][0]["text"]
recovered_code = plan.parse(heredoc)["calls"][0].input["code"]
print("Written:", repr(heredoc))
print("Recovered:", repr(recovered_code))
print("Code preserved exactly:", recovered_code == exact_code)
```

Text call IDs are generated per reply (`call_1`, …). They are not a global
identity. The probe checks the tool name and arguments, not ID preservation.

## 6. What does the bind-time probe actually do?

Inspect the shipped transport. Its sample is a valid call to `run_python`,
not the old generic `probe({probe: true})` that a code-only reader cannot read.

```python
transport = lmcc_std.code.heredoc_tools({})
show(transport.spelling)
show(plan.describe()["turns"])

entry = adapter.dump(registry=registry)
print("Argument-writer version:", entry["versions"]["vocab"]["format/code_arguments"])
loaded = lmcc.load(entry, registry=registry)
print("Artifact round-trips:", loaded.dump(registry=registry) == entry)
```

At bind, the same writer used for past calls spells the sample call, the
transport's own find rule captures it, and the calls format reads it back.
A different name or input object means `spelling-drift`.

You can provide a different representative sample, without adding Python
code to the artifact:

```python
custom = lmcc_std.code.heredoc_tools({})
custom.spelling["probe"] = {
    "name": "run_python",
    "input": {"code": 'print({"total": 6 * 7})\n'},
}
custom_adapter = lmcc.adapter(messages=adapter.template, formats=adapter.formats,
                              transports={"reasoning": reasoning, "tools": custom})
custom_plan = agent.bind(custom_adapter, capabilities={"instruct": True}, registry=registry)
print("Custom sample accepted.")
```

Now deliberately break the writer. The failure happens at bind, without a
model request or executing the sample:

```python
def show_refusal(operation):
    try:
        operation()
        print("No refusal")
    except lmcc.Refusal as error:
        print(error.code)
        print(error.hint)
        print("Next step:", error.fix)

broken = lmcc_std.code.heredoc_tools({})
broken.spelling["call"] = "CALL {name}: {input}"
broken_adapter = lmcc.adapter(messages=adapter.template, formats=adapter.formats,
                              transports={"tools": broken, "reasoning": reasoning})
show_refusal(lambda: agent.bind(broken_adapter, capabilities={"instruct": True}, registry=registry))
```

## 7. Delimiter collisions are rejected

For this literal-delimiter transport, `PY_END` is forbidden anywhere inside
code. This is conservative: even a harmless string mentioning it is rejected.
Choose another marker in **both** the transport and the calls format if needed.

```python
show_refusal(lambda: plan.render(called("print('PY_END')")))
```

## What this does not promise

- The probe proves its **sample**, not every possible program. Regression
  tests separately cover whitespace, Unicode, empty bodies and stream splits.
- Core `between` find rule is not a strict shell-heredoc parser. Unterminated
  blocks can remain ordinary reply text. Only structured `calls` may be
  considered for execution—never raw model text.
- This shipped transport supports one configured tool. A multi-tool agent needs
  a deliberate dispatch protocol, not shell evaluation of the header.
- The application must validate, authorize and sandbox execution, associate
  results with calls, and bound the number of continuation turns.
- Reasoning-only replies may be continued by the application, but LMCC does
  not create an autonomous loop. Tool-result text is untrusted too.

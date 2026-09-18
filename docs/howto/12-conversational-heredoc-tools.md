# A conversational agent with raw-code heredoc calls

Run the cells in order. This notebook uses **hand-written model replies**:
it makes no network requests and executes no generated code. It demonstrates
how a conversation turn becomes values, and how those values become history
for the next model call. `./dev-venv` prepares the project notebook environment.

We will use three independent components of a turn: a conversational reply,
optional reasoning, and a request to run Python. A turn may contain more than
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
class Turn:
    reply: str
    reasoning: lmcc.Role["reasoning", str]
    calls: lmcc.Role["tools.calls", list[ToolCall]]

@lmcc.fn
def agent(message: str, tools: lmcc.Role["tools", list[Tool]]) -> Turn:
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

The ordinary reply is whatever remains after routing. Reasoning is removed
from the prose, and a heredoc becomes a structured call. There is no shell
execution here: `run_python <<'PY_END'` is a literal message spelling.

```python
reasoning = lmcc.Strategy(
    visible=False,
    fragments={"system": "If you include analysis, put it inside <think>...</think>."},
    routings=[{"from": "text", "between": ["<think>", "</think>"],
               "to": "@role", "consume": True}],
)

adapter = lmcc.adapter(
    messages=[
        lmcc.system("{instruction}\n{reply}"),
        lmcc.user("{message}"),
        lmcc.history(),
    ],
    formats={
        "list[Tool]": lmcc.use("function_tool"),
        "list[ToolCall]": lmcc.use("code_calls"),
    },
    strategies={"reasoning": reasoning, "tools": lmcc.use("heredoc_tools")},
)
plan = agent.bind(adapter, capabilities={"instruct": True}, registry=registry)
question = "Could you calculate 6 times 7?"
rendered = plan.render(message=question, tools=[python_tool])
print(rendered.system)
print("\nUser:", rendered.messages[0]["parts"][0]["text"])
```

The tools strategy writes the catalog as text (`via: tool_catalog`). Its
`turns.input_format` is **code_arguments**: it writes `{"code": ...}` as raw
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

## 4. The writer: structured call → the next prompt

Suppose the application approved that call and its sandbox returned `42`.
We **supply that result as a fixture** below; this notebook does not run the
code. We store the call and result in lm15's normal message shapes, not as
hand-built heredoc strings.

```python
call = values["calls"][0]
history = [
    {"role": "assistant", "parts": [
        {"type": "tool_call", **dataclasses.asdict(call)},
    ]},
    {"role": "tool", "parts": [
        {"type": "tool_result", "id": call.id, "name": call.name,
         "content": [{"type": "text", "text": "42"}]},
    ]},
]
next_request = plan.render(message=question, tools=[python_tool], history=history)
for message in next_request.messages:
    print(f"\n{message['role']}:")
    for part in message["parts"]:
        print(part.get("text", part))

print("\nA possible final answer:")
show(plan.parse("The result is 42."))
```

The adapter has written the heredoc for you and converted the result into a
user message. The sequence is question → call → result. Keep the initial
question fixed while continuing this tool exchange. A larger chat loop
manages subsequent user turns and history explicitly.

## 5. Code whitespace is data

The reader uses the raw captured parts, **not** the trimmed `span.text` view.
Here the code contains indentation, Unicode, CRLF and a trailing newline.
The envelope adds its own newline before `PY_END`; that newline is not code.

```python
exact_code = '    # café\r\n    print(6 * 7)\r\n'
exact_history = [{"role": "assistant", "parts": [
    {"type": "tool_call", "id": "example", "name": "run_python", "input": {"code": exact_code}},
]}]
request_with_code = plan.render(message=question, tools=[python_tool], history=exact_history)
heredoc = request_with_code.messages[-1]["parts"][0]["text"]
recovered_code = plan.parse(heredoc)["calls"][0].input["code"]
print("Written:", repr(heredoc))
print("Recovered:", repr(recovered_code))
print("Code preserved exactly:", recovered_code == exact_code)
```

Text call IDs are generated per reply (`call_1`, …). They are not a global
identity. The probe checks the tool name and arguments, not ID preservation.

## 6. What does the bind-time probe actually do?

Inspect the shipped strategy. Its sample is a valid call to `run_python`,
not the old generic `probe({probe: true})` that a code-only reader cannot read.

```python
strategy = lmcc_std.code.heredoc_tools({})
show(strategy.turns)
show(plan.describe()["turns"])

entry = adapter.dump(registry=registry)
print("Argument-writer version:", entry["versions"]["vocab"]["format/code_arguments"])
loaded = lmcc.load(entry, registry=registry)
print("Artifact round-trips:", loaded.dump(registry=registry) == entry)
```

At bind, the same writer used for history spells the sample call, the
strategy's own routing captures it, and the calls format reads it back.
A different name or input object means `turns-drift`.

You can provide a different representative sample, without adding Python
code to the artifact:

```python
custom = lmcc_std.code.heredoc_tools({})
custom.turns["probe"] = {
    "name": "run_python",
    "input": {"code": 'print({"total": 6 * 7})\n'},
}
custom_adapter = lmcc.adapter(messages=adapter.template, formats=adapter.formats,
                              strategies={"reasoning": reasoning, "tools": custom})
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
broken.turns["call"] = "CALL {name}: {input}"
broken_adapter = lmcc.adapter(messages=adapter.template, formats=adapter.formats,
                              strategies={"tools": broken, "reasoning": reasoning})
show_refusal(lambda: agent.bind(broken_adapter, capabilities={"instruct": True}, registry=registry))
```

## 7. Delimiter collisions are rejected

For this literal-delimiter transport, `PY_END` is forbidden anywhere inside
code. This is conservative: even a harmless string mentioning it is rejected.
Choose another marker in **both** the strategy and the calls format if needed.

```python
unsafe_history = [{"role": "assistant", "parts": [
    {"type": "tool_call", "id": "c2", "name": "run_python", "input": {"code": "print('PY_END')"}},
]}]
show_refusal(lambda: plan.render(message=question, tools=[python_tool], history=unsafe_history))
```

## What this does not promise

- The probe proves its **sample**, not every possible program. Regression
  tests separately cover whitespace, Unicode, empty bodies and stream splits.
- Core `between` routing is not a strict shell-heredoc parser. Unterminated
  blocks can remain ordinary reply text. Only structured `calls` may be
  considered for execution—never raw model text.
- This shipped strategy supports one configured tool. A multi-tool agent needs
  a deliberate dispatch protocol, not shell evaluation of the header.
- The application must validate, authorize and sandbox execution, associate
  results with calls, and bound the number of continuation turns.
- Reasoning-only replies may be continued by the application, but LMCC does
  not create an autonomous loop. Tool-result text is untrusted too.

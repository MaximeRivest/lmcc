# Research notebook: tool-call transport × reasoning style, from scratch

**Question.** Does a tool-call convention interact with where a model writes
its reasoning? Build the experiment without importing a standard vocabulary
pack: just `lmcc` and Python's standard library.

We will build a **3 × 3 design**:

| Factor | Levels |
|---|---|
| Tool-call transport | native calls · JSON fences · raw-code heredocs |
| Reasoning presentation | native thinking · top-level think tags · code comments |

Every cell is executable Python. Run top to bottom in the project notebook
kernel prepared by `./dev-venv`. The final matrix uses **simulated model
responses**, with known tool results. This is an offline transport experiment,
not evidence about model quality. It costs nothing and never executes model code.

The researcher swaps a **complete adapter variant**. Formats and strategies
are reusable implementation pieces inside that variant. The task, tool schema,
agent signature and episode runner stay the same.

## 1. The fixed program and tool

This is the function whose calling convention we will vary. The model can
reply, supply reasoning, or request a Python call; a turn may combine them.

```python
import ast
import dataclasses
import io
import itertools
import json
import tokenize

import lmcc

registry = lmcc.Registry(extensions=())   # no vocabulary pack, no regex extension

def show(value):
    print(json.dumps(value, indent=2, ensure_ascii=False,
                     default=lambda x: dataclasses.asdict(x) if dataclasses.is_dataclass(x) else str(x)))

@dataclasses.dataclass
class Tool:
    name: str
    description: str
    parameters: dict

@dataclasses.dataclass
class Call:
    id: str
    name: str
    input: dict

@dataclasses.dataclass
class AgentTurn:
    reply: str
    reasoning: lmcc.Role["reasoning", str]
    calls: lmcc.Role["tools.calls", list[Call]]

@lmcc.fn
def researcher_agent(task: str, tools: lmcc.Role["tools", list[Tool]]) -> AgentTurn:
    """Help the user solve the task. Reply conversationally when no tool is needed.
    A tool request is not execution. Wait for a tool result before claiming success.
    """

python_tool = Tool(
    name="run_python",
    description="Request Python execution from the application's approved sandbox.",
    parameters={"type": "object", "properties": {"code": {"type": "string"}},
                "required": ["code"], "additionalProperties": False},
)
TOOLS = [python_tool]
TASK = "Use Python to calculate 6 times 7, then tell me the result."

for field in researcher_agent.signature.fields:
    print(f"{field.direction:<6} {field.name:<10} role={field.role}")
```

`tools` appears before the output fields in signature order. This matters
later: its routing runs before the reasoning routing. The kernel does not
know that these role names mean a coding agent; we supply their behavior.

## 2. Name the two factors and their wire spellings

The text transports differ only in the call envelope and argument spelling.
The native transport uses lm15's canonical tool-call parts. We work with
plain dictionaries here; no provider client is needed.

```python
TRANSPORTS = ("native", "json_fence", "heredoc")
REASONING_STYLES = ("native", "think_tags", "code_comments")
FENCE = "`" * 3
MARKER = "CODE_END"
ENVELOPES = {
    "json_fence": (FENCE + "tool\n", "\n" + FENCE),
    "heredoc": ("run_python <<'" + MARKER + "'\n", "\n" + MARKER),
}

for transport in TRANSPORTS:
    print(transport, "→", ENVELOPES.get(transport, "lm15 tool_call parts"))
```

These are literal delimiters, not shell syntax. The heredoc variant is a
single-tool protocol. It does not dispatch arbitrary commands.

## 3. Define the input formats: native tool definitions or a text catalog

A format answers **how a value is spelled**. The same `list[Tool]` becomes
native function definitions or prompt text, depending on the adapter variant.
We select its format in the adapter; no `via` override is needed here.

```python
class ToolInventory(lmcc.Format):
    accepts = ("list[*]",)
    direction = "in"

    def __init__(self, options):
        self.transport = options["transport"]
        if self.transport not in TRANSPORTS:
            raise ValueError("unknown tool transport")
        self.emits = "parts" if self.transport == "native" else "text"

    def describe(self, field):
        return "available tools"

    def write(self, value, field):
        specs = [dataclasses.asdict(tool) for tool in value]
        if self.transport == "native":
            return [{"type": "function", **spec} for spec in specs]
        return "\n".join(
            f"- {s['name']}: {s['description']}\n  arguments: "
            + json.dumps(s["parameters"], ensure_ascii=False)
            for s in specs
        )

registry.register_format("research/tool_inventory", ToolInventory, version="0.1.0")
```

## 4. Define the call reader and raw-code argument writer

We normalize all three transports into the **same** `Call` objects.
The reader never executes code. Argument validation deliberately accepts
only the one tool and one argument shape in this experiment.

Raw code uses a format rather than a template expression such as
`{input.code}`. It writes the code verbatim, including indentation and
trailing newlines. Its conservative marker check is a transport limitation,
not a rule about which Python programs are valid.

```python
def check_arguments(arguments):
    if (not isinstance(arguments, dict) or set(arguments) != {"code"}
            or not isinstance(arguments["code"], str)):
        raise ValueError("expected exactly {code: string}")
    return arguments

class RawCode(lmcc.Format):
    accepts = ("object",)
    emits = "text"

    def __init__(self, options):
        pass

    def write(self, arguments, field):
        code = check_arguments(arguments)["code"]
        if MARKER in code:
            raise ValueError("code contains the heredoc delimiter; choose another protocol marker")
        return code

    def read(self, span, field):
        if any(p.get("type") != "text" or not isinstance(p.get("text"), str) for p in span.parts):
            raise ValueError("expected raw text parts")
        code = "".join(p["text"] for p in span.parts)   # NOT span.text: no whitespace stripping
        if MARKER in code:
            raise ValueError("code contains the heredoc delimiter")
        return {"code": code}

raw_code = RawCode({})

def decode_calls(span, transport, field):
    calls = []
    for part in span.parts:
        if transport == "native":
            if part.get("type") != "tool_call":
                raise ValueError("expected a native tool_call part")
            name, arguments, call_id = part["name"], part["input"], part["id"]
        elif transport == "json_fence":
            value = json.loads(part["text"])
            if not isinstance(value, dict) or set(value) != {"name", "input"}:
                raise ValueError("a fenced call must contain exactly name and input")
            name, arguments = value["name"], value["input"]
            call_id = f"call_{len(calls) + 1}"
        else:
            name = "run_python"
            arguments = raw_code.read(lmcc.Span([part]), field)
            call_id = f"call_{len(calls) + 1}"
        if name != "run_python" or not isinstance(call_id, str) or not call_id:
            raise ValueError("unknown tool or missing call id")
        calls.append(Call(call_id, name, check_arguments(arguments)))
    return calls

class Calls(lmcc.Format):
    accepts = ("list[*]",)
    direction = "out"

    def __init__(self, options):
        self.transport = options["transport"]
        if self.transport not in TRANSPORTS:
            raise ValueError("unknown tool transport")
        self.reads = ("tool_call",) if self.transport == "native" else ("text",)

    def read(self, span, field):
        return decode_calls(span, self.transport, field)

registry.register_format("research/raw_code", RawCode, version="0.1.0")
registry.register_format("research/calls", Calls, version="0.1.0")
```

The history writer and bind-time probe will use `research/raw_code` too.
The sample proves one call round-trips through our configuration, not that
all possible code is valid or safe.

## 5. Define what counts as reasoning

Native and tagged reasoning are separate text channels. Comment reasoning
is different: it lives **inside the decoded code argument**. We first decode
the call with the same reader, then extract designated Python comments.

Use standalone `# reason:` comments above logical statements. Python's
`tokenize` distinguishes comments from strings containing `# reason:`.
We leave comments in the code that the tool would receive.

This extracts comments; it does not prove there is a comment above every
statement, nor that a comment is a faithful description of model reasoning.
Those are separate benchmark measurements.

```python
def comment_reasoning(code):
    lines = code.splitlines()
    notes = []
    for token in tokenize.generate_tokens(io.StringIO(code).readline):
        if token.type != tokenize.COMMENT:
            continue
        row, column = token.start
        standalone = not lines[row - 1][:column].strip()
        if standalone and token.string.startswith("# reason:"):
            note = token.string[len("# reason:"):].strip()
            if note:
                notes.append(note)
    return "\n".join(notes)

class Reasoning(lmcc.Format):
    accepts = ("string",)
    direction = "out"

    def __init__(self, options):
        self.style, self.transport = options["style"], options["transport"]
        if self.style not in REASONING_STYLES or self.transport not in TRANSPORTS:
            raise ValueError("unknown experimental factor")
        if self.style == "native":
            self.reads = ("thinking",)
        elif self.style == "code_comments" and self.transport == "native":
            self.reads = ("tool_call",)
        else:
            self.reads = ("text",)

    def read(self, span, field):
        if self.style != "code_comments":
            return span.text
        calls = decode_calls(span, self.transport, field)
        return "\n".join(note for call in calls
                         if (note := comment_reasoning(call.input["code"])))

registry.register_format("research/reasoning", Reasoning, version="0.1.0")

print(comment_reasoning('text = "# reason: not a comment"\n# reason: Compute the product.\nprint(6 * 7)'))
```

## 6. Define the strategies: where each value travels

One helper supplies the call extractor for both the tools and reasoning
strategies. That avoids independently maintained delimiter definitions.

For text calls with comment reasoning, **tools capture without consuming**;
the later reasoning routing reads that same call body and consumes it.
Otherwise tools consume immediately. Native parts can be routed to both
fields without this text-consumption issue.

This is a real interaction between the factors, not a completely independent
switch. The adapter factory owns this coordination; the episode runner does not.

```python
def call_routing(transport, target, *, consume=False, suffices=False):
    if transport == "native":
        route = {"from": "channel:tool_call", "to": target}
    else:
        route = {"from": "text", "between": list(ENVELOPES[transport]),
                 "to": target, "consume": consume}
    if suffices:
        route["suffices"] = True
    return route

def tool_strategy(transport, reasoning_style):
    route = call_routing(transport, "@role.calls",
                         consume=(reasoning_style != "code_comments"), suffices=True)
    if transport == "native":
        return lmcc.Strategy(
            requires=["native_function_calling"], visible=False,
            placement={"@role": "controls.tools"}, routings=[route],
        )

    opening, closing = ENVELOPES[transport]
    if transport == "json_fence":
        example = opening + '{"name": "run_python", "input": {"code": "print(42)"}}' + closing
        call_template = opening + '{{"name": "{name}", "input": {input}}}' + closing
    else:
        example = opening + "print(42)" + closing
        call_template = "{name} <<'" + MARKER + "'\n{input}" + closing

    turns = {
        "call": call_template,
        "result": "Tool result for {name} ({id}):\n{output}",
        "probe": {"name": "run_python", "input": {"code": "print(6 * 7)\n"}},
    }
    if transport == "heredoc":
        turns["input_format"] = {"use": "research/raw_code"}

    return lmcc.Strategy(
        requires=["instruct"], visible=False,
        placement={"@role": "message:system"}, routings=[route], turns=turns,
        fragments={"system": "To request a tool, use this spelling and wait for its result:\n" + example},
    )

def reasoning_strategy(style, transport):
    if style == "native":
        return lmcc.Strategy(
            requires=["native_reasoning"], visible=False,
            controls={"config": {"reasoning": {"effort": "low"}}},
            routings=[{"from": "channel:thinking", "to": "@role"}],
        )
    if style == "think_tags":
        return lmcc.Strategy(
            requires=["instruct"], visible=False,
            controls={"config": {"reasoning": {"effort": "off"}}},
            fragments={"system": "When you include reasoning, put one <think>...</think> block at the top, before the reply or tool call."},
            routings=[{"from": "text", "between": ["<think>", "</think>"],
                       "to": "@role", "consume": True}],
        )
    return lmcc.Strategy(
        requires=["instruct"], visible=False,
        controls={"config": {"reasoning": {"effort": "off"}}},
        fragments={"system": "When writing Python tool code, put a standalone '# reason: ...' comment immediately above each logical statement. Do not put reasoning outside the code."},
        routings=[call_routing(transport, "@role", consume=True)],
    )
```

Our tagged reader extracts the tags; it does not enforce that they were
placed at the top. The prompt requests that location. A benchmark can score
placement separately instead of silently equating successful extraction
with instruction compliance.

## 7. The swappable research artifact

This factory is the researcher's main interface: two factor values in,
one complete adapter out. No kernel changes and no standard pack.

The reasoning format is bound by the named `Analysis` type below rather
than by all strings: the reply and reasoning must not share that reader.
The kernel's JSON signature representation lets us assign that type name
without inventing a Python class just for a registry lookup.

```python
signature_data = lmcc.signature_to_dict(researcher_agent.signature)
for field in signature_data["fields"]:
    if field.get("role", "plain") == "reasoning":
        field["type"] = "Analysis"
signature = lmcc.signature_from_dict(signature_data)

def make_adapter(transport, style):
    if transport not in TRANSPORTS or style not in REASONING_STYLES:
        raise ValueError("unknown factor level")
    return lmcc.adapter(
        name=f"research/{transport}/{style}",
        messages=[lmcc.system("{instruction}\n{reply}"), lmcc.user("{task}"), lmcc.history()],
        formats={
            "list[Tool]": lmcc.use("research/tool_inventory", transport=transport),
            "list[Call]": lmcc.use("research/calls", transport=transport),
            "Analysis": lmcc.use("research/reasoning", transport=transport, style=style),
        },
        strategies={
            "tools": tool_strategy(transport, style),
            "reasoning": reasoning_strategy(style, transport),
        },
    )

# These facts describe our SIMULATED endpoint, not every real model/provider.
CAPABILITIES = {"instruct": True, "native_function_calling": True, "native_reasoning": True}
adapters = {(transport, style): make_adapter(transport, style)
            for transport, style in itertools.product(TRANSPORTS, REASONING_STYLES)}
plans = {key: adapter.bind(signature, CAPABILITIES, registry=registry)
         for key, adapter in adapters.items()}

for key, plan in plans.items():
    print(key, "→", plan.describe()["routings"])
```

The neutral signature retains the same field names, roles and shapes across
all nine cells. Its named `Analysis` field lets the artifact select a format
for reasoning only. Values returned by our custom calls reader are still
`Call` objects because we explicitly construct them.

## 8. Compare the requests before spending anything

Look at a native/native cell and a heredoc/comments cell. The native one
sets `tools` and requests native reasoning at `low` effort; the text one
describes both conventions in its prompt and explicitly requests native
thinking `off`. The common task is unchanged.

```python
for key in (("native", "native"), ("heredoc", "code_comments")):
    request = plans[key].render(task=TASK, tools=TOOLS).request(model="simulated-endpoint")
    print("\nVARIANT:", key)
    show(request)
```

**Real-endpoint warning:** requesting native thinking does not guarantee the
provider exposes its text. Simply omitting `config.reasoning` may not turn
native thinking off, so we explicitly request `off` for tags and comments.
These controls are part of our treatment. Verify the endpoint supports the
required on/off settings; if it does not, mark the affected cells unsupported
rather than silently dropping the control. Uncontrollable native reasoning
is a confound. All nine adapters binding is not proof of endpoint support.

## 9. Create independently authored fixture replies

We are not using the adapter's writer to generate these test replies. Doing
so could let the writer and reader share the same bug. The input messages
are explicit examples of each transport, combined with each presentation.

```python
PLAIN_CODE = "product = 6 * 7\nprint(product)\n"
COMMENT_CODE = (
    "# reason: Multiply the two numbers.\n"
    "product = 6 * 7\n"
    "# reason: Report the result.\n"
    "print(product)\n"
)
RATIONALE = "Multiply the two numbers and report the result."

def simulated_call_reply(transport, style):
    code = COMMENT_CODE if style == "code_comments" else PLAIN_CODE
    parts = []
    if style == "native":
        parts.append({"type": "thinking", "text": RATIONALE})
    elif style == "think_tags":
        parts.append({"type": "text", "text": "<think>" + RATIONALE + "</think>\n"})

    if transport == "native":
        parts.append({"type": "tool_call", "id": "fixture_call", "name": "run_python", "input": {"code": code}})
    elif transport == "json_fence":
        payload = json.dumps({"name": "run_python", "input": {"code": code}})
        parts.append({"type": "text", "text": FENCE + "tool\n" + payload + "\n" + FENCE})
    else:
        parts.append({"type": "text", "text": "run_python <<'CODE_END'\n" + code + "\nCODE_END"})
    return {"role": "assistant", "parts": parts}

example_reply = simulated_call_reply("heredoc", "code_comments")
print(example_reply["parts"][0]["text"])
show(plans[("heredoc", "code_comments")].parse(example_reply))
```

The calls format preserves the comments in `calls[0].input['code']`.
The reasoning format extracts their explanatory text into `reasoning`.
Both projections describe the same reply; no comments were executed or deleted.

## 10. One episode runner for the whole matrix

The runner sees only a bound plan, a provider function and an executor.
It has no `if heredoc` or `if code_comments` branches. For this offline
notebook, the provider returns fixtures and the executor returns a known
fixture result. Neither is a real model or Python sandbox.

We preserve the provider's assistant message, including native continuation
metadata if present, in history. Text replies already have the right spelling.
Structured calls can alternatively be written by the adapter's `turns` face;
we demonstrate that independently in the next section.

```python
def fixture_provider(transport, style):
    replies = iter([
        simulated_call_reply(transport, style),
        {"role": "assistant", "parts": [{"type": "text", "text": "The result is 42."}]},
    ])
    def complete(request):
        return next(replies)
    return complete

def fixture_executor(call):
    if call.name != "run_python":
        raise ValueError("unexpected tool")
    # Known answer for this fixture; deliberately NO eval/exec/subprocess.
    return "42"

def run_episode(plan, complete, execute, *, max_turns=3):
    history, records, requests = [], [], []
    for turn_index in range(max_turns):
        rendered = plan.render(task=TASK, tools=TOOLS, history=history)
        request = rendered.request(model="simulated-endpoint")
        requests.append(request)
        message = complete(request)
        values = plan.parse(message)   # let malformed replies fail visibly; no silent fallback
        records.append(values)
        history.append(message)
        calls = values.get("calls", [])
        if calls:
            for call in calls:
                result = execute(call)
                history.append({"role": "tool", "parts": [{
                    "type": "tool_result", "id": call.id, "name": call.name,
                    "content": [{"type": "text", "text": result}],
                }]})
        elif values.get("reply", "").strip():
            return records, requests
        # A reasoning-only turn may continue, but only within the explicit limit.
    raise RuntimeError("turn budget exhausted")

episodes = {}
rows = []
for transport, style in itertools.product(TRANSPORTS, REASONING_STYLES):
    key = (transport, style)
    records, requests = run_episode(plans[key], fixture_provider(*key), fixture_executor)
    episodes[key] = (records, requests)
    first = records[0]
    code = first["calls"][0].input["code"]
    ast.parse(code)  # syntax check only, not execution
    rows.append({
        "transport": transport,
        "reasoning": style,
        "turns": len(records),
        "calls": len(first["calls"]),
        "reasoning_extracted": bool(first["reasoning"]),
        "final_reply": records[-1]["reply"],
        "code_chars": len(code),
    })

print("SIMULATED TRANSPORT CHECK — NOT MODEL BENCHMARK RESULTS")
print(f"{'transport':<12} {'reasoning':<15} {'turns':<6} {'calls':<6} {'analysis?':<10} reply")
for row in rows:
    print(f"{row['transport']:<12} {row['reasoning']:<15} {row['turns']:<6} "
          f"{row['calls']:<6} {str(row['reasoning_extracted']):<10} {row['final_reply']}")
```

Code-comment reasoning is **not applicable on a turn without code**. In this
example the final conversational answer has no such reasoning. Do not count
that as a failure of comment extraction or quietly turn it into a think tag.
Native thinking may also be absent or opaque on real endpoints; record that
separately from visible native reasoning.

## 11. Inspect the history writer and its sample check

For raw code, the argument format does the body spelling and `turns` does
the envelope. Nothing new was added to the kernel to define this experiment.

```python
key = ("heredoc", "code_comments")
first_call = episodes[key][0][0]["calls"][0]
structured_history = [{"role": "assistant", "parts": [
    {"type": "tool_call", **dataclasses.asdict(first_call)},
]}]
history_request = plans[key].render(task=TASK, tools=TOOLS, history=structured_history)
written = history_request.messages[-1]["parts"][0]["text"]
print(written)
print("Code preserved through history:", plans[key].parse(written)["calls"][0].input["code"] == COMMENT_CODE)
show(tool_strategy(*key).turns)
```

Change the writer but not the reader, and binding should refuse before any
provider call. This checks the representative call, not model compliance.

```python
broken = tool_strategy("heredoc", "think_tags")
broken.turns["call"] = "CALL {name}: {input}"
good = adapters[("heredoc", "think_tags")]
broken_adapter = lmcc.adapter(messages=good.template, formats=good.formats,
                               strategies={"tools": broken, "reasoning": reasoning_strategy("think_tags", "heredoc")})
try:
    broken_adapter.bind(signature, CAPABILITIES, registry=registry)
except lmcc.Refusal as error:
    print(error.code, error.fix)
```

## 12. Save the treatments, not just their labels

An artifact contains the selected layout, strategies, format references and
versions. The custom factories still need to be registered on the loading
host: dumping references does not bundle their Python implementation.
For a real study, archive these artifacts **and** this notebook/source commit,
provider/model version, task data, endpoint controls, results and evaluation
policy. A name such as `heredoc + comments` is not enough to reproduce a run.

```python
artifacts = {f"{transport}/{style}": adapter.dump(registry=registry)
             for (transport, style), adapter in adapters.items()}
selected = artifacts["heredoc/code_comments"]
show(selected["versions"])
reloaded = lmcc.load(selected, registry=registry)
restored_plan = reloaded.bind(signature, CAPABILITIES, registry=registry)
show(restored_plan.parse(example_reply))
```

## What to replace for a real benchmark

Keep `run_episode` and the adapter matrix. Replace the two fixture functions:

- `complete(request)` → your provider bridge returning a canonical lm15
  assistant message, preserving metadata needed for replay;
- `execute(call)` → an allowlisted, validated, authorized sandbox executor.

Do not execute raw model text. Do not let model-chosen IDs or names select
arbitrary functions. The text IDs in this notebook are reply-local; a real
runner must track which result belongs to which pending call.

Hold tasks, tool behavior, endpoint, permissions, evaluator and continuation
policy fixed. Record native-thinking settings explicitly. Report parse failures,
wrong tools, malformed arguments, task success, latency, token usage and tool
errors separately. The comment condition generally uses more code-output tokens;
a fixed output-token ceiling is a resource constraint, not an equal reasoning
budget. The extraction of a rationale is not proof of reasoning quality.

Finally, this notebook's literal scanners are not a strict heredoc grammar.
Missing closing markers can remain conversational text; code-comment extraction
can encounter invalid Python; native thinking may be hidden. These are conditions
to test and report—not reasons to make the parser silently guess.

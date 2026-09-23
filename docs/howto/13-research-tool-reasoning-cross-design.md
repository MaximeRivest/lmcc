# Research notebook: tool-call style × reasoning style, from scratch

**Question.** Does a tool-call convention interact with where a model writes its reasoning? Build the experiment without importing a standard vocabulary pack: just `lmcc` and Python's standard library.

We will build a **3 × 3 design**:

| Factor | Levels |
|---|---|
| Tool-call style | native calls · JSON fences · raw-code heredocs |
| Reasoning presentation | native thinking · top-level think tags · code comments |

Every cell is executable Python. Run top to bottom in the project notebook kernel prepared by `./dev-venv`. The final matrix uses **simulated model responses**, with known tool results. This is an offline transport experiment, not evidence about model quality. It costs nothing and never executes model code.

The researcher swaps a **complete adapter variant**. Formats and transports are reusable implementation pieces inside that variant. The task, tool schema, agent signature and episode runner stay the same.

## 1. The fixed program and tool

This is the function whose calling convention we will vary. The model can reply, supply reasoning, or request a Python call; a turn may combine them.

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
    reasoning: lmcc.Purpose["reasoning", str]
    calls: lmcc.Purpose["tools.calls", list[Call]]

@lmcc.fn
def researcher_agent(task: str, tools: lmcc.Purpose["tools", list[Tool]]) -> AgentTurn:
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
    print(f"{field.direction:<6} {field.name:<10} purpose={field.purpose}")
```

```output
input  task       purpose=plain
input  tools      purpose=tools
output reply      purpose=plain
output reasoning  purpose=reasoning
output calls      purpose=tools.calls
```

`tools` appears before the output fields in signature order. This matters later: its find rule runs before the reasoning find rule. The kernel does not know that these role names mean a coding agent; we supply their behavior.

## 2. Name the two factors and their wire spellings

The text call styles differ only in the call envelope and argument spelling. The native style uses lm15's canonical tool-call parts. We work with plain dictionaries here; no provider client is needed.

```python
CALL_STYLES = ("native", "json_fence", "heredoc")
REASONING_STYLES = ("native", "think_tags", "code_comments")
FENCE = "`" * 3
MARKER = "CODE_END"
ENVELOPES = {
    "json_fence": (FENCE + "tool\n", "\n" + FENCE),
    "heredoc": ("run_python <<'" + MARKER + "'\n", "\n" + MARKER),
}

for call_style in CALL_STYLES:
    print(call_style, "→", ENVELOPES.get(call_style, "lm15 tool_call parts"))
```

These are literal delimiters, not shell syntax. The heredoc variant is a single-tool protocol. It does not dispatch arbitrary commands.

## 3. Define the input formats: native tool definitions or a text catalog

A format answers **how a value is spelled**. The same `list[Tool]` becomes native function definitions or prompt text, depending on the adapter variant. We select its format in the adapter; no `written_as` override is needed here.

```python
class ToolInventory(lmcc.Format):
    accepts = ("list[*]",)
    direction = "in"

    def __init__(self, options):
        self.call_style = options["call_style"]
        if self.call_style not in CALL_STYLES:
            raise ValueError("unknown tool call_style")
        self.writes = "parts" if self.call_style == "native" else "text"

    def describe(self, field):
        return "available tools"

    def write(self, value, field):
        specs = [dataclasses.asdict(tool) for tool in value]
        if self.call_style == "native":
            return [{"type": "function", **spec} for spec in specs]
        return "\n".join(
            f"- {s['name']}: {s['description']}\n  arguments: "
            + json.dumps(s["parameters"], ensure_ascii=False)
            for s in specs
        )

registry.register_format("research/tool_inventory", ToolInventory, version="0.1.0")
```

## 4. Define the call reader and raw-code argument writer

We normalize all three call styles into the **same** `Call` objects. The reader never executes code. Argument validation deliberately accepts only the one tool and one argument shape in this experiment.

Raw code uses a format rather than a template expression such as `{input.code}`. It writes the code verbatim, including indentation and trailing newlines. Its conservative marker check is a transport limitation, not a rule about which Python programs are valid.

```python
def check_arguments(arguments):
    if (not isinstance(arguments, dict) or set(arguments) != {"code"}
            or not isinstance(arguments["code"], str)):
        raise ValueError("expected exactly {code: string}")
    return arguments

class RawCode(lmcc.Format):
    accepts = ("object",)
    writes = "text"

    def __init__(self, options):
        pass

    def write(self, arguments, field):
        code = check_arguments(arguments)["code"]
        if MARKER in code:
            raise ValueError("code contains the heredoc delimiter; choose another protocol marker")
        return code

    def read(self, capture, field):
        if any(p.get("type") != "text" or not isinstance(p.get("text"), str) for p in capture.parts):
            raise ValueError("expected raw text parts")
        code = "".join(p["text"] for p in capture.parts)   # NOT capture.text: no whitespace stripping
        if MARKER in code:
            raise ValueError("code contains the heredoc delimiter")
        return {"code": code}

raw_code = RawCode({})

def decode_calls(capture, call_style, field):
    calls = []
    for part in capture.parts:
        if call_style == "native":
            if part.get("type") != "tool_call":
                raise ValueError("expected a native tool_call part")
            name, arguments, call_id = part["name"], part["input"], part["id"]
        elif call_style == "json_fence":
            value = json.loads(part["text"])
            if not isinstance(value, dict) or set(value) != {"name", "input"}:
                raise ValueError("a fenced call must contain exactly name and input")
            name, arguments = value["name"], value["input"]
            call_id = f"call_{len(calls) + 1}"
        else:
            name = "run_python"
            arguments = raw_code.read(lmcc.Capture([part]), field)
            call_id = f"call_{len(calls) + 1}"
        if name != "run_python" or not isinstance(call_id, str) or not call_id:
            raise ValueError("unknown tool or missing call id")
        calls.append(Call(call_id, name, check_arguments(arguments)))
    return calls

class Calls(lmcc.Format):
    accepts = ("list[*]",)
    direction = "both"

    def __init__(self, options):
        self.call_style = options["call_style"]
        if self.call_style not in CALL_STYLES:
            raise ValueError("unknown tool call_style")
        self.reads = ("tool_call",) if self.call_style == "native" else ("text",)

    def read(self, capture, field):
        return decode_calls(capture, self.call_style, field)

    def write(self, calls, field):
        # Past calls as lm15 tool_call parts; the tools transport's `spelling` writes them for text styles.
        return [{"type": "tool_call", "id": c.id, "name": c.name, "input": check_arguments(c.input)}
                for c in calls]

registry.register_format("research/raw_code", RawCode, version="0.1.0")
registry.register_format("research/calls", Calls, version="0.1.0")
```

The writer of past calls and the bind-time probe will use `research/raw_code` too. The sample proves one call round-trips through our configuration, not that all possible code is valid or safe.

## 5. Define what counts as reasoning

Native and tagged reasoning are separate text channels. Comment reasoning is different: it lives **inside the decoded code argument**. We first decode the call with the same reader, then extract designated Python comments.

Use standalone `# reason:` comments above logical statements. Python's `tokenize` distinguishes comments from strings containing `# reason:`. We leave comments in the code that the tool would receive.

This extracts comments; it does not prove there is a comment above every statement, nor that a comment is a faithful description of model reasoning. Those are separate benchmark measurements.

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
    direction = "both"

    def __init__(self, options):
        self.style, self.call_style = options["style"], options["call_style"]
        if self.style not in REASONING_STYLES or self.call_style not in CALL_STYLES:
            raise ValueError("unknown experimental factor")
        if self.style == "native":
            self.reads = ("thinking",)
        elif self.style == "code_comments" and self.call_style == "native":
            self.reads = ("tool_call",)
        else:
            self.reads = ("text",)

    def read(self, capture, field):
        if self.style != "code_comments":
            return capture.text
        calls = decode_calls(capture, self.call_style, field)
        return "\n".join(note for call in calls
                         if (note := comment_reasoning(call.input["code"])))

    def write(self, value, field):
        # Written back only for tagged reasoning, between its own tags. Native thinking is
        # replayed from the recorded reply; comment reasoning lives inside the call it came from.
        return value

registry.register_format("research/reasoning", Reasoning, version="0.1.0")

print(comment_reasoning('text = "# reason: not a comment"\n# reason: Compute the product.\nprint(6 * 7)'))
```

## 6. Define the transports: where each value travels

One helper supplies the call extractor for both the tools and reasoning transports. That avoids independently maintained delimiter definitions.

For text calls with comment reasoning, **tools capture without removing**; the later reasoning find rule reads that same call body and removes it. Otherwise tools remove immediately. Native parts can be routed to both fields without this text-consumption issue.

This is a real interaction between the factors, not a completely independent switch. The adapter factory owns this coordination; the episode runner does not.

```python
def call_find_rule(call_style, target, *, remove=False, complete_reply=False):
    if call_style == "native":
        route = {"from": "part:tool_call", "to": target}
    else:
        route = {"from": "text", "between": list(ENVELOPES[call_style]),
                 "to": target, "remove": remove}
    if complete_reply:
        route["complete_reply"] = True
    return route

def tool_transport(call_style, reasoning_style):
    route = call_find_rule(call_style, "@purpose.calls",
                         remove=(reasoning_style != "code_comments"), complete_reply=True)
    if call_style == "native":
        return lmcc.Transport(
            requires=["native_function_calling"], in_template=False,
            put={"@purpose": "request.tools"}, find=[route],
        )

    opening, closing = ENVELOPES[call_style]
    if call_style == "json_fence":
        example = opening + '{"name": "run_python", "input": {"code": "print(42)"}}' + closing
        call_template = opening + '{{"name": "{name}", "input": {input}}}' + closing
    else:
        example = opening + "print(42)" + closing
        call_template = "{name} <<'" + MARKER + "'\n{input}" + closing

    spelling = {
        "call": call_template,
        "result": "Tool result for {name} ({id}):\n{output}",
        "probe": {"name": "run_python", "input": {"code": "print(6 * 7)\n"}},
    }
    if call_style == "heredoc":
        spelling["input_format"] = {"use": "research/raw_code"}

    return lmcc.Transport(
        requires=["instruct"], in_template=False,
        put={"@purpose": "message:system"}, find=[route], spelling=spelling,
        tell={"system": "To request a tool, use this spelling and wait for its result:\n" + example},
    )

def reasoning_transport(style, call_style):
    if style == "native":
        return lmcc.Transport(
            requires=["native_reasoning"], in_template=False,
            request_settings={"config": {"reasoning": {"effort": "low"}}},
            find=[{"from": "part:thinking", "to": "@purpose"}],
        )
    if style == "think_tags":
        return lmcc.Transport(
            requires=["instruct"], in_template=False,
            request_settings={"config": {"reasoning": {"effort": "off"}}},
            tell={"system": "When you include reasoning, put one <think>...</think> block at the top, before the reply or tool call."},
            find=[{"from": "text", "between": ["<think>", "</think>"],
                       "to": "@purpose", "remove": True}],
        )
    return lmcc.Transport(
        requires=["instruct"], in_template=False,
        request_settings={"config": {"reasoning": {"effort": "off"}}},
        tell={"system": "When writing Python tool code, put a standalone '# reason: ...' comment immediately above each logical statement. Do not put reasoning outside the code."},
        find=[call_find_rule(call_style, "@purpose", remove=True)],
    )
```

Our tagged reader extracts the tags; it does not enforce that they were placed at the top. The prompt requests that location. A benchmark can score put separately instead of silently equating successful extraction with instruction compliance.

## 7. The swappable research artifact

This factory is the researcher's main interface: two factor values in, one complete adapter out. No kernel changes and no standard pack.

The reasoning format is bound by the named `Analysis` type below rather than by all strings: the reply and reasoning must not share that reader. The kernel's JSON signature representation lets us assign that type name without inventing a Python class just for a registry lookup.

```python
signature_data = lmcc.signature_to_dict(researcher_agent.signature)
for field in signature_data["fields"]:
    if field.get("purpose", "plain") == "reasoning":
        field["type"] = "Analysis"
signature = lmcc.signature_from_dict(signature_data)

def make_adapter(call_style, style):
    if call_style not in CALL_STYLES or style not in REASONING_STYLES:
        raise ValueError("unknown factor level")
    return lmcc.adapter(
        name=f"research/{call_style}/{style}",
        messages=[lmcc.system("{instruction}\n{reply}"), lmcc.turns(), lmcc.user("{task}")],
        formats={
            "list[Tool]": lmcc.use("research/tool_inventory", call_style=call_style),
            "list[Call]": lmcc.use("research/calls", call_style=call_style),
            "Analysis": lmcc.use("research/reasoning", call_style=call_style, style=style),
        },
        transports={
            "tools": tool_transport(call_style, style),
            "reasoning": reasoning_transport(style, call_style),
        },
    )

# These facts describe our SIMULATED endpoint, not every real model/provider.
CAPABILITIES = {"instruct": True, "native_function_calling": True, "native_reasoning": True}
adapters = {(call_style, style): make_adapter(call_style, style)
            for call_style, style in itertools.product(CALL_STYLES, REASONING_STYLES)}
plans = {key: adapter.bind(signature, CAPABILITIES, registry=registry)
         for key, adapter in adapters.items()}

for key, plan in plans.items():
    print(key, "→", plan.describe()["find"])
```

The neutral signature retains the same field names, purposes and shapes across all nine cells. Its named `Analysis` field lets the artifact select a format for reasoning only. Values returned by our custom calls reader are still `Call` objects because we explicitly construct them.

## 8. Compare the requests before spending anything

Look at a native/native cell and a heredoc/comments cell. The native one sets `tools` and requests native reasoning at `low` effort; the text one describes both conventions in its prompt and explicitly requests native thinking `off`. The common task is unchanged.

```python
for key in (("native", "native"), ("heredoc", "code_comments")):
    request = plans[key].render(task=TASK, tools=TOOLS).request(model="simulated-endpoint")
    print("\nVARIANT:", key)
    show(request)
```

**Real-endpoint warning:** requesting native thinking does not guarantee the provider exposes its text. Simply omitting `config.reasoning` may not turn native thinking off, so we explicitly request `off` for tags and comments. These request settings are part of our treatment. Verify the endpoint supports the required on/off settings; if it does not, mark the affected cells unsupported rather than silently dropping the control. Uncontrollable native reasoning is a confound. All nine adapters binding is not proof of endpoint support.

## 9. Create independently authored fixture replies

We are not using the adapter's writer to generate these test replies. Doing so could let the writer and reader share the same bug. The input messages are explicit examples of each call style, combined with each presentation.

```python
PLAIN_CODE = "product = 6 * 7\nprint(product)\n"
COMMENT_CODE = (
    "# reason: Multiply the two numbers.\n"
    "product = 6 * 7\n"
    "# reason: Report the result.\n"
    "print(product)\n"
)
RATIONALE = "Multiply the two numbers and report the result."

def simulated_call_reply(call_style, style):
    code = COMMENT_CODE if style == "code_comments" else PLAIN_CODE
    parts = []
    if style == "native":
        parts.append({"type": "thinking", "text": RATIONALE})
    elif style == "think_tags":
        parts.append({"type": "text", "text": "<think>" + RATIONALE + "</think>\n"})

    if call_style == "native":
        parts.append({"type": "tool_call", "id": "fixture_call", "name": "run_python", "input": {"code": code}})
    elif call_style == "json_fence":
        payload = json.dumps({"name": "run_python", "input": {"code": code}})
        parts.append({"type": "text", "text": FENCE + "tool\n" + payload + "\n" + FENCE})
    else:
        parts.append({"type": "text", "text": "run_python <<'CODE_END'\n" + code + "\nCODE_END"})
    return {"role": "assistant", "parts": parts}

example_reply = simulated_call_reply("heredoc", "code_comments")
print(example_reply["parts"][0]["text"])
show(plans[("heredoc", "code_comments")].parse(example_reply))
```

The calls format preserves the comments in `calls[0].input['code']`. The reasoning format extracts their explanatory text into `reasoning`. Both projections describe the same reply; no comments were executed or deleted.

## 10. One episode runner for the whole matrix

The runner sees only a bound plan, a provider function and an executor. It has no `if heredoc` or `if code_comments` branches. For this offline notebook, the provider returns fixtures and the executor returns a known fixture result. Neither is a real model or Python sandbox.

An episode is **one turn**: the task, then each model reply and tool result as a step, then the answer. `rendered.step(reply)` records a reply with its parsed values and the message exactly as it came, so the next request sends it back unchanged, native continuation metadata included. `turn.tool(id, output)` records a result for a pending call. The runner returns the finished turn: one record that can be saved, compared and replayed.

```python
def fixture_provider(call_style, style):
    replies = iter([
        simulated_call_reply(call_style, style),
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

def run_episode(plan, complete, execute, *, max_model_calls=3):
    turn = plan.turn(task=TASK, tools=TOOLS)
    requests = []
    for _ in range(max_model_calls):
        rendered = plan.render(turn)
        requests.append(rendered.request(model="simulated-endpoint"))
        turn = rendered.step(complete(requests[-1]))   # malformed replies fail visibly; no fallback
        calls = turn.pending_calls()
        for call in calls:
            turn = turn.tool(call.id, execute(call))
        if not calls and turn.steps[-1].outputs.get("reply", "").strip():
            return turn.finish(), requests
        # A reasoning-only reply may continue, but only within the explicit limit.
    raise RuntimeError("model-call budget exhausted")

episodes = {}
rows = []
for call_style, style in itertools.product(CALL_STYLES, REASONING_STYLES):
    key = (call_style, style)
    episodes[key] = run_episode(plans[key], fixture_provider(*key), fixture_executor)
    turn = episodes[key][0]
    replies = [s.outputs for s in turn.steps if s.kind == "model"]
    first = replies[0]
    code = first["calls"][0].input["code"]
    ast.parse(code)  # syntax check only, not execution
    rows.append({
        "call_style": call_style,
        "reasoning": style,
        "turns": len(replies),
        "calls": len(first["calls"]),
        "reasoning_extracted": bool(first["reasoning"]),
        "final_reply": turn.outputs["reply"],
        "code_chars": len(code),
    })

print("SIMULATED TRANSPORT CHECK — NOT MODEL BENCHMARK RESULTS")
print(f"{'call_style':<12} {'reasoning':<15} {'turns':<6} {'calls':<6} {'analysis?':<10} reply")
for row in rows:
    print(f"{row['call_style']:<12} {row['reasoning']:<15} {row['turns']:<6} "
          f"{row['calls']:<6} {str(row['reasoning_extracted']):<10} {row['final_reply']}")
```

Code-comment reasoning is **not applicable on a turn without code**. In this example the final conversational answer has no such reasoning. Do not count that as a failure of comment extraction or quietly turn it into a think tag. Native thinking may also be absent or opaque on real endpoints; record that separately from visible native reasoning.

## 11. Rewrite one episode for another adapter, and check the writer

The nine episodes agree on the answer and differ on the wire. That is the claim of the design, and now it is a check rather than a printed table:

```python
reference = episodes[("native", "native")][0]
for key, (turn, requests) in episodes.items():
    assert turn.outputs["reply"] == reference.outputs["reply"]
    assert key == ("native", "native") or requests[0] != episodes[("native", "native")][1][0]
print("Same reply in all nine cells; different first request in every other cell.")
```

A recorded turn is values, so another adapter can write it. Take the native/native episode and give it to the heredoc/comments plan: the plan cannot read the recorded native reply, so it writes the step again from its values — the raw-code argument format spells the body, `turns` the envelope. Nothing new was added to the kernel to define this experiment.

```python
key = ("heredoc", "code_comments")
native_turn = episodes[("native", "native")][0]
respelled = plans[key].render(task="Next task.", tools=TOOLS, turns=[native_turn])
written = respelled.messages[1]["parts"][0]["text"]
print(written)
print("Code preserved:", plans[key].parse(written)["calls"][0].input["code"] == PLAIN_CODE)
show(plans[key].describe()["turns"]["projections"])
show(tool_transport(*key).spelling)
```

The native episode's thinking does not appear. In this plan, reasoning *is* the comments inside the code (a projection of the call), and the recorded code has none. A value the target spelling cannot express is not invented or moved elsewhere; compare cells by the values they recorded.

Change the writer but not the reader, and binding should refuse before any provider call. This checks the representative call, not model compliance.

```python
broken = tool_transport("heredoc", "think_tags")
broken.spelling["call"] = "CALL {name}: {input}"
good = adapters[("heredoc", "think_tags")]
broken_adapter = lmcc.adapter(messages=good.template, formats=good.formats,
                               transports={"tools": broken, "reasoning": reasoning_transport("think_tags", "heredoc")})
try:
    broken_adapter.bind(signature, CAPABILITIES, registry=registry)
except lmcc.Refusal as error:
    print(error.code, error.fix)
```

## 12. Save the treatments, not just their labels

An artifact contains the selected layout, transports, format references and versions. The custom factories still need to be registered on the loading host: dumping references does not bundle their Python implementation. For a real study, archive these artifacts **and** this notebook/source commit, provider/model version, task data, endpoint settings, results and evaluation policy. A name such as `heredoc + comments` is not enough to reproduce a run.

```python
artifacts = {f"{call_style}/{style}": adapter.dump(registry=registry)
             for (call_style, style), adapter in adapters.items()}
selected = artifacts["heredoc/code_comments"]
show(selected["versions"])
reloaded = lmcc.load(selected, registry=registry)
restored_plan = reloaded.bind(signature, CAPABILITIES, registry=registry)
show(restored_plan.parse(example_reply))
```

## What to replace for a real benchmark

Keep `run_episode` and the adapter matrix. Replace the two fixture functions:

- `complete(request)` → your provider bridge returning a canonical lm15 assistant message, preserving metadata needed for replay;
- `execute(call)` → an allowlisted, validated, authorized sandbox executor.

Do not execute raw model text. Do not let model-chosen IDs or names select arbitrary functions. The text IDs in this notebook are reply-local; the turn pairs each result with its pending call (`turn.tool` refuses a result that answers none), and ids written as native parts are made unique per request.

Hold tasks, tool behavior, endpoint, permissions, evaluator and continuation policy fixed. Record native-thinking settings explicitly. Report parse failures, wrong tools, malformed arguments, task success, latency, token usage and tool errors separately. The comment condition generally uses more code-output tokens; a fixed output-token ceiling is a resource constraint, not an equal reasoning budget. The extraction of a rationale is not proof of reasoning quality.

Finally, this notebook's literal scanners are not a strict heredoc grammar. Missing closing markers can remain conversational text; code-comment extraction can encounter invalid Python; native thinking may be hidden. These are conditions to test and report—not reasons to make the parser silently guess.

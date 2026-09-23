# Plan 12 — `Turn`: one record for demos, history, trajectories (kernel 0.7)

**Status: implemented in Python, kernel 0.7 (D-39).** The normative text is `contract/spec/kernel.md` §3a; the corpus pins it (03, 47, 53, 54, 103, 107, 116, 122, 128–148). This file keeps the design history: the pre-prototype vignette (superseded API) and the prototype's findings, which shaped the kernel. The prototype itself is removed; see git history.

### What shipped, and how it differs from the findings below

- **F2 projections** apply to native channels too (reasoning read from `tool_call` parts is a projection of the calls).
- **F3 read-only formats** refuse at bind (`turns-drift`), with `turns.write: null` as the explicit way to drop a field.
- **F4 position** is `turns.position`; `reasoning_tags` 0.2.0 declares `before`.
- **F6 ids**: assigned ids written as native parts become `s<k>_<id>`; provider ids never change.
- **F7**: a model step stores the reply and `request: sha256:…`, not the request.
- **F10 images** from tools follow the result text on text transports.
- **F11 empty slots**: `{% if slot %}…{% endif %}` guards. **F13**: `{m.kind}` (`input`, `model`, `tool`).
- **Doubt 1 (replay)**: the adapter chooses (`replay: "recorded" | "values"`); recorded replies are sent verbatim when the plan reads them back into the same values.
- Found while implementing: placements and fragments used to land in a past turn's message (the live sources were attached to an earlier question) — fixed and pinned (case 143).

### Still open

1. **Other languages** are rebuilt from the contract once the language settles (D-41). The Go kernel that passed 0.6 is at the tag `kernel-0.6`; TypeScript is on the branch `ts/cleanroom`.
2. **Live providers**: verify id qualification and verbatim replay (thinking signatures, tool-call continuation data) against real endpoints through lm15.
3. **dspy_session on turns**: sessions, memory policy and training data built on `Turn`, outside the kernel.
4. **Field-level text layout** of a turn (`{% for f in t.inputs %}`) — deferred.
5. **Test the words** (D-40): give `docs/glossary.md` and three small examples to someone new, ask them to predict what each setting does; every wrong guess is a naming bug.
6. An example whose outputs hold calls but no tool steps is writable (useful on text transports); on native transports it would send unanswered calls. Decide whether to refuse it.

## Revision after the prototype

### What changed in the design

1. **The live turn is a Turn.** `render(plan, current, turns=past)` renders *this turn, in the context of those turns*: past turns at the template's turns slot, the live inputs once, then the current turn's steps. `rendered.step(reply)` parses and appends a model step with its exchange; `current.tool(id, output, children=())` appends a tool step; `current.finish()` sets outputs from the last model step. The vignette's duplicated user message (old open decision 1) is gone, not suppressed. Proven by `test_in_progress_turn_renders_live_input_once`.
2. **A tool step is not a Turn.** `Turn = {signature, inputs, steps, outputs?, score?, meta}`; `ModelStep = {outputs, exchange, calls_field}`; `ToolStep = {id, name, output: parts, children: [Turn]}`. RLM sub-calls hang under the tool step that made them and never render into the parent's prompt (`test_tool_step_holds_child_turns`).
3. **A Turn names its signature.** `signature` is a fingerprint of field names, directions, shapes, roles and type names. Instructions are excluded so that editing or optimizing a docstring does not orphan recorded turns. A mismatch refuses `signature-mismatch`. The same signature under a different adapter has the same fingerprint, which is what makes re-spelling legal (`test_same_turns_respelled_by_fenced_adapter`).
4. **The turns slot must precede the live input.** Today `history()` serves both as "past conversation" (before the live message) and as "continuation" (after it, howto 12). With an in-progress Turn the continuation is implicit, so a slot after the live input refuses `turns-misplaced` when past turns are given. Migration: howto 12 moves its `history()` up.

### What the prototype found (evidence, not argument)

| # | finding | evidence | resolution proposed for the spec |
|---|---|---|---|
| F1 | Today's value-based history (`{"fields": …}`) writes **only visible outputs**; reasoning and calls are silently skipped | `plan._render_turns` | hidden routed fields get writers: derived for `between`, declared or `null` for `pattern`, native part for `channel:*` |
| F2 | Two routings can read **the same span** (calls, and reasoning extracted from comments in the call body). Writing both **duplicated the tool call**, and my first tests passed anyway | howto 13 `native×code_comments`; `test_projection_is_not_written_twice` (fails without the fix) | fields sharing a span form a group; the calls field (which has `turns.call`) writes, the others are *projections*, re-read and never written; a group without an owner refuses `turns-ambiguous` at bind |
| F3 | A hidden field whose format only reads cannot go into past turns. howto 13's reasoning format is read-only: 3 of 9 cells refused until it gained a one-line `write` | `howto13_matrix.py` (6 OK, 3 refuse; `FIX_FORMAT=1`: 9 OK); `test_read_only_format_refuses_instead_of_dropping` | refuse at **bind** (`turns-drift`) for any hidden routed, non-projected field in a placed slot whose format cannot write. Separately, a kernel bug: the `format-write-error` hint is empty when the exception has no message |
| F4 | Position is real and undeclared: `<think>` must precede the visible block, calls follow it. The prototype hard-codes `reasoning → before` | `POSITION` in `lmcc_turns.py` | a declared `position: before \| after` per writer, as the vignette proposed; now confirmed necessary |
| F5 | Pairing tool results with calls needs to know which output **is** the calls field. The signature knows; a Turn checked without a plan does not | `ModelStep.calls_field` | the model step records it |
| F6 | **Call ids collide.** Text transports number calls per reply (`call_1` each time); re-spelled as native parts, three past turns all send `call_1`. Some providers likely reject this (not verified live) | prototype run: ids `call_1, call_1, call_1` | the renderer qualifies ids deterministically per turn when writing native parts (`t0_call_1`), call and result together; pairing is positional, so meaning is unchanged **[open]** |
| F7 | **Stored sessions grow quadratically**: each model step stores its full request, and each request contains the whole conversation. 8 short turns = 42 KB, growing faster each turn | prototype measurement | `exchange = {message, request_sha256}`: keep the reply verbatim (it holds opaque parts), keep only a hash of the request, which is re-derivable by re-rendering. Full requests become an opt-in audit log outside the kernel |
| F8 | JSON has no types. Reading a Turn back needs the plan to lift values to their annotations | `Turn.from_dict(d, plan=)`; `test_json_round_trip_renders_identically` | stated rule: serde is typed only against a signature |
| F9 | Separators between written pieces (`<think>…</think>`, visible block, spelled call) are unpinned. The prototype uses `\n`, which reads back byte-identically for every tested strategy | `test_writer_equals_reader_for_hidden_fields`, `test_in_progress_turn_renders_live_input_once` | pin in spec and corpus |

### Second round: slots, images, tool results in the system prompt

The prototype now implements turn slots without touching the kernel: a slot is a private-use marker that the kernel renders as literal text, and the prototype fills it after render (`lmcc_turns.adapter`, `lmcc_turns.turns`). 8 more scenarios, 24 in total.

- **Named slots.** `turns("conversation")` expands a slot as messages. `{% for m in examples %}[{m.role}] {m.text}\n{% endfor %}` inside any message places a slot as text, iterating the messages the pairs form would send, so tool calls and results use the same writers. `history()` is the slot `turns`. Proven: examples in the system prompt with the conversation as messages; a whole tool exchange as a system-prompt example; refusals `turns-unplaced`, `turns-double-placed`, `turns-slot-collides`, and `template-syntax` for any loop attribute other than `role`/`text`.
- **The current turn's steps are a slot too.** The reserved slot `steps` holds the current turn's own steps. Unplaced, they follow the live input (the default). Placed as text, they become "work so far" in the system prompt, so the prompt ends with the live question alone. A tool result cannot be placed apart from its call: a result without the request it answers means nothing, and native providers reject it. If only a result should be context, it is an *input* of the next call (an ordinary input field placed in the system prompt), which works today.
- **Images from tools.** See F10.

| # | finding | evidence | resolution proposed for the spec |
|---|---|---|---|
| F10 | **Kernel bug today:** on text transports, `turns.result` keeps only a tool result's text parts; an image returned by a tool is **silently dropped**. Native transports keep it | `test_tool_image_kept_on_text_transport` (fails without the prototype's fix) | `turns.result` writes the text; the result's non-text parts follow it, in order, in the same message. In the text form (a string), non-text parts refuse `turns-not-text`. Whether lm15 or the provider accepts images in that position is lm15's per-provider media policy, not lmcc's |
| F11 | An empty slot leaves its surrounding text behind: with no examples, the prompt still says "Worked examples:" followed by nothing. The template has no conditionals | prototype run | **[open]** (a) accept; (b) per-slot `before`/`after` text rendered only when the slot is non-empty; (c) the caller binds a different adapter. (b) is small and keeps the template free of an expression language |
| F12 | The whole-reply rule (a bare `{reply}` must end its message) means a loop over turns in the same message must come **before** `{reply}`. My first templates put it after and bind refused `not-lensable` | first run of the new tests | not a turns problem; a layout rule the teaching must state |
| F13 | In the text form, `{m.role}` is the role **after** spelling: a text transport sends tool results as `user`, so a transcript shows `[user] Result of …` | prototype output | **[open]** add `{m.kind}` (`input`, `model`, `tool`), or accept |
| F14 | A turns loop inside a **user** message would repeat in every past turn's user side (past turns are rendered through the template's user messages) | `test_loop_in_user_message_does_not_repeat_in_past_turns` | turn slots render empty inside past turns' user sides |

### What the prototype did **not** test

- **`pattern` routings with declared writers** (only the refusal exists).
- **Streaming**: untouched; the parse side is unchanged.
- **dspy_session on top**: not ported yet.
- **Any live provider**: all replies are fixtures. F6 especially needs one real request per provider.

### Open decisions, updated

1. ~~Continuation duplication~~: resolved by change 1.
2. Legacy verbatim lm15 history without values: render frozen, or refuse.
3. ~~`meta.plan` fingerprint~~: replaced by the required `signature` field.
4. Tool outputs as parts: yes. The prototype stores parts; text writers join the text parts.
5. **New:** F6 id qualification, and F7 request hashing instead of storage.
6. **New:** F11 empty-slot text (per-slot `before`/`after`?), F13 `{m.kind}`.

---

*The original pre-prototype design follows. §2–§3 and the "Design summary" use the superseded API (`kind` on Turn, `rendered.turn`, a fake past turn for continuation).*

## Motivation

Today the kernel has two ways to put past exchanges in a prompt — `demos` (field values, spelled by the lens) and `history` (lm15 messages, passed verbatim; only tool parts are re-spelled) — and the loop that produces those exchanges is rewritten in every notebook, returning ad-hoc tuples. Three consequences:

- switching adapters mid-conversation leaves the old spelling in history;
- hidden routed fields (reasoning, calls) have readers but no writers, so a past turn cannot be re-spelled from its values;
- nothing records an agent's inner steps in a form that sessions, optimizers, or other languages can consume.

One record fixes all three. A **Turn** is one round trip: field values in, field values out, the exact wire exchange, and an inner trajectory of Turns. Demos are Turns that did not happen here. History is Turns that did. An agent episode is one Turn whose trajectory is its steps. The kernel gains one construct (`turns` slots) and loses two (`demos`, `history`). Everything above — loops, sessions, scoring — stays outside and speaks Turn.

---

## The vignette

### 1. The program and adapter you already know

Same agent as `docs/howto/12`: reply, optional reasoning, optional Python call. Nothing about signatures changes.

```python
import dataclasses, json
import lmcc
from lmcc_std import fenced_tools, reasoning_tags, native_tools, native_reasoning

def show(v): print(json.dumps(v, indent=2, default=lambda x: dataclasses.asdict(x) if dataclasses.is_dataclass(x) else str(x)))

@dataclasses.dataclass
class Tool:  name: str; description: str; parameters: dict
@dataclasses.dataclass
class Call:  id: str; name: str; input: dict

@dataclasses.dataclass
class AgentTurn:
    reply: str
    reasoning: lmcc.Role["reasoning", str]
    calls: lmcc.Role["tools.calls", list[Call]]

@lmcc.fn
def agent(message: str, tools: lmcc.Role["tools", list[Tool]]) -> AgentTurn:
    """Help the user. Reply when no tool is needed. A tool request is not
    execution; wait for its result before claiming success."""

python_tool = Tool("run_python", "Run Python in the approved sandbox.",
                   {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]})
TOOLS = [python_tool]
CAPS_TEXT   = {"instruct": True}
CAPS_NATIVE = {"instruct": True, "native_function_calling": True, "native_reasoning": True}
```

The only new thing in the adapter is `lmcc.turns()` where `lmcc.history()` used to be. `demos` is gone too; a demo is a Turn like any other.

```python
text_adapter = lmcc.adapter(
    name="agent/text",
    messages=[lmcc.system("{instruction}"), lmcc.turns(), lmcc.user("{message}")],
    strategies={"tools": fenced_tools(), "reasoning": reasoning_tags()},
)
text_plan = text_adapter.bind(agent.signature, CAPS_TEXT)
show(text_plan.describe()["turns"])
```

```output (simulated)
{
  "slots": [{"name": "turns", "form": "messages", "position": 1}],
  "writers": {
    "reasoning": {"source": "derived:between", "position": "before"},
    "tools.calls": {"source": "turns.call", "position": "after"},
    "tools.results": {"source": "turns.result", "role": "user"}
  },
  "dropped": []
}
```

Read it: one slot, expanded as message pairs, sitting between system and the live user message. Reasoning has a writer *derived from its own routing* (`<think>` … `</think>`, placed before the lens block); calls use the strategy's `turns.call`; results become a `user` message. Nothing is dropped. Every writer here passed the bind-time probe.

### 2. A Turn is born from a render and a reply

`render` is unchanged. What is new is `rendered.turn(message)`: parse the reply and pack inputs, outputs and the exact exchange into one record. Pure — it is `parse` plus bookkeeping.

```python
rendered = text_plan.render(message="what is 6 times 7? use python", tools=TOOLS)
request = rendered.request(model="simulated")

model_reply = {"role": "assistant", "parts": [{"type": "text", "text":
    "<think>Arithmetic; the user asked for Python.</think>\n"
    "```tool\n{\"name\": \"run_python\", \"input\": {\"code\": \"print(6*7)\"}}\n```"}]}

step1 = rendered.turn(model_reply)
show(step1)
```

```output (simulated)
{
  "kind": "model",
  "inputs":  {"message": "what is 6 times 7? use python", "tools": [{"name": "run_python", ...}]},
  "outputs": {"reasoning": "Arithmetic; the user asked for Python.",
              "calls": [{"id": "call_1", "name": "run_python", "input": {"code": "print(6*7)"}}]},
  "trajectory": [],
  "exchange": {"request": {...}, "message": {...}},
  "score": null,
  "meta": {"plan": "sha256:3f9c…", "model": "simulated"}
}
```

`reply` is absent, not empty: the call sufficed. `meta.plan` is the bound plan's fingerprint (`versions` + artifact hash), written by `turn()` and never read by the kernel — it is there so *other* layers can tell which spelling produced this exchange.

The application runs the tool (we supply the result) and records that as a Turn too. A tool step has no exchange; its inputs are the call, its output the result.

```python
call = step1.outputs["calls"][0]
tool_step = lmcc.Turn.tool(call, output="42")
show(tool_step)
```

```output (simulated)
{"kind": "tool", "inputs": {"id": "call_1", "name": "run_python", "input": {"code": "print(6*7)"}},
 "outputs": {"output": "42"}, "trajectory": [], "exchange": null, "score": null, "meta": {}}
```

### 3. The second request: turns in, messages out

To ask again, we pass the steps so far as turns. The kernel spells each one through **this adapter's** writers — the same writers the parser is derived from. We did not build any message by hand.

```python
episode_so_far = lmcc.Turn(inputs=step1.inputs, outputs={}, trajectory=[step1, tool_step])
rendered2 = text_plan.render(message="what is 6 times 7? use python", tools=TOOLS,
                             turns=[episode_so_far])
for m in rendered2.messages: print(f"--- {m['role']}\n{m['parts'][0]['text']}")
```

```output (simulated)
--- system
Help the user. Reply when no tool is needed. A tool request is not
execution; wait for its result before claiming success.

To request a tool, write:
```tool
{"name": ..., "input": ...}
```
When you include reasoning, put one <think>...</think> block first. --- user what is 6 times 7? use python --- assistant
<think>Arithmetic; the user asked for Python.</think>

```tool
{"name": "run_python", "input": {"code": "print(6*7)"}}
```
--- user Tool result for run_python (call_1): 42 --- user what is 6 times 7? use python
```

**[open]** The final live `user` repeats the message because the loop is
mid-episode: the turn's `inputs` and the live inputs are the same. A loop
library will normally render the *continuation* with the same inputs; the
kernel does not deduplicate. Options: (a) leave it — it is what DSPy's
ReAct does; (b) a turn with empty `outputs` and a trajectory whose last
step is a tool step renders its inputs but the template's live user
message is suppressed. (b) is magic; (a) is the default unless the
corpus shows real cost.

```python
final_reply = {"role": "assistant", "parts": [{"type": "text", "text": "The result is 42."}]}
step2 = rendered2.turn(final_reply)
episode = lmcc.Turn(inputs=step1.inputs, outputs=step2.outputs, trajectory=[step1, tool_step, step2])
print(episode.outputs, len(episode.trajectory))
```

```output (simulated)
{'reply': 'The result is 42.'} 3
```

### 4. Swap the adapter; the conversation follows

Same Turns, native adapter. Reasoning goes to the thinking channel, calls to `tool_call` parts, results to `tool_result` parts. Nothing was re-recorded.

```python
native_adapter = lmcc.adapter(
    name="agent/native",
    messages=[lmcc.system("{instruction}"), lmcc.turns(), lmcc.user("{message}")],
    strategies={"tools": native_tools(), "reasoning": native_reasoning()},
)
native_plan = native_adapter.bind(agent.signature, CAPS_NATIVE)
show(native_plan.describe()["turns"])
```

```output (simulated)
{
  "slots": [{"name": "turns", "form": "messages", "position": 1}],
  "writers": {
    "reasoning": {"source": "exchange:thinking", "note": "opaque; replayed from exchange when present, else dropped"},
    "tools.calls": {"source": "native:tool_call"},
    "tools.results": {"source": "native:tool_result", "role": "tool"}
  },
  "dropped": ["reasoning (when no exchange)"]
}
```

```python
r = native_plan.render(message="now 8 times 9", tools=TOOLS, turns=[episode])
show([ {"role": m["role"], "parts": [p["type"] for p in m["parts"]]} for m in r.messages ])
show(r.request(model="simulated")["tools"][0]["name"])
```

```output (simulated)
[
  {"role": "user",      "parts": ["text"]},
  {"role": "assistant", "parts": ["tool_call"]},
  {"role": "tool",      "parts": ["tool_result"]},
  {"role": "assistant", "parts": ["text"]},
  {"role": "user",      "parts": ["text"]}
]
"run_python"
```

The past assistant turn has **no** `thinking` part: the recorded exchange came from a text adapter, so there is no signed native block to replay, and native thinking cannot be forged from a string. `describe()` said so under `dropped`. Had the episode been recorded natively, the block would be replayed verbatim from `exchange`. That is the whole values-vs-wire rule: values always; the exchange only for opaque native parts.

### 5. Named slots: examples and conversation in different places

A slot is a name the template chooses. The caller fills it. The kernel does not know what "example" means.

```python
coach = lmcc.adapter(
    messages=[
        lmcc.system("{instruction}\n\nWorked examples:\n"
                    "{% for m in examples %}[{m.role}] {m.text}\n{% endfor %}"),
        lmcc.turns("conversation"),
        lmcc.user("{message}"),
    ],
    strategies={"tools": fenced_tools(), "reasoning": reasoning_tags()},
).bind(agent.signature, CAPS_TEXT)

demo = lmcc.Turn(inputs={"message": "hi"}, outputs={"reply": "Hello! What can I run for you?"})
r = coach.render(message="8 times 9", tools=TOOLS, turns=None,
                 examples=[demo], conversation=[episode])
print(r.messages[0]["parts"][0]["text"])
print([m["role"] for m in r.messages])
```

```output (simulated)
Help the user. Reply when no tool is needed. ...

Worked examples:
[user] hi
[assistant] Hello! What can I run for you?

['system', 'user', 'assistant', 'user', 'assistant', 'user']
```

The text form iterates the **messages** the pairs form would have produced (`m.role`, `m.text`), so tool steps and multi-part turns appear exactly as they would as messages, with the same writers. Native-only parts are dropped in text form; bind refuses if a routed role has no text writer and no explicit `null`. A slot placed twice refuses `turns-double-placed`. A slot named like a signature input refuses at bind.

Field-level layout inside a turn (`{% for f in t.inputs %}`) is **deferred**: it is expressible with nested loops, but it is a second rule set and nothing here needs it yet.

### 6. Refusals, before money

**A writer that cannot be derived.** A `pattern` routing has a reader but no obvious writer. Declare one, or drop the field on purpose.

```python
regex_reasoning = lmcc.Strategy(
    requires=["instruct"], visible=False,
    routings=[{"from": "text", "pattern": r"(?s)^Thoughts: (.*?)\n\n", "to": "@role", "consume": True}],
    extensions=["pattern/legacy-re2"],
)
try:
    lmcc.adapter(messages=text_adapter.template,
                 strategies={"tools": fenced_tools(), "reasoning": regex_reasoning}
                 ).bind(agent.signature, CAPS_TEXT, registry=registry_with_re2)
except lmcc.Refusal as e:
    print(e.code, "|", e.hint, "|", e.fix)
```

```output (simulated)
turns-drift | strategy for role "reasoning": routing is a pattern; a turns slot is placed but no writer is declared | {"action": "declare", "at": ".strategies.reasoning.turns.write", "one_of": ["template", null]}
```

```python
regex_reasoning.turns = {"write": "Thoughts: {value}\n\n", "position": "before"}   # probed at bind
# or: regex_reasoning.turns = {"write": None}   # drop reasoning from past turns, deliberately
```

**An unpaired call.** Providers reject a history with a call and no result; so does bind-free render, naming the id.

```python
try:
    native_plan.render(message="again", tools=TOOLS,
                       turns=[lmcc.Turn(inputs=step1.inputs, outputs={}, trajectory=[step1])])
except lmcc.Refusal as e:
    print(e.code, "|", e.hint)
```

```output (simulated)
turn-incomplete | turns[0].trajectory[0]: call "call_1" has no tool step with that id
```

**A field this signature does not have.**

```python
try:
    text_plan.render(message="x", tools=TOOLS,
                     turns=[lmcc.Turn(inputs={"question": "?"}, outputs={"reply": "!"})])
except lmcc.Refusal as e:
    print(e.code, "|", e.hint)
```

```output (simulated)
value-invalid | turns[0].inputs.question: not a field of this signature
```

A subset of fields is fine (that is how a session drops bulky inputs); an unknown field is not. Absent *outputs* are omitted, as demos do today. A lossy format (`round_trip: false`) refuses `demo-not-renderable`, same code as before, now covering turns.

### 7. A Turn is JSON, in every language

```python
blob = json.dumps(episode.to_dict())
again = lmcc.Turn.from_dict(json.loads(blob))
print(again == episode, len(blob))
```

```output (simulated)
True 2311
```

Values take the signature's `shape` in JSON (structured values as JSON, media as parts). A host-only value with no JSON shape refuses `turn-not-serializable`, naming the field. The Go kernel reads the same blob and renders the same bytes — that is a corpus case, not a promise.

---

## What sits on top (not kernel, shown for review)

### 8. The loop, in twenty lines, returning a Turn

```python
def run(plan, provider, execute, inputs, *, max_steps=6):
    steps = []
    for _ in range(max_steps):
        so_far = lmcc.Turn(inputs=inputs, outputs={}, trajectory=steps) if steps else None
        rendered = plan.render(**inputs, turns=[so_far] if so_far else None)
        step = rendered.turn(provider(rendered.request(model="simulated")))
        steps.append(step)
        for call in step.outputs.get("calls", []):
            steps.append(lmcc.Turn.tool(call, output=execute(call)))
        if step.outputs.get("reply", "").strip():
            return lmcc.Turn(inputs=inputs, outputs=step.outputs, trajectory=steps)
    raise RuntimeError("step budget exhausted")
```

No `if heredoc`, no `if native`. The plan spells; the loop decides. Compare `docs/howto/13` §10, which returns two parallel lists and never records the tool result.

### 9. A session, in fifteen

```python
class Session:
    def __init__(self, program, *, slot="turns", keep=lambda t: t):
        self.program, self.slot, self.keep, self.turns = program, slot, keep, []
    def __call__(self, **inputs):
        turn = self.program(inputs, turns={self.slot: [self.keep(t) for t in self.turns]})
        self.turns.append(turn)
        return turn.outputs

chat = Session(lambda inputs, turns: run(text_plan, provider, execute, inputs | turns))
chat(message="my name is Max. what is 6 times 7?", tools=TOOLS)
chat(message="and my name?", tools=TOOLS)
```

`keep` is the memory policy: strip trajectories, drop fields, window, summarize. The kernel renders what it is given. This is dspy_session's core with the DSPy dependency removed; its blueprint/state split and per-child policies layer on unchanged.

### 10. RLM: the trajectory is a tree

The recursive call is itself a `run(...)` on another plan; its Turn hangs under the step that made it.

```python
def rlm_execute(call):                       # the REPL is the environment
    if call.name == "lm":                    # one tool is the model
        child = run(sub_plan, provider, rlm_execute, call.input)
        current_step.trajectory.append(child)
        return child.outputs["answer"]
    return repl.exec(call.input["code"])

root = run(rlm_plan, provider, rlm_execute, {"query": q, "context_name": "context"})
def walk(t, d=0):
    print("  " * d + f"{t.kind} {list(t.outputs)}")
    for s in t.trajectory: walk(s, d + 1)
walk(root)
```

```output (simulated)
model ['answer']
  model ['reasoning', 'calls']
    tool ['output']
  model ['reasoning', 'calls']
    tool ['output']
    model ['answer']            ← a sub-call, with its own steps
      model ['reasoning', 'calls']
        tool ['output']
      model ['answer']
  model ['answer']
```

The kernel renders one level; deeper turns belong to another plan and are opaque to it. The big `context` never enters a prompt: it is a `Role["env", str]` spelled by a summary format and bound in the REPL by the loop — a vocabulary-pack convention, not a kernel construct (decision pending; see "What is out").

### 11. One record, two kinds of training data

```python
outer = [(t.inputs, t.outputs, t.score) for t in chat.turns]                       # the conversation
inner = [(s.inputs, s.outputs) for t in chat.turns for s in t.trajectory if s.kind == "model"]  # which tool, when
```

Both lists are Turns rendered by the same adapter that will be trained on them, so every training example is guaranteed parseable by it.

---

## Design summary (normative intent)

**Record.** `Turn = {kind: "model"|"tool", inputs, outputs, trajectory: [Turn], exchange?: {request, message}, score?, meta}`. The kernel reads `kind`, `inputs`, `outputs`, one level of `trajectory`, and opaque native parts in `exchange.message`. It carries the rest untouched.

**Slots.** The template declares turn slots: `lmcc.turns("name")` (messages form) or `{% for m in name %}` (text form over the messages the pairs form would produce). `lmcc.turns()` is the slot `turns`. `render(..., **slots)`; an unsupplied slot renders nothing. `describe() ["turns"]` lists slots, forms, writers, drops.

**Per-turn spelling — one law.** Inputs through the template's user messages (subset allowed; unknown field `value-invalid`; bare slot without value `missing-input`). Visible outputs through the lens (absent ones omitted; lossy format `demo-not-renderable`). Hidden routed outputs through a writer: derived for `between` routings, declared (`turns.write`) or explicitly `null` for `pattern` routings, native part for `channel:*` routings. Writers carry `position: before|after` the lens block (default `after`, per case 66); signature order within a position. Every writer is probed at bind; a placed slot with an unwritable routed role refuses `turns-drift`.

**Values vs exchange.** Values are canonical. `exchange` is consulted only for opaque native parts (signed thinking, continuation metadata) when the current routing is native; absent, the part is dropped and `describe()` says so. Byte-exact replay is not a kernel promise.

**Trajectory.** Empty → `user(inputs), assistant(outputs)`. Non-empty → `user(inputs)` then each step (model → assistant; tool → tool message, or `turns.result` text as `user`); outer outputs not repeated. Deeper levels opaque. After a model step with calls, tool steps must cover exactly those ids in order, else `turn-incomplete`.

**Prefix.** Everything before the first message with an input slot, turn slots included.

**Out of the kernel.** Selecting, ordering, windowing, summarizing, classifying turns; running loops; executing tools; environments (`env` stays a pack role until evidence says otherwise).

## Migration

Kernel 0.7. `demos` and `history` load as aliases of the `turns` slot for one minor version, then refuse `version-incompatible` with a fix. Demo dicts and `{"fields": {...}}` history items convert to Turns mechanically. Verbatim lm15 history messages have no values and cannot convert; a loader emits a Turn with `outputs={}` and the message under `exchange` **[open]**: render it verbatim (today's behavior, spelling frozen) or refuse. Recommendation: verbatim, flagged in `describe()`.

## Acceptance criteria

- `contract/spec/kernel.md`: §2 slot table and §3 render signature rewritten; new §"Turns" replacing the demos/history paragraphs; `schema/turn.schema.json`; `errors.md` rows for `turn-incomplete`, `turns-double-placed`, `turn-not-serializable` with fixes.
- Corpus, hand-authored first: every existing demo case and cases 100–127 re-expressed as `turns`; new cases for each cell of {between-derived, declared, null, native} × {before, after}; text-form placement incl. native-drop; named slots; unpaired call; unknown field; subset inputs; lossy format; prefix with a leading slot; cross-adapter re-spelling of the same Turn (text→native, native→text); JSON round trip of a nested Turn rendered identically by both kernels.
- Both kernels green through the harness; `tests/test_coherence.py` extended to the new codes; streaming untouched (parse side).
- `docs/howto/12` and `13` rewritten on `rendered.turn()`; §10 of `13` returns one Turn and asserts the nine cells agree on `reply` and differ on `exchange.request`.
- One decision entry: demos and history merged; values canonical; exchange for opaque parts only; selection outside the kernel.

## Open decisions to ratify before spec work

1. §3 continuation duplication: leave (a) or suppress (b).
2. Legacy verbatim history: render frozen or refuse.
3. `meta.plan` fingerprint: written by `rendered.turn()` (proposed) or left entirely to callers.
4. Whether `Turn.tool` outputs are `{"output": text}` only or may carry parts (images from a tool). Proposed: parts allowed; `turns.result` text writers get `{output}` as text parts joined, native passes parts.

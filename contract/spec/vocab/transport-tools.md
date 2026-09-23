# The tools transports and formats — 0.1.0

The `tools` purpose (`purposes.md`): the program hands the model what it may
call (`tools`, an **input**, `list` of tool specs) and reads back what
it asked for (`tools.calls`, an **output**, `list` of calls). Two
transports serve it; the program never changes. Every value shape is
lm15's (`../../LM15_CONTRACT_PIN`): a tool spec is a `FunctionTool`
(`{"type": "function", "name", "description"?, "parameters"}`), a call
is a `ToolCallPart` minus `type` (`{"id", "name", "input"}`).

**A call turn.** A reply that carries calls need not carry the other
outputs: the find rule that reads calls declares `complete_reply: true` (kernel
§6), so `parse` returns the calls and omits the outputs the reader cannot
find — never refuses. Running the tool and asking again is the caller's
loop; the call and its result are steps of one turn (kernel §3a), which
the next prompt writes back: as `tool_call` and `tool_result` parts under
`native_tools`, *spelled* as text by `fenced_tools`'s `spelling`.

## format/function_tool

`accepts: list[*], object, *` · `direction: in` · `writes: parts` ·
`round_trip: true`. Writes each item as an lm15 `FunctionTool` part
(`type: function`): an item is a dict with `name` (required),
`description`, `parameters` (JSON Schema object; default
`{"type": "object", "properties": {}}`); unknown keys refuse
`format-write-error`. `describe`: `tools`. Read is the inverse (strips
`type`).

## format/tool_catalog

`accepts: list[*], object, *` · `direction: in` · `writes: text`. The same
items as text for a model without native tool calling, one per line:
`- <name>(<parameters as canonical JSON>): <description>` — exact bytes
pinned by case 106.

## format/tool_calls

`accepts: list[*], *` · `direction: both` · `writes: parts` · `reads:
tool_call, text` · `round_trip: true`. Read: from `tool_call` parts, each
part minus `type` and `continuation` — id, name, input verbatim; from
text parts (a fenced call), each part's text is one JSON object
`{"name", "input"}` (else `format-read-error`) and the id is assigned
`call_1`, `call_2`, … in reply order — the model has no id to give, and
`Message.tool(id, …)` must still round-trip. An empty capture reads `[]`.
Write (turns): each call as a `tool_call` part.

## transport/native_tools

Requires `native_function_calling`. **Hidden.** Put `{"@purpose":
"request.tools"}` (the specs enter `Request.tools`); find rule `{from:
part:tool_call, to: @purpose.calls, complete_reply: true}`. No tell, no
`spelling` (calls and results are written as native parts). Bind refuses
`format-put-mismatch` if `tools` is not bound to a format that writes parts
format — `function_tool` is the one shipped.

## transport/fenced_tools

Requires `instruct`. **Hidden.** Put `{"@purpose": "message:system"}`
with `written_as: {"@purpose": "tool_catalog"}` (the catalog joins the system
prompt as text, whatever format the type is bound to);
`tell` (system):

> You may call a tool by replying with exactly one fenced block:
> ```tool
> {"name": "<tool>", "input": {…}}
> ```
> and nothing else; you will be given the result and asked again.

FindRule `{from: text, between: ["```tool\n", "\n```"], to: @purpose.calls,
remove: true, complete_reply: true}`. Turns (kernel §6): `call` →
```tool
{"name": "{name}", "input": {input}}
```
`result` → `Result of {name} ({id}):\n{output}`. The bind-time probe
renders `call` and reads it back through this find rule and `tool_calls`.

# The tools strategies and formats — 0.1.0

The `tools` role (`roles.md`): the program hands the model what it may
call (`tools`, an **input**, `list` of tool specs) and reads back what
it asked for (`tools.calls`, an **output**, `list` of calls). Two
strategies serve it; the program never changes. Every value shape is
lm15's (`../../LM15_CONTRACT_PIN`): a tool spec is a `FunctionTool`
(`{"type": "function", "name", "description"?, "parameters"}`), a call
is a `ToolCallPart` minus `type` (`{"id", "name", "input"}`).

**A call turn.** A reply that carries calls need not carry the other
outputs: the routing that reads calls declares `suffices: true` (kernel
§6), so `parse` returns the calls and omits the outputs the lens cannot
find — never refuses. Running the tool and asking again is the caller's
loop; the next prompt shows the call and result as history: lm15
messages (`assistant` with `tool_call` parts, `tool` with `tool_result`
parts) pass verbatim under `native_tools`, and are *spelled* by
`fenced_tools`'s `turns` face.

## format/function_tool

`accepts: list[*], object, *` · `direction: in` · `emits: parts` ·
`round_trip: true`. Writes each item as an lm15 `FunctionTool` part
(`type: function`): an item is a dict with `name` (required),
`description`, `parameters` (JSON Schema object; default
`{"type": "object", "properties": {}}`); unknown keys refuse
`format-write-error`. `describe`: `tools`. Read is the inverse (strips
`type`).

## format/tool_catalog

`accepts: list[*], object, *` · `direction: in` · `emits: text`. The same
items as text for a model without native tool calling, one per line:
`- <name>(<parameters as canonical JSON>): <description>` — exact bytes
pinned by case 106.

## format/tool_calls

`accepts: list[*], *` · `direction: both` · `emits: parts` · `reads:
tool_call, text` · `round_trip: true`. Read: from `tool_call` parts, each
part minus `type` and `continuation` — id, name, input verbatim; from
text parts (a fenced call), each part's text is one JSON object
`{"name", "input"}` (else `format-read-error`) and the id is assigned
`call_1`, `call_2`, … in reply order — the model has no id to give, and
`Message.tool(id, …)` must still round-trip. An empty span reads `[]`.
Write (demos): each call as a `tool_call` part.

## strategy/native_tools

Requires `native_function_calling`. **Hidden.** Placement `{"@role":
"controls.tools"}` (the specs enter `Request.tools`); routing `{from:
channel:tool_call, to: @role.calls, suffices: true}`. No fragments, no
`turns` (lm15 messages pass verbatim). Bind refuses
`format-placement-mismatch` if `tools` is not bound to a parts-emitting
format — `function_tool` is the one shipped.

## strategy/fenced_tools

Requires `instruct`. **Hidden.** Placement `{"@role": "message:system"}`
with `via: {"@role": "tool_catalog"}` (the catalog joins the system
prompt as text, whatever format the type is bound to);
fragment (system):

> You may call a tool by replying with exactly one fenced block:
> ```tool
> {"name": "<tool>", "input": {…}}
> ```
> and nothing else; you will be given the result and asked again.

Routing `{from: text, between: ["```tool\n", "\n```"], to: @role.calls,
consume: true, suffices: true}`. Turns (kernel §6): `call` →
```tool
{"name": "{name}", "input": {input}}
```
`result` → `Result of {name} ({id}):\n{output}`. The bind-time probe
renders `call` and reads it back through this routing and `tool_calls`.

# Glossary

Every LMCC word, one sentence each, in the order you need them. If a sentence here is wrong about the code, the code or this page is a bug.

## Level 1: one call

| word | meaning |
|---|---|
| **signature** | What goes in and what comes out: typed fields and an instruction. Written as a Python function. |
| **field** | One input or output of a signature: a name, a type, and a purpose. |
| **adapter** | How a signature's values are written into messages and read back from the reply. |
| **template** | The list of messages the adapter writes, with `{slots}` where values go. |
| **slot** | `{name}` in the template: an input's value goes here, or an output's placeholder. |
| **loop** | `{% for f in outputs %}…{% endfor %}`: repeat a piece of template once per field. |
| **reader** | How a reply is read. By default (`reader: {"kind": "derived"}`) it is the template read backwards: you never write a parser. |
| **bind** | Check a signature, an adapter and a model's abilities together; refuse before any money is spent. |
| **plan** | The checked result of `bind`. It renders requests and parses replies. |
| **render** | Build the exact request from input values. Pure: no network, no cost. |
| **parse** | Turn a reply into typed output values, or refuse. It never guesses. |
| **read** | `parse` plus the list of repairs the reader made to get the values. |
| **marker** | Fixed text of the template the reader looks for in a reply, such as `<answer>` or `Answer:`. |
| **repair** | Reading a misspelled marker (`<Answer>`, `**Answer:**`) as the template's spelling. Also a value slip (`42.`, `"positive"`, `None`) and a misspelled reasoning tag (`<Think>`). Always reported, never a guess. |
| **strict** | An adapter setting: `strict=True` reads replies exactly, with no repairs. |
| **truncated** | A reply the provider cut at its length limit (`finish_reason: "length"`); an output that may be cut refuses `parse-truncated`. |
| **refusal** | A named error with a `fix`: the next thing to do, as data. |

## Level 2: your own types

| word | meaning |
|---|---|
| **format** | How one type is written into a request (`write`) and read back from a reply (`read`). |
| **registry** | Where formats and transports are kept by name, so an adapter saved as JSON can refer to them. |
| **capture** | The piece of the reply found for one field; a format's `read` receives it. |
| **part** | One piece of a message: text, an image, a tool call, thinking… (lm15's word). |
| **writes** | What a format's `write` produces: `"text"` or `"parts"`. |
| **reads** | Which kinds of parts a format's `read` accepts, like `("tool_call",)`. |

## Level 3: values that travel differently

| word | meaning |
|---|---|
| **purpose** | What a field is for in the exchange: `plain`, `reasoning`, `tools`, `tools.calls`, `citations`… |
| **transport** | How fields of one purpose travel: where they go, where they are found, what the model is told. |
| **in_template** | `False` takes the field out of the template; the transport then carries it instead. |
| **put** | Where an input goes instead of a template slot: `request.tools` (a request setting) or `message:system` (into a message). |
| **`lmcc.find`, `put`, `when`, `choose`** | Helpers that build find rules, puts, predicates and `choose` lists; each returns the plain data you could write by hand. |
| **find** | Rules for where an output is found in the reply: `between` two markers, on lines starting with a prefix (`line_prefixed`), or in parts of one type (`from: "part:thinking"`). |
| **remove** | Cut what `find` took out of the text, so the rest of the reply does not contain it. |
| **complete_reply** | A value found this way (a tool call) is a whole reply; missing answer fields are fine. |
| **tell** | Extra text added to a message to tell the model what to do. |
| **request_settings** | Settings the transport adds to the request itself, like turning thinking on. |
| **written_as** | For one `put`, write the value with this other format (tools as text instead of native tools). |
| **requires** | Model abilities the transport needs; bind refuses if the model does not declare them. |
| **capabilities** | The abilities you declare a model has, like `native_reasoning`. Declared, never guessed. |
| **@purpose** | Inside a transport: "the field with this transport's purpose"; `@purpose.calls` is its `.calls` partner. |

## Level 4: conversations

| word | meaning |
|---|---|
| **turn** | One call of one signature, kept as values: inputs, steps, and outputs once finished. |
| **example** | A turn that did not really happen, shown to the model as a demonstration. |
| **step** | One thing that happened inside a turn: a model reply, or a tool result. |
| **turn slot** | A named place in the template where turns go: as messages (`lmcc.turns("name")`) or as text (`{% for m in name %}`). |
| **spelling** | How a transport writes past calls (`call`), tool results (`result`) and its hidden value (`value`, `position`) back into a request. |
| **replay** | Send a past reply exactly as it came (`recorded`), or always rebuild it from values (`values`). |

## Words that stay lm15's

`message`, `role` (of a message: system, user, assistant, tool), `part`, `request`, `config`, `tool_call`, `tool_result`, `thinking`. LMCC never renames them and never uses them for anything else.

## Old words (kernel 0.6)

Older notes, `decisions.md` before D-40, and the Go kernel at the tag `kernel-0.6` use these.

| 0.6 | 0.7 |
|---|---|
| strategy | transport |
| role (of a field), `Role[...]`, `@role` | purpose, `Purpose[...]`, `@purpose` |
| lens, `parse: {kind}` | reader, `reader: {kind}` |
| span | capture |
| `routings`, `consume`, `suffices`, `channel:` | `find`, `remove`, `complete_reply`, `part:` |
| `placement`, `controls.tools` | `put`, `request.tools` |
| `fragments`, `controls`, `via`, `visible` | `tell`, `request_settings`, `written_as`, `in_template` |
| `emits` | `writes` |
| strategy `turns: {call, result, write, position}` | transport `spelling: {call, result, value, position}` |
| patch (of a request) | request settings |
| `demos`, `history` | turns, turn slots |

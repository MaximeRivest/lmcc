# Refusal codes (normative)

**Version scope:** kernel 0.7. The extension refusals (`extension-undeclared`,
`extension-unsupported`; kernel §10) are distinct from malformed syntax: an
artifact that is internally inconsistent is malformed or undeclared, a host
that lacks a contract is unsupported. Never reinterpret one as the other.

Every refusal is a `Refusal` with a stable `code`, a `hint` naming the
exact offender and what to do, a `fix` (below) for every refusal that
fires before render, and for parse refusals a `partial` with what was
read. The corpus asserts codes and fixes; hints are for humans and may
improve without a version bump. Adding a code or a fix action is a
minor change; changing when a code fires, or renaming an action or its
parameters, is breaking.

| code | fires at | fix | meaning |
|---|---|---|---|
| `template-syntax` | construct | `edit-template` | bad template: bare brace, unclosed loop or guard, a turn slot placed twice or named `inputs`/`outputs`/`instruction`/`format`, a guard naming no placed slot, an attribute other than `role`/`kind`/`text` in a turn loop |
| `unknown-slot` | bind | `edit-template`, `assign-purpose` | slot names no field, or a dotted slot outside its loop; or a find rule/put targets `@purpose.sub` and no field bears that purpose |
| `unknown-reader` | construct/load/bind | `install-vocabulary`, `edit-entry` | `reader.kind` is neither `derived` nor a registered reader (`edit-entry` when it is not even a name) |
| `unknown-format` | load/dump | `install-vocabulary` | a `{"use": name}` format reference names nothing registered |
| `unknown-transport` | load/dump | `install-vocabulary` | a `{"use": name}` transport reference names nothing registered |
| `entry-malformed` | construct/load | `edit-entry` | structural problem; hint names the path (includes a find rule with no source, a `pattern` the bound dialect rejects, a bad predicate, a control outside the pinned lm15 request fields, a `system` message that does not lead the template, and a vocabulary reference whose factory rejects its `options` or returns malformed data) |
| `signature-malformed` | signature | `edit-signature` | field name not an ASCII identifier, duplicate name, bad direction, shape not an object |
| `version-incompatible` | load/bind | `match-version` | artifact needs a kernel, vocabulary, or extension version this implementation cannot honor |
| `extension-undeclared` | load/bind | `declare-extension` | a construct needs an extension family the artifact does not declare (a find rule carries `pattern` and no `pattern/*` is in `extensions`); hint names the construct's path |
| `extension-unsupported` | load/bind | `bind-extension` | the artifact declares an extension this host binds no implementation of |
| `already-registered` | registration | — | duplicate name without `exist_ok` |
| `capability-missing` | bind | `declare-capability`, `satisfy-predicate` | a transport's `when`/`requires`, a `choose` with no matching branch, or a reader's requirement fails against the declared facts |
| `not-readable` | bind | `edit-template` | the template cannot be read backwards; hint names the defect |
| `purpose-ambiguous` | bind | `edit-signature` | one purpose on two fields |
| `field-uncovered` | bind | `edit-template` | a visible input never rendered by the template |
| `field-double-covered` | bind | `edit-entry` | a field is both in the template and found by a transport |
| `setting-conflict` | bind | `edit-entry` | two transports, or a reader and a transport, set one request-control leaf (`config.<field>`, `tools`) to different values; the same value from both is not a conflict |
| `no-format` | bind (or, for composing formats, write/read) | `bind-format` | a structured shape with no format; hint carries the path (`answer`, `answer[].age`) |
| `format-shape-mismatch` | bind | `bind-format` | a format bound to a field whose shape it does not accept |
| `format-direction` | bind | `bind-format` | an input-only format on an output field, or the reverse |
| `format-capture-mismatch` | bind | `bind-format` | a find rule delivers a capture kind the field's format cannot read |
| `format-put-mismatch` | bind | `bind-format` | a put needs parts the field's format does not write |
| `spelling-drift` | bind | `edit-entry` | the representative `spelling.probe` (or default sample) cannot be written by `spelling.call`/`input_format` and read back through its text find rule and calls format with the same name and input; or, in a turns template (§3a), a hidden output found in text has no writer (a `pattern` find rule without `spelling.value`, text calls without `spelling.call`), a derived writer's format cannot write text, the calls format cannot write, or two fields share a capture the calls field does not own |
| `turns-layout` | bind | `edit-template` | a messages-form turn slot after the first message that renders an input (or `steps` before it), or a slot named like a signature field |
| `format-untrusted` | load | `place-udf` | the artifact ships a UDF and this runtime will not place code |
| `format-not-self-contained` | ship/load | `reship-udf` | a UDF's source reaches into free variables or non-module globals |
| `udf-tampered` | load | `reship-udf` | a shipped UDF's `sha256` does not match its source |
| `udf-unplaceable` | load | `place-udf` | a UDF's language has no placement in this host |
| `turn-not-renderable` | render | — | a turn value goes through a format whose `round_trip` is false or whose writer yields non-text parts where text is needed, the calls format yields no `tool_call` parts, or a text-form slot meets a message with a part that is not text |
| `turn-invalid` | turn/render | — | a turn that is not one of this plan's: another signature's fingerprint, a field the signature does not have, a tool step answering no pending call, a past turn with an unanswered call, a current turn rendered with pending calls, `finish` with pending calls or no model step, a malformed turn object |
| `turns-unplaced` | render | — | turns supplied for a slot the template does not place (or for the reserved `steps`), or a current turn with steps rendered by a template that places no slot |
| `unmapped-type` | signature | `edit-signature` | an annotation resolves to no shape |
| `missing-input` | render | — | no value supplied for a rendered field |
| `value-invalid` | render | — | a kernel-default format cannot spell the value (wrong kind, non-finite, null where not nullable, bad media part) |
| `format-write-error` | render | — | a format's `write` raised; hint names the field |
| `format-read-error` | parse | — | a format's `read` raised; hint names the field |
| `value-collides` | render | — | a spelled turn value contains a marker the reader or its writer reads |
| `parse-value` | parse | — | text a kernel-default format cannot read (`+5`, `maybe`, `null` where not nullable) |
| `parse-missing-fields` | parse | — | the reply lacks fields the reader expects; `partial` carries what was read |
| `parse-ambiguous` | parse | — | an anchor, close, tail, or JSON member appears twice — refused, never guessed; also two repaired marker spans that overlap (kernel §4a) |
| `parse-truncated` | parse | — | the provider cut the reply (`finish_reason: "length"`) and an output is missing or its capture ran to the end of the text; `partial` carries the outputs that ended before the cut (kernel §4a) |
| `reader-error` | parse | — | the reply does not fit the reader's document form at all |
| `response-malformed` | parse | — | the response is neither text nor an object with a content part list, or a part is not an object with string kind and optional string text (also checked at feed) |

## Fix actions (normative, closed)

A `fix` is the one next action that repairs the refusal, as plain data:
`{"action": <name>, ...parameters}`. It is machine-actionable: every
parameter is a name the caller can act on (a field, a purpose, a fact, a
vocabulary name, a locator into the artifact) — never prose. The
vocabulary is closed; a fix whose `action` or parameter set is not in
this table is a bug in the implementation. Every implementation emits the same
fix for the same refusal (the corpus pins it, `expect.fix`).

**Which refusals carry one.** Every refusal that fires *before render*
— at construct, signature, load, or bind — carries a `fix`; that is the
gate, and a gate that names the next step is the point of refusing
early. Refusals at render and parse carry none: their cause is a
program value or model text, and what to do about those (retry, ask
again, fall back) is orchestration, which lmcc refuses to be. The
registration refusal (`already-registered`) carries none: it is host
API misuse, not a defect in an artifact or a program. `no-format` is
the one code that can fire either side of render (a composing format
meeting an unformatted nested value); it carries its fix in both.

**One fix per refusal.** When several repairs exist (hide the field or
drop the find rule; bind a format or change the find rule), the fix names
the primary one — the repair that keeps the program and touches the
adapter, or, when the program is the offender, touches the program. The
hint prose may list the alternatives. This is a recommendation, not a
guess: the refusal is still the contract.

| action | parameters | do this |
|---|---|---|
| `install-vocabulary` | `kind` (`format` \| `transport` \| `reader`), `name` | register `name` in the registry (install the pack that provides it), or replace the reference with inline data / a shipped format |
| `match-version` | `entry` (`kernel`, `<kind>/<name>`, or `<family>/<name>`), `needs`, `provides` | run this artifact on a runtime that provides `needs`, or re-dump it from one that provides `provides` |
| `declare-extension` | `family`, `path` | add an entry of family `family` to the artifact's `extensions` (the contract that governs the construct at `path`), or rewrite the construct in core terms (`between`, `line_prefixed`) |
| `bind-extension` | `name`, `needs` | bind an implementation of extension `name` compatible with `needs` in this runtime (Python: `Registry(extensions=[...])` or `register_extension`), or run the artifact where one is bound, or rewrite the construct in core terms |
| `place-udf` | `language`, `path` | allow and place code of `language` in this runtime (Python: `Registry(allow_udf=True)`), or bind a runtime format for that type instead |
| `reship-udf` | `path` | correct the shipped source (self-contained; deps declared), then `ship` it again — the hash is recomputed |
| `edit-entry` | `path` | correct the artifact at `path` |
| `edit-template` | `path`, `slot`?, `field`? | correct the template message at `path` (`template[i]`; `template` when no single message is the offender); `slot` names the slot to fix, `field` names the field to add, anchor, or disambiguate |
| `edit-signature` | `field`?, `purpose`? | correct the signature; `field` names the offender (a dotted path for nested annotations), `purpose` the purpose to move |
| `assign-purpose` | `purpose` | give exactly one field the purpose `purpose` |
| `declare-capability` | `fact` | declare `fact: true` for this model, or choose a transport/reader that does not need it |
| `satisfy-predicate` | `purpose`, `predicate` | declare facts that make `predicate` (a kernel §6 predicate) true, or add an `else` branch / change `when` for the transport on `purpose` |
| `bind-format` | `field`, `key` | bind a format for `field` under `key` in the artifact, register one at runtime, or ship one; `key` is the field's type name when the frontend spelled one, else its most specific structural key, else `*`; the bound format must accept the field's shape, direction, the capture kinds its find rules deliver, and put |

**Locators.** `path` is the artifact path as the hint spells it:
`template[i]`, `reader`, `versions`, `transports['purpose']` (then
`.choose[i]`, `.when`, `.find[i]`, `.tell`, `.put`,
`.request_settings['key']`, `.in_template`, `.spelling`), `formats['key']` (then `.write`,
`.read`, `.describe`), `extensions`. Parameters marked `?` are optional;
every other parameter is present. Parameter values are strings, except
`predicate`, which is an object.

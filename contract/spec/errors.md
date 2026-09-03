# Refusal codes (normative)

Every refusal is a `Refusal` with a stable `code`, a `hint` naming the
exact offender and what to do, and for parse refusals a `partial` with
what was read. The corpus asserts codes; hints are for humans and may
improve without a version bump. Adding a code is a minor change;
changing when one fires is breaking.

| code | fires at | meaning |
|---|---|---|
| `template-syntax` | construct | bad template: bare brace, unclosed loop, unknown loop source |
| `unknown-slot` | bind | slot names no field, or a dotted slot outside its loop |
| `unknown-parse-kind` | construct/load/bind | `parse.kind` is neither `derived` nor a registered lens |
| `unknown-format` | load/dump | a `{"use": name}` format reference names nothing registered |
| `unknown-strategy` | load/dump | a `{"use": name}` strategy reference names nothing registered |
| `entry-malformed` | construct/load | structural problem; hint names the path (includes a routing with no source, a `pattern` regex outside the RE2 dialect, a bad predicate) |
| `signature-malformed` | signature | field name not an ASCII identifier, duplicate name, bad direction, shape not an object |
| `version-incompatible` | load | artifact needs a version this implementation cannot honor |
| `already-registered` | registration | duplicate name without `exist_ok` |
| `capability-missing` | bind | a strategy's `when`/`requires`, a `choose` with no matching branch, or a lens's requirement fails against the declared facts |
| `not-lensable` | bind | the template cannot be read backwards; hint names the defect |
| `role-ambiguous` | bind | one role on two fields |
| `field-uncovered` | bind | a visible input never rendered by the template |
| `field-double-covered` | bind | a field is both visible and routed |
| `control-conflict` | bind | two strategies, or a lens and a strategy, disagree on a request control |
| `no-format` | bind (or, for composing formats, write/read) | a structured shape with no format; hint carries the path (`answer`, `answer[].age`) |
| `format-shape-mismatch` | bind | a format bound to a field whose shape it does not accept |
| `format-direction` | bind | an input-only format on an output field, or the reverse |
| `format-span-mismatch` | bind | a routing delivers a span kind the field's format cannot read |
| `format-placement-mismatch` | bind | a placement needs parts the field's format does not emit |
| `format-untrusted` | load | the artifact ships a UDF and this runtime will not place code |
| `format-not-self-contained` | ship/load | a UDF's source reaches into free variables or non-module globals |
| `udf-tampered` | load | a shipped UDF's `sha256` does not match its source |
| `udf-unplaceable` | load | a UDF's language has no placement in this host |
| `demo-not-renderable` | render | a demo value goes through a format whose `round_trip` is false |
| `unmapped-type` | signature | an annotation resolves to no shape |
| `missing-input` | render | no value supplied for a rendered field |
| `value-invalid` | render | a kernel-default format cannot spell the value (wrong kind, non-finite, null where not nullable, bad media part, bad history item) |
| `format-write-error` | render | a format's `write` raised; hint names the field |
| `format-read-error` | parse | a format's `read` raised; hint names the field |
| `value-collides` | render | a spelled demo value contains a marker the lens reads |
| `parse-value` | parse | text a kernel-default format cannot read (`+5`, `maybe`, `null` where not nullable) |
| `parse-missing-fields` | parse | the reply lacks fields the lens expects; `partial` carries what was read |
| `parse-ambiguous` | parse | an anchor, close, tail, or JSON member appears twice — refused, never guessed |
| `lens-parse-error` | parse | the reply does not fit the lens's document form at all |
| `response-malformed` | parse | the response is neither text nor a part list |

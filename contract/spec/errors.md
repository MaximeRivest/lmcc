# Refusal codes (normative)

Every refusal is a `Refusal` with a stable `code`, a `hint` naming the
exact offender and what to do, a `fix` (below) for every refusal that
fires before render, and for parse refusals a `partial` with what was
read. The corpus asserts codes and fixes; hints are for humans and may
improve without a version bump. Adding a code or a fix action is a
minor change; changing when a code fires, or renaming an action or its
parameters, is breaking.

| code | fires at | fix | meaning |
|---|---|---|---|
| `template-syntax` | construct | `edit-template` | bad template: bare brace, unclosed loop, unknown loop source |
| `unknown-slot` | bind | `edit-template`, `assign-role` | slot names no field, or a dotted slot outside its loop; or a routing/placement targets `@role.sub` and no field bears that role |
| `unknown-parse-kind` | construct/load/bind | `install-vocabulary`, `edit-entry` | `parse.kind` is neither `derived` nor a registered lens (`edit-entry` when it is not even a name) |
| `unknown-format` | load/dump | `install-vocabulary` | a `{"use": name}` format reference names nothing registered |
| `unknown-strategy` | load/dump | `install-vocabulary` | a `{"use": name}` strategy reference names nothing registered |
| `entry-malformed` | construct/load | `edit-entry` | structural problem; hint names the path (includes a routing with no source, a `pattern` regex outside the RE2 dialect, a bad predicate) |
| `signature-malformed` | signature | `edit-signature` | field name not an ASCII identifier, duplicate name, bad direction, shape not an object |
| `version-incompatible` | load | `match-version` | artifact needs a version this implementation cannot honor |
| `already-registered` | registration | — | duplicate name without `exist_ok` |
| `capability-missing` | bind | `declare-capability`, `satisfy-predicate` | a strategy's `when`/`requires`, a `choose` with no matching branch, or a lens's requirement fails against the declared facts |
| `not-lensable` | bind | `edit-template` | the template cannot be read backwards; hint names the defect |
| `role-ambiguous` | bind | `edit-signature` | one role on two fields |
| `field-uncovered` | bind | `edit-template` | a visible input never rendered by the template |
| `field-double-covered` | bind | `edit-entry` | a field is both visible and routed |
| `control-conflict` | bind | `edit-entry` | two strategies, or a lens and a strategy, disagree on a request control |
| `no-format` | bind (or, for composing formats, write/read) | `bind-format` | a structured shape with no format; hint carries the path (`answer`, `answer[].age`) |
| `format-shape-mismatch` | bind | `bind-format` | a format bound to a field whose shape it does not accept |
| `format-direction` | bind | `bind-format` | an input-only format on an output field, or the reverse |
| `format-span-mismatch` | bind | `bind-format` | a routing delivers a span kind the field's format cannot read |
| `format-placement-mismatch` | bind | `bind-format` | a placement needs parts the field's format does not emit |
| `format-untrusted` | load | `place-udf` | the artifact ships a UDF and this runtime will not place code |
| `format-not-self-contained` | ship/load | `reship-udf` | a UDF's source reaches into free variables or non-module globals |
| `udf-tampered` | load | `reship-udf` | a shipped UDF's `sha256` does not match its source |
| `udf-unplaceable` | load | `place-udf` | a UDF's language has no placement in this host |
| `demo-not-renderable` | render | — | a demo value goes through a format whose `round_trip` is false |
| `unmapped-type` | signature | `edit-signature` | an annotation resolves to no shape |
| `missing-input` | render | — | no value supplied for a rendered field |
| `value-invalid` | render | — | a kernel-default format cannot spell the value (wrong kind, non-finite, null where not nullable, bad media part, bad history item) |
| `format-write-error` | render | — | a format's `write` raised; hint names the field |
| `format-read-error` | parse | — | a format's `read` raised; hint names the field |
| `value-collides` | render | — | a spelled demo value contains a marker the lens reads |
| `parse-value` | parse | — | text a kernel-default format cannot read (`+5`, `maybe`, `null` where not nullable) |
| `parse-missing-fields` | parse | — | the reply lacks fields the lens expects; `partial` carries what was read |
| `parse-ambiguous` | parse | — | an anchor, close, tail, or JSON member appears twice — refused, never guessed |
| `lens-parse-error` | parse | — | the reply does not fit the lens's document form at all |
| `response-malformed` | parse | — | the response is neither text nor a part list |

## Fix actions (normative, closed)

A `fix` is the one next action that repairs the refusal, as plain data:
`{"action": <name>, ...parameters}`. It is machine-actionable: every
parameter is a name the caller can act on (a field, a role, a fact, a
vocabulary name, a locator into the artifact) — never prose. The
vocabulary is closed; a fix whose `action` or parameter set is not in
this table is a bug in the implementation. Both kernels emit the same
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
drop the routing; bind a format or change the routing), the fix names
the primary one — the repair that keeps the program and touches the
adapter, or, when the program is the offender, touches the program. The
hint prose may list the alternatives. This is a recommendation, not a
guess: the refusal is still the contract.

| action | parameters | do this |
|---|---|---|
| `install-vocabulary` | `kind` (`format` \| `strategy` \| `lens`), `name` | register `name` in the registry (install the pack that provides it), or replace the reference with inline data / a shipped format |
| `match-version` | `entry` (`kernel` or `<kind>/<name>`), `needs`, `provides` | run this artifact on a runtime that provides `needs`, or re-dump it from one that provides `provides` |
| `place-udf` | `language`, `path` | allow and place code of `language` in this runtime (Python: `Registry(allow_udf=True)`), or bind a runtime format for that type instead |
| `reship-udf` | `path` | correct the shipped source (self-contained; deps declared), then `ship` it again — the hash is recomputed |
| `edit-entry` | `path` | correct the artifact at `path` |
| `edit-template` | `path`, `slot`?, `field`? | correct the template message at `path` (`template[i]`; `template` when no single message is the offender); `slot` names the slot to fix, `field` names the field to add, anchor, or disambiguate |
| `edit-signature` | `field`?, `role`? | correct the signature; `field` names the offender (a dotted path for nested annotations), `role` the role to move |
| `assign-role` | `role` | give exactly one field the role `role` |
| `declare-capability` | `fact` | declare `fact: true` for this model, or choose a strategy/lens that does not need it |
| `satisfy-predicate` | `role`, `predicate` | declare facts that make `predicate` (a kernel §6 predicate) true, or add an `else` branch / change `when` for the strategy on `role` |
| `bind-format` | `field`, `key` | bind a format for `field` under `key` in the artifact, register one at runtime, or ship one; `key` is the field's type name when the frontend spelled one, else its most specific structural key, else `*`; the bound format must accept the field's shape, direction, routed span kinds, and placement |

**Locators.** `path` is the artifact path as the hint spells it:
`template[i]`, `parse`, `versions`, `strategies['role']` (then
`.choose[i]`, `.when`, `.routings[i]`, `.fragments`, `.placement`,
`.controls['key']`, `.visible`), `formats['key']` (then `.write`,
`.read`, `.describe`). Parameters marked `?` are optional; every other
parameter is present. Parameter values are strings, except
`predicate`, which is an object.

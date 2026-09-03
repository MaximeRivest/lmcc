# Error codes (normative)

Every refusal carries a stable code and a message naming the exact
offender. The corpus asserts codes; messages are for humans and may improve
without a version bump. Adding a code is a minor change; changing when one
fires is breaking.

| code | fires at | meaning |
|---|---|---|
| `template-syntax` | construct | bad template: bare brace, unclosed loop, unknown loop source |
| `unknown-slot` | bake | slot names no field, or an output/dotted slot misused |
| `unknown-parse-kind` | construct/load/bake | parse.kind is neither the kernel lens `sections` nor a registered lens |
| `unknown-extract-kind` | construct/load | extractor not in the kernel algebra |
| `unknown-codec` | load/dump | codec name not registered |
| `unknown-strategy` | load/dump | strategy name not registered |
| `unknown-coercion` | parse | routing coercion not registered |
| `entry-malformed` | construct/load | structural problem; message names the path (includes a `pattern` regex outside the RE2 dialect) |
| `signature-malformed` | signature | field name not an ASCII identifier, duplicate name, bad direction, or shape not an object |
| `version-incompatible` | load | entry needs a version this implementation cannot honor |
| `already-registered` | registration | duplicate name without `exist_ok` |
| `capability-missing` | bake | a strategy's predicate/requires — or a lens's requirement — fails against the declared facts |
| `not-lensable` | bake | the template cannot be read backwards; message names the defect (no pattern block, unanchored hole, indistinct anchors) |
| `role-ambiguous` | bake | one role on two fields |
| `field-uncovered` | bake | visible input never rendered by the template |
| `field-double-covered` | bake | field is both a section and a routing target |
| `control-conflict` | bake | two strategies (or a lens and a strategy) disagree on a request control |
| `no-codec` | bake/render | structured shape (or non-scalar value) without a codec |
| `unmapped-type` | signature | annotation resolves to no shape and no host entry |
| `missing-input` | render | no value supplied for a rendered field |
| `value-invalid` | render/parse | scalar/enum/media value fails its shape |
| `value-collides` | render | a spelled demo value contains a marker the lens reads; the demo turn could not be read back as written |
| `codec-render-error` | render | codec raised; message names the field |
| `codec-parse-error` | parse | codec raised; message names the field |
| `parse-missing-fields` | parse | reply lacks fields the lens expects; `.partial` carries what was found |
| `parse-ambiguous` | parse | an anchor appears more than once in the reply — refused, never guessed |
| `lens-parse-error` | parse | reply does not fit the lens's document form at all (e.g. no JSON object) |
| `response-malformed` | parse | response is neither text nor a part list |

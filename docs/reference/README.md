# Reference index

**Version scope.** Kernel 0.7. Python is the one implementation; the
Go kernel that passed 0.6 is at the git tag `kernel-0.6` (D-41). Words: [the glossary](../glossary.md). The core needs no regex; a `pattern`
find rule declares its dialect as an extension (kernel §10,
[portability](../../contract/spec/portability.md)) and the host binds or refuses.

An index, not prose. Each line points to the normative text. The
contract (`contract/`) outranks this page; if they differ, the contract
is right and this page is wrong.

- Tutorial: [GUIDE.md](../../GUIDE.md). Tasks: [docs/howto](../howto/README.md). Words: [glossary](../glossary.md).
- Normative: [kernel.md](../../contract/spec/kernel.md) (sections cited as §n below).

## Python: `lmcc.__all__`

Signatures (kernel §1):

| name | what | section |
|---|---|---|
| `fn` | `@lmcc.fn`: parameters are inputs, return type is the output, docstring is the instruction | §1 |
| `Fn` | the decorated function: `.signature`, `.bind(adapter, capabilities=, registry=)` | §1 |
| `One` | `One[T]`: return one structured value, not the dataclass's fields | §1 |
| `Purpose` | `Purpose["reasoning", T]`: what a field is for | §1, [purposes.md](../../contract/spec/vocab/purposes.md) |
| `signature` | `signature(instructions, inputs={...}, outputs={...})` from annotations or raw shapes | §1 |
| `field` | `field(T, purpose=, desc=)`: annotate one `signature` entry | §1 |
| `SignatureCore` | the neutral form: `.instructions`, `.fields`, `.inputs()`, `.outputs()`, `.field_named()` | §1 |
| `Field` | one lowered field: `name`, `direction`, `shape`, `type`, `purpose`, `desc` | §1 |
| `signature_to_dict`, `signature_from_dict` | the plain-data form ([signature.schema.json](../../contract/schema/signature.schema.json)) | §1 |
| `typename` | the type's name as the frontend spells it | §1, §5 |

Adapters and templates (kernel §2):

| name | what | section |
|---|---|---|
| `adapter` | `adapter(messages=, reader=, transports=, formats=, name=, replay=)`; `reader={"kind": "derived", "markers": "exact"}` turns marker repair off | §2, §4a |
| `Adapter` | `.template`, `.reader`, `.transports`, `.formats`, `.replay`, `.bind()`, `.dump()` | §2 |
| `system`, `user`, `assistant`, `message` | one template message `{role, text}` | §2 |
| `turns` | `turns(slot="turns")`: a turn slot in messages form `{directive: "turns", slot?}` | §2, §3a |
| `Turn`, `ModelStep`, `ToolStep` | the turn record: `.tool()`, `.finish()`, `.pending_calls()`, `.to_dict()`, `Turn.from_dict()` | §3a |
| `Plan.turn`, `Plan.example`, `Plan.load_turn` | a new turn, an example turn, a turn from JSON with typed values | §3a |
| `RenderResult.step` | parse a reply and record it as the turn's next model step | §3a |
| `signature_fingerprint` | the `sha256:` identity a turn carries | §3a |
| `use` | `use(name, **options)`: a reference to a named format or transport | §5, §6 |

Bind, render, parse, stream (kernel §3, §4, §8):

| name | what | section |
|---|---|---|
| `bind` | `bind(adapter, signature, capabilities, registry) -> Plan`; every refusal fires here | §3 |
| `Plan` | `.render()`, `.read()`, `.parse()`, `.stream()`, `.describe()`, `.explain()`, `.skeleton()`, `.prefix()` | §3 |
| `RenderResult` | `.system`, `.messages`, `.request_settings`, `.request(model=None)` — an lm15 request minus its model | §3 |
| `Reader` | one reply document form: `split`, `join`, `format`, `requires`, `request_settings`, `skeleton`, `stream` | §4 |
| `Reading` | what `plan.read(reply)` returns: `.values`, `.repairs` (marker, unclosed, ignored — in order), `.clean` | §4a |
| `Stream` | `.feed(delta) -> [event]`, `.finish(finish_reason=None) -> StreamResult` | §8 |
| `StreamResult` | `.events`, `.values`, `.repairs` | §8 |

Formats (kernel §5, §7):

| name | what | section |
|---|---|---|
| `Format` | the protocol: `accepts`, `direction`, `writes`, `round_trip`, `reads`, `write`, `read`, `describe` | §5 |
| `make_format` | build a `Format` from functions | §5 |
| `format` | `format(T, write=, read=, describe=)`: bind `T` in the default registry | §5 |
| `ship` | serialize a function-built format as a UDF entry (language, deps, sha256, author) | §5 |
| `Capture` | what a find rule or the reader captured: `.parts`, `.text`, `.of(kind)`, `.kinds()` | §5, §6 |

Transports (kernel §6):

| name | what | section |
|---|---|---|
| `Transport` | `when`, `requires`, `in_template`, `tell`, `request_settings`, `put`, `written_as`, `find`, `spelling`, or `choose` | §6 |

Registry and artifact (kernel §5, §6, §9):

| name | what | section |
|---|---|---|
| `Registry` | `Registry(allow_udf=, extensions=)`: `register_format`, `register_transport`, `register_reader`, `register_extension`, `format`, `describe` — `extensions=()` is a core-only host | §5, §6, §10 |
| `native_extensions()`, `ExtensionBinding`, `PatternBinding` | what this runtime binds by default; the protocol a host implements to bind its own | §10 |
| `lmcc_lm15.request(rendered, model=, config=, override=)` | an `lm15.Request`; the plan's request settings are the base, a contradicting Config raises `ConfigConflict` | §3 |
| `lmcc_lm15.parse(plan, response)`, `lmcc_lm15.read(plan, response)`, `lmcc_lm15.stream(plan, events)`, `lmcc_lm15.step(rendered, response)` | typed values (and repairs) from an `lm15.Response`/`Message`; drive the sans-I/O stream; record a reply as a turn's next step. Each passes the response's `finish_reason`, so a cut reply refuses `parse-truncated` | §3, §3a, §4a, §8 |
| `default_registry` | the registry `lmcc.format` and `Fn.bind` use when none is given | §5 |
| `dump`, `load` | the artifact ([entry.schema.json](../../contract/schema/entry.schema.json)); `load` never runs a UDF | §5, §9 |
| `KERNEL_VERSION` | `"0.8.0"` | §9 |

Refusals:

| name | what | section |
|---|---|---|
| `Refusal` | `.code`, `.hint`, `.fix`, `.partial`, `.describe()` | §3, [errors.md](../../contract/spec/errors.md) |
| `refuse` | `refuse(code, hint, fix=, partial=)`: raise one | [errors.md](../../contract/spec/errors.md) |

## Error codes and fix actions

The table of codes, when each fires, and its fix action is
[contract/spec/errors.md](../../contract/spec/errors.md). The fix
payload schema is [fix.schema.json](../../contract/schema/fix.schema.json).
This page does not copy the table.

## Vocabulary

Facts: [capabilities.md](../../contract/spec/vocab/capabilities.md).
Purposes: [purposes.md](../../contract/spec/vocab/purposes.md). Every word: [the glossary](../glossary.md). How an entry
graduates: [vocab/README.md](../../contract/spec/vocab/README.md).

The std pack (`python/lmcc_std`; install with
`lmcc_std.install(registry)`):

| entry | spec |
|---|---|
| `format/json` | [format-json.md](../../contract/spec/vocab/format-json.md) |
| `format/table` | [format-table.md](../../contract/spec/vocab/format-table.md) |
| `format/scaled_number` | [format-scaled_number.md](../../contract/spec/vocab/format-scaled_number.md) |
| `transport/prefix_cot`, `transport/reasoning_tags`, `transport/native_reasoning` | [transport-reasoning.md](../../contract/spec/vocab/transport-reasoning.md) |
| `reader/json_object` | [reader-json_object.md](../../contract/spec/vocab/reader-json_object.md) |

The DSPy frontend (`python/lmcc_dspy`): `lower(signature, registry=)`,
`Lowered` (`.signature`, `.history_field`, `.split_inputs()`),
`adapter(registry)`, `entry()`, `bind_dspy_types(registry)`. Claimed
features: `python/tests/dspy/test_catalog.py`.

## Conformance

The corpus: [contract/corpus/README.md](../../contract/corpus/README.md).
The harness and driver protocol: [contract/harness/runner.py](../../contract/harness/runner.py), kernel.md §9; a reference driver to copy: [python_driver.py](../../contract/harness/python_driver.py).
One command: `./check`.

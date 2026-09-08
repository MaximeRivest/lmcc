# Reference index

**Version scope.** Kernel 0.3. The core needs no regex; a `pattern`
routing declares its dialect as an extension (kernel §10,
[portability](../../contract/spec/portability.md)) and the host binds or refuses.

An index, not prose. Each line points to the normative text. The
contract (`contract/`) outranks this page; if they differ, the contract
is right and this page is wrong.

- Tutorial: [GUIDE.md](../../GUIDE.md). Tasks: [docs/howto](../howto/README.md).
- Normative: [kernel.md](../../contract/spec/kernel.md) (sections cited as §n below).

## Python: `lmcc.__all__`

Signatures (kernel §1):

| name | what | section |
|---|---|---|
| `fn` | `@lmcc.fn`: parameters are inputs, return type is the output, docstring is the instruction | §1 |
| `Fn` | the decorated function: `.signature`, `.bind(adapter, capabilities=, registry=)` | §1 |
| `One` | `One[T]`: return one structured value, not the dataclass's fields | §1 |
| `Role` | `Role["reasoning", T]`: a role name on a field | §1, [roles.md](../../contract/spec/vocab/roles.md) |
| `signature` | `signature(instructions, inputs={...}, outputs={...})` from annotations or raw shapes | §1 |
| `field` | `field(T, role=, desc=)`: annotate one `signature` entry | §1 |
| `SignatureCore` | the neutral form: `.instructions`, `.fields`, `.inputs()`, `.outputs()`, `.field_named()` | §1 |
| `Field` | one lowered field: `name`, `direction`, `shape`, `type`, `role`, `desc` | §1 |
| `signature_to_dict`, `signature_from_dict` | the plain-data form ([signature.schema.json](../../contract/schema/signature.schema.json)) | §1 |
| `typename` | the type's name as the frontend spells it | §1, §5 |

Adapters and templates (kernel §2):

| name | what | section |
|---|---|---|
| `adapter` | `adapter(messages=, parse=, strategies=, formats=, name=)` | §2 |
| `Adapter` | `.template`, `.parse`, `.strategies`, `.formats`, `.bind()`, `.dump()` | §2 |
| `system`, `user`, `assistant`, `message` | one template message `{role, text}` | §2 |
| `demos`, `history`, `directive` | a directive `{directive: "demos" \| "history"}` | §2, §3 |
| `use` | `use(name, **options)`: a reference to a named format or strategy | §5, §6 |

Bind, render, parse, stream (kernel §3, §4, §8):

| name | what | section |
|---|---|---|
| `bind` | `bind(adapter, signature, capabilities, registry) -> Plan`; every refusal fires here | §3 |
| `Plan` | `.render()`, `.parse()`, `.stream()`, `.describe()`, `.explain()`, `.skeleton()`, `.prefix()` | §3 |
| `RenderResult` | `.system`, `.messages`, `.patch`, `.request(model=None)` — an lm15 request minus its model | §3 |
| `Lens` | one reply document form: `split`, `join`, `format`, `requires`, `patch`, `skeleton`, `stream` | §4 |
| `Stream` | `.feed(delta) -> [event]`, `.finish() -> StreamResult` | §8 |
| `StreamResult` | `.events`, `.values` | §8 |

Formats (kernel §5, §7):

| name | what | section |
|---|---|---|
| `Format` | the protocol: `accepts`, `direction`, `emits`, `round_trip`, `reads`, `write`, `read`, `describe` | §5 |
| `make_format` | build a `Format` from functions | §5 |
| `format` | `format(T, write=, read=, describe=)`: bind `T` in the default registry | §5 |
| `ship` | serialize a function-built format as a UDF entry (language, deps, sha256, author) | §5 |
| `Span` | what a routing or the lens captured: `.parts`, `.text`, `.of(kind)`, `.kinds()` | §5, §6 |

Strategies (kernel §6):

| name | what | section |
|---|---|---|
| `Strategy` | `when`, `requires`, `visible`, `fragments`, `controls`, `placement`, `routings`, or `choose` | §6 |

Registry and artifact (kernel §5, §6, §9):

| name | what | section |
|---|---|---|
| `Registry` | `Registry(allow_udf=, extensions=)`: `register_format`, `register_strategy`, `register_lens`, `register_extension`, `format`, `describe` — `extensions=()` is a core-only host | §5, §6, §10 |
| `native_extensions()`, `ExtensionBinding`, `PatternBinding` | what this runtime binds by default; the protocol a host implements to bind its own | §10 |
| `lmcc_lm15.request(rendered, model=, config=, override=)` | an `lm15.Request`; the plan's patch is the base, a contradicting Config raises `ConfigConflict` | §3 |
| `lmcc_lm15.parse(plan, response)`, `lmcc_lm15.stream(plan, events)` | typed values from an `lm15.Response`/`Message`; drive the sans-I/O stream from `lm.stream(...)` | §3, §8 |
| `default_registry` | the registry `lmcc.format` and `Fn.bind` use when none is given | §5 |
| `dump`, `load` | the artifact ([entry.schema.json](../../contract/schema/entry.schema.json)); `load` never runs a UDF | §5, §9 |
| `KERNEL_VERSION` | `"0.4.0"` | §9 |

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
Roles: [roles.md](../../contract/spec/vocab/roles.md). How an entry
graduates: [vocab/README.md](../../contract/spec/vocab/README.md).

The std pack (`python/lmcc_std`, `go/lmccstd`; install with
`lmcc_std.install(registry)` / `lmccstd.Install(reg)`):

| entry | spec |
|---|---|
| `format/json` | [format-json.md](../../contract/spec/vocab/format-json.md) |
| `format/table` | [format-table.md](../../contract/spec/vocab/format-table.md) |
| `format/scaled_number` | [format-scaled_number.md](../../contract/spec/vocab/format-scaled_number.md) |
| `strategy/prefix_cot`, `strategy/reasoning_tags`, `strategy/native_reasoning` | [strategy-reasoning.md](../../contract/spec/vocab/strategy-reasoning.md) |
| `lens/json_object` | [lens-json_object.md](../../contract/spec/vocab/lens-json_object.md) |

The DSPy frontend (`python/lmcc_dspy`): `lower(signature, registry=)`,
`Lowered` (`.signature`, `.history_field`, `.split_inputs()`),
`adapter(registry)`, `entry()`, `bind_dspy_types(registry)`. Claimed
features: `python/tests/dspy/test_catalog.py`.

## Go: package `lmcc` (`go doc ./lmcc`)

User guide: [go/README.md](../../go/README.md). Full listing:
`go doc -all ./lmcc` in `go/`.

| name | what | section |
|---|---|---|
| `StructSignature(instructions, in, out, reg)` | lower two structs by `lmcc:"name,role=,desc="` tags | §1 |
| `SignatureOf(instructions, inputs, outputs, reg)` | lower from `*Object` entries of types, samples, shapes, or `Spec` | §1 |
| `SignatureFromJSON`, `SignatureToJSON` | the plain-data form | §1 |
| `Signature`, `Field`, `Spec` | the lowered form; `Inputs()`, `Outputs()`, `FieldNamed()` | §1 |
| `NewAdapter(name, template, parse, strategies, formats, extensions)` | build from data; template syntax and the extension declaration validated | §2, §10 |
| `NewRegistry()`, `NewCoreRegistry()`, `RegisterExtension(b, existOK)`, `NativeExtensions()` | what this host binds beyond the core; core-only binds nothing | §10 |
| `Adapter` | `.Bind(sig, caps, reg)`, `.Dump(reg)` | §2 |
| `Bind(adapter, sig, caps, reg)` | every refusal fires here | §3 |
| `Plan` | `Render`, `Parse`, `Stream`, `Describe`, `DescribeStreaming`, `Explain`, `Skeleton`, `Prefix` | §3 |
| `RenderResult` | `.Messages`, `.Patch` | §3 |
| `Stream`, `StreamResult` | `Feed(delta)`, `Finish()`; `.Events`, `.Values` | §8 |
| `Lens`, `BaseLens`, `DerivedLens`, `Anchor`, `Spelled` | one document form; the template read backwards; a `{Name, Text}` pair | §4 |
| `StreamingLens`, `LensStreamReducer` | the optional streaming face of a vocabulary lens | §8 |
| `Format`, `FormatSpec`, `FormatFactory`, `LensFactory` | the format protocol; a function-built format; named factories | §5 |
| `Strategy`, `NewStrategy`, `StrategyFactory` | how a meaning travels, as data | §6 |
| `Registry`, `NewRegistry` | `RegisterFormat`, `RegisterStrategy`, `RegisterLens`, `BindFormat`, `BindFormatByName`, `Describe`; `.AllowUDF` | §5, §6 |
| `Load(entry, reg)`, `Dump(adapter, reg)` | the artifact; `Load` never runs a UDF | §5, §9 |
| `Error`, `AsError` | a refusal: `.Code`, `.Detail`, `.Fix`, `.Partial`, `.Describe()` | [errors.md](../../contract/spec/errors.md) |
| `Object`, `NewObject`, `Obj` | an insertion-ordered JSON object: `Get`, `Set`, `Str`, `List`, `Object`, `Keys` | — |
| `Span`, `SpanOfText` | what a routing or the lens captured: `.Text()`, `.Of(kind)` | §5, §6 |
| `MarshalJSON`, `ParseJSON`, `Equal`, `DeepClone` | JSON text and JSON equality over plain values | §9 |
| `Strip`, `RStrip`, `ReadInteger`, `ReadNumber`, `ReadBoolean`, `ReadValue`, `SpellValue`, `FormatNumber`, `RoundHalfEven` | the §7a text rules | §7a |
| `TypeName`, `StructuralKeys`, `FormatKey`, `IsStructured`, `IsMedia`, `NullableBase`, `ShapeSummary` | shapes and resolution keys | §1, §5 |
| `MakeMessage`, `TextPart`, `MergeTextParts`, `AsParts`, `ResponseTextAndParts` | messages and parts | §3 |
| `Digest`, `QuoteJSON`, `Members`, `Member`, `IsIdentifier`, `KernelVersion` | the UDF hash rule; JSON helpers; the version | §5, §9 |

## Go: package `lmccstd` (`go doc ./lmccstd`)

| name | what |
|---|---|
| `Install(reg)` | register the whole pack |
| `JSONFormat`, `TableFormat`, `ScaledNumberFormat` | `format/json`, `format/table`, `format/scaled_number` |
| `JSONObjectLens` | `lens/json_object` |
| `Version` | `"0.1.0"` |

## Conformance

The corpus: [contract/corpus/README.md](../../contract/corpus/README.md).
The harness and driver protocol: [contract/harness/runner.py](../../contract/harness/runner.py), kernel.md §9.
One command: `./check`.

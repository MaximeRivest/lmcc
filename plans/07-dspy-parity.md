# Plan 07 — DSPy signature parity

**Motivation.** "Anything a DSPy signature can hold, a SignatureCore can
carry" must be a checked claim, not a belief. The check is a *total
lowering with refusal*: every DSPy signature either lowers to a
SignatureCore that carries all of its information, or refuses naming
the exact attribute it cannot carry. Silent loss is the forbidden
outcome (rule 3).

**How the claim is made checkable.**

1. `python/lmcc_dspy/` — a frontend pack: `lower(dspy_signature,
   registry) -> SignatureCore`, plus the DSPy-dialect entry (the
   `[[ ## name ## ]]` sections lens, already pinned by corpus 21).
2. A **feature catalog** test (`tests/test_dspy_catalog.py`): one DSPy
   signature per row of the table below. Each row must either lower and
   round-trip (render → parse, both kernels via corpus cases of the
   lowered data) or refuse with the named code. A DSPy feature absent
   from the catalog is *not claimed*.
3. A **differential** check against DSPy's own `ChatAdapter.format`:
   for every catalog row, DSPy's messages and LMCC's render of the
   DSPy-dialect entry compare byte for byte. This is the strongest
   possible "make sure": the prompts are DSPy's prompts. It needs
   `dspy` importable; `./check` runs it when a DSPy dev shell exists
   and **fails loudly, never skips**, when the step is requested but
   the shell is missing.

## Inventory (upstream `stanfordnlp/dspy` main @ 59ce7601, 2026-08-31)

| DSPy holds | SignatureCore today | status | needs |
|---|---|---|---|
| instructions (docstring) | `instructions` | ✅ | — |
| field order, input/output | ordered `fields`, `direction` | ✅ | — |
| name (Python identifier) | ASCII identifier | ✅ (Unicode names refuse `signature-malformed`, stated) | — |
| `desc` / pydantic `description` | `desc` | ✅ | — |
| `prefix`, `format`, `parser` | — | ✅ **deprecated upstream (#9394): "has no effect in DSPy"**; still stored in `json_schema_extra` and in `dump_state` for round-trip only | dropped by the lowering, stated in its spec — dropping what DSPy itself ignores loses nothing DSPy would have shown a model. (Decisions A and H withdrawn.) |
| `IS_TYPE_UNDEFINED` marker (field declared without a type → `str`) | — | no prompt effect (only `Predict` coercion, `predict.py:208`) | not carried, stated |
| duplicate input/output names | `signature-malformed` | ✅ parity (#9432 rejects them too) | — |
| `append_instructions` (#9923), `dump_state`/`load_state` (instructions + per-field desc) | plain-data edits; SignatureCore *is* that state | ✅ | — |
| pydantic constraints (`ge`, `min_length`, …) | JSON-Schema keywords carried untouched in `shape` | ✅ carried, ⚠ not shown: the mechanical `{f.schema}` hint ignores them; DSPy prints `Constraints: …` | small: hint rule lists constraint keywords (kernel §3), corpus case |
| `str`, `int`, `float`, `bool` | scalars | ✅ | — |
| `list[X]`, `dict`, nested generics | array/object shapes | ⚠ a codec must be bound **by field name in the entry**, but adapters are signature-independent, so no DSPy-generic adapter can exist | **B**: shape-keyed default bindings in entries (`"codecs": {"@structured": {"kind": "json"}}`) with name bindings winning |
| `Literal[...]` | `enum` | ✅ strings/integers; other literal types refuse | — |
| `Optional[X]`, `X \| None` | shape carries `anyOf`/`null`; parse refuses missing | ❌ no null rule | **C**: nullable shapes read/write `null` (kernel §7a) |
| pydantic `BaseModel`, `TypedDict`, dataclass | `model_json_schema()` as shape (with `$defs`), json codec, host lift/lower | ⚠ works per registered type; no *family* binding ("every BaseModel subclass") | **E**: host entries may compute `shape` from the type |
| non-optional `Union[str, int]` | `anyOf` | ❌ reading is ambiguous by construction | refuse at lower (`unmapped-type`), stated |
| `Enum` classes, `datetime` | enum / string+format | ✅ via pydantic schema + host lift | — |
| `Any` | — | refuse (`unmapped-type`) | — |
| `dspy.Image/Audio/File/Document` inputs | `{"media": …}` | ✅ | — |
| `dspy.History` input | the `history` directive | ⚠ DSPy history turns are **field dicts** rendered through the signature; LMCC history expects `{role, content}` messages | **D**: history turns may be field dicts, rendered like demos (template + lens) |
| `dspy.Reasoning` output (native response type) | role `reasoning` + `native_reasoning` | ✅ | — |
| `dspy.Tool`, `list[Tool]`, `ToolCalls`, `Citations` | roles `tools`/`citations` reserved | ❌ no strategies | plan 04 |
| `dspy.Code` | — | ❌ | vocabulary: `codec/code` (fenced block) |
| defaults / incomplete demos | render refuses `missing-input` | ❌ DSPy renders "Not supplied for this particular example." | **F**: entry-declared placeholder for missing demo inputs, or keep refusing (decide) |
| string syntax `"q, ctx: list[str] -> a"` | — | frontend parses, or lowers a built `dspy.Signature` | ✅ trivial |
| `with_instructions`, `append`, `insert`, `delete`, `equals` | plain-data edits | ✅ trivial | — |

## DSPy adapters (the differential check needs them)

| DSPy adapter | LMCC document form | status |
|---|---|---|
| `ChatAdapter` (`[[ ## name ## ]]`) | `sections`, DSPy dialect (corpus 21) | ✅ |
| `JSONAdapter` | `lens/json_object` (mode, gated) | ✅ |
| `XMLAdapter` (reworked upstream) | `sections` with close markers (corpus 20) covers plain fields; upstream now **escapes `<`/`&` in string outputs and nests structured outputs as XML** | ⚠ needs a vocabulary `lens/xml` with escaping and nesting — note this is DSPy's answer to the collision problem D-15 refuses on; as a *different document form* it belongs in vocabulary, not the kernel |
| `BAMLAdapter` | — | ❌ a schema-rendering style; vocabulary later |
| `TwoStepAdapter` | — | out of scope: two calls composed, a program not an adapter |
| parsing: `json_repair` + `ast.literal_eval` fallback + pydantic validation | refuse (`value-invalid`, `codec-parse-error`) | by design different: LMCC never guesses; recovery is plan 02 (combinators) and plan 06 (fix hints), declared as data |
| native tool-call history replay (#9823/#9824) | — | plan 04 + decision D |

## Decisions required before code (each: spec → corpus → both kernels)

- **B** shape-keyed default codec bindings in entries — the largest gap;
  without it LMCC cannot express a DSPy-style "one adapter for every
  signature" at all when signatures have structured fields.
- **C** nullable scalars.
- **D** history turns as field dicts.
- **E** host type families.
- **F** incomplete demos: refuse (current) or placeholder text declared
  in the entry.

## Acceptance criteria

- [ ] Decisions B–F ratified and logged (`decisions.md`).
- [ ] Kernel spec amended for each; corpus cases for each (lowered
      data, so the Go kernel proves them without DSPy).
- [ ] `python/lmcc_dspy` lowers every catalog row or refuses by name;
      `tests/test_dspy_catalog.py` covers every row of the table.
- [ ] Differential check: catalog prompts equal `dspy.ChatAdapter`
      output byte for byte (DSPy-dialect entry).
- [ ] Rows marked plan 04 stay listed as *not claimed* until plan 04.

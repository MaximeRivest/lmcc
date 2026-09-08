# Plan 04 — strategy vocabularies for `tools` and `citations`

**Done (kernel 0.5, D-37).** Shipped as designed, with three changes the
work forced: the text tier reads fences with `between` (core), not a
pattern extension; `cli_text` became `fenced_tools` and `xml_blocks` was
not built (no demand); a tool-call reply is a *call turn* (`suffices`),
never a missing-fields refusal. Live: `python/integration/lm15_tools_citations.py`.

**Motivation.** `roles.md` reserves `tools`, `citations`, `citable`;
the mechanics (hide, route, fragments, predicate) already serve any
role — but no shipped strategies exist, so the roles are names without
conduct.

**Design sketch.**
- `tools` role, three rules mirroring the reasoning trio:
  - `native_fc`: predicate `native_function_calling`; controls carry
    tool declarations; routing reads `parts {part: "tool_call"}`.
  - `cli_text`: fragment teaches a CLI spelling (`!call name {json}`);
    a declared pattern extension reads it; predicate `instruct` remains a model fact.
  - `xml_blocks`: same shape, XML spelling.
- `citations` role:
  - `native_citations`: routing over citation parts.
  - `inline_markers`: fragment teaches `[n]` markers + a routing that
    extracts them against a `citable`-role input field.
- Depends on Plan 03 for result spelling; land read-side first if
  sequenced separately.

**Acceptance criteria.**
- [x] `spec/vocab/strategy-tools.md` and `strategy-citations.md`
      (fragments, routings, controls, predicates — exact spellings).
- [x] `roles.md` rows flip from *reserved* to *live*.
- [x] Corpus: per rule, a render case (fragment bytes) and a parse case
      (routing recovery); capability-refusal cases for the native pair.
- [x] Same signature runs unchanged across all three tool rules in a
      test (the orthogonality proof).
- [x] `./check` green.

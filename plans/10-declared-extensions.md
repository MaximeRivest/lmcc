# Plan 10 — shared core and declared execution extensions

## Motivation

Plan 09 exposed regex dialect differences between three implementations.
Requiring broad regex semantics and a stdlib-only Python kernel led to an
experimental custom matcher. Owning that engine is not LMCC's mission.
D-31 ratifies a small exact core plus explicit, versioned optional extensions.
`contract/spec/portability.md` defines the direction, not a shipped schema.

## Design

Separate semantic requirements from host bindings. Frontends declare requirements;
hosts provide compatible implementations or refuse before a usable plan is returned.
Keep model capability facts separate from host execution support.

Define the smallest useful routing-pattern contract from real adapter needs.
Evaluate mature libraries against its cases. Do not choose a backend merely
because it passes five examples, or build an engine merely to avoid a dependency.

Keep the existing 0.2 contract readable and its cases unchanged until migration.
Version the requirements, discovery, bindings, and refusal behavior deliberately.
This plan gates regex-related work in plan 09; its other safety fixes remain useful.

## Status

**Phase 1 — the mechanism — landed as kernel 0.3 (D-33).** The contract
now has a declaration (`entry.extensions`), a binding table
(`Registry.extensions`), discovery (`registry.describe()["extensions"]`),
inspection (`plan.describe()["extensions"]`), three refusals with fixes,
scoped harness claims, and one extension (`pattern/legacy-re2`, the
migration bridge). **Phase 2 — a rigorously specified pattern dialect
with library evidence — is open** and is the only regex work left.

## Acceptance criteria

Phase 1 (done, kernel 0.3):

- [x] Enumerate mandatory core operations and their conformance cases (`spec/portability.md`).
- [x] Specify named extension identity, version compatibility, and artifact requirements (kernel §10, `spec/extensions/README.md`, `schema/entry.schema.json`).
- [x] Specify host support discovery independently of model capabilities (`Registry.extensions`, `describe()`).
- [x] Specify binding inspection, unsupported requirements, and exact fix actions (`plan.describe()["extensions"]`; `extension-undeclared` → `declare-extension`, `extension-unsupported` → `bind-extension`, `version-incompatible` → `match-version`).
- [x] Author cases first for supported, missing, mismatched-version, and incompatible bindings (cases 40, 42, 91–95).
- [x] Test that a core-only host refuses an extension-dependent artifact before model I/O (case 92; `tests/test_extensions.py`; `go/lmcc/extensions_test.go`).
- [x] Test identical extraction and streaming results across two claimed implementations (harness: Go passes 40 and 42 byte-exactly with matching stream traces).
- [x] Specify the migration of legacy bare `pattern` strings without silently changing their meaning (kernel §10: undeclared refuses; `pattern/legacy-re2` is defined as 0.2's behavior).
- [x] Add schemas and harness support for scoped claims; never count missing extensions as passes (`requires` generalized; drivers bind exactly what is listed).
- [x] Implement in Python and Go; update docs, plans, versions, decisions; `./check` green.

Phase 2 (open):

- [ ] Define routing-pattern syntax and all observable matching semantics, with Unicode and capture cases, as a new contract `pattern/<name>` — not by tightening `legacy-re2`.
- [ ] Compare mature libraries (Go `regexp`, Python `re`/`regex`, RE2 bindings, Rust `regex`) against those cases; record limits, dependencies, and rejected alternatives; pick bindings per kernel by evidence.
- [ ] Test the TypeScript clean-room implementation independently against 0.3 (it currently targets 0.2 and will refuse `version-incompatible`; its regex gaps become a *claim* question, not a defect).
- [ ] Decide whether `udf:<language>` placement joins the extension mechanism (`udf/<language>`) in a later version; today it stays a separate `requires` form because unifying it would change existing refusal codes without a corpus reason.
- [ ] Decide whether trust admission for bindings that start services needs a declaration beyond the binding label.

## Trade-offs

Optional support makes compatibility explicit rather than universal.
Artifacts and hosts need more metadata. Mature libraries can add packaging costs.
A remote executor adds latency and host policy requirements. None permits hidden inference.

The plan does not select identifiers, a wire protocol, a regex library, or a custom engine.
Those choices require evidence and review before implementation.

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

**Phase 1 — the mechanism — landed as kernel 0.3 (D-33, D-34).** The
contract has a declaration (`entry.extensions`), a binding table
(`Registry.extensions`), discovery, inspection, three refusals with fixes,
scoped harness claims, one extension (`pattern/legacy-re2`), and the
constructor declares that default tier for you.

**Phase 2 is demand-driven, not scheduled.** The earlier text here asked
for a rigorously authored regex dialect and a library benchmark. That
was inertia from the era when regex was mandatory (D-14); D-31 removed
the mandate and D-34 removes the task. Regex is not in LMCC's one
sentence; `between` and `line_prefixed` cover the extraction real
adapters do (the corpus has one `pattern` parse case, and it could be
`line_prefixed`). The next regex work starts when an adapter needs what
the default tier cannot give, and it is *binding an engine* — a row in
the tier table of `spec/extensions/README.md` — never authoring a
grammar or a matcher.

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

Phase 2 (when demanded — each item needs a real adapter that asks for it):

- [ ] **Exact, one language:** a contract named for one engine and version (`pattern/cpython-re` at a Python minor; `pattern/go-regexp` at a Go minor). Spec = "that engine, that version, these cases"; the binding is the runtime itself; other runtimes refuse `extension-unsupported`. Acceptance: spec file, index row, cases that `requires` it, a native binding that claims it only when the runtime matches.
- [ ] **Exact, every language:** one shared engine, bound from a pack (RE2 bindings, or a Rust `regex` build as WebAssembly). Acceptance: the same cases pass byte-exactly through Python and Go via the *same* engine; the dependency lives outside the kernel (`test_agent_surface` stays green); costs recorded.
- [ ] Constructor default for *named* strategies: today only inline strategies are seen (kernel §10); if a pack ever emits `pattern`, decide whether the pack declares it or bind fills it.

Housekeeping (not regex, still open):

- [ ] Test the TypeScript clean-room implementation against 0.3 (it targets 0.2 and refuses `version-incompatible`); its regex gaps become a *claim* question, not a defect.
- [ ] Decide whether `udf:<language>` placement joins the extension mechanism (`udf/<language>`) in a later version; today it stays a separate `requires` form because unifying it would change existing refusal codes without a corpus reason.
- [ ] Decide whether trust admission for bindings that start services needs a declaration beyond the binding label.

## Trade-offs

Optional support makes compatibility explicit rather than universal.
Artifacts and hosts need more metadata. Mature libraries can add packaging costs.
A remote executor adds latency and host policy requirements. None permits hidden inference.

The plan does not select identifiers, a wire protocol, a regex library, or a custom engine.
Those choices require evidence and review before implementation.

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

## Acceptance criteria

- [ ] Enumerate mandatory core operations and their conformance cases.
- [ ] Specify named extension identity, version compatibility, and artifact requirements.
- [ ] Specify host support discovery independently of model capabilities.
- [ ] Specify binding inspection, trust admission, unsupported requirements, and exact fix actions.
- [ ] Define routing-pattern syntax and all observable matching semantics, with Unicode and capture cases.
- [ ] Compare mature libraries with those cases; record limits, dependencies, and rejected alternatives.
- [ ] Author cases first for supported, missing, mismatched-version, and incompatible bindings.
- [ ] Test that a core-only host refuses an extension-dependent artifact before model I/O.
- [ ] Test identical extraction and streaming results across two claimed implementations.
- [ ] Specify the migration of legacy bare `pattern` strings without silently changing their meaning.
- [ ] Add schemas and harness support for scoped claims; never count missing extensions as passes.
- [ ] Implement the ratified design in Python and Go; test TypeScript independently.
- [ ] Update docs, plans, versions, and decisions; run `./check` before completion.

## Trade-offs

Optional support makes compatibility explicit rather than universal.
Artifacts and hosts need more metadata. Mature libraries can add packaging costs.
A remote executor adds latency and host policy requirements. None permits hidden inference.

The plan does not select identifiers, a wire protocol, a regex library, or a custom engine.
Those choices require evidence and review before implementation.

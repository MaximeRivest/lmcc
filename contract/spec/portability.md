# Portability — a shared core and declared extensions

**Status:** ratified design direction, not an implemented artifact version.
D-31 supersedes the universal regex requirement in D-14 and the corresponding
implementation mandate in D-29 and plan 09. Kernel 0.2 artifacts, schemas,
refusal stages, and corpus cases remain unchanged until a versioned migration.

## Shared meaning, independent execution

LMCC defines transformations, not one execution engine. Implementations may
use different algorithms and libraries. An admitted artifact must retain the
same meaning on every host that claims its required contract.

Portability is a claim about a supported feature set and its pinned versions,
not a claim that every host implements every extension. A smaller implementation
must refuse unsupported requirements rather than substitute approximate behavior.

## Mandatory core

Keep the mandatory core small: typed signatures, the template grammar,
derived parsing, parts and spans, scalar text rules, strategy mechanics,
binding, inspection, and stable refusals. Exact core behavior remains mandatory.
Literal `between` and `line_prefixed` extraction need no general regex engine.
The next version must enumerate the core requirements and their fixtures.

General regex execution is not a mandatory kernel implementation requirement.
A host need not build or bundle a regex engine to implement the core.
This changes the next version's requirements; it does not silently remove
`pattern` support from existing 0.2 conformance claims.

## Optional execution contracts

An artifact using an extension declares a named, versioned semantic contract.
For routing patterns, that contract must define syntax, flags, Unicode rules,
match selection, capture priority, empty matches, consumption, and failures.
A library name alone does not establish those semantics. Two libraries with
RE2 ancestry still need independent conformance evidence.

The artifact declares what behavior it requires. The host binds a compatible
implementation: a mature library, a local executor, or a declared remote service.
Location, packaging, isolation, and credentials do not redefine the operation.
Code-bearing formats follow the same identity-versus-binding distinction;
this document does not replace their execution or admission specification.

Use mature execution libraries when they satisfy the contract. A custom engine
is not forbidden, but implementing one is not required by LMCC conformance.
No default choice of library, transport, or extension identifier is ratified here.

## Binding and capability discovery

Hosts expose supported extension contracts and versions separately from model
capabilities. A model's `native_reasoning` fact says nothing about the host's
regex library. Do not overload the model capability vocabulary for host support.

Resolve required extensions before returning a usable bound plan and before
sending a model request. Unknown versions, unsupported semantics, or incompatible
bindings refuse explicitly. Never fall back to a host's default regex dialect.
Existing 0.2 load refusals remain at load; this principle does not move them.
New refusal codes, stages, and fix actions require specs and corpus cases first.

Loading declarations does not authorize running shipped code or starting services.
The host controls execution permission. An artifact name never triggers an import
or an unapproved remote call.

Plans must expose required contracts, resolved versions, and selected bindings
without exposing secrets. The exact serialized fields remain to be specified.

## Frontends and conformance

Frontends lower into the shared description and declare any required extensions.
They may translate an operation only when the translation preserves its meaning.
Unsupported translation refuses; it must not silently change extraction.

Claims name the core version, extension versions, and execution limitations.
Each claimed extension passes its own byte-exact cases. Missing extensions are
reported separately; they are not passes. A caller can check compatibility before
using the plan. No implementation is advertised as universally complete.

Existing `requires: ["udf:python"]` cases remain placement-specific. They do not
yet define a general extension-requirements schema or discovery protocol.

## Migration and costs

Do not relabel bare 0.2 `pattern` strings with new semantics. Define a versioned
migration with explicit requirements, legacy behavior, and unsupported-host tests.
Old corpus bytes remain evidence for the version they describe.

D-29's DOTALL choice can inform an explicitly named legacy-compatible pattern
contract. It is not a global default for every future pattern extension.
The experimental Batch 1 Python matcher is unmerged and is not the chosen backend.
Keep its findings as evidence; do not import it merely to satisfy the old mandate.

Costs: artifacts carry more compatibility information; hosts can support fewer
artifacts; deployment may need extra libraries or services. In return, the core
stays small and independently implementable. Silent semantic drift remains forbidden.

See `../../plans/10-declared-extensions.md` for the specification and corpus gates.

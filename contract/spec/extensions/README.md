# Extensions — declared execution contracts

An **extension** is a named, versioned semantic contract for behavior the
kernel core does not define (kernel §10, `../portability.md`). The core
is exact and mandatory; an extension is exact and optional: an artifact
declares it, a host binds an implementation or refuses before any plan
exists. Nothing is ever approximated silently.

**Identity.** `<family>/<name>`, both lowercase (`[a-z][a-z0-9_]*` /
`[a-z][a-z0-9_-]*`). The family is the construct the contract governs;
an artifact declares at most one contract per family. Versions are
semver and follow the kernel's compatibility rule (§9): while major = 0,
minor must match exactly; from 1, major must match and the host's minor
must be at least the artifact's.

**What a spec file must pin.** Everything two hosts could disagree on:
syntax admitted and refused, the meaning of every observable outcome,
Unicode behavior, empty and overlapping cases, failure behavior, and the
corpus cases that are its evidence. A library name is not a contract;
two libraries with shared ancestry still need the cases.

**How a host claims one.** Bind an implementation under the name and
version; pass every corpus case that `requires` it byte-exactly. A host
that binds none is "core only" — a complete claim, counted apart by the
harness, never a pass by omission.

**Distinct from** model capabilities (`../vocab/capabilities.md`: facts
about the model, declared per call) and from UDF placement (`udf:<lang>`
on cases; `format-untrusted` / `udf-unplaceable` at load): those admit
artifact *code*; an extension binds host *behavior*. Unifying placement
under the extension mechanism is a recorded follow-up, not done here.

## Tiers — divergence is normal, undeclared divergence is not

Engines legitimately differ, as SQL dialects do. What LMCC forbids is
not knowing which one an artifact meant. Three tiers exist or can, all
as rows of the same table, resolved by the same mechanism:

| tier | contract shape | exactness | cost |
|---|---|---|---|
| **default** — the host's own engine | `pattern/legacy-re2` | agrees on its cases; beyond them hosts may differ, and the spec says where | none; the constructor declares it for you |
| **exact, one language** | a contract named for one engine and version (`pattern/cpython-re` at a Python minor, `pattern/go-regexp` at a Go minor) | identical wherever that runtime runs; other runtimes refuse | pin the runtime version — usually already done |
| **exact, every language** | one shared engine (RE2 bindings, or a Rust `regex` build as WebAssembly) | byte-identical across hosts by construction | a native or WASM dependency, outside the kernel, in a pack |

Only the first exists. The others are added when an adapter demands
what the default cannot give — by *binding an engine*, never by
authoring a grammar or a matcher (D-32, D-34).

## Families and contracts

| family | governs | contract | version | spec | evidence |
|---|---|---|---|---|---|
| `pattern` | the `pattern` key of a text routing (kernel §6) | `pattern/legacy-re2` | 0.1.0 | `pattern-legacy-re2.md` | cases 40, 42 |

Mechanism cases (declare, bind, refuse; kernel §10): 91–95.

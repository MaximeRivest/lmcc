# Portability — a shared core and declared extensions

**Status:** normative from kernel 0.3 (D-31 ratified the direction, D-33
the mechanism). The mechanism itself is kernel §10; this file states the
boundary — what is core, what is extension, and what a conformance claim
means — and inventories the core against its evidence.

## Shared meaning, independent execution

LMCC defines transformations, not one execution engine. Implementations
may use different algorithms and libraries. An admitted artifact must
retain the same meaning on every host that claims its required
contracts.

Portability is a claim about a supported feature set and its pinned
versions, not a claim that every host implements every extension. A
smaller implementation refuses unsupported requirements before any plan
exists rather than substitute approximate behavior.

## The mandatory core

Exact and mandatory for every implementation. No general regex engine is
needed to implement it: `between` and `line_prefixed` are plain scans.

| core operation | kernel | evidence (corpus) |
|---|---|---|
| signature validity, shape table, nullable and enum forms | §1 | 43, 48–52 |
| template constructs: slots, loops, escapes, syntax refusal | §2 | 01, 05, 47, 79 |
| demos, history, field turns, media parts | §3, §7b | 02–04, 53, 54 |
| derived lens: anchors, closes, tails, bare slots, ambiguity, collisions | §4 | 20, 21, 27, 30–33, 38, 39, 69, 70, 80 |
| scalar text rules: strip, integer and number grammars, spelling, overflow | §7a | 35–37, 44, 51, 52, 89, 90 |
| format resolution order and bind-time format refusals | §5 | 14, 48–50, 55, 56, 67, 68 |
| vocabulary references, factory failures, version pins, unknown names | §5, §6, §9 | 09, 13, 24, 26, 77, 81, 82 |
| shipped-format admission (never run at load); placement refusals | §5 | 57–62 (`udf:python`) |
| strategies: predicates, `choose`, `requires`, fragments, controls, placement, visibility | §6 | 10, 34, 63–66, 73–76, 78 |
| literal routings: `between`, `line_prefixed`, `channel:`, sub-roles | §6 | 07, 41, 64, 71 |
| response part validation and coalescing | §6, §8 | 83–88 |
| streaming refinement, event timing, linear per-feed work | §8 | every parse case, replayed at every split, trace-compared |
| plan faces: skeleton, prefix | §3 | 72 |
| data-only load with an empty registry; roundtrip | §5, §9 | 08 |
| extension mechanics: declare, bind, refuse, roundtrip | §10 | 91–95 |

The standard vocabulary (`format/json`, `format/table`,
`format/scaled_number`, the reasoning strategies, `lens/json_object`) is
**not** core: it is claimable separately, by the same rule as extensions
(`vocab/README.md`; cases 15–19, 22, 23, 25, 28, 29, 45, 46).

## Extensions

Everything else is a named, versioned contract (`extensions/README.md`).
For a routing pattern the contract must define syntax, flags, Unicode
rules, match selection, capture priority, empty matches, consumption,
and failures — or state, as `pattern/legacy-re2` does, exactly where it
leaves behavior unspecified. A library name alone establishes nothing;
two libraries with RE2 ancestry still need independent evidence.

The artifact declares what it requires. The host binds a compatible
implementation — a standard library, a mature package, a local executor,
a declared remote service. Location, packaging, isolation and credentials
do not redefine the operation and never appear in the artifact. Binding
is a table entry; it runs nothing and starts nothing.

Use mature libraries when they satisfy the contract. A custom engine is
not forbidden; building one is not required by conformance.

## Discovery and binding

Hosts expose bound extensions and versions
(`registry.describe()["extensions"]`) separately from model capabilities.
A model's `native_reasoning` fact says nothing about the host's regex
library, and the capability vocabulary is never overloaded to say so.

Required extensions resolve at load, and again at bind for adapters
built in code — always before a usable plan and before any model
request. Unknown contracts, incompatible versions, and undeclared uses
refuse by name with a fix (kernel §10, `errors.md`). There is no
fallback to a host's default dialect.

Plans expose required contracts, resolved versions and binding labels
(`plan.describe()["extensions"]`), without secrets.

## Frontends and conformance

Frontends lower into the shared description and declare the extensions
their lowering needs. They may translate an operation only when meaning
is preserved; otherwise they refuse.

A conformance claim names the core version and each extension passed.
Each claimed extension passes its own byte-exact cases. Missing
extensions are reported as `unclaimed`, never as passes. No
implementation is advertised as universally complete.

`udf:<language>` on a case remains a placement requirement for shipped
code, handled by the existing admission refusals; it is listed in the
same `requires` array as extensions because a driver treats both the
same way (bind exactly these, or answer `unclaimed`).

## Migration and costs

Kernel 0.2 artifacts refuse `version-incompatible` under 0.3, as any
minor change while major = 0 does. Migrating one is two edits (kernel
§10): the kernel version, and — only if it uses `pattern` — declaring
`pattern/legacy-re2` 0.1.0, whose contract is by definition what 0.2
did. Bare `pattern` strings are never relabeled: an undeclared one
refuses.

Costs: artifacts carry compatibility information; a host may support
fewer artifacts; deployment may need a library or a service. In return
the core stays small and independently implementable, and every
difference between two hosts is either a named contract or a refusal.

See `../../plans/10-declared-extensions.md` for what remains open.

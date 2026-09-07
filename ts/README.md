# LMCC — TypeScript clean-room implementation

A third, independent implementation of the LMCC contract (kernel 0.2.0 and
the std vocabulary 0.1.0), written from `../contract/` alone: the spec,
the schemas, the corpus, and the harness. No other implementation was
consulted. Runtime dependencies: the Node.js standard library only; there
is no `package.json` dependency list, no bundler, no build step.

## Layout

| path | what |
|---|---|
| `lmcc/refusal.ts` | `Refusal(code, hint, fix, partial)`; the closed fix vocabulary as types |
| `lmcc/json.ts` | strict RFC 8259 reader (ordered members, member source spans, BigInt beyond 2^53, duplicate detection) and the format-json.md writer |
| `lmcc/text.ts` | kernel §7a: strip, integer/number grammars, ECMAScript number spelling, booleans, half-to-even, RE2-subset lint and translation |
| `lmcc/signature.ts` | signature validation, the closed shape set, structural keys, mechanical hints |
| `lmcc/template.ts` | the three template constructs → nodes |
| `lmcc/formats.ts` | `Format` interface, kernel defaults (scalars/enums/nullables, media parts), resolution order |
| `lmcc/registry.ts` | the vocabulary socket (formats, strategies, lenses, versions) |
| `lmcc/strategy.ts` | predicates, `choose`, routings as data |
| `lmcc/routing.ts` | `between` / `line_prefixed` / `pattern` scans, plus their stable projections for streaming |
| `lmcc/lens.ts` | the derived lens (pattern derivation, join, format, split, skeleton, projection) and the `Lens` socket |
| `lmcc/plan.ts` | `bind` → `Plan`: render, prefix, skeleton, parse, describe, explain |
| `lmcc/stream.ts` | the §8 reducer: `feed` / `finish`, prefix-monotone projections, batch at EOF |
| `lmcc/serde.ts` | `load` (every load-time refusal, UDF hash admission) and `dump` |
| `lmccstd/` | the std pack: `format/json`, `format/table`, `format/scaled_number`, `lens/json_object`, `strategy/prefix_cot`, `strategy/reasoning_tags`, `strategy/native_reasoning` — registered through the socket, never imported by the kernel |
| `conform/main.ts` | the JSON Lines driver (kernel §9); replays streaming at every chunking the corpus README names |
| `tests/` | `node --test` unit tests (text rules, kernel, streaming law under random chunkings) |
| `types/node-shim.d.ts` | minimal ambient types for the Node APIs used (no `@types/node` offline) |
| `check` | one verify command |
| `AUDIT.md` | the corpus audit: every guess, with a proposed case and spec sentence |

## Run

```
cd ts
./check                                   # tsc --noEmit, node --test, corpus harness
node --experimental-strip-types conform/main.ts   # the driver: one case per stdin line
python3 ../contract/harness/runner.py --driver 'node --experimental-strip-types conform/main.ts' --cwd .
```

Requires Node 22 (`--experimental-strip-types`; only erasable TypeScript
syntax is used), Python 3 for the harness, and `tsc` 5.9 (the `check`
script falls back to `nix shell nixpkgs#typescript`).

## Conformance claim (as measured)

`python3 ../contract/harness/runner.py --driver 'node --experimental-strip-types conform/main.ts' --cwd ts`
reports:

    80 corpus cases: 74 passed, 0 failed, 6 unclaimed (udf:python)

The six unclaimed cases (57, 58, 60, 61, 62, 68) declare
`requires: ["udf:python"]`; this runtime places no code, so it answers
`{"ok": true, "unclaimed": "udf:python"}` as kernel §9 prescribes.
For every parse and parse-refusal case the driver replays the streaming
reducer whole, one Unicode scalar at a time, at every scalar split, and at
every split inside each text-bearing part, and additionally checks that
the concatenated deltas equal the batch raw text per field (a check the
Python harness does not make).

## Provenance

Written from `contract/` alone (spec, schema, corpus, harness). Every
place the contract left a behavior open is listed in `AUDIT.md` with the
choice made, the case that pins it (or none), a proposed corpus case, and
the spec sentence that would remove the guess. Trade-offs taken by this
runtime (JavaScript regex is not RE2; integers beyond 2^53 are BigInt;
JavaScript objects reorder integer-like keys; shipped UDFs are never
placed) are stated there, not absorbed.

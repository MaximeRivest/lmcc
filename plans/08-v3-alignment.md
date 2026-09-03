# Plan 08 — align the contract with the ideal README v3  ✅ done (kernel 0.2, D-24)

**Goal (ratified 2026-09-03).** Rewrite the contract, both kernels, the
corpus and the docs so that they are the v3 design (`research/
ideal-readme-v3.md`): six nouns, one verb — signature, adapter,
template, lens, format, part/span, role, strategy, capability; `bind`.
The 0.1 kernel implemented a narrower thing (codecs by field name, a
declared `sections` lens, media as a kernel special case, no parts, no
UDFs, no `@lmcc.fn`). This plan closes that distance.

## What v3 fixes, item by item (0.1 → v3)

| 0.1 | v3 | where |
|---|---|---|
| `codecs` keyed by **field name** | `formats` keyed by **type name** (as the frontend spells it) or structural shape; the artifact never names a field | §5, §11 |
| codec = text in, text out | format = `write(value) → parts`, `read(span) → value`, optional `describe(type) → text` | §5 |
| nesting is a codec's private business | a type inside a type with no format refuses **at its path** (`no-format: answer.age`) | §5 |
| data-only artifacts; code deferred (`requires` gap) | a format may be **shipped whole**: language, source, deps, sha256, author; the loader never runs it, the host places it or refuses | §5, §11 |
| media is a kernel special case | media is a type with a format that emits an image part; `write` returns parts | §5 |
| `sections` kernel lens + `derived` | **derived only**; markers are the pattern, read backwards (tails and bare output slots included) | §4 |
| strategy routings `{extract:{kind…}, field, join, strip}` | `{from: "text" \| "channel:<part>", between/pattern/line_prefixed, to: "@role" \| "@role.sub", consume}` | §6, §11 |
| strategy predicate only | `choose: [{when, use}, {else}]` inside a strategy; `placement: {"@role": "controls.tools"}` | §6, §11 |
| `LMCCError(code, detail, partial)` | `Refusal(code, hint, partial)`; read-side value errors are `parse-value` | §9 |
| no typed-function surface | `@lmcc.fn`, dataclass return for several outputs, `Role["reasoning", str]`, `fn.bind(adapter, capabilities=…) → plan` | §1, §3 |
| plan = render, parse, describe | + `skeleton()` (prefill, stops, grammar), `prefix()` (cache-stable bytes), `parser()` (streaming) | §8, §10 |
| `template: {"messages": [...]}` | `template: [...]` | §11 |

## Choices v3 leaves open — taken here, veto any

- **V3-1 Kernel defaults exist for scalars, enums, null, and media
  parts.** v3's page defines even `int` on the page ("no batteries").
  A calling convention that does not say how an `int` crosses is
  incomplete (C's does); the §7a portable text rules stay as the
  kernel's *default formats* for `string/integer/number/boolean/enum/
  null`, and a media value that is already a part passes through. Any
  registered format for those types overrides. Everything with
  structure has **no default**: `no-format`.
- **V3-2 The lens socket stays** (`parse.kind` may name a vocabulary
  lens such as `json_object`). v3 says JSON mode is "a strategy gated on
  a capability" with the pattern spelled in the template — but a
  signature-independent template cannot spell a JSON *object* of N
  fields with the three constructs (no separator between loop items).
  Keeping the socket is one addition to v3; `json_object` carries its
  own capability gate and patch, as today.
- **V3-3 Strict escapes stay.** v3 §4 writes `{"answer": "{answer}"}`
  with bare braces. The kernel keeps `{{`/`}}` (strictness keeps
  templates analyzable); the page's example is spelled
  `{{"answer": "{answer}"}}`.
- **V3-4 Fields carry an optional `type` name.** SignatureCore gains
  `type: str?` — the frontend's spelling (`Person`, `pd.DataFrame`,
  `list[Person]`) — because formats resolve by type name first. Shapes
  stay for structural resolution and for describing.
- **V3-5 `span.text`** is the text parts of the span, each stripped,
  joined by `\n`. This is what today's `join: "\n"` did; v3 says only
  "a text-only format just reads `span.text`".
- **V3-6 Cross-language UDFs.** A case whose formats are shipped UDFs
  declares `"requires": ["udf:python"]`; a driver that cannot place that
  language answers `{"ok": true, "unclaimed": "udf:python"}` and the
  harness reports the count separately — declared, never silent. The
  Go kernel loads such artifacts and refuses `format-untrusted` unless
  the host supplies a placer.
- **V3-7 Self-containment check.** The Python runtime refuses
  `format-not-self-contained` when a shipped `write`/`read` closes over
  free variables or names globals other than modules and builtins.
  Deps are declared, not inferred.
- **V3-8 Corpus provenance.** Cases 01–54 are re-authored to the v3
  artifact form. Mechanical parts (template list, format keys, routing
  form) are transformed by a script; every case where the *semantics*
  changed (`sections` templates becoming patterns) is rewritten by hand
  and reviewed. The corpus README records this second seeding.
- **V3-9 `reach` is not adopted.** `for-pack-authors.md` (tied to v2)
  has registration-time reach checks; v3's page does not. The two
  bind-time contracts v3 names (`format-span-mismatch`,
  `format-placement-mismatch`) are adopted; `reach-violation` is not.
- **V3-10 `skeleton()`** ships prefill and stops derived from the lens;
  the grammar face is a stated gap (plan 01/10). `parser()` streaming
  stays plan 01.

## Acceptance criteria

- [x] `kernel.md` rewritten around v3's nouns; `errors.md` carries v3's
      codes; schemas updated (entry: `template` list, `formats`,
      strategy `choose`/`placement`/routing form; signature: `type`).
- [x] Corpus re-authored (V3-8) and extended: cases 55–73 — formats by
      type and by structural shape, shape mismatch, shipped UDF (render,
      parse, untrusted, tampered, not-self-contained, roundtrip),
      `choose` (else, native, patch), `placement`, span/placement
      mismatch, bare output slots, `@role.sub` routing, `plan` kind
      (`skeleton`/`prefix`), unknown routing target.
- [x] Python kernel: formats (accepts/direction/emits/round_trip/reads),
      parts/spans, resolution order, UDF ship/admission, `@lmcc.fn` +
      `Role` + `One`, `Refusal`, plan faces.
- [x] Go kernel: the same; shipped UDFs verify their hash then refuse
      `udf-unplaceable`; cases needing `udf:python` are declared
      unclaimed (V3-6).
- [x] std and the DSPy frontend re-expressed as formats and v3
      strategies; the 16-row catalog green.
- [x] README rewritten from v3 with every block executed by the tests;
      GUIDE, AGENTS, decisions (D-24) updated; `./check` green.

**Found while building (added to the plan's choices).** V3-11: a
dataclass return is several outputs (v3 §1) unless marked `One[T]`
(v3 §5's `-> Person` example is otherwise ambiguous). V3-12: `*` is
consulted after the kernel's scalar defaults, so `"*": json` never
quotes a plain string. V3-13: for bare output slots the pattern is the
*line* holding the hole (v3 §4's "lines … become anchors"); for loops
the tail is the rest of its line, never the prose after it. V3-14:
`@role.<sub>` targets the field bearing role `<role>.<sub>`; roles are
namespaced strings. V3-15: `inspect.getsource` cannot see code `exec`'d
from a string, so shipped formats must be defined in real files.

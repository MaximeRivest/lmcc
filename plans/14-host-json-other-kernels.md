# Plan 14 — host types' JSON form and lm15 media parts in TypeScript, Julia and R

**Status: done 2026-10-07 (D-62). Python was done in kernel 0.8.6 (D-61, issues #3 and #4).**

**Motivation.** A frontend that logs, caches or replays calls keeps every
input as JSON (a turn, kernel §3a) and must get its host values back. In
Python, `lmcc.format(T, to_json=, from_json=)` gives a type its JSON form,
`plan.load_turn` rebuilds it, and the format bound to the type always
receives the type itself; `import lmcc_lm15` makes lm15's media parts
field types and media values. The other kernels have the same gaps, each
in its own form, checked on 2026-10-07:

- **TypeScript.** `loadTurn` keeps values as JSON, so a format bound with
  `registry.format("Pages", ...)` receives a `Pages` live and JSON on
  replay. An lm15-ts part (`image({...})`) is a plain object with
  camelCase keys: given to a media field it is written as
  `{"type": "image", "mediaType": ...}`, which lm15 refuses only when the
  request is built ("ImagePart requires media_type"). The kernel cannot
  recognise an lm15 part by its value.
- **Julia.** `to_json` refuses any struct, so a turn with a host value
  cannot be written; an `LM15.ImagePart` given to a media field refuses
  `value-invalid` ("a Dict of part data").
- **R.** `load_turn` keeps values as JSON (no type is rebuilt from a
  turn). What an lm15 R part does as a media value was not checked (the
  lm15 R package is not installed here); `is_obj` accepts lm15's
  `lm15_json_object`, so it may pass as part data or not.

**Design to settle first (per language, its idiom, stated in its README).**
The rule is Python's: a binding may carry the type's JSON form both ways;
the format bound to the type receives the type, every other format its
JSON form; `load_turn` rebuilds. Where the hook lives differs: TypeScript
binds by type name (`registry.format("Pages", {toJson, fromJson})`) and
must find a field's binding by `field.type`, since a plain object carries
no class; Julia's natural hook is a method (`LMCC.to_json(::T)`,
`LMCC.from_json(::Type{T}, data)`); R's is an S3 method. Each bridge
(`lmcc/lm15`, `LMCCLM15Ext`, `lm15_*`) binds lm15's media parts.

**Acceptance criteria.**
1. In each kernel, a test: a bound type written, turned into JSON, loaded
   with `load_turn`, written again, with equal requests, and its own
   format seeing the host type both times (the Python test is
   `python/tests/test_host_json.py`).
2. In each bridge, a test: an lm15 image part as a field's value writes
   lm15's canonical part (`media_type`, never `mediaType`), a part of
   another kind refuses `value-invalid`, and the part survives a turn's
   JSON round trip.
3. Each README states its host difference; one decision entry.
4. `./check` green; the corpus is unchanged (host types are not data).

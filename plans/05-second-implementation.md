# Plan 05 — a second implementation (Go)  ✅ done

**Motivation.** "Cross-language" is a hope until a second kernel passes
the harness byte-exactly. This plan is the proof — and the forcing
function that flushes every accidental Python-ism out of the spec.

**What landed.** `go/` — kernel (`go/lmcc`), std pack (`go/lmccstd`),
corpus runner (`go/conform`, shared by `go test` and the driver), and
the JSON Lines driver `go/cmd/lmcc-conform`. Stdlib only. A Go
struct-tag signature frontend (`StructSignature`) proves a second
signature syntax lowers to the same SignatureCore. See D-18.

**What the spec had underspecified** (each fixed spec → corpus → both
kernels; decisions D-13 to D-17):
- whitespace, integer/number/boolean text grammars, number spelling,
  rounding (§7a; cases 35–37, 44, 45)
- the regex dialect and the exact `between`/`line_prefixed` scans
  (§5; cases 40–42)
- write-side invertibility and repeated close/tail markers (§4; 38–39)
- signature validation and a schema for signatures and cases (§1; 43)
- `json_object` handing over source text instead of a re-serialization,
  duplicate keys, strict JSON (vocab spec; case 46)
- the `json` codec's single-line layout (`, ` / `: `), which case 28
  had pinned as Python's default without saying so

**Acceptance criteria.**
- [x] `harness` gains `--driver CMD` subprocess mode (language-neutral,
      JSON Lines, one process for the whole corpus).
- [x] The new kernel passes **all** corpus cases byte-exactly, including
      every refusal code (46/46).
- [x] Every divergence found landed as a spec clarification + corpus
      case first, then fixes in both kernels (D-02 discipline).
- [x] One-command check for the new language (`go/check`), called from
      `./check`, which also runs the Go binary through the harness.
- [x] Decision-log entries: D-13 … D-18.
- [x] Both kernels raise exactly the same error-code set
      (`test_coherence.py`).

**Still open (not this plan).** Media emission, streaming, and the
`requires` sidecar mechanism are kernel gaps in both implementations
alike; `describe()` output is not corpus-pinned, so the two `describe`
shapes agree by construction, not by proof.

# Plan 05 — a second implementation (Go or TypeScript)

**Motivation.** "Cross-language" is a hope until a second kernel passes
the harness byte-exactly. This plan is the proof — and the forcing
function that flushes every accidental Python-ism out of the spec.

**Design sketch.**
- Implement L1 mechanics only (core, template, lens, plan, serde,
  registry sockets) + the std vocabulary claimed by the corpus.
- Driver protocol (already in `spec/kernel.md` §conformance): read one
  case JSON on stdin, write `{"ok": bool, "detail": str}` on stdout.
  Wire it into `harness/runner.py` as a subprocess driver.
- Known portability traps to spec-check before coding: JSON number
  formatting, unicode escaping (`ensure_ascii=False` semantics), dict
  member order preservation, regex dialect (kernel algebra uses plain
  patterns; combinators restrict to RE2).

**Acceptance criteria.**
- [ ] `harness` gains `--driver CMD` subprocess mode (language-neutral).
- [ ] The new kernel passes **all** corpus cases byte-exactly, including
      every refusal code.
- [ ] Every divergence found lands as a spec clarification + corpus
      case first, then fixes in both kernels (D-02 discipline).
- [ ] CI-style one-command check for the new language, mirroring
      `./check`.
- [ ] Decision-log entry: what the spec had underspecified.

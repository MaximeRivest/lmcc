# Plan 02 — parse combinators (declared recovery, level 1)

**D-31 update:** regex execution is a declared optional extension in the next
version, not a mandatory engine in every kernel. Plan 10 gates the extension
contract, migration, and backend choice. Existing 0.2 evidence stays historical.

**Kernel 0.8 update (D-42):** the obvious part landed in the kernel, not
as a combinator pack: misspelled markers are repaired by one rule (kernel
§4a), every repair and old tolerance is reported by `plan.read`, and a
reply cut at its length limit refuses `parse-truncated`. What this plan
still covers: declared recovery beyond markers (value spellings, fenced
JSON, find rule delimiters), with the census gate below.

**Motivation.** The lens inverts what the template wrote. Real replies
add sloppiness the template never wrote: case-drifted labels, fenced
blocks, truncation. Today that residue has no declared home — the gap
the research calls "level 1" (adapter-parse-dsl.md).

**Design sketch.**
- A small combinator vocabulary, each with ~5-line pinned semantics:
  `alternatives` (ordered try), `fenced_block`, `tolerant_labels`
  (case/whitespace), `regex` (a declared, versioned pattern contract — cross-language
  identical for hosts claiming that contract), `json_repair` (policy enum),
  `truncation_policy`, `strip`/`split`.
- Entries may declare a pipeline as the parse spec or as a per-field
  recovery step *after* the lens refuses — refusal stays the default;
  recovery is opt-in, visible data.
- Vocabulary, not kernel: ships in `lmcc_std` behind a socket, versioned
  `combinator/<name>`.

**Guard.** Census before vocabulary freeze: harvest real-world custom
parsers; admit a combinator only with evidence (the north-star rule:
counts, not taste).

**Acceptance criteria.**
- [ ] `spec/vocab/combinators.md`: each combinator's semantics incl.
      the ugly cases; name the required pattern contract and its version.
- [ ] Corpus: per combinator ≥1 positive case + 1 refusal case;
      one pipeline-composition case pinned byte-exact.
- [ ] `parse-ambiguous`/`parse-missing-fields` semantics unchanged when
      no pipeline is declared (prove with existing cases untouched).
- [ ] `describe()` shows declared pipelines; `./check` green.

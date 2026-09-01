# Plan 02 — parse combinators (declared recovery, level 1)

**Motivation.** The lens inverts what the template wrote. Real replies
add sloppiness the template never wrote: case-drifted labels, fenced
blocks, truncation. Today that residue has no declared home — the gap
the research calls "level 1" (adapter-parse-dsl.md).

**Design sketch.**
- A small combinator vocabulary, each with ~5-line pinned semantics:
  `alternatives` (ordered try), `fenced_block`, `tolerant_labels`
  (case/whitespace), `regex` (**RE2 subset only** — cross-language
  identical, no backtracking bombs), `json_repair` (policy enum),
  `truncation_policy`, `strip`/`split`.
- Entries may declare a pipeline as the parse spec or as a per-field
  recovery step *after* the lens refuses — refusal stays the default;
  recovery is opt-in, visible data.
- Vocabulary, not kernel: ships in `a15_std` behind a socket, versioned
  `combinator/<name>`.

**Guard.** Census before vocabulary freeze: harvest real-world custom
parsers; admit a combinator only with evidence (the north-star rule:
counts, not taste).

**Acceptance criteria.**
- [ ] `spec/vocab/combinators.md`: each combinator's semantics incl.
      the ugly cases; RE2 restriction normative.
- [ ] Corpus: per combinator ≥1 positive case + 1 refusal case;
      one pipeline-composition case pinned byte-exact.
- [ ] `parse-ambiguous`/`parse-missing-fields` semantics unchanged when
      no pipeline is declared (prove with existing cases untouched).
- [ ] `describe()` shows declared pipelines; `./check` green.

# `pattern/legacy-re2` — version 0.1.0

**Status:** the migration bridge. This contract is, by definition, the
behavior kernel 0.2 required of every `pattern` routing (D-14, D-29,
D-30/D-32), given a name and a version so that a 0.3 artifact can
declare it and a host can honestly say whether it binds it. It is not
the rigorously specified dialect plan 10 still owes; when that lands it
will be a different contract (`pattern/<name>`), and this one stays as
what it is.

## What the artifact writes

`{"from": "text", "pattern": <regex>, "to": …, "consume"?: bool}`. The
regex is a string; the extension defines everything about it.

## Syntax admitted

RE2 syntax **minus**: lookaround (`(?=`, `(?!`, `(?<=`, `(?<!`),
backreferences (`\1`…`\9`, `\k<…>`), named groups (`(?P<…>`, `(?<…>`),
atomic groups (`(?>`), and possessive quantifiers (`*+`, `++`, `?+`,
`}+`). A regex using any of these, or one the host's engine cannot
compile, refuses `entry-malformed` at the routing's path, at load (or at
bind for an adapter built in code), with fix `edit-entry`.

The exclusion check is lexical, on the regex with its escaped characters
removed (`\` followed by anything but `1`–`9` or `k`); that is exactly
what both kernels do (`_NON_RE2` / `nonRE2`).

## Matching

- **Flags.** DOTALL: `.` matches any scalar including newline. No other
  flag is set; inline `(?i)` and friends are whatever the host engine
  accepts (see *Limits*).
- **Search.** Non-overlapping matches, left to right, leftmost-first
  semantics as the host engine defines them.
- **Empty matches** are discarded: a match whose start equals its end is
  not a capture and does not consume.
- **Capture.** If the regex has at least one capturing group, the
  capture is group 1's text (empty when group 1 did not participate);
  otherwise the whole match. Each capture becomes one text part; the
  field's span is those parts in match order, stripped per §7a.
- **Consume.** With `consume: true` the whole match (not only group 1)
  is removed from the text later routings and the lens see.
- **Streaming.** A pattern routing buffers until EOF (kernel §8) because
  a later byte can change any match; the plan says so in
  `describe()["streaming"]`.

## Limits — stated, not hidden

The two reference bindings are `python:re` (Python's `re` with
`re.DOTALL`) and `go:regexp` (Go's RE2 with `(?s)`). They agree on every
corpus case that requires this contract; **full equivalence is not
claimed**. The independent clean-room audit (plan 09) found dialect
gaps beyond the cases — Unicode classes, POSIX classes, `\Q…\E`, some
escapes, `\b` semantics, capture priority under repetition — and the
experiment that closed them (a custom matcher) was withdrawn (D-32).
Under this contract those inputs are **unspecified**: a host may accept
or refuse them, and two hosts may differ. An artifact that needs any of
them has no portable spelling until a stricter contract exists. This is
the honest reason this contract is named *legacy*.

## Evidence

Cases 40 (group-1 capture, consume, multiple matches) and 42 (refused
syntax). A host claiming this contract passes both; a host that does
not claim it answers `unclaimed` and refuses every artifact that
declares it with `extension-unsupported`.

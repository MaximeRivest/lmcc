# Plan 11 — formatted tool arguments and representative turns probes

## Motivation

Raw-code heredocs need a writer for the argument body, not JSON escaping.
The hard-coded `probe` call cannot test a single-tool, code-only reader.
Keep body spelling in a format and envelope spelling in the strategy.

## Design

Kernel 0.6 adds `turns.input_format` (a normal named-format reference) and
`turns.probe` (an explicit `{name, input, id?}` example). The same bound
writer is used by history rendering and the bind-time probe. Existing
turns remain JSON-based by default. The probe checks name and input,
not transport-generated IDs, and is evidence for its sample only.

The std pack adds `code_arguments`, `code_calls`, and `heredoc_tools`.
No model calls or execution are necessary to prove the transport.

## Acceptance criteria

- [x] Normative semantics, failures, versioning and pack specs precede code.
- [x] Authored corpus covers history bytes, exact code parsing and streaming,
      drift, malformed samples, unavailable writers and version pins (116–127).
- [x] Python and Go preserve indentation, CRLF and trailing newlines; reject
      delimiter collisions on writing; nested choices load and dump correctly.
- [x] Probe and history use one writer; custom formats and explicit samples work.
- [x] Runnable notebook shows conversation, reasoning, calls, history and refusal
      without executing generated code. All nine cells ran in sequence in `py@lmcc`.
- [x] `./check` green (418 Python tests, 127 corpus cases, both kernels,
      DSPy and lm15 gates); D-38 records limitations and compatibility costs.

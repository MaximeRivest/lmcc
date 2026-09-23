# Vocabulary specifications

Every named format, transport, and reader is a **vocabulary entry**: a
versioned spec file here plus corpus cases pinning its behavior. No entry
is privileged — `format/json` and your lab's format graduate the same way:

1. Write the spec file (behavior, options, the ugly cases: escaping,
   nulls, fences — everything two implementations could disagree on).
2. Add corpus cases exercising it (`"vocab": ["std"]` or your pack name).
3. Ship a package that registers it and passes the harness.

An implementation may claim any subset of the vocabulary. Claimed entries
must pass their cases byte-exactly; unclaimed names refuse at load
(`unknown-format` / `unknown-transport` / `unknown-reader`) — never
silently.

**Extensions are the same principle for host behavior** (kernel §10,
`../extensions/README.md`): a find rule `pattern` dialect is a named,
versioned contract the artifact declares in `extensions` and the host
binds or refuses. Vocabulary entries are *referenced* (`{"use": name}`)
and pinned in `versions.vocab`; extensions govern a *construct* and are
must-understand. Regex is not a kernel obligation.

Purpose names are themselves vocabulary — what each name means and
its alignment with the wire layer's part kinds live in `purposes.md`.
The capability facts predicates may name live in `capabilities.md`.

Current entries (all 0.1.0 except `transport/reasoning_tags` 0.2.0, provided by `python/lmcc_std`; `go/lmccstd` provides the kernel-0.6 spelling of the same entries):

| entry | spec |
|---|---|
| `format/json` | `format-json.md` |
| `format/table` | `format-table.md` |
| `format/scaled_number` | `format-scaled_number.md` |
| `transport/prefix_cot` | `transport-reasoning.md` |
| `transport/reasoning_tags` | `transport-reasoning.md` |
| `transport/native_reasoning` | `transport-reasoning.md` |
| `reader/json_object` | `reader-json_object.md` |
| `format/function_tool` | `transport-tools.md` |
| `format/tool_catalog` | `transport-tools.md` |
| `format/tool_calls` | `transport-tools.md` |
| `format/code_arguments` | `format-code.md` |
| `format/code_calls` | `format-code.md` |
| `transport/heredoc_tools` | `format-code.md` |
| `transport/native_tools` | `transport-tools.md` |
| `transport/fenced_tools` | `transport-tools.md` |
| `format/citations` | `transport-citations.md` |
| `format/source_list` | `transport-citations.md` |
| `transport/native_citations` | `transport-citations.md` |
| `transport/inline_citations` | `transport-citations.md` |

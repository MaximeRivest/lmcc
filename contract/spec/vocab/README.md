# Vocabulary specifications

Every named format, strategy, and lens is a **vocabulary entry**: a
versioned spec file here plus corpus cases pinning its behavior. No entry
is privileged — `format/json` and your lab's format graduate the same way:

1. Write the spec file (behavior, options, the ugly cases: escaping,
   nulls, fences — everything two implementations could disagree on).
2. Add corpus cases exercising it (`"vocab": ["std"]` or your pack name).
3. Ship a package that registers it and passes the harness.

An implementation may claim any subset of the vocabulary. Claimed entries
must pass their cases byte-exactly; unclaimed names refuse at load
(`unknown-format` / `unknown-strategy` / `unknown-parse-kind`) — never
silently.

**Extensions are the same principle for host behavior** (kernel §10,
`../extensions/README.md`): a routing `pattern` dialect is a named,
versioned contract the artifact declares in `extensions` and the host
binds or refuses. Vocabulary entries are *referenced* (`{"use": name}`)
and pinned in `versions.vocab`; extensions govern a *construct* and are
must-understand. Regex is not a kernel obligation.

Role names are themselves vocabulary — the function each name means and
its alignment with the wire layer's part kinds live in `roles.md`.
The capability facts predicates may name live in `capabilities.md`.

Current entries (all 0.1.0, provided by `python/lmcc_std` and, byte-identically, by `go/lmccstd`):

| entry | spec |
|---|---|
| `format/json` | `format-json.md` |
| `format/table` | `format-table.md` |
| `format/scaled_number` | `format-scaled_number.md` |
| `strategy/prefix_cot` | `strategy-reasoning.md` |
| `strategy/reasoning_tags` | `strategy-reasoning.md` |
| `strategy/native_reasoning` | `strategy-reasoning.md` |
| `lens/json_object` | `lens-json_object.md` |

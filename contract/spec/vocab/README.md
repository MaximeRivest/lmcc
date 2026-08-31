# Vocabulary specifications

Every named codec and strategy is a **vocabulary entry**: a versioned spec
file here plus corpus cases pinning its behavior. No entry is privileged —
`codec/json` and your lab's codec graduate the same way:

1. Write the spec file (behavior, options, the ugly cases: escaping,
   nulls, fences — everything two implementations could disagree on).
2. Add corpus cases exercising it (`"vocab": ["std"]` or your pack name).
3. Ship a package that registers it and passes the harness.

An implementation may claim any subset of the vocabulary. Claimed entries
must pass their cases byte-exactly; unclaimed names refuse at load
(`unknown-codec` / `unknown-strategy`) — never silently.

Current entries (all 0.1.0, provided by `a15_std`):

| entry | spec |
|---|---|
| `codec/json` | `codec-json.md` |
| `codec/table` | `codec-table.md` |
| `codec/scaled_number` | `codec-scaled_number.md` |
| `strategy/prefix_cot` | `strategy-reasoning.md` |
| `strategy/reasoning_tags` | `strategy-reasoning.md` |
| `strategy/native_reasoning` | `strategy-reasoning.md` |

# Plan 13 — helpers you can autocomplete (design draft for review)

**Status: built 2026-09-23 (the maintainer approved the recommendations). `python/lmcc/helpers.py`, `tests/test_helpers.py`, GUIDE §7.**

**Motivation.** A transport today is written with strings you must
remember and cannot autocomplete: `"@purpose.calls"`, `"part:thinking"`,
`"message:system"`, `{"not": {"capability": "native_reasoning"}}`. The
learning review of 2026-09-23 (conversation `01a0c9fd`) found that
recognition beats recall. Helpers would let an editor suggest each piece,
and each would say what it does.

**Rule.** Every helper returns the same plain data you can write by hand
today. `print(helper(...))` shows the dict. The artifact, the corpus and
the spec do not change; the helpers are Python sugar over kernel §6, like
`lmcc.system(...)` is over a template message.

## Today and with helpers

```python
# today
think_aloud = lmcc.Transport(
    when={"not": {"capability": "native_reasoning"}},
    tell={"system": "Wrap every thought in <think>...</think>."},
    find=[{"from": "text", "between": ["<think>", "</think>"], "to": "@purpose",
           "remove": True, "repair": True}],
    in_template=False)

# with helpers
from lmcc import find, when

think_aloud = lmcc.Transport(
    when=when.lacks("native_reasoning"),
    tell={"system": "Wrap every thought in <think>...</think>."},
    find=[find.between("<think>", "</think>", remove=True, repair=True)],
    in_template=False)
```

## The helpers

**`lmcc.find`**: where an output is found in the reply (kernel §6 find rules).

| helper | returns |
|---|---|
| `find.between(open, close, *, to=None, remove=False, repair=False, whole_reply=False)` | `{"from": "text", "between": [open, close], "to": "@purpose", ...}` |
| `find.lines(prefix, *, to=None, remove=False)` | `{"from": "text", "line_prefixed": prefix, "to": ...}` |
| `find.pattern(regex, *, to=None, remove=False)` | `{"from": "text", "pattern": regex, "to": ...}` (needs `pattern/*`, as today) |
| `find.part(type, *, to=None, whole_reply=False)` | `{"from": "part:<type>", "to": ...}`, e.g. `find.part("thinking")` |

`to=None` is the purpose itself (`"@purpose"`); `to="calls"` is
`"@purpose.calls"`. `whole_reply=True` is today's `complete_reply`: a
reply holding a match is a whole reply (a tool call turn).

**`lmcc.put`**: where an input goes (kernel §6 `put`).

| helper | returns |
|---|---|
| `put.system()`, `put.user()`, `put.developer()` | `{"@purpose": "message:system"}` … |
| `put.request("tools")` | `{"@purpose": "request.tools"}` |

**`lmcc.when`**: when a transport applies (predicates over capabilities).

| helper | returns |
|---|---|
| `when.has("native_reasoning")` | `{"capability": "native_reasoning"}` |
| `when.lacks("native_reasoning")` | `{"not": {"capability": "native_reasoning"}}` |
| `when.all(p, q)`, `when.any(p, q)` | `{"all": [p, q]}`, `{"any": [p, q]}` |

**`lmcc.choose`**: pick the first transport that applies.

```python
reasoning = lmcc.choose(
    (when.has("native_reasoning"), "native_reasoning"),
    otherwise="reasoning_tags")
```

returns `lmcc.Transport(choose=[{"when": ..., "use": ...}, {"else": ...}])`.

## Names considered and rejected

- `find.text_between`: the `from` is always text for a between rule; the
  shorter name loses nothing.
- `when.not_`: needs the underscore, and `lacks` reads as English.
- `lmcc.route`, `lmcc.place`: the vocabulary is `find` and `put` (D-40).

## Acceptance criteria

- [x] `python/lmcc/helpers.py`: each helper returns the dict above; a
      wrong argument raises `TypeError` in Python (a host misuse, not a
      `Refusal`, like `Fn.__call__`).
- [x] `tests/test_helpers.py`: every helper equals its hand-written dict,
      and a transport built both ways dumps to the same entry.
- [x] GUIDE §7 uses the helpers (how-tos 03, 11, 12 still show the raw dicts; they teach the data) —, showing the dict
      once so a reader sees it is data.
- [x] Glossary rows; `./check` green.

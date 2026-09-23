"""Reading the reply: find_rules, captures, and the reader.

Find rules run before the reader (kernel §6): each collects a **capture** of
parts for a field — text matches (``between``, ``pattern``,
``line_prefixed``) or response parts of a channel kind — and may
``remove`` its text matches from what the reader sees.

The reader (kernel §4) is one document form for the reply with three faces
on one object: ``split`` reads, ``join`` writes turns, ``format`` writes
the ``{format}`` skeleton. ``derived`` is kernel grammar: the template
read backwards. Any other kind is vocabulary through the reader socket.
"""

from __future__ import annotations

import re

from . import core
from .errors import refuse


# ---------------------------------------------------------------- find_rules


def _text_captures(text: str, rule: dict, pattern=None) -> list[tuple[int, int, str]]:
    """(start, end, capture) for one text extractor: the kernel §6 plain
    scans, or the bound ``pattern/*`` extension for a ``pattern`` rule
    (kernel §10; bind guarantees one is bound when any rule needs it)."""
    captures: list[tuple[int, int, str]] = []
    if "between" in rule:
        open_, close = rule["between"]
        pos = 0
        while True:
            i = text.find(open_, pos)
            if i < 0:
                break
            j = text.find(close, i + len(open_))
            if j < 0:
                break
            captures.append((i, j + len(close), text[i + len(open_):j]))
            pos = j + len(close)
    elif "line_prefixed" in rule:
        prefix = rule["line_prefixed"]
        pos = 0
        for line in text.split("\n"):
            if line.startswith(prefix):
                captures.append((pos, pos + len(line), line[len(prefix):]))
            pos += len(line) + 1
    else:
        captures = pattern.captures(rule["pattern"], text)
    return captures


def apply_find_rules(text: str, parts: list[dict], find_rules: list[tuple[str, dict]],
                   pattern=None) -> tuple[str, dict[str, core.Capture]]:
    """Run all find_rules; return (remaining text, {field: Capture})."""
    found: dict[str, core.Capture] = {}
    for field_name, r in find_rules:
        if r["from"].startswith("part:"):
            kind = r["from"].split(":", 1)[1]
            capture = core.Capture([p for p in parts if p.get("type") == kind])
        else:
            captures = _text_captures(text, r, pattern)
            capture = core.Capture([core.text_part(cap) for _, _, cap in captures])
            if r.get("remove") and captures:
                pieces, pos = [], 0
                for start, end, _ in captures:
                    pieces.append(text[pos:start])
                    pos = end
                pieces.append(text[pos:])
                text = "".join(pieces)
        if field_name in found:
            found[field_name] = core.Capture(found[field_name].parts + capture.parts)
        else:
            found[field_name] = capture
    return text, found


# ------------------------------------------------------------------ readers


class Reader:
    """One reply document form; three faces on one object (kernel §4)."""

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        raise NotImplementedError

    def join(self, spelled: list[tuple[str, str]]) -> str:
        raise NotImplementedError

    def format(self, placeholders: list[tuple[str, str]]) -> str:
        return self.join(placeholders)

    def requires(self) -> list[str]:
        return []

    def request_settings(self, fields: list) -> dict:
        return {}

    def skeleton(self) -> dict:
        return {}

    def stream(self, field_names: list[str]):
        """Optional kernel §8 face. Vocabulary readers override this and
        return a reducer with ``feed(text_delta)`` and ``finish()``."""
        return None


def _cut_at_close(chunk: str, close: str, name: str) -> str:
    if not close:
        return chunk
    count = chunk.count(close)
    if count > 1:
        refuse("parse-ambiguous",
               f"close marker {close!r} for field {name!r} appears {count} times in its "
               f"section — refusing to guess where it ends")
    idx = chunk.find(close)
    return chunk if idx < 0 else chunk[:idx]


def check_collisions(spelled: list[tuple[str, str]], markers: list[str]) -> None:
    for name, value in spelled:
        for marker in markers:
            if marker and marker in value:
                refuse("value-collides",
                       f"field {name!r}: its spelled value contains the reader marker "
                       f"{marker!r}; the turn could not be read back as written")


# ---------------------------------------------------------- marker repair
#
# Kernel §4a. A marker matches its misspellings through its *key*: the text
# without ignorable characters, ASCII lowercased. The line feed is not
# ignorable, so a repair never joins lines.

IGNORABLE = frozenset(" \t\x0b\x0c\r*_#")
DECORATION = frozenset("*_#")
EMPHASIS = frozenset("*_")


def _fold(c: str) -> str:
    return chr(ord(c) + 32) if "A" <= c <= "Z" else c


def marker_key(text: str) -> str:
    """The key a marker is matched by (kernel §4a)."""
    return "".join(_fold(c) for c in text if c not in IGNORABLE)


def repairable_markers(markers: list[str]) -> tuple[list[str], list[str]]:
    """(repairable, unrepaired): markers with a non-empty key that no other
    marker string shares, and the rest, each in first-seen order."""
    distinct = list(dict.fromkeys(m for m in markers if m))
    by_key: dict[str, list[str]] = {}
    for m in distinct:
        by_key.setdefault(marker_key(m), []).append(m)
    ok = [m for m in distinct if marker_key(m) and len(by_key[marker_key(m)]) == 1]
    return ok, [m for m in distinct if m not in ok]


def decoration_start(text: str, run_start: int, core_start: int) -> int | None:
    """Where the left decoration of a core begins, or None (kernel §4a):
    the first ``*``, ``_`` or ``#`` in the ignorable run before the core
    whose preceding character is whitespace or the start of text."""
    for i in range(run_start, core_start):
        if text[i] in DECORATION and (i == 0 or text[i - 1] in core.WHITESPACE):
            return i
    return None


def occurrence_span(text: str, core_start: int, core_end: int,
                    run_start: int, word_start: int) -> tuple[int, int]:
    """The span of a loose occurrence: its core widened over decoration.
    Decoration sits before the core's first character that is not a line
    feed (``word_start``, whose ignorable run starts at ``run_start``): a
    marker that begins a line keeps its line feed outside the decoration."""
    left = decoration_start(text, run_start, word_start)
    if left is None:
        return core_start, core_end
    end = core_end
    if any(c in EMPHASIS for c in text[left:word_start]):
        while end < len(text) and text[end] in EMPHASIS:
            end += 1
    return min(core_start, left), end


def _normalized(text: str) -> tuple[str, list[int], list[int]]:
    """The reader text without ignorables, ASCII lowercased; for each kept
    character its position and the start of the ignorable run before it."""
    chars: list[str] = []
    pos: list[int] = []
    runs: list[int] = []
    run = 0
    for i, c in enumerate(text):
        if c in IGNORABLE:
            continue
        chars.append(_fold(c))
        pos.append(i)
        runs.append(run)
        run = i + 1
    return "".join(chars), pos, runs


def loose_occurrences(text: str, marker: str, norm=None) -> list[tuple[int, int]]:
    """Every loose occurrence of ``marker`` as its span (start, end),
    leftmost first, without overlap in the key sequence."""
    key = marker_key(marker)
    if not key:
        return []
    chars, pos, runs = norm or _normalized(text)
    lead = len(key) - len(key.lstrip("\n"))
    out: list[tuple[int, int]] = []
    k = chars.find(key)
    while k >= 0:
        last = k + len(key) - 1
        w = min(k + lead, last)
        out.append(occurrence_span(text, pos[k], pos[last] + 1, runs[w], pos[w]))
        k = chars.find(key, k + len(key))
    return out


def written_exactly(text: str, marker: str, spans: list[tuple[int, int]]) -> bool:
    """Kernel §4a: the marker occurs as plain text (as §4 searches it),
    and that occurrence is not the inside of a larger loose span — which
    would make it decoration-wrapped (``**Answer:**`` for ``Answer:``)."""
    p = text.find(marker)
    while p >= 0:
        q = p + len(marker)
        if not any(a <= p and q <= b and b - a > q - p for a, b in spans):
            return True
        p = text.find(marker, q)
    return False


def repair_markers(text: str, markers: list[str]) -> tuple[str, list[dict]]:
    """Kernel §4a: rewrite every misspelled marker to its template spelling
    unless the marker is written exactly somewhere. Returns the rewritten
    text and the ``marker`` repairs in reply order."""
    norm = _normalized(text)
    chosen: list[tuple[int, int, str]] = []
    for marker in markers:
        spans = loose_occurrences(text, marker, norm)
        if written_exactly(text, marker, spans):
            continue
        chosen += [(a, b, marker) for a, b in spans]
    if not chosen:
        return text, []
    chosen.sort()
    for (a1, b1, m1), (a2, b2, m2) in zip(chosen, chosen[1:]):
        if a2 < b1:
            refuse("parse-ambiguous",
                   f"the reply's {text[a1:b1]!r} and {text[a2:b2]!r} overlap; read as the "
                   f"markers {m1!r} and {m2!r} they would share text — refusing to guess")
    pieces: list[str] = []
    repairs: list[dict] = []
    pos = 0
    for a, b, marker in chosen:
        pieces += [text[pos:a], marker]
        repairs.append({"repair": "marker", "marker": marker, "saw": text[a:b]})
        pos = b
    pieces.append(text[pos:])
    return "".join(pieces), repairs


def refuse_missing(raw: dict[str, str], field_names: list[str]) -> None:
    missing = [n for n in field_names if n not in raw]
    if missing:
        refuse("parse-missing-fields",
               "reply is missing pattern section(s): " + ", ".join(repr(n) for n in missing),
               partial=raw)


class ReaderResult:
    """What the derived reader found: raw captures, the tolerances it
    applied (kernel §4a), and which fields ran to the end of the text."""

    __slots__ = ("raw", "repairs", "to_end")

    def __init__(self, raw: dict[str, str], repairs: list[dict], to_end: set[str]):
        self.raw = raw
        self.repairs = repairs
        self.to_end = to_end


class DerivedReader(Reader):
    """The template read backwards. ``anchors`` are ``(name, prefix,
    suffix)`` per in_template output field, instantiated at bind; ``tail`` is
    the literal after the pattern (kernel §4). With ``repair`` misspelled
    markers are repaired (kernel §4a); a strict adapter passes False."""

    def __init__(self, anchors: list[tuple[str, str, str]], tail: str = "",
                 repair: bool = True):
        self.anchors = list(anchors)
        self.tail = tail
        searched = [core.rstrip(p) for _, p, _ in self.anchors] + \
                   [core.strip(s) for _, _, s in self.anchors] + [core.strip(self.tail)]
        self.repairable, self.unrepaired = repairable_markers(searched)
        if not repair:
            self.repairable, self.unrepaired = [], []

    def markers(self) -> list[str]:
        out = []
        for _, prefix, suffix in self.anchors:
            out.append(core.rstrip(prefix))
            out.append(core.strip(suffix))
        if core.strip(self.tail):
            out.append(core.strip(self.tail))
        return [m for m in out if m]

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        return self.read(text, field_names).raw

    def read(self, text: str, field_names: list[str], *, allow_missing: bool = False) -> ReaderResult:
        """Kernel §4 and §4a: repair markers, then read the rewritten text.
        With ``allow_missing`` the caller decides what a missing field means."""
        repairs: list[dict] = []
        if self.repairable:
            text, repairs = repair_markers(text, self.repairable)
        wanted = [a for a in self.anchors if a[0] in field_names]
        boundaries: list[tuple[int, int, str | None, str]] = []
        for name, prefix, suffix in wanted:
            marker = core.rstrip(prefix)
            if not marker:          # the whole-reply field (kernel §4): anchored at the start
                boundaries.append((0, 0, name, suffix))
                continue
            count = text.count(marker)
            if count > 1:
                refuse("parse-ambiguous",
                       f"anchor {marker!r} for field {name!r} appears {count} times in the "
                       f"reply — refusing to guess")
            idx = text.find(marker)
            if idx < 0:
                continue
            boundaries.append((idx, idx + len(marker), name, suffix))
        tail = core.strip(self.tail)
        if tail:
            count = text.count(tail)
            if count > 1:
                refuse("parse-ambiguous",
                       f"tail {tail!r} appears {count} times in the reply — refusing to "
                       f"guess which one ends the reply")
            t_idx = text.find(tail)
            if t_idx >= 0:
                boundaries.append((t_idx, t_idx, None, ""))
        boundaries.sort(key=lambda b: (b[0], b[1]))
        raw: dict[str, str] = {}
        to_end: set[str] = set()
        notes: list[dict] = []

        def ignored(piece: str) -> None:
            if core.strip(piece):
                notes.append({"repair": "ignored", "saw": core.strip(piece)})

        if boundaries:
            ignored(text[:boundaries[0][0]])
        for i, (start, after, name, suffix) in enumerate(boundaries):
            last = i + 1 == len(boundaries)
            if name is None:        # the tail: the reply ends here
                if last:
                    ignored(text[start + len(tail):])
                continue
            chunk = text[after:len(text) if last else boundaries[i + 1][0]]
            close = core.strip(suffix)
            raw[name] = core.strip(_cut_at_close(chunk, close, name))
            idx = chunk.find(close) if close else -1
            if idx >= 0:
                ignored(chunk[idx + len(close):])
            elif last:
                to_end.add(name)
            elif close:
                notes.append({"repair": "unclosed", "field": name, "close": close})
        if not allow_missing:
            refuse_missing(raw, field_names)
        return ReaderResult(raw, repairs + notes, to_end)

    def join(self, spelled: list[tuple[str, str]]) -> str:
        by_name = dict(spelled)
        check_collisions(spelled, self.markers())
        pieces = [prefix + by_name[name] + suffix
                  for name, prefix, suffix in self.anchors if name in by_name]
        return ("".join(pieces) + (self.tail if pieces else "")).strip("\n")

    def skeleton(self) -> dict:
        """What the reply must contain: the bytes before the first hole
        (prefill) and the marker that ends it (stop)."""
        if not self.anchors:
            return {"prefill": "", "stops": []}
        prefill = self.anchors[0][1]
        last_close = core.strip(self.anchors[-1][2])
        stop = core.strip(self.tail) or last_close
        return {"prefill": prefill, "stops": [stop] if stop else []}

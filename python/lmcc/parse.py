"""Reading the reply: routings, spans, and the lens.

Routings run before the lens (kernel §6): each collects a **span** of
parts for a field — text matches (``between``, ``pattern``,
``line_prefixed``) or response parts of a channel kind — and may
``consume`` its text matches from what the lens sees.

The lens (kernel §4) is one document form for the reply with three faces
on one object: ``split`` reads, ``join`` writes demos, ``format`` writes
the ``{format}`` skeleton. ``derived`` is kernel grammar: the template
read backwards. Any other kind is vocabulary through the lens socket.
"""

from __future__ import annotations

import re

from . import core
from .errors import refuse


# ---------------------------------------------------------------- routings


def _text_spans(text: str, routing: dict) -> list[tuple[int, int, str]]:
    """(start, end, capture) for one text extractor — kernel §6 scans."""
    spans: list[tuple[int, int, str]] = []
    if "between" in routing:
        open_, close = routing["between"]
        pos = 0
        while True:
            i = text.find(open_, pos)
            if i < 0:
                break
            j = text.find(close, i + len(open_))
            if j < 0:
                break
            spans.append((i, j + len(close), text[i + len(open_):j]))
            pos = j + len(close)
    elif "line_prefixed" in routing:
        prefix = routing["line_prefixed"]
        pos = 0
        for line in text.split("\n"):
            if line.startswith(prefix):
                spans.append((pos, pos + len(line), line[len(prefix):]))
            pos += len(line) + 1
    else:
        pattern = re.compile(routing["pattern"], re.DOTALL)
        for m in pattern.finditer(text):
            if m.end() == m.start():
                continue
            cap = m.group(1) if pattern.groups else m.group(0)
            spans.append((m.start(), m.end(), cap if cap is not None else ""))
    return spans


def apply_routings(text: str, parts: list[dict], routings: list[tuple[str, dict]]
                   ) -> tuple[str, dict[str, core.Span]]:
    """Run all routings; return (remaining text, {field: Span})."""
    found: dict[str, core.Span] = {}
    for field_name, r in routings:
        if r["from"].startswith("channel:"):
            kind = r["from"].split(":", 1)[1]
            span = core.Span([p for p in parts if p.get("kind") == kind])
        else:
            spans = _text_spans(text, r)
            span = core.Span([core.text_part(cap) for _, _, cap in spans])
            if r.get("consume") and spans:
                pieces, pos = [], 0
                for start, end, _ in spans:
                    pieces.append(text[pos:start])
                    pos = end
                pieces.append(text[pos:])
                text = "".join(pieces)
        if field_name in found:
            found[field_name] = core.Span(found[field_name].parts + span.parts)
        else:
            found[field_name] = span
    return text, found


# ------------------------------------------------------------------ lenses


class Lens:
    """One reply document form; three faces on one object (kernel §4)."""

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        raise NotImplementedError

    def join(self, spelled: list[tuple[str, str]]) -> str:
        raise NotImplementedError

    def format(self, placeholders: list[tuple[str, str]]) -> str:
        return self.join(placeholders)

    def requires(self) -> list[str]:
        return []

    def patch(self, fields: list) -> dict:
        return {}

    def skeleton(self) -> dict:
        return {}


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
                       f"field {name!r}: its spelled value contains the lens marker "
                       f"{marker!r}; the demo could not be read back as written")


class DerivedLens(Lens):
    """The template read backwards. ``anchors`` are ``(name, prefix,
    suffix)`` per visible output field, instantiated at bind; ``tail`` is
    the literal after the pattern (kernel §4)."""

    def __init__(self, anchors: list[tuple[str, str, str]], tail: str = ""):
        self.anchors = list(anchors)
        self.tail = tail

    def markers(self) -> list[str]:
        out = []
        for _, prefix, suffix in self.anchors:
            out.append(core.rstrip(prefix))
            out.append(core.strip(suffix))
        if core.strip(self.tail):
            out.append(core.strip(self.tail))
        return [m for m in out if m]

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        wanted = [a for a in self.anchors if a[0] in field_names]
        boundaries: list[tuple[int, int, str | None, str]] = []
        for name, prefix, suffix in wanted:
            marker = core.rstrip(prefix)
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
        for i, (start, after, name, suffix) in enumerate(boundaries):
            if name is None:
                continue
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
            chunk = _cut_at_close(text[after:end], core.strip(suffix), name)
            raw[name] = core.strip(chunk)
        missing = [n for n in field_names if n not in raw]
        if missing:
            refuse("parse-missing-fields",
                   "reply is missing pattern section(s): " + ", ".join(repr(n) for n in missing),
                   partial=raw)
        return raw

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

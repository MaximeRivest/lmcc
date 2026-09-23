"""Incremental, sans-I/O parsing (kernel §8).

This is a reducer over response deltas, not a second parser. Every feed
does work proportional to the delta, never to the reply: markers are
found by incremental scanners over a small overlap window, and each
field keeps only the text it already emitted plus a short held tail
(outer whitespace and any suffix that can still grow into a marker).
``finish`` delegates the final structural checks and typed reads to
:meth:`Plan.parse`, then releases EOF-held text and typed ``field_done``
events, after proving that the incremental projection agrees with batch.

Hazard rule. A marker occurrence *acts* — opens a field's section, ends
the previous one, or fixes a close — only once no boundary marker can
still be growing across it. Otherwise a marker learned later could start
inside an earlier one and shrink a section whose text was already
emitted, which the hold-back law forbids. The check is exact: it costs
nothing for templates whose markers cannot overlap.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import core
from .reader import (DerivedReader, EMPHASIS, IGNORABLE, Reader, _fold, _text_captures,
                     marker_key, repair_markers)

_WS = core.WHITESPACE


@dataclass(frozen=True)
class StreamResult:
    """The events caused by EOF and the final typed values."""

    events: list[dict]
    values: dict
    repairs: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.repairs is None:
            object.__setattr__(self, "repairs", [])


# ------------------------------------------------------------ primitives


class _Prefixes:
    """Every proper prefix of a marker set: "can this suffix still grow
    into a marker?" answered in O(longest marker)."""

    def __init__(self, markers: list[str]):
        self.table: set[str] = set()
        self.longest = 0
        for marker in markers:
            for n in range(1, len(marker)):
                self.table.add(marker[:n])
            self.longest = max(self.longest, len(marker) - 1)

    def hold(self, text: str) -> int:
        """Length of the longest suffix of ``text`` that is a proper prefix
        of some marker (kernel §8 hold-back)."""
        for n in range(min(len(text), self.longest), 0, -1):
            if text[-n:] in self.table:
                return n
        return 0

    def grows_between(self, window: str, end: int, lo: int, hi: int) -> bool:
        """Does any suffix of the text (whose last ``len(window)`` characters
        are ``window`` and which ends at absolute ``end``) that can still grow
        into a marker start strictly between absolute ``lo`` and ``hi``?"""
        first = max(1, end - hi + 1)
        last = min(self.longest, len(window), end - lo - 1)
        for n in range(first, last + 1):
            if window[-n:] in self.table:
                return True
        return False


class _Scanner:
    """Non-overlapping occurrences of one marker (``str.count`` order),
    reported by absolute start as soon as each is complete."""

    __slots__ = ("marker", "end", "pending")

    def __init__(self, marker: str, start: int):
        self.marker = marker
        self.end = start          # absolute position up to which text was seen
        self.pending = ""         # unresolved suffix (shorter than the marker)

    def feed(self, text: str) -> list[int]:
        marker = self.marker
        if not text or not marker:
            self.end += len(text)
            return []
        buf = self.pending + text
        base = self.end - len(self.pending)
        found: list[int] = []
        i = 0
        while True:
            j = buf.find(marker, i)
            if j < 0:
                break
            found.append(base + j)
            i = j + len(marker)
        self.end += len(text)
        keep = max(i, len(buf) - (len(marker) - 1))
        self.pending = buf[keep:]
        return found


class _Field:
    """Per-field emission state shared by every projection kind."""

    __slots__ = ("name", "present", "started", "emitted", "has_emitted", "pending")

    def __init__(self, name: str):
        self.name = name
        self.present = False
        self.started = False
        self.emitted: list[str] = []
        self.has_emitted = False
        self.pending: list[str] = []

    def emit(self, text: str) -> None:
        if text:
            self.emitted.append(text)
            self.has_emitted = True
            self.pending.append(text)

    def emitted_text(self) -> str:
        return "".join(self.emitted)


# -------------------------------------------------------------- find rules
#
# Each rule is a transducer: it receives the text delta left by the
# previous stage and returns the stable text it passes on. Removing
# stages hold text that may still become a match; the rest streams.


class _Between:
    def __init__(self, rule: dict):
        self.open, self.close = rule["between"]
        self.remove = bool(rule.get("remove"))
        self.hold = _Prefixes([self.open])
        self.buf = ""
        self.inside = False
        self.captures: list[str] = []

    def feed(self, delta: str, final: bool) -> str:
        out: list[str] = [] if self.remove else [delta]
        buf = self.buf + delta
        while True:
            if not self.inside:
                i = buf.find(self.open)
                if i < 0:
                    if self.remove:
                        keep = 0 if final else self.hold.hold(buf)
                        out.append(buf[:len(buf) - keep])
                        buf = buf[len(buf) - keep:]
                    else:
                        keep = min(len(buf), max(len(self.open) - 1, 0))
                        buf = buf[len(buf) - keep:]
                    break
                if self.remove:
                    out.append(buf[:i])
                buf = buf[i:]
                self.inside = True
            j = buf.find(self.close, len(self.open))
            if j < 0:
                if final and self.remove:
                    out.append(buf)  # batch ignores an unclosed extractor
                    buf = ""
                break
            self.captures.append(core.strip(buf[len(self.open):j]))
            buf = buf[j + len(self.close):]
            self.inside = False
            if not self.open and not self.close:
                break  # batch loops forever here; do not hang the reducer too
        self.buf = buf
        return "".join(out)


class _LinePrefixed:
    def __init__(self, rule: dict):
        self.prefix = rule["line_prefixed"]
        self.remove = bool(rule.get("remove"))
        self.line = ""
        self.captures: list[str] = []

    def feed(self, delta: str, final: bool) -> str:
        out: list[str] = [] if self.remove else [delta]
        lines = (self.line + delta).split("\n")
        last = lines.pop()
        for line in lines:
            if line.startswith(self.prefix):
                self.captures.append(core.strip(line[len(self.prefix):]))
                if self.remove:
                    out.append("\n")
            elif self.remove:
                out.append(line + "\n")
        if final:
            if last.startswith(self.prefix):
                self.captures.append(core.strip(last[len(self.prefix):]))
            elif self.remove:
                out.append(last)
            last = ""
        self.line = last
        return "".join(out)


class _Pattern:
    """A regex needs the whole text: later bytes can change any match."""

    def __init__(self, rule: dict, pattern):
        self.rule = rule
        self.pattern = pattern
        self.remove = bool(rule.get("remove"))
        self.pieces: list[str] = []
        self.captures: list[str] = []

    def feed(self, delta: str, final: bool) -> str:
        self.pieces.append(delta)
        if not final:
            return "" if self.remove else delta
        text = "".join(self.pieces)
        captures = _text_captures(text, self.rule, self.pattern)
        self.captures = [core.strip(cap) for _, _, cap in captures]
        if not self.remove:
            return ""
        if not captures:
            return text
        out, pos = [], 0
        for start, end, _ in captures:
            out.append(text[pos:start])
            pos = end
        out.append(text[pos:])
        return "".join(out)


class _PartSource:
    """Text of every part of one kind, each stripped, joined by newlines."""

    def __init__(self, kind: str):
        self.kind = kind
        self.texts: list[list[str]] = []   # one piece list per text-bearing part
        self.any_part = False               # matching parts, text or not
        self.held = ""
        self.has_emitted = False

    @property
    def captures(self) -> list[str]:
        return [core.strip("".join(pieces)) for pieces in self.texts]

    def part(self, kind: str, text: str | None, new_part: bool) -> str:
        """A part delta arrived; return this rule's stable raw delta."""
        if kind != self.kind:
            return ""
        self.any_part = True
        if text is None:
            return ""
        out = ""
        if new_part:
            self.texts.append([])
            self.held = ""
            self.has_emitted = False
            if len(self.texts) > 1:
                out = "\n"
        self.texts[-1].append(text)
        candidate = self.held + text
        if not self.has_emitted:
            candidate = candidate.lstrip(_WS)
        stable = candidate.rstrip(_WS)
        self.held = candidate[len(stable):]
        if stable:
            self.has_emitted = True
        return out + stable


# ---------------------------------------------------------- derived reader


class _Section:
    """One field's section of the reader text (kernel §4 read backwards)."""

    __slots__ = ("field", "start", "after", "close", "scanner", "close_starts",
                 "end", "received", "held", "fixed", "hold")

    def __init__(self, field: _Field, start: int, after: int, close: str, hold: _Prefixes):
        self.field = field
        self.start = start
        self.after = after
        self.close = close
        self.scanner = _Scanner(close, after) if close else None
        self.close_starts: list[int] = []
        self.end: int | None = None
        self.received = after     # absolute position up to which held reaches
        self.held = ""            # a suffix of T[after:received] not yet emitted
        self.fixed: str | None = None
        self.hold = hold          # boundary markers + own close

    def cut(self, limit: int) -> str:
        """The held text up to absolute ``limit``; drops the rest."""
        if limit >= self.received:
            return self.held
        drop = self.received - limit
        if drop > len(self.held):
            if self.field.has_emitted:
                raise RuntimeError(
                    f"stream projection for {self.field.name!r} revised emitted text")
            return ""
        return self.held[:len(self.held) - drop]

    def advance(self, limit: int | None) -> None:
        """Emit the stable prefix of the held text (up to ``limit``)."""
        candidate = self.held if limit is None else self.cut(limit)
        rest = "" if limit is None else self.held[len(candidate):]
        if not self.field.has_emitted:
            candidate = candidate.lstrip(_WS)
        n = self.hold.hold(candidate)
        stable = candidate[:len(candidate) - n].rstrip(_WS)
        self.field.emit(stable)
        self.held = candidate[len(stable):] + rest

    def fix(self, limit: int) -> None:
        """The section is final up to ``limit``: release everything."""
        candidate = self.cut(limit)
        if not self.field.has_emitted:
            candidate = candidate.lstrip(_WS)
        self.field.emit(candidate.rstrip(_WS))
        self.fixed = self.field.emitted_text()
        self.held = ""


class _DerivedReducer:
    def __init__(self, reader: DerivedReader, fields: dict[str, _Field], names: list[str]):
        self.fields = fields
        self.wanted = [(name, core.rstrip(prefix), core.strip(suffix))
                       for name, prefix, suffix in reader.anchors if name in names]
        self.tail = core.strip(reader.tail)
        markers = [m for _, m, _ in self.wanted] + ([self.tail] if self.tail else [])
        self.bounds = _Prefixes(markers)
        self.holds: dict[str, _Prefixes] = {}
        for _, _, close in self.wanted:
            if close not in self.holds:
                self.holds[close] = _Prefixes(markers + ([close] if close else []))
        self.scanners = {m: _Scanner(m, 0) for m in dict.fromkeys(markers)}
        self.first: dict[str, int] = {}
        self.duplicated: set[str] = set()
        self.sections: dict[str, _Section] = {}
        self.length = 0
        self.window = ""
        self.poisoned = False

    def feed(self, delta: str, final: bool) -> None:
        a = self.length
        b = a + len(delta)
        self.length = b
        if self.bounds.longest:
            self.window = (self.window + delta)[-self.bounds.longest:]

        # 1. boundary occurrences (first position, duplicates) — global, like str.count
        for marker, scanner in self.scanners.items():
            for q in scanner.feed(delta):
                if marker in self.first:
                    self.duplicated.add(marker)
                else:
                    self.first[marker] = q

        # 2. sections in batch order: sorted first occurrences, tail last on ties
        bounds: list[tuple[int, int, str | None, str]] = []
        for name, marker, close in self.wanted:
            if marker in self.first:
                bounds.append((self.first[marker], self.first[marker] + len(marker), name, close))
        if self.tail and self.tail in self.first:
            bounds.append((self.first[self.tail], self.first[self.tail], None, ""))
        bounds.sort(key=lambda x: (x[0], x[1]))
        for i, (start, after, name, close) in enumerate(bounds):
            if name is None:
                continue
            section = self.sections.get(name)
            if section is None:
                field = self.fields[name]
                field.present = True
                section = _Section(field, start, after, close, self.holds[close])
                self.sections[name] = section
            end = bounds[i + 1][0] if i + 1 < len(bounds) else None
            if section.end is not None and end is not None and end < section.end and section.fixed is not None:
                raise RuntimeError(f"stream projection for {name!r} revised emitted text")
            section.end = end

        # 3. route the delta into sections; feed close scanners
        for section in self.sections.values():
            limit = b if section.end is None else min(b, section.end)
            if section.fixed is not None:
                pass  # raw is final; only its close scanner keeps counting
            elif section.received < limit:
                section.held += delta[max(0, section.received - a):limit - a]
                section.received = limit
            elif section.received > limit:
                section.held = section.cut(limit)  # a boundary landed inside held text
                section.received = limit
            scanner = section.scanner
            if scanner is not None and scanner.end < b and (
                    section.end is None or scanner.end < section.end):
                section.close_starts.extend(scanner.feed(delta[max(0, scanner.end - a):]))

        # 4. the longest boundary prefix still growing at the end of the text
        grow_start = b - self.bounds.hold(self.window)

        # 5. resolve: duplicates, fixes, and stable emission
        poisoned = bool(self.duplicated)
        for section in self.sections.values():
            end = section.end
            closes = [q for q in section.close_starts
                      if end is None or q + len(section.close) <= end]
            if len(closes) >= 2:
                poisoned = True
            if section.fixed is not None:
                continue
            stop = b if end is None else end
            if end is not None and end <= section.after:
                section.fix(section.after)
            elif final:
                section.fix(closes[0] if closes else stop)
            elif end is not None and grow_start >= end:
                section.fix(closes[0] if closes else end)
            elif closes and end is None and grow_start >= closes[0] + len(section.close):
                section.fix(closes[0])
            elif not self.bounds.grows_between(self.window, b, section.start - 1, section.after):
                section.advance(closes[0] if closes else None)
        self.poisoned = poisoned

    def final_raw(self) -> dict[str, str]:
        return {name: section.fixed for name, section in self.sections.items()
                if section.fixed is not None}


# ---------------------------------------------------------- marker repair


class _MarkerRepair:
    """Kernel §4a/§8: the stage between the find rules and the derived
    reader. It passes text on unchanged, holding only what could still grow
    into a loose occurrence or its decoration; from the first span that
    needs a repair it holds everything until EOF, where the batch rewrite
    decides (a later exact marker can still make that span content)."""

    def __init__(self, markers: list[str]):
        self.markers = list(markers)
        self.keys = [(marker_key(m).lstrip("\n"), m,
                      len(marker_key(m)) - len(marker_key(m).lstrip("\n")))
                     for m in self.markers]
        self.lead = max(lead for _, _, lead in self.keys)
        self.longest = max(len(k) for k, _, _ in self.keys)
        self.prefixes = _Prefixes([k for k, _, _ in self.keys])
        self.pieces: list[str] = []
        self.buf = ""            # text[released:]
        self.before = ""         # text[released - 1], for decoration checks
        self.released = 0
        self.length = 0
        self.run_start = 0       # start of the trailing ignorable run
        self.window: list[tuple[str, int, int]] = []   # (folded char, position, run start)
        self.pending: list[tuple[str, int, int, int]] = []  # awaiting their right decoration
        self.held_from: int | None = None
        self.holding_reason: str | None = None

    def _at(self, j: int) -> str:
        return self.buf[j - self.released] if j >= self.released else self.before

    def _text(self, a: int, b: int) -> str:
        return self.buf[a - self.released:b - self.released]

    def feed(self, delta: str, final: bool) -> str:
        a = self.length
        self.pieces.append(delta)
        self.buf += delta
        self.length += len(delta)
        if final:
            text = "".join(self.pieces)
            rewritten, _ = repair_markers(text, self.markers)
            if rewritten[:self.released] != text[:self.released]:
                raise RuntimeError("marker repair revised text it had already passed on")
            out = rewritten[self.released:]
            self.released, self.buf = len(text), ""
            return out
        if self.held_from is not None:
            return ""
        for offset, c in enumerate(delta):
            i = a + offset
            if c in IGNORABLE:
                continue
            self.window.append((_fold(c), i, self.run_start))
            self.run_start = i + 1
            if len(self.window) > self.longest:
                del self.window[0]
            for key, marker, lead in self.keys:
                n = len(key)
                if n <= len(self.window) and key[-1] == self.window[-1][0] and \
                        "".join(ch for ch, _, _ in self.window[-n:]) == key:
                    _, core_start, run = self.window[-n]
                    self.pending.append((marker, run, core_start, lead, i + 1))
        # resolve occurrences whose span is known
        waiting = []
        for item in self.pending:
            marker, run, core_start, lead, core_end = item
            left = decoration_start_at(self._at, run, core_start)
            end = core_end
            if left is not None and any(self._at(j) in EMPHASIS for j in range(left, core_start)):
                while end < self.length and self._at(end) in EMPHASIS:
                    end += 1
                if end == self.length:
                    waiting.append(item)
                    continue
            start = core_start if left is None else left
            if lead:
                q = start
                while q > self.released and self._at(q - 1) in " \t\x0b\x0c\r":
                    q -= 1
                taken = 0
                while taken < lead and q > self.released and self._at(q - 1) == "\n":
                    q -= 1
                    taken += 1
                if taken:
                    start = q
            if self._text(start, end) != marker:
                self.held_from = start
                break
        self.pending = [] if self.held_from is not None else waiting
        # the release point: nothing that could still start a repaired span
        limit = self.length if self.held_from is None else self.held_from
        if self.run_start < self.length:
            limit = min(limit, self.run_start)
        n = self.prefixes.hold("".join(ch for ch, _, _ in self.window))
        if n:
            limit = min(limit, self.window[-n][2])
        for _, run, _, _, _ in self.pending:
            limit = min(limit, run)
        # a span may take the line feeds (and spaces) just before it: hold them
        for _ in range(self.lead):
            while limit > self.released and self._at(limit - 1) in " \t\x0b\x0c\r":
                limit -= 1
            if limit > self.released and self._at(limit - 1) == "\n":
                limit -= 1
        limit = max(limit, self.released)
        out = self.buf[:limit - self.released]
        if out:
            self.before = out[-1]
            self.buf = self.buf[len(out):]
            self.released = limit
        return out


def decoration_start_at(at, run_start: int, core_start: int) -> int | None:
    """``reader.decoration_start`` over a character accessor."""
    for i in range(run_start, core_start):
        if at(i) in "*_#" and (i == 0 or at(i - 1) in core.WHITESPACE):
            return i
    return None


# -------------------------------------------------------------- describe


def describe_streaming(plan) -> dict:
    """The buffering choices in_template through ``plan.describe()``."""
    counts: dict[str, int] = {}
    for field, _ in plan.find_rules:
        counts[field] = counts.get(field, 0) + 1
    routes = []
    modes = []
    removing_pattern = False
    for field, rule in plan.find_rules:
        reason = None
        if "pattern" in rule:
            mode, reason = "buffered", "a pattern find rule waits for EOF"
            removing_pattern |= bool(rule.get("remove"))
        elif counts[field] > 1:
            mode, reason = "buffered", "multiple find rules concatenate by declaration order"
        else:
            mode = "incremental"
        item = {"field": field, "from": rule["from"], "mode": mode}
        if reason:
            item["reason"] = reason
        routes.append(item)
        modes.append(mode)
    custom_face = getattr(type(plan.reader), "stream", None)
    custom_stream = custom_face is not None and custom_face is not Reader.stream
    if (isinstance(plan.reader, DerivedReader) or custom_stream) and not removing_pattern:
        reader_mode, reader_reason = "incremental", None
    elif isinstance(plan.reader, DerivedReader) or custom_stream:
        reader_mode, reader_reason = "buffered", "a removing pattern find rule can revise the reader's text"
    else:
        reader_mode, reader_reason = "buffered", "reader provides no streaming face"
    reader = {"mode": reader_mode}
    if reader_reason:
        reader["reason"] = reader_reason
    modes.append(reader_mode)
    mode = "incremental" if set(modes) == {"incremental"} else (
        "buffered" if set(modes) == {"buffered"} else "hybrid")
    out = {"mode": mode, "reader": reader, "find": routes, "field_done": "finish"}
    out["repairs"] = ({"mode": "strict"} if plan.adapter.strict else
                      {"mode": "forgiving",
                       "reason": "from the first misspelled marker the rest of the reply waits "
                                 "for finish"})
    return out


# ----------------------------------------------------------------- stream


class Stream:
    """A plan-bound streaming parse reducer. Create with ``plan.stream()``."""

    def __init__(self, plan):
        self.plan = plan
        self._pieces: list[str] = []
        self._parts: list[dict] = []
        self._part_texts: list[list[str]] = []
        self._part_mode = False
        self._finished = False
        self._fields: dict[str, _Field] = {f.name: _Field(f.name) for f in plan.signature.fields}
        names = [f.name for f in plan.visible_outputs]
        # rule stages in declaration order; each field's stages by order
        self._stages: list[tuple[str, object]] = []
        self._by_field: dict[str, list[object]] = {}
        for field, rule in plan.find_rules:
            source = rule["from"]
            if source.startswith("part:"):
                stage: object = _PartSource(source.split(":", 1)[1])
            elif "between" in rule:
                stage = _Between(rule)
            elif "line_prefixed" in rule:
                stage = _LinePrefixed(rule)
            else:
                stage = _Pattern(rule, plan.pattern_binding())
            self._stages.append((field, stage))
            self._by_field.setdefault(field, []).append(stage)
        self._counted: dict[str, int] = {}   # captures already turned into deltas
        self._derived = (_DerivedReducer(plan.reader, self._fields, names)
                         if isinstance(plan.reader, DerivedReader) else None)
        self._repair = (_MarkerRepair(plan.reader.repairable)
                        if self._derived is not None and plan.reader.repairable else None)
        self._repair_find = _MarkerRepair(plan.find_repairable) if plan.find_repairable else None
        make_reader_stream = getattr(plan.reader, "stream", None)
        self._reader_stream = (None if self._derived is not None or make_reader_stream is None
                             else make_reader_stream(names))
        self._reader_prefixes: dict[str, str] = {}
        self._reader_final_names: set[str] | None = None

    # ------------------------------------------------------------ input

    def feed(self, delta: object) -> list[dict]:
        if self._finished:
            raise RuntimeError("stream is already finished")
        text, part = self._append(delta)
        self._run(text, part, final=False)
        return self._events(final=False)

    def finish(self, finish_reason: str | None = None) -> StreamResult:
        """End of stream. ``finish_reason`` is the lm15 stream end's; with
        ``"length"`` a cut output refuses ``parse-truncated`` (kernel §4a)."""
        if self._finished:
            raise RuntimeError("stream is already finished")
        self._finished = True
        response: object = {"role": "assistant", "parts": self._materialized_parts()} if self._part_mode \
            else "".join(self._pieces)
        if finish_reason is not None:
            message = response if isinstance(response, dict) else \
                {"role": "assistant", "parts": [core.text_part(response)]}
            response = {"message": message, "finish_reason": finish_reason}
        # Batch is the final authority. It preserves refusal code, fix,
        # partial, structural order, and typed-read order exactly.
        values, captures, repairs = self.plan._parse_with_captures(response)
        self._run("", None, final=True)
        events = self._events(final=True, final_captures=captures, values=values)
        return StreamResult(events, values, repairs)

    def _append(self, delta: object) -> tuple[str, tuple[str, str | None, bool] | None]:
        """Record the delta; return (text delta, part delta) where the part
        delta is (kind, text or None, is_new_part)."""
        if isinstance(delta, str):
            self._pieces.append(delta)
            if self._part_mode:
                return delta, self._append_part(core.text_part(delta))
            return delta, None
        core.validate_response_part(delta)
        if not self._part_mode:
            self._part_mode = True
            if self._pieces:
                self._append_part(core.text_part("".join(self._pieces)))
        part = self._append_part(dict(delta))
        text = delta.get("text", "") if delta.get("type") == "text" else ""
        if text:
            self._pieces.append(text)
        return text, part

    def _append_part(self, part: dict) -> tuple[str, str | None, bool]:
        kind = part.get("type")
        text = part.get("text")
        has_text = isinstance(text, str)
        if has_text and self._parts and self._parts[-1].get("type") == kind \
                and self._part_texts[-1] is not None:
            previous = self._parts[-1]
            self._part_texts[-1].append(text)
            for key, value in part.items():
                if key not in ("type", "text"):
                    previous[key] = value
            return kind, text, False
        self._parts.append(part)
        self._part_texts.append([text] if has_text else None)
        return kind, (text if has_text else None), True

    def _materialized_parts(self) -> list[dict]:
        out = []
        for part, texts in zip(self._parts, self._part_texts):
            if texts is not None:
                part = {**part, "text": "".join(texts)}
            out.append(part)
        return out

    # ------------------------------------------------------- projection

    def _run(self, text: str, part: tuple[str, str | None, bool] | None, *, final: bool) -> None:
        stage_text = text
        if self._repair_find is not None:      # §4a pass 1, before the find rules
            stage_text = self._repair_find.feed(stage_text, final)
        for field, stage in self._stages:
            if isinstance(stage, _PartSource):
                if part is not None:
                    kind, ptext, new_part = part
                    delta = stage.part(kind, ptext, new_part)
                    if stage.any_part:
                        self._fields[field].present = True
                    if len(self._by_field[field]) == 1:
                        self._fields[field].emit(delta)
                continue
            stage_text = stage.feed(stage_text, final)
            f = self._fields[field]
            if stage.captures:
                f.present = True
            if len(self._by_field[field]) == 1:
                done = self._counted.get(field, 0)
                for capture in stage.captures[done:]:
                    f.emit(("\n" if done else "") + capture)
                    done += 1
                self._counted[field] = done
        if self._derived is not None:
            if self._repair is not None:
                stage_text = self._repair.feed(stage_text, final)
            self._derived.feed(stage_text, final)
        elif self._reader_stream is not None:
            prefixes = self._reader_stream.feed(stage_text) if stage_text or not final else {}
            if final:
                prefixes = self._reader_stream.finish()
                self._reader_final_names = set(prefixes)
            for name, raw in prefixes.items():
                f = self._fields.get(name)
                if f is None:
                    continue
                f.present = True
                before = self._reader_prefixes.get(name, "")
                if not raw.startswith(before):
                    raise RuntimeError(f"reader stream prefix for {name!r} revised emitted text")
                self._reader_prefixes[name] = raw
                f.emit(raw[len(before):])

    def _final_projection(self) -> dict[str, str]:
        """What the incremental projection says each present field's raw
        text is, at EOF — checked against the batch captures."""
        out: dict[str, str] = {}
        if self._derived is not None:
            out.update(self._derived.final_raw())
        elif self._reader_stream is not None:
            out.update(self._reader_prefixes)
        for field, stages in self._by_field.items():
            f = self._fields[field]
            if not f.present:
                continue
            if len(stages) > 1:
                out[field] = "\n".join(c for stage in stages for c in stage.captures)
            else:
                out[field] = f.emitted_text()
        return out

    # ----------------------------------------------------------- events

    def _events(self, final: bool, *, final_captures: dict | None = None,
                values: dict | None = None) -> list[dict]:
        if self._derived is not None and self._derived.poisoned and not final:
            # A later delta can still supersede this provisional structural
            # reading; finish() invokes the batch parser and raises the
            # authoritative refusal. Pending text waits.
            return []
        events: list[dict] = []
        if final:
            assert final_captures is not None and values is not None
            projected = self._final_projection()
            if self._reader_stream is not None:
                expected = {f.name for f in self.plan.visible_outputs}
                actual = self._reader_final_names or set()
                if actual != expected:
                    raise RuntimeError(
                        f"reader stream fields {sorted(actual)!r} disagree with batch fields {sorted(expected)!r}")
            for name, raw in projected.items():
                if name in final_captures and raw != final_captures[name].text:
                    raise RuntimeError(f"stream projection for {name!r} disagrees with batch parse")
            for field in self.plan.signature.fields:
                if field.name not in final_captures:
                    continue
                f = self._fields[field.name]
                if not f.started:
                    f.started = True
                    events.append({"kind": "field_started", "field": field.name})
                raw = final_captures[field.name].text
                before = f.emitted_text()
                held_back = "".join(f.pending)
                if not raw.startswith(before[:len(before) - len(held_back)]):
                    raise RuntimeError(f"stream projection for {field.name!r} revised emitted text")
                already = before[:len(before) - len(held_back)]
                delta = raw[len(already):]
                if delta:
                    events.append({"kind": "field_delta", "field": field.name, "text": delta})
                events.append({"kind": "field_done", "field": field.name,
                               "value": values[field.name]})
            return events

        for field in self.plan.signature.fields:
            f = self._fields[field.name]
            if not f.present:
                continue
            if not f.started:
                f.started = True
                events.append({"kind": "field_started", "field": field.name})
            if f.pending:
                text = "".join(f.pending)
                f.pending.clear()
                events.append({"kind": "field_delta", "field": field.name, "text": text})
        return events

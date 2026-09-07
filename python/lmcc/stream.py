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
from .errors import refuse
from .parse import DerivedLens, Lens, _text_spans

_WS = core.WHITESPACE


@dataclass(frozen=True)
class StreamResult:
    """The events caused by EOF and the final typed values."""

    events: list[dict]
    values: dict


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


# -------------------------------------------------------------- routings
#
# Each routing is a transducer: it receives the text delta left by the
# previous stage and returns the stable text it passes on. Consuming
# stages hold text that may still become a match; the rest streams.


class _Between:
    def __init__(self, routing: dict):
        self.open, self.close = routing["between"]
        self.consume = bool(routing.get("consume"))
        self.hold = _Prefixes([self.open])
        self.buf = ""
        self.inside = False
        self.captures: list[str] = []

    def feed(self, delta: str, final: bool) -> str:
        out: list[str] = [] if self.consume else [delta]
        buf = self.buf + delta
        while True:
            if not self.inside:
                i = buf.find(self.open)
                if i < 0:
                    if self.consume:
                        keep = 0 if final else self.hold.hold(buf)
                        out.append(buf[:len(buf) - keep])
                        buf = buf[len(buf) - keep:]
                    else:
                        keep = min(len(buf), max(len(self.open) - 1, 0))
                        buf = buf[len(buf) - keep:]
                    break
                if self.consume:
                    out.append(buf[:i])
                buf = buf[i:]
                self.inside = True
            j = buf.find(self.close, len(self.open))
            if j < 0:
                if final and self.consume:
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
    def __init__(self, routing: dict):
        self.prefix = routing["line_prefixed"]
        self.consume = bool(routing.get("consume"))
        self.line = ""
        self.captures: list[str] = []

    def feed(self, delta: str, final: bool) -> str:
        out: list[str] = [] if self.consume else [delta]
        lines = (self.line + delta).split("\n")
        last = lines.pop()
        for line in lines:
            if line.startswith(self.prefix):
                self.captures.append(core.strip(line[len(self.prefix):]))
                if self.consume:
                    out.append("\n")
            elif self.consume:
                out.append(line + "\n")
        if final:
            if last.startswith(self.prefix):
                self.captures.append(core.strip(last[len(self.prefix):]))
            elif self.consume:
                out.append(last)
            last = ""
        self.line = last
        return "".join(out)


class _Pattern:
    """A regex needs the whole text: later bytes can change any match."""

    def __init__(self, routing: dict):
        self.routing = routing
        self.consume = bool(routing.get("consume"))
        self.pieces: list[str] = []
        self.captures: list[str] = []

    def feed(self, delta: str, final: bool) -> str:
        self.pieces.append(delta)
        if not final:
            return "" if self.consume else delta
        text = "".join(self.pieces)
        spans = _text_spans(text, self.routing)
        self.captures = [core.strip(cap) for _, _, cap in spans]
        if not self.consume:
            return ""
        if not spans:
            return text
        out, pos = [], 0
        for start, end, _ in spans:
            out.append(text[pos:start])
            pos = end
        out.append(text[pos:])
        return "".join(out)


class _Channel:
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
        """A part delta arrived; return this routing's stable raw delta."""
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


# ---------------------------------------------------------- derived lens


class _Section:
    """One field's section of the lens text (kernel §4 read backwards)."""

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
    def __init__(self, lens: DerivedLens, fields: dict[str, _Field], names: list[str]):
        self.fields = fields
        self.wanted = [(name, core.rstrip(prefix), core.strip(suffix))
                       for name, prefix, suffix in lens.anchors if name in names]
        self.tail = core.strip(lens.tail)
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


# -------------------------------------------------------------- describe


def describe_streaming(plan) -> dict:
    """The buffering choices visible through ``plan.describe()``."""
    counts: dict[str, int] = {}
    for field, _ in plan.routings:
        counts[field] = counts.get(field, 0) + 1
    routes = []
    modes = []
    consuming_pattern = False
    for field, routing in plan.routings:
        reason = None
        if "pattern" in routing:
            mode, reason = "buffered", "pattern routing waits for EOF"
            consuming_pattern |= bool(routing.get("consume"))
        elif counts[field] > 1:
            mode, reason = "buffered", "multiple routings concatenate by declaration order"
        else:
            mode = "incremental"
        item = {"field": field, "from": routing["from"], "mode": mode}
        if reason:
            item["reason"] = reason
        routes.append(item)
        modes.append(mode)
    custom_face = getattr(type(plan.lens), "stream", None)
    custom_stream = custom_face is not None and custom_face is not Lens.stream
    if (isinstance(plan.lens, DerivedLens) or custom_stream) and not consuming_pattern:
        lens_mode, lens_reason = "incremental", None
    elif isinstance(plan.lens, DerivedLens) or custom_stream:
        lens_mode, lens_reason = "buffered", "a consuming pattern routing can revise lens text"
    else:
        lens_mode, lens_reason = "buffered", "lens provides no streaming face"
    lens = {"mode": lens_mode}
    if lens_reason:
        lens["reason"] = lens_reason
    modes.append(lens_mode)
    mode = "incremental" if set(modes) == {"incremental"} else (
        "buffered" if set(modes) == {"buffered"} else "hybrid")
    return {"mode": mode, "lens": lens, "routings": routes, "field_done": "finish"}


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
        # routing stages in declaration order; each field's stages by order
        self._stages: list[tuple[str, object]] = []
        self._by_field: dict[str, list[object]] = {}
        for field, routing in plan.routings:
            source = routing["from"]
            if source.startswith("channel:"):
                stage: object = _Channel(source.split(":", 1)[1])
            elif "between" in routing:
                stage = _Between(routing)
            elif "line_prefixed" in routing:
                stage = _LinePrefixed(routing)
            else:
                stage = _Pattern(routing)
            self._stages.append((field, stage))
            self._by_field.setdefault(field, []).append(stage)
        self._counted: dict[str, int] = {}   # captures already turned into deltas
        self._derived = (_DerivedReducer(plan.lens, self._fields, names)
                         if isinstance(plan.lens, DerivedLens) else None)
        make_lens_stream = getattr(plan.lens, "stream", None)
        self._lens_stream = (None if self._derived is not None or make_lens_stream is None
                             else make_lens_stream(names))
        self._lens_prefixes: dict[str, str] = {}
        self._lens_final_names: set[str] | None = None

    # ------------------------------------------------------------ input

    def feed(self, delta: object) -> list[dict]:
        if self._finished:
            raise RuntimeError("stream is already finished")
        text, part = self._append(delta)
        self._run(text, part, final=False)
        return self._events(final=False)

    def finish(self) -> StreamResult:
        if self._finished:
            raise RuntimeError("stream is already finished")
        self._finished = True
        response: object = {"content": self._materialized_parts()} if self._part_mode \
            else "".join(self._pieces)
        # Batch is the final authority. It preserves refusal code, fix,
        # partial, structural order, and typed-read order exactly.
        values, spans = self.plan._parse_with_spans(response)
        self._run("", None, final=True)
        events = self._events(final=True, final_spans=spans, values=values)
        return StreamResult(events, values)

    def _append(self, delta: object) -> tuple[str, tuple[str, str | None, bool] | None]:
        """Record the delta; return (text delta, part delta) where the part
        delta is (kind, text or None, is_new_part)."""
        if isinstance(delta, str):
            self._pieces.append(delta)
            if self._part_mode:
                return delta, self._append_part(core.text_part(delta))
            return delta, None
        if not isinstance(delta, dict) or not isinstance(delta.get("kind"), str):
            refuse("response-malformed", "stream delta must be text or a part object with a string 'kind'")
        if "text" in delta and not isinstance(delta["text"], str):
            refuse("response-malformed", "a stream part delta's 'text' must be text")
        if not self._part_mode:
            self._part_mode = True
            if self._pieces:
                self._append_part(core.text_part("".join(self._pieces)))
        part = self._append_part(dict(delta))
        text = delta.get("text", "") if delta.get("kind") == "text" else ""
        if text:
            self._pieces.append(text)
        return text, part

    def _append_part(self, part: dict) -> tuple[str, str | None, bool]:
        kind = part.get("kind")
        text = part.get("text")
        has_text = isinstance(text, str)
        if has_text and self._parts and self._parts[-1].get("kind") == kind \
                and self._part_texts[-1] is not None:
            previous = self._parts[-1]
            self._part_texts[-1].append(text)
            for key, value in part.items():
                if key not in ("kind", "text"):
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
        for field, stage in self._stages:
            if isinstance(stage, _Channel):
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
            self._derived.feed(stage_text, final)
        elif self._lens_stream is not None:
            prefixes = self._lens_stream.feed(stage_text) if stage_text or not final else {}
            if final:
                prefixes = self._lens_stream.finish()
                self._lens_final_names = set(prefixes)
            for name, raw in prefixes.items():
                f = self._fields.get(name)
                if f is None:
                    continue
                f.present = True
                before = self._lens_prefixes.get(name, "")
                if not raw.startswith(before):
                    raise RuntimeError(f"lens stream prefix for {name!r} revised emitted text")
                self._lens_prefixes[name] = raw
                f.emit(raw[len(before):])

    def _final_projection(self) -> dict[str, str]:
        """What the incremental projection says each present field's raw
        text is, at EOF — checked against the batch spans."""
        out: dict[str, str] = {}
        if self._derived is not None:
            out.update(self._derived.final_raw())
        elif self._lens_stream is not None:
            out.update(self._lens_prefixes)
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

    def _events(self, final: bool, *, final_spans: dict | None = None,
                values: dict | None = None) -> list[dict]:
        if self._derived is not None and self._derived.poisoned and not final:
            # A later delta can still supersede this provisional structural
            # reading; finish() invokes the batch parser and raises the
            # authoritative refusal. Pending text waits.
            return []
        events: list[dict] = []
        if final:
            assert final_spans is not None and values is not None
            projected = self._final_projection()
            if self._lens_stream is not None:
                expected = {f.name for f in self.plan.visible_outputs}
                actual = self._lens_final_names or set()
                if actual != expected:
                    raise RuntimeError(
                        f"lens stream fields {sorted(actual)!r} disagree with batch fields {sorted(expected)!r}")
            for name, raw in projected.items():
                if name in final_spans and raw != final_spans[name].text:
                    raise RuntimeError(f"stream projection for {name!r} disagrees with batch parse")
            for field in self.plan.signature.fields:
                if field.name not in final_spans:
                    continue
                f = self._fields[field.name]
                if not f.started:
                    f.started = True
                    events.append({"kind": "field_started", "field": field.name})
                raw = final_spans[field.name].text
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

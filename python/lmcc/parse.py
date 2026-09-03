"""The lens machinery: extract algebra, the lens protocol, sections.

The extractor algebra (``between``, ``pattern``, ``line_prefixed``,
``parts``) is kernel grammar, like the template syntax — a fixed, versioned
set, not a registry. Named codecs and strategies are vocabulary; the algebra
they are built from is mechanics.

Routings run *before* section splitting. A routing with ``"strip": true``
removes its matches from the text, so e.g. inline ``<think>`` spans do not
pollute the sections they appear inside.
"""

from __future__ import annotations

import re

from . import core
from .errors import refuse

EXTRACT_KINDS = ("between", "pattern", "line_prefixed", "parts")

# Regex constructs outside the portable dialect (kernel §5): lookaround,
# backreferences, atomic groups, possessive quantifiers, and named groups
# (Python spells them (?P<n>), JavaScript (?<n>) — neither is universal;
# the algebra reads group 1, so names buy nothing). Scanned with escapes
# skipped so ``\(?=`` is not a false positive.
_NON_RE2 = re.compile(r"\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+")


def validate_extract(spec: dict, *, where: str) -> None:
    kind = spec.get("kind")
    if kind not in EXTRACT_KINDS:
        refuse("unknown-extract-kind",
               f"{where}: extract kind {kind!r} is not in the kernel algebra "
               f"{EXTRACT_KINDS}")
    required = {"between": ("open", "close"), "pattern": ("regex",),
                "line_prefixed": ("prefix",), "parts": ("part",)}[kind]
    for key in required:
        if key not in spec or not isinstance(spec[key], str) or (
                key != "part" and spec[key] == ""):
            refuse("entry-malformed",
                   f"{where}: extract {kind!r} needs a non-empty string {key!r}")
    if kind == "pattern":
        _check_re2(spec["regex"], where=where)


def _check_re2(regex: str, *, where: str) -> None:
    unescaped = re.sub(r"\\[^1-9k]", "", regex)   # drop escapes, keep \1 \k
    hit = _NON_RE2.search(unescaped)
    if hit:
        refuse("entry-malformed",
               f"{where}: regex {regex!r} uses {hit.group(0)!r}, which is "
               f"outside the portable RE2 dialect (no lookaround, "
               f"backreferences, named groups, atomic or possessive "
               f"constructs)")
    try:
        re.compile(regex, re.DOTALL)
    except re.error as exc:
        refuse("entry-malformed", f"{where}: regex {regex!r} does not compile: {exc}")


def run_text_extract(text: str, spec: dict, strip: bool) -> tuple[str, list[str]]:
    """Apply one extractor to text. Returns (possibly stripped text, matches).

    Semantics are spelled out in kernel §5 so that no host regex quirk
    leaks in: ``between`` and ``line_prefixed`` are plain scans; ``pattern``
    is leftmost-first, non-overlapping, dot-matches-newline, empty matches
    discarded."""
    kind = spec["kind"]
    spans: list[tuple[int, int, str]] = []   # (start, end, capture)
    if kind == "between":
        open_, close = spec["open"], spec["close"]
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
    elif kind == "line_prefixed":
        prefix = spec["prefix"]
        pos = 0
        for line in text.split("\n"):
            if line.startswith(prefix):
                spans.append((pos, pos + len(line), line[len(prefix):]))
            pos += len(line) + 1
    elif kind == "pattern":
        pattern = re.compile(spec["regex"], re.DOTALL)
        for m in pattern.finditer(text):
            if m.end() == m.start():
                continue
            spans.append((m.start(), m.end(),
                          m.group(1) if pattern.groups else m.group(0)))
    else:
        refuse("unknown-extract-kind", f"extract kind {kind!r} does not read text")
    matches = [cap if cap is not None else "" for _, _, cap in spans]
    if strip and spans:
        pieces, pos = [], 0
        for start, end, _ in spans:
            pieces.append(text[pos:start])
            pos = end
        pieces.append(text[pos:])
        text = "".join(pieces)
    return text, matches


def run_part_extract(parts: list[dict], spec: dict) -> list[str]:
    wanted = spec["part"]
    return [p.get("text", "") for p in parts if p.get("kind") == wanted]


def apply_routings(text: str, parts: list[dict], routings: list[dict],
                   coercions: dict) -> tuple[str, dict[str, object]]:
    """Run all routings; return (remaining text, {field: value})."""
    found: dict[str, object] = {}
    for routing in routings:
        spec = routing["extract"]
        if spec["kind"] == "parts":
            matches = run_part_extract(parts, spec)
        else:
            text, matches = run_text_extract(
                text, spec, strip=bool(routing.get("strip", False)))
        value: object = matches
        if "join" in routing:
            value = routing["join"].join(core.strip(m) for m in matches)
        coerce = routing.get("coerce")
        if coerce is not None:
            fn = coercions.get(coerce["kind"])
            if fn is None:
                refuse("unknown-coercion",
                       f"routing for {routing.get('field')!r}: coercion "
                       f"{coerce['kind']!r} is not registered")
            value = fn(value, coerce.get("options", {}))
        found[routing["field"]] = value
    return text, found


# ---------------------------------------------------------------- sections


def split_sections(text: str, spec: dict, field_names: list[str]) -> dict[str, str]:
    """Split visible text into per-field raw strings using the lens spec.

    ``spec``: ``{"kind": "sections", "open": "<{name}>", "close": ...?,
    "tail": ...?}``. Markers may appear in any order; the first occurrence
    of each wins. Capture runs to the next marker (or the tail / end).
    Missing fields refuse with code ``parse-missing-fields``, carrying the
    values that were found in ``.partial``.
    """
    open_tpl = spec["open"]
    close_tpl = spec.get("close")
    tail = spec.get("tail")

    boundaries: list[tuple[int, int, str | None]] = []  # (start, end_of_marker, name)
    positions: dict[str, int] = {}
    for name in field_names:
        marker = open_tpl.replace("{name}", name)
        count = text.count(marker)
        if count > 1:
            refuse("parse-ambiguous",
                   f"marker {marker!r} for field {name!r} appears {count} "
                   f"times in the reply — refusing to guess which one is real")
        idx = text.find(marker)
        if idx < 0:
            continue
        positions[name] = idx
        boundaries.append((idx, idx + len(marker), name))
    if tail:
        count = text.count(tail)
        if count > 1:
            refuse("parse-ambiguous",
                   f"tail {tail!r} appears {count} times in the reply — "
                   f"refusing to guess which one ends the reply")
        t_idx = text.find(tail)
        if t_idx >= 0:
            boundaries.append((t_idx, t_idx, None))
    boundaries.sort()

    raw: dict[str, str] = {}
    for i, (start, after, name) in enumerate(boundaries):
        if name is None:
            continue
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        chunk = text[after:end]
        if close_tpl:
            chunk = _cut_at_close(chunk, close_tpl.replace("{name}", name), name)
        raw[name] = core.strip(chunk)

    missing = [n for n in field_names if n not in raw]
    if missing:
        refuse("parse-missing-fields",
               "reply is missing section(s): " + ", ".join(repr(n) for n in missing),
               partial=raw)
    return raw


def _cut_at_close(chunk: str, close: str, name: str) -> str:
    """Capture up to the field's close marker. A close appearing twice in
    the capture region is refused, exactly like a repeated anchor — the
    value contains the marker and the reply cannot be read one way."""
    if not close:
        return chunk
    count = chunk.count(close)
    if count > 1:
        refuse("parse-ambiguous",
               f"close marker {close!r} for field {name!r} appears {count} "
               f"times in its section — refusing to guess where it ends")
    idx = chunk.find(close)
    return chunk if idx < 0 else chunk[:idx]


def check_collisions(spelled: list[tuple[str, str]],
                     markers: list[str]) -> None:
    """The write-side half of invertibility (kernel §4): a spelled value
    that contains any marker the lens reads would produce a demo the lens
    reads differently. Refuse, naming field and marker."""
    for name, value in spelled:
        for marker in markers:
            if marker and marker in value:
                refuse("value-collides",
                       f"field {name!r}: its spelled value contains the lens "
                       f"marker {marker!r}; the demo could not be read back "
                       f"as written")


def sections_markers(spec: dict, names: list[str]) -> list[str]:
    out = []
    for name in names:
        out.append(spec["open"].replace("{name}", name))
        if spec.get("close"):
            out.append(spec["close"].replace("{name}", name))
    if spec.get("tail"):
        out.append(spec["tail"])
    return out


def render_sections(spec: dict, spelled: list[tuple[str, str]]) -> str:
    """The lens writing forward: render gold outputs in the exact layout the
    parser reads. Used for demo assistant turns, so demos can never drift
    from the parser."""
    check_collisions(spelled, sections_markers(spec, [n for n, _ in spelled]))
    pieces: list[str] = []
    for name, value in spelled:
        open_marker = spec["open"].replace("{name}", name)
        piece = f"{open_marker}\n{value}\n"
        if spec.get("close"):
            piece += spec["close"].replace("{name}", name) + "\n"
        pieces.append(piece)
    out = "".join(pieces)
    if spec.get("tail"):
        out += spec["tail"]
    return out


# ------------------------------------------------------------------ lenses


class Lens:
    """The lens protocol: one reply document form, read and written by the
    same object. ``requires``/``patch`` are the mode hooks: a lens may
    demand declared capability facts and contribute request-side data
    (e.g. provider-enforced structured output), checked at bake.

    - ``split(text, field_names)`` reads visible output fields out of the
      reply text, returning ``{name: raw string}``. Missing fields refuse
      ``parse-missing-fields`` carrying whatever was recovered; a reply
      that does not fit the document form at all refuses
      ``lens-parse-error``.
    - ``join(spelled)`` writes gold outputs (``[(name, spelled_text)]``)
      in exactly the layout ``split`` reads — demo assistant turns can
      therefore never drift from the parser. This dual use is normative.
    - ``format(placeholders)`` writes the reply *skeleton* the prompt
      shows the model (the ``{format}`` template slot). The default is
      ``join`` over the placeholder texts, so the skeleton, the demos,
      and the parser are one object — the third face of the lens.

    Vocabulary packages subclass this and register a factory
    ``factory(parse_spec) -> Lens`` via ``Registry.register_lens``.
    """

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        raise NotImplementedError

    def join(self, spelled: list[tuple[str, str]]) -> str:
        raise NotImplementedError

    def format(self, placeholders: list[tuple[str, str]]) -> str:
        return self.join(placeholders)

    def requires(self) -> list[str]:
        """Capability facts the model must declare for this document form."""
        return []

    def patch(self, fields: list) -> dict:
        """Request-side data this document form needs (engine controls)."""
        return {}


def validate_sections_spec(spec: dict) -> None:
    if "open" not in spec or "{name}" not in str(spec["open"]):
        refuse("entry-malformed",
               "parse.open must contain the '{name}' placeholder")


class SectionsLens(Lens):
    """The kernel lens: marker-delimited sections. Kernel grammar, like the
    extract algebra — always available, never registered, never replaced.
    Marker templates are data, so XML-style (``<{name}>`` / ``</{name}>``)
    and DSPy-style (``[[ ## {name} ## ]]`` + tail) are both spellings of
    this one lens, not new lens kinds."""

    def __init__(self, spec: dict):
        validate_sections_spec(spec)
        self.spec = dict(spec)

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        return split_sections(text, self.spec, field_names)

    def join(self, spelled: list[tuple[str, str]]) -> str:
        return render_sections(self.spec, spelled)


class DerivedLens(Lens):
    """The template read backwards: anchors are the literal text around
    each ``{f.value}`` hole in the template's output-pattern block.

    ``anchors``: ordered ``[(field_name, prefix, suffix)]``, instantiated
    per visible output field at bake. Matching uses the whitespace-
    stripped forms; ``join`` reproduces the full literals, so demos show
    the exact pattern the parser reads."""

    def __init__(self, anchors: list[tuple[str, str, str]]):
        self.anchors = list(anchors)

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        wanted = [a for a in self.anchors if a[0] in field_names]
        boundaries: list[tuple[int, int, str, str]] = []
        for name, prefix, suffix in wanted:
            marker = core.rstrip(prefix)
            count = text.count(marker)
            if count > 1:
                refuse("parse-ambiguous",
                       f"anchor {marker!r} for field {name!r} appears {count} "
                       f"times in the reply — refusing to guess")
            idx = text.find(marker)
            if idx < 0:
                continue
            boundaries.append((idx, idx + len(marker), name, suffix))
        boundaries.sort()
        raw: dict[str, str] = {}
        for i, (start, after, name, suffix) in enumerate(boundaries):
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
            chunk = _cut_at_close(text[after:end], core.strip(suffix), name)
            raw[name] = core.strip(chunk)
        missing = [n for n in field_names if n not in raw]
        if missing:
            refuse("parse-missing-fields",
                   "reply is missing pattern section(s): "
                   + ", ".join(repr(n) for n in missing), partial=raw)
        return raw

    def join(self, spelled: list[tuple[str, str]]) -> str:
        by_name = dict(spelled)
        markers = []
        for name, prefix, suffix in self.anchors:
            markers.append(core.rstrip(prefix))
            markers.append(core.strip(suffix))
        check_collisions(spelled, markers)
        pieces = [prefix + by_name[name] + suffix
                  for name, prefix, suffix in self.anchors if name in by_name]
        return "".join(pieces).strip("\n")

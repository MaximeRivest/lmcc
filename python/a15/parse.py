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

from .errors import refuse

EXTRACT_KINDS = ("between", "pattern", "line_prefixed", "parts")


def validate_extract(spec: dict, *, where: str) -> None:
    kind = spec.get("kind")
    if kind not in EXTRACT_KINDS:
        refuse("unknown-extract-kind",
               f"{where}: extract kind {kind!r} is not in the kernel algebra "
               f"{EXTRACT_KINDS}")
    required = {"between": ("open", "close"), "pattern": ("regex",),
                "line_prefixed": ("prefix",), "parts": ("part",)}[kind]
    for key in required:
        if key not in spec:
            refuse("entry-malformed", f"{where}: extract {kind!r} needs {key!r}")


def run_text_extract(text: str, spec: dict, strip: bool) -> tuple[str, list[str]]:
    """Apply one extractor to text. Returns (possibly stripped text, matches)."""
    kind = spec["kind"]
    if kind == "between":
        pattern = re.compile(
            re.escape(spec["open"]) + r"(.*?)" + re.escape(spec["close"]), re.DOTALL)
    elif kind == "pattern":
        pattern = re.compile(spec["regex"], re.DOTALL)
    elif kind == "line_prefixed":
        pattern = re.compile(
            r"^" + re.escape(spec["prefix"]) + r"(.*)$", re.MULTILINE)
    else:
        refuse("unknown-extract-kind", f"extract kind {kind!r} does not read text")
    matches: list[str] = []
    for m in pattern.finditer(text):
        matches.append(m.group(1) if pattern.groups else m.group(0))
    if strip:
        text = pattern.sub("", text)
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
            value = routing["join"].join(m.strip() for m in matches)
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
        idx = text.find(marker)
        if idx < 0:
            continue
        positions[name] = idx
        boundaries.append((idx, idx + len(marker), name))
    if tail:
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
            close = close_tpl.replace("{name}", name)
            c_idx = chunk.find(close)
            if c_idx >= 0:
                chunk = chunk[:c_idx]
        raw[name] = chunk.strip()

    missing = [n for n in field_names if n not in raw]
    if missing:
        refuse("parse-missing-fields",
               "reply is missing section(s): " + ", ".join(repr(n) for n in missing),
               partial=raw)
    return raw


def render_sections(spec: dict, spelled: list[tuple[str, str]]) -> str:
    """The lens writing forward: render gold outputs in the exact layout the
    parser reads. Used for demo assistant turns, so demos can never drift
    from the parser."""
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
    same object.

    - ``split(text, field_names)`` reads visible output fields out of the
      reply text, returning ``{name: raw string}``. Missing fields refuse
      ``parse-missing-fields`` carrying whatever was recovered; a reply
      that does not fit the document form at all refuses
      ``lens-parse-error``.
    - ``join(spelled)`` writes gold outputs (``[(name, spelled_text)]``)
      in exactly the layout ``split`` reads — demo assistant turns can
      therefore never drift from the parser. This dual use is normative.

    Vocabulary packages subclass this and register a factory
    ``factory(parse_spec) -> Lens`` via ``Registry.register_lens``.
    """

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        raise NotImplementedError

    def join(self, spelled: list[tuple[str, str]]) -> str:
        raise NotImplementedError


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

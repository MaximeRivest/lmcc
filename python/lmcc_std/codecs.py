"""Standard codecs: json, table, scaled_number.

Each codec is one *spelling* of plain data. Normative behavior (including
the ugly cases: escaping, nulls, fences) lives in contract/spec/vocab/ and
is pinned by corpus cases — two implementations that disagree have a
failing test, not an argument.
"""

from __future__ import annotations

import re

from lmcc import core
from lmcc.errors import LMCCError
from lmcc.registry import Codec

from . import jsontext

VERSION = "0.1.0"

_WS = "[ \t\n\r\f\v]*"
_FENCE = re.compile(
    "^" + _WS + "```[a-zA-Z0-9_-]*" + _WS + r"\n(.*?)\n?" + _WS + "```" + _WS + "$",
    re.DOTALL)


class JsonCodec(Codec):
    """Values spelled as JSON. Options: ``indent`` (default 2)."""

    def __init__(self, options: dict):
        self.indent = options.get("indent", 2)

    def render_schema(self, shape: dict) -> str:
        return "JSON matching this schema: " + jsontext.dumps(shape, indent=None)

    def render_value(self, value, shape: dict) -> str:
        return jsontext.dumps(value, indent=self.indent)

    def parse_value(self, text: str, shape: dict):
        m = _FENCE.match(text)
        if m:
            text = m.group(1)
        return jsontext.loads(text)


class TableCodec(Codec):
    """A list of flat objects spelled as a delimiter table.

    Options: ``columns`` (required), ``delimiter`` ("|"), ``escape``
    ("\\\\"), ``null`` (""). A delimiter inside a cell is escaped; a cell
    equal to ``null`` reads back as None. A row whose cells equal the
    column names is a header and is skipped on parse.
    """

    def __init__(self, options: dict):
        if "columns" not in options:
            raise ValueError("table codec requires the 'columns' option")
        self.columns: list[str] = list(options["columns"])
        self.delimiter: str = options.get("delimiter", "|")
        self.escape: str = options.get("escape", "\\")
        self.null: str = options.get("null", "")

    def render_schema(self, shape: dict) -> str:
        d = self.delimiter
        return (f"{d} " + f" {d} ".join(self.columns) + f" {d}"
                + "  (one row per item)")

    def render_value(self, value, shape: dict) -> str:
        rows = []
        for item in value:
            cells = []
            for col in self.columns:
                cell = item.get(col)
                cell = self.null if cell is None else self._spell(cell, col)
                cell = cell.replace(self.escape, self.escape * 2)
                cell = cell.replace(self.delimiter, self.escape + self.delimiter)
                cells.append(cell)
            d = self.delimiter
            rows.append(f"{d} " + f" {d} ".join(cells) + f" {d}")
        return "\n".join(rows)

    @staticmethod
    def _spell(cell, col: str) -> str:
        if isinstance(cell, str):
            return cell
        if isinstance(cell, bool):
            return "true" if cell else "false"
        if isinstance(cell, int):
            return str(cell)
        if isinstance(cell, float):
            return core.format_number(cell)
        raise ValueError(f"column {col!r}: {type(cell).__name__} is not a cell value")

    def parse_value(self, text: str, shape: dict):
        item_props = (shape.get("items") or {}).get("properties", {})
        out = []
        for line in text.split("\n"):
            line = core.strip(line)
            if not line.startswith(self.delimiter):
                continue
            cells = self._split(line)
            if [core.strip(c) for c in cells] == self.columns:
                continue  # header row
            if len(cells) != len(self.columns):
                raise ValueError(
                    f"row has {len(cells)} cells, expected {len(self.columns)} "
                    f"({self.columns}): {line!r}")
            item = {}
            for col, cell in zip(self.columns, cells):
                cell = core.strip(cell)
                if cell == self.null:
                    item[col] = None
                    continue
                item[col] = _read(item_props.get(col, {}), cell, f"column {col!r}")
            out.append(item)
        return out

    def _split(self, line: str) -> list[str]:
        inner = line[len(self.delimiter):]
        if inner.endswith(self.delimiter):
            inner = inner[: -len(self.delimiter)]
        cells, cur, i = [], [], 0
        while i < len(inner):
            ch = inner[i]
            if ch == self.escape and i + 1 < len(inner):
                cur.append(inner[i + 1])
                i += 2
                continue
            if inner.startswith(self.delimiter, i):
                cells.append("".join(cur))
                cur = []
                i += len(self.delimiter)
                continue
            cur.append(ch)
            i += 1
        cells.append("".join(cur))
        return cells

class ScaledNumberCodec(Codec):
    """Numbers spelled at a friendlier scale, e.g. 0.78 ⇄ "78%".

    Options: ``scale`` (1), ``suffix`` (""), ``round`` (None).
    """

    def __init__(self, options: dict):
        self.scale = options.get("scale", 1)
        self.suffix = options.get("suffix", "")
        self.round = options.get("round")

    def render_schema(self, shape: dict) -> str:
        example = f"{83 if self.scale == 100 else 0.83}{self.suffix}"
        return f"a number like {example}"

    def render_value(self, value, shape: dict) -> str:
        scaled = float(value) * self.scale
        if self.round is not None:
            # kernel §7a rounding: half-to-even on the binary64 value
            p = 10.0 ** self.round
            scaled = round(scaled * p) / p
        return f"{core.format_number(scaled)}{self.suffix}"

    def parse_value(self, text: str, shape: dict):
        text = core.strip(text)
        if self.suffix and text.endswith(self.suffix):
            text = text[: -len(self.suffix)]
        return _read({"type": "number"}, text, "scaled_number") / self.scale


def _read(shape: dict, text: str, where: str):
    """Kernel scalar rules, surfaced as a codec error (the spec's word)."""
    try:
        return core.read_value(shape, text, where=where)
    except LMCCError as err:
        raise ValueError(err.detail) from None


def install(registry, *, exist_ok: bool = True) -> None:
    registry.register_codec("json", JsonCodec, version=VERSION, exist_ok=exist_ok)
    registry.register_codec("table", TableCodec, version=VERSION, exist_ok=exist_ok)
    registry.register_codec("scaled_number", ScaledNumberCodec, version=VERSION,
                            exist_ok=exist_ok)

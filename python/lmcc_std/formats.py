"""Standard formats: json, table, scaled_number.

Each format is one *spelling* of a value: ``write(value, field) → text``,
``read(span, field) → value``, ``describe(field) → text``. Normative
behavior (escaping, nulls, fences) lives in contract/spec/vocab/ and is
pinned by corpus cases — two implementations that disagree have a failing
test, not an argument.

The Python ``json`` format also carries native values across: dataclasses,
pydantic models and Enums are lowered on write and lifted back on read
through the field's annotation — the language-home convenience the
contract allows (kernel §5, resolution step 3 is per runtime).
"""

from __future__ import annotations

import dataclasses
import enum
import re
import typing

from lmcc import core
from lmcc.errors import Refusal
from lmcc.formats import Format

from . import jsontext

VERSION = "0.1.0"

_WS = "[ \t\n\r\f\v]*"
_FENCE = re.compile(
    "^" + _WS + "```[a-zA-Z0-9_-]*" + _WS + r"\n(.*?)\n?" + _WS + "```" + _WS + "$",
    re.DOTALL)


class JsonFormat(Format):
    """Values spelled as JSON. Options: ``indent`` (default 2)."""

    accepts = ("*",)

    def __init__(self, options: dict):
        self.indent = options.get("indent", 2)

    def describe(self, field):
        return "JSON matching this schema: " + jsontext.dumps(field.shape, indent=None)

    def write(self, value, field):
        return jsontext.dumps(lower(value), indent=self.indent)

    def read(self, span, field):
        text = span.text
        m = _FENCE.match(text)
        if m:
            text = m.group(1)
        return lift(field.annotation, jsontext.loads(text))


# ---------------------------------------------------- native values (python)


def lower(value):
    """Native → plain data: dataclasses, pydantic models, Enums, and
    containers of them. Plain data passes through."""
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: lower(getattr(value, f.name)) for f in dataclasses.fields(value)}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if isinstance(value, dict):
        return {k: lower(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [lower(v) for v in value]
    return value


def lift(annotation, data):
    """Plain data → native, guided by the annotation; unknown annotations
    return the data unchanged."""
    if annotation is None:
        return data
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Union or (origin is not None and getattr(origin, "__name__", "") == "UnionType"):
        if data is None:
            return None
        real = [a for a in args if a is not type(None)]
        return lift(real[0], data) if len(real) == 1 else data
    if origin in (list, typing.List) and isinstance(data, list) and args:
        return [lift(args[0], v) for v in data]
    if origin in (dict, typing.Dict) and isinstance(data, dict) and len(args) == 2:
        return {k: lift(args[1], v) for k, v in data.items()}
    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            return annotation(data)
        if dataclasses.is_dataclass(annotation) and isinstance(data, dict):
            hints = typing.get_type_hints(annotation)
            return annotation(**{f.name: lift(hints.get(f.name), data[f.name])
                                 for f in dataclasses.fields(annotation) if f.name in data})
        validate = getattr(annotation, "model_validate", None)
        if callable(validate) and isinstance(data, (dict, str)):
            return validate(data)
    return data


class TableFormat(Format):
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

    accepts = ("list[object]", "list[*]")

    def describe(self, field):
        d = self.delimiter
        return (f"{d} " + f" {d} ".join(self.columns) + f" {d}"
                + "  (one row per item)")

    def write(self, value, field):
        rows = []
        for item in lower(value):
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

    def read(self, span, field):
        item_props = (field.shape.get("items") or {}).get("properties", {})
        out = []
        for line in span.text.split("\n"):
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
        return lift(field.annotation, out)

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

class ScaledNumberFormat(Format):
    """Numbers spelled at a friendlier scale, e.g. 0.78 ⇄ "78%".

    Options: ``scale`` (1), ``suffix`` (""), ``round`` (None).
    """

    accepts = ("number", "integer")

    def __init__(self, options: dict):
        self.scale = options.get("scale", 1)
        self.suffix = options.get("suffix", "")
        self.round = options.get("round")

    def describe(self, field):
        example = f"{83 if self.scale == 100 else 0.83}{self.suffix}"
        return f"a number like {example}"

    def write(self, value, field):
        scaled = float(value) * self.scale
        if self.round is not None:
            # kernel §7a rounding: half-to-even on the binary64 value
            p = 10.0 ** self.round
            scaled = round(scaled * p) / p
        return f"{core.format_number(scaled)}{self.suffix}"

    def read(self, span, field):
        text = core.strip(span.text)
        if self.suffix and text.endswith(self.suffix):
            text = text[: -len(self.suffix)]
        return _read({"type": "number"}, text, "scaled_number") / self.scale


def _read(shape: dict, text: str, where: str):
    """Kernel scalar rules, surfaced as a codec error (the spec's word)."""
    try:
        return core.read_value(shape, text, where=where)
    except Refusal as err:
        raise ValueError(err.hint) from None


def install(registry, *, exist_ok: bool = True) -> None:
    registry.register_format("json", JsonFormat, version=VERSION, exist_ok=exist_ok)
    registry.register_format("table", TableFormat, version=VERSION, exist_ok=exist_ok)
    registry.register_format("scaled_number", ScaledNumberFormat, version=VERSION,
                             exist_ok=exist_ok)

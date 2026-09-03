"""JSON text, spelled the way the vocabulary specs legislate.

The standard library's ``json`` module spells floats as Python does
(``1.0``, ``1e+20``) and accepts non-JSON (``NaN``, duplicate members).
The specs (``codec-json.md``, ``lens-json_object.md``) pin one portable
spelling — numbers per kernel §7a, two layouts — and strict reading. This
module is that spelling; both the codec and the lens go through it so
they cannot disagree.
"""

from __future__ import annotations

import json

from lmcc import core


# ------------------------------------------------------------------ write


def dumps(value: object, *, indent: int | None = 2) -> str:
    """Indented layout when ``indent`` is an int (ECMAScript
    ``JSON.stringify(v, null, n)``), single-line layout with ``, `` / ``: ``
    when None."""
    out: list[str] = []
    _write(value, out, indent, 0)
    return "".join(out)


def _write(value: object, out: list[str], indent: int | None, depth: int) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(core.format_number(value))
    elif isinstance(value, str):
        out.append(quote(value))
    elif isinstance(value, dict):
        if not value:
            out.append("{}")
            return
        out.append("{")
        _members(list(value.items()), out, indent, depth, keyed=True)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        if not value:
            out.append("[]")
            return
        out.append("[")
        _members([(None, v) for v in value], out, indent, depth, keyed=False)
        out.append("]")
    else:
        raise TypeError(f"{type(value).__name__} is not JSON data")


def _members(items, out, indent, depth, *, keyed: bool) -> None:
    if indent is None:
        sep, key_sep, pad, end = ", ", ": ", "", ""
    else:
        pad = "\n" + " " * (indent * (depth + 1))
        sep, key_sep, end = "," + pad, ": ", "\n" + " " * (indent * depth)
    for i, (k, v) in enumerate(items):
        out.append(pad if i == 0 else sep)
        if keyed:
            if not isinstance(k, str):
                raise TypeError("object keys must be strings")
            out.append(quote(k) + key_sep)
        _write(v, out, indent, depth + 1)
    out.append(end)


_SHORT = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f",
          '"': '\\"', "\\": "\\\\"}


def quote(text: str) -> str:
    out = ['"']
    for ch in text:
        if ch in _SHORT:
            out.append(_SHORT[ch])
        elif ch < " ":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


# ------------------------------------------------------------------- read


def _reject_constant(name: str):
    raise ValueError(f"{name} is not JSON")


def _reject_duplicates(pairs):
    obj: dict = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError(f"duplicate member {k!r}")
        obj[k] = v
    return obj


_DECODER = json.JSONDecoder(parse_constant=_reject_constant,
                            object_pairs_hook=_reject_duplicates)


def loads(text: str) -> object:
    """Strict RFC 8259: no NaN/Infinity, no duplicate members."""
    return _DECODER.decode(text)


def members(text: str) -> list[tuple[str, object, str]]:
    """Read one JSON object and return ``[(key, value, source_text)]`` for
    its top-level members, in document order, with duplicates kept — the
    lens decides what a duplicate means. ``source_text`` is the member's
    value exactly as written. Raises ValueError when the text is not a
    JSON object."""
    s = text
    i = _ws(s, 0)
    if i >= len(s) or s[i] != "{":
        raise ValueError("not a JSON object")
    i = _ws(s, i + 1)
    out: list[tuple[str, object, str]] = []
    if i < len(s) and s[i] == "}":
        _end(s, i + 1)
        return out
    while True:
        if i >= len(s) or s[i] != '"':
            raise ValueError(f"expected a member name at {i}")
        key, i = _DECODER.raw_decode(s, i)
        i = _ws(s, i)
        if i >= len(s) or s[i] != ":":
            raise ValueError(f"expected ':' at {i}")
        i = _ws(s, i + 1)
        value, j = _DECODER.raw_decode(s, i)
        out.append((key, value, s[i:j]))
        i = _ws(s, j)
        if i < len(s) and s[i] == ",":
            i = _ws(s, i + 1)
            continue
        if i < len(s) and s[i] == "}":
            _end(s, i + 1)
            return out
        raise ValueError(f"expected ',' or '}}' at {i}")


def _ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    return i


def _end(s: str, i: int) -> None:
    if _ws(s, i) != len(s):
        raise ValueError("trailing data after the JSON object")

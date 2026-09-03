"""The neutral core: signatures, shapes, values, messages.

This module owns the plain-data types every other part of the kernel speaks:

- ``SignatureCore``: the frontend-neutral typed contract (instructions + fields).
- Shapes: JSON-Schema dicts. The kernel maps Python's *own* constructs
  (str, int, float, bool, list[...], Literal[...]) mechanically; anything
  else must come through the host socket (registry) or is refused by name.
- Scalar spelling: the kernel spells scalars as JSON literals and passes
  strings through verbatim. Anything structured (object/array) requires a
  codec — that line is the contract's "mechanics vs vocabulary" boundary.
- Messages: plain dicts, structurally lm15-shaped
  ``{"role": ..., "content": [{"kind": "text", "text": ...}, ...]}``.

Imports nothing outside the standard library. That is a rule, not an accident.
"""

from __future__ import annotations

import dataclasses
import decimal
import enum
import math
import re
import typing
from dataclasses import dataclass, field as dc_field

from .errors import refuse

DIRECTIONS = ("input", "output")

# ------------------------------------------------- text rules (kernel §7a)
#
# Portable by construction: every strip/grammar below is defined on ASCII
# so that Go, JS, Rust and Python agree byte for byte. Never use str.strip()
# or int()/float() directly on model text anywhere in the kernel or std.

WHITESPACE = " \t\n\r\f\v"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ROLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_INTEGER = re.compile(r"^-?[0-9]+$")
_NUMBER = re.compile(r"^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$")


def strip(text: str) -> str:
    """Trim the six ASCII whitespace characters, nothing else."""
    return text.strip(WHITESPACE)


def rstrip(text: str) -> str:
    return text.rstrip(WHITESPACE)


def is_identifier(name: object) -> bool:
    return isinstance(name, str) and _IDENTIFIER.match(name) is not None


def format_number(value: float) -> str:
    """ECMAScript Number::toString over the shortest round-trip digits.

    ``3.0`` → ``3``, ``1e21`` → ``1e+21``, ``1e-7`` → ``1e-7``, ``-0.0`` → ``0``.
    Refuses non-finite values: they have no portable text.
    """
    value = float(value)
    if not math.isfinite(value):
        refuse("value-invalid", f"{value!r} has no portable number spelling")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    digits_t, exponent = decimal.Decimal(repr(abs(value))).as_tuple()[1:]
    digits = "".join(map(str, digits_t)).lstrip("0") or "0"
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)
    digits = stripped
    k = len(digits)
    n = k + exponent            # value = 0.d1..dk × 10^n
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mant = digits if k == 1 else digits[0] + "." + digits[1:]
        body = f"{mant}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + body


def read_integer(text: str, *, where: str) -> int:
    t = strip(text)
    if not _INTEGER.match(t):
        refuse("parse-value", f"{where}: {t!r} is not an integer")
    return int(t)


def read_number(text: str, *, where: str) -> float:
    t = strip(text)
    if not _NUMBER.match(t):
        refuse("parse-value", f"{where}: {t!r} is not a number")
    return float(t)


def read_boolean(text: str, *, where: str) -> bool:
    t = strip(text)
    low = "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in t)
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    refuse("parse-value", f"{where}: {t!r} is not a boolean")

_SCALAR_SHAPES: dict[type, dict] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
}


# ---------------------------------------------------------------- signature


@dataclass
class FieldSpec:
    """User-facing marker built by :func:`field` before lowering."""

    annotation: object
    role: str = "plain"
    desc: str | None = None


def field(annotation: object, *, role: str = "plain", desc: str | None = None) -> FieldSpec:
    """Annotate a signature entry with a role and/or description.

    Example:
        >>> lmcc.signature("...", outputs={"reasoning": lmcc.field(str, role="reasoning")})
    """
    return FieldSpec(annotation, role=role, desc=desc)


@dataclass
class Field:
    """One lowered signature field. ``shape`` is always a JSON-Schema dict;
    ``type`` is the type's name as the frontend spells it (formats resolve
    by it first); ``annotation`` is the host type, never serialized."""

    name: str
    direction: str
    shape: dict
    type: str | None = None
    role: str = "plain"
    desc: str | None = None
    annotation: object | None = None


@dataclass
class SignatureCore:
    """The neutral input every frontend lowers to."""

    instructions: str
    fields: list[Field] = dc_field(default_factory=list)

    @property
    def inputs(self) -> list[Field]:
        return [f for f in self.fields if f.direction == "input"]

    @property
    def outputs(self) -> list[Field]:
        return [f for f in self.fields if f.direction == "output"]

    def field_named(self, name: str) -> Field | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


def signature(
    instructions: str,
    *,
    inputs: dict[str, object] | None = None,
    outputs: dict[str, object] | None = None,
    registry=None,
) -> SignatureCore:
    """Build a SignatureCore from Python annotations (or raw shape dicts).

    Each value in ``inputs``/``outputs`` may be a Python annotation
    (``str``, ``list[int]``, ``Literal["a", "b"]``), a raw JSON-Schema
    dict, or an :func:`field` spec carrying a role/description.
    Unknown types resolve through the registry's host socket, or refuse
    naming the field and the type.
    """
    fields: list[Field] = []
    for direction, entries in (("input", inputs or {}), ("output", outputs or {})):
        for name, spec in entries.items():
            role, desc, ann = "plain", None, spec
            if isinstance(spec, FieldSpec):
                role, desc, ann = spec.role, spec.desc, spec.annotation
            shape = annotation_to_shape(ann, registry, field_name=name)
            fields.append(Field(name, direction, shape, type=typename(ann),
                                role=role, desc=desc,
                                annotation=None if isinstance(ann, dict) else ann))
    return _validated(SignatureCore(instructions, fields))


def typename(ann: object) -> str | None:
    """The type's name as this frontend spells it: ``str``, ``Person``,
    ``list[Person]``, ``Optional[int]``. Raw shape dicts have no name."""
    if isinstance(ann, dict) or ann is None:
        return None
    if isinstance(ann, type):
        return ann.__name__
    origin, args = typing.get_origin(ann), typing.get_args(ann)
    if origin is typing.Literal:
        return "Literal[" + ", ".join(repr(a) for a in args) + "]"
    if origin is typing.Union or (origin is not None and origin.__name__ == "UnionType"):
        names = [typename(a) for a in args if a is not type(None)]
        if len(args) == len(names) + 1:
            return "Optional[" + " | ".join(names) + "]" if len(names) == 1 else " | ".join(names + ["None"])
        return " | ".join(names)
    if origin is not None:
        return f"{typename(origin)}[{', '.join(typename(a) or '?' for a in args)}]"
    return getattr(ann, "__name__", None) or str(ann)


def signature_from_dict(data: dict) -> SignatureCore:
    """Load a signature from its plain-data form (the corpus form)."""
    if not isinstance(data, dict) or not isinstance(data.get("fields", []), list):
        refuse("signature-malformed", "a signature is an object with a fields list")
    fields = []
    for f in data.get("fields", []):
        if not isinstance(f, dict):
            refuse("signature-malformed", "each field is an object")
        fields.append(Field(f.get("name"), f.get("direction"), f.get("shape"),
                            type=f.get("type"), role=f.get("role", "plain"),
                            desc=f.get("desc")))
    return _validated(SignatureCore(data.get("instructions", ""), fields))


def _validated(sig: SignatureCore) -> SignatureCore:
    """The rules of schema/signature.schema.json plus name uniqueness."""
    seen: set[str] = set()
    for f in sig.fields:
        if not is_identifier(f.name):
            refuse("signature-malformed",
                   f"field name {f.name!r} is not an ASCII identifier "
                   f"([A-Za-z_][A-Za-z0-9_]*)")
        if f.name in seen:
            refuse("signature-malformed", f"field {f.name!r} is declared twice")
        seen.add(f.name)
        if f.direction not in DIRECTIONS:
            refuse("signature-malformed",
                   f"field {f.name!r}: direction {f.direction!r} is not input/output")
        if not isinstance(f.shape, dict):
            refuse("signature-malformed", f"field {f.name!r}: shape must be an object")
        if not isinstance(f.role, str) or not _ROLE.match(f.role):
            refuse("signature-malformed",
                   f"field {f.name!r}: role {f.role!r} is not a (dotted) identifier")
        if f.type is not None and not isinstance(f.type, str):
            refuse("signature-malformed", f"field {f.name!r}: type must be a string")
        if f.desc is not None and not isinstance(f.desc, str):
            refuse("signature-malformed", f"field {f.name!r}: desc must be a string")
    return sig


def signature_to_dict(sig: SignatureCore) -> dict:
    return {
        "instructions": sig.instructions,
        "fields": [
            {"name": f.name, "direction": f.direction, "shape": f.shape,
             **({"type": f.type} if f.type else {}),
             **({"role": f.role} if f.role != "plain" else {}),
             **({"desc": f.desc} if f.desc is not None else {})}
            for f in sig.fields
        ],
    }


# ------------------------------------------------------------------ shapes


def annotation_to_shape(ann: object, registry=None, *, field_name: str = "?") -> dict:
    """Map a Python annotation to a JSON-Schema shape, mechanically.

    Only the language's own constructs are mapped here. Foreign types
    (Pillow, DataFrame, ...) resolve through the host socket; if nothing
    claims them, refuse by name (code ``unmapped-type``).
    """
    if isinstance(ann, dict):
        return dict(ann)
    if ann in _SCALAR_SHAPES:
        return dict(_SCALAR_SHAPES[ann])
    origin = typing.get_origin(ann)
    if origin is typing.Literal:
        values = list(typing.get_args(ann))
        shape: dict = {"enum": values}
        types = {type(v) for v in values}
        if types == {str}:
            shape["type"] = "string"
        elif types == {int}:
            shape["type"] = "integer"
        return shape
    if origin in (list, typing.List):
        args = typing.get_args(ann)
        items = annotation_to_shape(args[0], registry, field_name=field_name) if args else {}
        return {"type": "array", "items": items}
    if origin in (dict, typing.Dict) or ann is dict:
        return {"type": "object"}
    if ann is list:
        return {"type": "array"}
    if origin is typing.Union or (origin is not None and getattr(origin, "__name__", "") == "UnionType"):
        args = typing.get_args(ann)
        return {"anyOf": [annotation_to_shape(a, registry, field_name=field_name)
                          if a is not type(None) else {"type": "null"} for a in args]}
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        values = [m.value for m in ann]
        shape = {"enum": values}
        if all(isinstance(v, str) for v in values):
            shape["type"] = "string"
        elif all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            shape["type"] = "integer"
        else:
            refuse("unmapped-type", f"field {field_name!r}: enum {ann.__name__} mixes member kinds")
        return shape
    if isinstance(ann, type) and dataclasses.is_dataclass(ann):
        # the language's own construct: lowered mechanically, still structured
        hints = typing.get_type_hints(ann)
        props = {f.name: annotation_to_shape(hints[f.name], registry, field_name=f"{field_name}.{f.name}")
                 for f in dataclasses.fields(ann)}
        return {"type": "object", "properties": props, "required": [f.name for f in dataclasses.fields(ann)]}
    refuse("unmapped-type",
           f"field {field_name!r}: cannot map annotation {ann!r} to a shape; "
           f"pass a JSON-Schema dict, or lower it in your frontend")


_SCALAR_TYPES = ("string", "integer", "number", "boolean")


def nullable_base(shape: dict) -> tuple[dict, bool]:
    """Kernel §1: a nullable form of a scalar/enum shape is that shape plus
    null. Returns ``(base_shape, is_nullable)``; non-nullable shapes come
    back unchanged. Only the two spellings the spec names are recognized:
    ``{"type": [T, "null"]}`` and ``{"anyOf": [S, {"type": "null"}]}``."""
    t = shape.get("type")
    if isinstance(t, list):
        others = [x for x in t if x != "null"]
        if "null" in t and len(others) == 1 and len(t) == 2:
            base = {k: v for k, v in shape.items() if k != "type"}
            base["type"] = others[0]
            return base, True
        return shape, False
    alts = shape.get("anyOf")
    if isinstance(alts, list) and len(alts) == 2 and len(shape) == 1:
        nulls = [a for a in alts if isinstance(a, dict) and a == {"type": "null"}]
        others = [a for a in alts if a not in nulls]
        if len(nulls) == 1 and len(others) == 1 and isinstance(others[0], dict):
            base = others[0]
            if "enum" in base or base.get("type") in _SCALAR_TYPES:
                return base, True
    return shape, False


def shape_summary(shape: dict) -> str:
    """A short human hint for a field's shape, used by ``{f.schema}`` when
    no codec is bound. Codecs override this with their own schema prose."""
    shape, _ = nullable_base(shape)
    if "enum" in shape:
        return "one of: " + ", ".join(str(v) for v in shape["enum"])
    if "media" in shape:
        return f"({shape['media']})"
    t = shape.get("type")
    if t in ("integer", "number", "boolean"):
        return f"({t})"
    return ""


def is_media(shape: dict) -> bool:
    return "media" in shape


def is_structured(shape: dict) -> bool:
    """Structured shapes require a codec; the kernel refuses to guess.
    Kernel §1: object/array, and every *uninterpreted* shape (no media, no
    enum, no scalar type) — the set the kernel spells itself is closed."""
    base, _ = nullable_base(shape)
    if is_media(base) or "enum" in base:
        return False
    return base.get("type") not in _SCALAR_TYPES


# ---------------------------------------------------- scalar spell / parse


def spell_value(shape: dict, value: object, *, where: str) -> str:
    """Kernel mechanics (§7a): strings verbatim, integers in decimal,
    numbers by the ECMAScript spelling, booleans as ``true``/``false``,
    enums by member spelling, ``null`` for nullable shapes. Refuses
    anything structured (``no-codec``)."""
    shape, nullable = nullable_base(shape)
    if value is None:
        if nullable:
            return "null"
        refuse("value-invalid", f"{where}: null is not allowed by the shape")
    if "enum" in shape:
        if isinstance(value, bool) or value not in shape["enum"]:
            refuse("value-invalid",
                   f"{where}: value {value!r} is not one of {shape['enum']}")
        return str(value)
    t = shape.get("type")
    if t == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return format_number(value)
        refuse("value-invalid", f"{where}: {value!r} is not text")
    if t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            refuse("value-invalid", f"{where}: {value!r} is not an integer")
        return str(value)
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            refuse("value-invalid", f"{where}: {value!r} is not a number")
        return format_number(value)
    if t == "boolean":
        if not isinstance(value, bool):
            refuse("value-invalid", f"{where}: {value!r} is not a boolean")
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    refuse("no-format",
           f"{where}: value of type {type(value).__name__} has no codec "
           f"bound and is not a scalar — bind a codec for this field")


def read_value(shape: dict, text: str, *, where: str) -> object:
    """Kernel mechanics (§7a), reading direction. Vocabulary reuses this
    (the table codec reads cells with it) so one grammar rules everywhere."""
    shape, nullable = nullable_base(shape)
    if nullable and strip(text) == "null":
        return None
    if "enum" in shape:
        stripped = strip(text)
        for v in shape["enum"]:
            if str(v) == stripped:
                return v
        refuse("parse-value", f"{where}: {stripped!r} is not one of {shape['enum']}")
    t = shape.get("type")
    if t == "integer":
        return read_integer(text, where=where)
    if t == "number":
        return read_number(text, where=where)
    if t == "boolean":
        return read_boolean(text, where=where)
    return text


def spell_scalar(f: Field, value: object) -> str:
    return spell_value(f.shape, value, where=f"field {f.name!r}")


def parse_scalar(f: Field, text: str) -> object:
    return read_value(f.shape, text, where=f"field {f.name!r}")


# ------------------------------------------------------------ parts, spans


class Span:
    """What a routing or the lens captured for one field: a list of parts.
    ``text`` is the text parts, each stripped, joined by newlines (kernel
    §6); ``of(kind)`` selects parts by kind."""

    def __init__(self, parts: list[dict]):
        self.parts = list(parts)

    @classmethod
    def of_text(cls, text: str) -> "Span":
        return cls([text_part(text)])

    @property
    def text(self) -> str:
        """Every part that carries text (text, thinking, ...), stripped,
        joined by newlines (kernel §6)."""
        return "\n".join(strip(p["text"]) for p in self.parts
                         if isinstance(p.get("text"), str))

    def of(self, kind: str) -> list[dict]:
        return [p for p in self.parts if p.get("kind") == kind]

    @property
    def kinds(self) -> set[str]:
        return {p.get("kind") for p in self.parts}

    def __repr__(self) -> str:
        return f"Span({self.parts!r})"


def as_parts(written: object, *, where: str) -> list[dict]:
    """A format's ``write`` returns text (one text part) or a part list."""
    if isinstance(written, str):
        return [text_part(written)]
    if isinstance(written, list) and all(isinstance(p, dict) and "kind" in p for p in written):
        return list(written)
    refuse("format-write-error",
           f"{where}: write must return text or a list of parts, got {type(written).__name__}")


# ---------------------------------------------------------------- messages


def text_part(text: str) -> dict:
    return {"kind": "text", "text": text}


def make_message(role: str, parts: list[dict]) -> dict:
    return {"role": role, "content": parts}


def merge_text_parts(parts: list[dict]) -> list[dict]:
    """Adjacent text parts merge; empty text parts vanish."""
    out: list[dict] = []
    for p in parts:
        if p.get("kind") == "text":
            if not p.get("text"):
                continue
            if out and out[-1].get("kind") == "text":
                out[-1] = text_part(out[-1]["text"] + p["text"])
                continue
        out.append(p)
    return out


def response_text_and_parts(response: object) -> tuple[str, list[dict]]:
    """Accept a bare string or an lm15-shaped response dict."""
    if isinstance(response, str):
        return response, []
    if isinstance(response, dict) and isinstance(response.get("content"), list):
        parts = response["content"]
        text = "".join(p.get("text", "") for p in parts if p.get("kind") == "text")
        return text, parts
    refuse("response-malformed",
           "response must be a string or a dict with a 'content' part list")

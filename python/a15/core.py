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

import json
import typing
from dataclasses import dataclass, field as dc_field

from .errors import refuse

DIRECTIONS = ("input", "output")

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
        >>> a15.signature("...", outputs={"reasoning": a15.field(str, role="reasoning")})
    """
    return FieldSpec(annotation, role=role, desc=desc)


@dataclass
class Field:
    """One lowered signature field. ``shape`` is always a JSON-Schema dict."""

    name: str
    direction: str
    shape: dict
    role: str = "plain"
    desc: str | None = None
    annotation: object | None = None  # kept for host lifting; never serialized


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
            fields.append(Field(name, direction, shape, role=role, desc=desc,
                                annotation=None if isinstance(ann, dict) else ann))
    return SignatureCore(instructions, fields)


def signature_from_dict(data: dict) -> SignatureCore:
    """Load a signature from its plain-data form (the corpus form)."""
    fields = [
        Field(f["name"], f["direction"], f["shape"],
              role=f.get("role", "plain"), desc=f.get("desc"))
        for f in data.get("fields", [])
    ]
    return SignatureCore(data.get("instructions", ""), fields)


def signature_to_dict(sig: SignatureCore) -> dict:
    return {
        "instructions": sig.instructions,
        "fields": [
            {"name": f.name, "direction": f.direction, "shape": f.shape,
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
    if registry is not None:
        host = registry.host_for(ann)
        if host is not None:
            return dict(host.shape)
    refuse("unmapped-type",
           f"field {field_name!r}: cannot map annotation {ann!r} to a shape; "
           f"register a host type for it or pass a JSON-Schema dict")


def shape_summary(shape: dict) -> str:
    """A short human hint for a field's shape, used by ``{f.schema}`` when
    no codec is bound. Codecs override this with their own schema prose."""
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
    """Structured shapes require a codec; the kernel refuses to guess."""
    return shape.get("type") in ("object", "array")


# ---------------------------------------------------- scalar spell / parse


def spell_scalar(f: Field, value: object) -> str:
    """Kernel mechanics: strings verbatim, scalars as JSON literals."""
    shape = f.shape
    if "enum" in shape:
        if value not in shape["enum"]:
            refuse("value-invalid",
                   f"field {f.name!r}: value {value!r} is not one of {shape['enum']}")
        return str(value)
    t = shape.get("type")
    if t == "string":
        return value if isinstance(value, str) else str(value)
    if t in ("integer", "number", "boolean"):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    refuse("no-codec",
           f"field {f.name!r}: value of type {type(value).__name__} has no codec "
           f"bound and is not a scalar — bind a codec for this field")


def parse_scalar(f: Field, text: str) -> object:
    shape = f.shape
    if "enum" in shape:
        stripped = text.strip()
        for v in shape["enum"]:
            if str(v) == stripped:
                return v
        refuse("value-invalid",
               f"field {f.name!r}: {stripped!r} is not one of {shape['enum']}")
    t = shape.get("type")
    if t == "integer":
        try:
            return int(text.strip())
        except ValueError:
            refuse("value-invalid", f"field {f.name!r}: {text.strip()!r} is not an integer")
    if t == "number":
        try:
            return float(text.strip())
        except ValueError:
            refuse("value-invalid", f"field {f.name!r}: {text.strip()!r} is not a number")
    if t == "boolean":
        low = text.strip().lower()
        if low in ("true", "yes"):
            return True
        if low in ("false", "no"):
            return False
        refuse("value-invalid", f"field {f.name!r}: {text.strip()!r} is not a boolean")
    return text


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

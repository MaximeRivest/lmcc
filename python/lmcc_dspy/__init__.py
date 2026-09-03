"""lmcc_dspy — the DSPy signature frontend.

Lowers any ``dspy.Signature`` to an LMCC ``SignatureCore`` (kernel §1)
and ships one LMCC-idiomatic entry shaped like DSPy's chat dialect.
The claim this package makes, and ``tests/dspy/test_catalog.py`` checks
against a real DSPy, is:

1. **Total lowering.** Every DSPy signature lowers. Nothing is dropped
   except what DSPy itself declares a no-op: ``prefix``, ``format``,
   ``parser`` (deprecated upstream, "has no effect"), the internal
   type-undefined marker, and field *defaults* (program-side values a
   caller supplies; never shown to a model). Anything else the frontend
   cannot carry refuses ``unmapped-type`` naming the field.
2. **Always renderable.** Every lowered signature bakes, renders and
   parses with :func:`adapter` — structured and uninterpreted shapes go
   through ``@structured: json`` (D-20), ``Optional[X]`` is nullable
   (D-21), ``dspy.History`` becomes history field turns (D-22).

What is *not* claimed: DSPy's prompt bytes (LMCC renders its own way),
lenient parsing (``json_repair``; LMCC refuses instead), and native
tool/citation channels (plan 04) — those roles lower and render as
plain visible fields until a strategy is bound.

Kernel stays stdlib-only; this package imports ``dspy`` and ``pydantic``.
"""

from __future__ import annotations

import enum
import typing

import pydantic

import lmcc
from lmcc import core
from lmcc.errors import refuse

VERSION = "0.1.0"

# DSPy field-level extras that carry no prompt meaning (see module doc).
_DROPPED = ("prefix", "format", "parser", "__dspy_field_type",
            "__dspy_is_type_undefined", "constraints")


class Lowered:
    """The result of :func:`lower`: the signature, plus what the frontend
    needed to move out of it — the name of a ``dspy.History`` input, if
    any, which renders as history turns rather than as a field."""

    def __init__(self, signature: core.SignatureCore, history_field: str | None):
        self.signature = signature
        self.history_field = history_field

    def split_inputs(self, values: dict) -> tuple[dict, list[dict]]:
        """Separate a DSPy-style inputs dict into (field inputs, history
        turns) for :meth:`Baked.render`."""
        values = dict(values)
        turns: list[dict] = []
        if self.history_field and self.history_field in values:
            history = values.pop(self.history_field)
            messages = getattr(history, "messages", history) or []
            turns = [{"fields": dict(m)} for m in messages]
        return values, turns


def lower(signature, *, registry: lmcc.Registry | None = None) -> Lowered:
    """Lower a ``dspy.Signature`` class (or a signature string) to a
    SignatureCore. ``registry`` receives host bindings for every pydantic
    model and Enum met, so values lift back to native types on parse."""
    import dspy
    from dspy.adapters.types import History

    sig = dspy.ensure_signature(signature)
    registry = registry if registry is not None else lmcc.default_registry
    fields: list[core.Field] = []
    history_field: str | None = None
    for name, info in sig.fields.items():
        extra = info.json_schema_extra or {}
        direction = extra.get("__dspy_field_type")
        if direction not in ("input", "output"):
            refuse("signature-malformed", f"field {name!r}: not an InputField/OutputField")
        ann = info.annotation
        if ann is History:
            if direction != "input":
                refuse("unmapped-type", f"field {name!r}: dspy.History must be an input")
            if history_field is not None:
                refuse("unmapped-type", f"field {name!r}: a second dspy.History input")
            history_field = name
            continue
        desc = extra.get("desc")
        if desc == f"${{{name}}}" or desc == "":
            desc = None
        shape, role = _shape_and_role(ann, info, name, registry)
        fields.append(core.Field(name, direction, shape, role=role, desc=desc,
                                 annotation=ann))
    lowered = core._validated(core.SignatureCore(sig.instructions, fields))
    return Lowered(lowered, history_field)


# ------------------------------------------------------------------ shapes


def _shape_and_role(ann, info, name: str, registry: lmcc.Registry) -> tuple[dict, str]:
    """Map one annotation to (shape, role). Roles follow spec/vocab/roles.md;
    media types become parts; everything else is pydantic's JSON schema."""
    import dspy
    from dspy.adapters.types import Audio, Image
    from dspy.adapters.types.tool import Tool, ToolCalls

    role = "plain"
    origin, args = typing.get_origin(ann), typing.get_args(ann)
    base = args[0] if origin is list and args else ann

    if ann is dspy.Reasoning:
        return {"type": "string"}, "reasoning"
    if base is Tool:
        # a Tool wraps a callable; what a model sees is its declaration
        _register_tool(Tool, registry)
        shape = _TOOL_SHAPE if ann is Tool else {"type": "array", "items": _TOOL_SHAPE}
        return dict(shape), "tools"
    if ann is ToolCalls:
        role = "tools"
    citations = getattr(dspy, "Citations", None)
    if citations is not None and ann is citations:
        role = "citations"
    if ann is Image:
        return {"media": "image"}, role
    if ann is Audio:
        return {"media": "audio"}, role
    for media_name in ("File", "Document"):
        t = getattr(dspy, media_name, None)
        if t is not None and ann is t:
            return {"media": media_name.lower()}, role

    code_t = getattr(dspy, "Code", None)
    if code_t is not None and isinstance(ann, type) and issubclass(ann, code_t):
        # dspy.Code dumps to and validates from a bare string; the language
        # lives on the (parametrized) class and travels as a shape keyword
        shape = {"type": "string", "format": "code"}
        lang = getattr(ann, "language", None)
        if isinstance(lang, str) and lang:
            shape["language"] = lang
        if registry.host_for(ann) is None:
            registry.register_host(ann, shape=dict(shape),
                                   lower=lambda v: v.model_dump(mode="json") if isinstance(v, code_t) else v,
                                   lift=lambda v, _c=ann: _c.model_validate(v) if isinstance(v, str) else v)
        return shape, role
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        _register_enum(ann, registry)
        return _enum_shape(ann), role
    if isinstance(ann, type) and issubclass(ann, pydantic.BaseModel):
        _register_model(ann, registry)
    if origin is list and isinstance(base, type) and issubclass(base, pydantic.BaseModel):
        _register_model(base, registry)

    try:
        annotated = typing.Annotated[(ann, *info.metadata)] if info.metadata else ann
        shape = pydantic.TypeAdapter(annotated).json_schema()
    except Exception as exc:  # noqa: BLE001 — refuse by name
        refuse("unmapped-type",
               f"field {name!r}: cannot lower annotation {ann!r} to a shape ({exc})")
    shape.pop("title", None)
    return shape, role


_TOOL_SHAPE = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                   "parameters": {"type": "object"}},
    "required": ["name", "description", "parameters"],
}


def _register_tool(cls, registry: lmcc.Registry) -> None:
    """A dspy.Tool lowers to its declaration (the function-calling shape);
    the callable itself never travels — it is host code."""
    if registry.host_for(cls) is None:
        registry.register_host(
            cls, shape=dict(_TOOL_SHAPE),
            lower=lambda t: {"name": t.name, "description": t.desc or "",
                             "parameters": {"type": "object", "properties": dict(t.args or {})}})


def _enum_shape(cls) -> dict:
    values = [m.value for m in cls]
    shape: dict = {"enum": values}
    if all(isinstance(v, str) for v in values):
        shape["type"] = "string"
    elif all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        shape["type"] = "integer"
    else:
        refuse("unmapped-type",
               f"enum {cls.__name__}: members must all be strings or all integers")
    return shape


def _register_enum(cls, registry: lmcc.Registry) -> None:
    if registry.host_for(cls) is None:
        registry.register_host(cls, shape=_enum_shape(cls),
                               lower=lambda v: v.value if isinstance(v, cls) else v,
                               lift=lambda v: cls(v))


def _register_model(cls, registry: lmcc.Registry) -> None:
    if registry.host_for(cls) is None:
        registry.register_host(
            cls, shape=cls.model_json_schema(),
            lower=lambda v: v.model_dump(mode="json") if isinstance(v, cls) else v,
            lift=lambda v: cls.model_validate(v) if isinstance(v, dict) else v)


# ----------------------------------------------------------------- entry


def entry() -> dict:
    """The DSPy-shaped LMCC entry: `[[ ## name ## ]]` sections (corpus 21),
    a field description block, the lens's own skeleton, and `json` for
    every structured or uninterpreted shape. Idiomatic LMCC — one
    description renders the prompt, writes the demos and history, and
    derives nothing by hand."""
    return {
        "name": "dspy_chat",
        "versions": {"kernel": lmcc.KERNEL_VERSION, "vocab": {"codec/json": "0.1.0"}},
        "template": {"messages": [
            {"role": "system", "text":
                "Your input fields are:\n"
                "{% for f in inputs %}- {f.name}: {f.desc} {f.schema}\n{% endfor %}"
                "Your output fields are:\n"
                "{% for f in outputs %}- {f.name}: {f.desc} {f.schema}\n{% endfor %}"
                "\nAll interactions will be structured in the following way, "
                "with the appropriate values filled in.\n\n"
                "{% for f in inputs %}[[ ## {f.name} ## ]]\n{{{f.name}}}\n\n{% endfor %}"
                "{format}\n\n"
                "In adhering to this structure, your objective is: {instruction}"},
            {"directive": "demos"},
            {"directive": "history"},
            {"role": "user", "text":
                "{% for f in inputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}"
                "Respond with the corresponding output fields, then end with the "
                "marker for `[[ ## completed ## ]]`."},
        ]},
        "parse": {"kind": "sections", "open": "[[ ## {name} ## ]]",
                  "tail": "[[ ## completed ## ]]"},
        "codecs": {"@structured": {"kind": "json", "options": {"indent": None}}},
        "requires": [],
    }


def adapter(registry: lmcc.Registry | None = None):
    """Load :func:`entry` against a registry that has ``lmcc_std``."""
    import lmcc_std
    registry = registry if registry is not None else lmcc.default_registry
    lmcc_std.install(registry)
    return lmcc.load(entry(), registry=registry)

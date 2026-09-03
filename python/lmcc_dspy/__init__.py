"""lmcc_dspy — the DSPy signature frontend.

Lowers any ``dspy.Signature`` to an LMCC ``SignatureCore`` (kernel §1)
and ships one LMCC-idiomatic adapter shaped like DSPy's chat dialect.
The claim this package makes, and ``tests/dspy/test_catalog.py`` checks
against a real DSPy, is:

1. **Total lowering.** Every DSPy signature lowers. Nothing is dropped
   except what DSPy itself declares a no-op: ``prefix``, ``format``,
   ``parser`` (deprecated upstream, "has no effect"), the internal
   type-undefined marker, and field *defaults* (program-side values a
   caller supplies; never shown to a model). Anything else the frontend
   cannot carry refuses ``unmapped-type`` naming the field.
2. **Always renderable.** Every lowered signature binds, renders and
   parses with :func:`adapter`: structured and uninterpreted shapes go
   through the ``*`` → ``json`` format (kernel §5), ``Optional[X]`` is
   nullable, ``dspy.History`` becomes history field turns, and the DSPy
   types that are not plain data (``Image``, ``Audio``, ``Tool``,
   ``Code``) get runtime type bindings — per language, never serialized.

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


class Lowered:
    """The result of :func:`lower`: the signature, plus the name of a
    ``dspy.History`` input, if any (rendered as history turns)."""

    def __init__(self, signature: core.SignatureCore, history_field: str | None):
        self.signature = signature
        self.history_field = history_field

    def split_inputs(self, values: dict) -> tuple[dict, list[dict]]:
        values = dict(values)
        turns: list[dict] = []
        if self.history_field and self.history_field in values:
            history = values.pop(self.history_field)
            messages = getattr(history, "messages", history) or []
            turns = [{"fields": dict(m)} for m in messages]
        return values, turns


def lower(signature, *, registry: lmcc.Registry | None = None) -> Lowered:
    """Lower a ``dspy.Signature`` class (or a signature string). ``registry``
    receives the runtime type bindings DSPy's own types need."""
    import dspy
    from dspy.adapters.types import History

    sig = dspy.ensure_signature(signature)
    registry = registry if registry is not None else lmcc.default_registry
    bind_dspy_types(registry)
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
        shape, role = _shape_and_role(ann, info, name)
        fields.append(core.Field(name, direction, shape, type=_typename(ann), role=role,
                                 desc=desc, annotation=ann))
    lowered = core._validated(core.SignatureCore(sig.instructions, fields))
    return Lowered(lowered, history_field)


def _typename(ann) -> str:
    import dspy
    if isinstance(ann, type) and issubclass(ann, getattr(dspy, "Code", ())):
        return "Code"
    return core.typename(ann) or "?"


# ------------------------------------------------------------------ shapes


def _shape_and_role(ann, info, name: str) -> tuple[dict, str]:
    import dspy
    from dspy.adapters.types import Audio, Image
    from dspy.adapters.types.tool import Tool, ToolCalls

    role = "plain"
    origin, args = typing.get_origin(ann), typing.get_args(ann)
    base = args[0] if origin is list and args else ann

    if ann is dspy.Reasoning:
        return {"type": "string"}, "reasoning"
    if base is Tool:
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
        shape = {"type": "string", "format": "code"}
        lang = getattr(ann, "language", None)
        if isinstance(lang, str) and lang:
            shape["language"] = lang
        return shape, role
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return core.annotation_to_shape(ann, None, field_name=name), role
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


# --------------------------------------------- runtime bindings for dspy types


def _tool_declaration(t) -> dict:
    return {"name": t.name, "description": t.desc or "",
            "parameters": {"type": "object", "properties": dict(t.args or {})}}


def bind_dspy_types(registry: lmcc.Registry) -> None:
    """Formats for the DSPy types that are not plain data (kernel §5,
    step 3 — per runtime, never serialized). Idempotent."""
    import dspy
    from dspy.adapters.types import Audio, Image
    from dspy.adapters.types.tool import Tool

    if getattr(registry, "_lmcc_dspy_bound", False):
        return
    registry._lmcc_dspy_bound = True
    from lmcc_std import jsontext

    registry.format(Image, write=lambda im: [{"kind": "image", "url": im.url}],
                    accepts=("media:image",), emits="parts", direction="in")
    registry.format(Audio, write=lambda au: [{"kind": "audio", "url": getattr(au, "url", None)}],
                    accepts=("media:audio",), emits="parts", direction="in")
    registry.format(Tool, write=lambda t: jsontext.dumps(_tool_declaration(t), indent=None),
                    accepts=("Tool", "object"), direction="in")
    registry.format(list[Tool],
                    write=lambda ts: jsontext.dumps([_tool_declaration(t) for t in ts], indent=None),
                    accepts=("list[Tool]", "list[object]"), direction="in")
    code_t = getattr(dspy, "Code", None)
    if code_t is not None:
        registry.format(code_t,
                        write=lambda c: c.model_dump(mode="json") if isinstance(c, code_t) else c,
                        read=lambda span, f: f.annotation.model_validate(span.text),
                        accepts=("Code", "string"))


# ----------------------------------------------------------------- adapter


def entry() -> dict:
    """The DSPy-shaped LMCC artifact: `[[ ## name ## ]]` markers as a derived
    pattern (corpus 21), a field description block, and `json` for every
    structured or uninterpreted shape (`*`, consulted after the kernel's
    scalar defaults). Idiomatic LMCC — one description renders the prompt,
    writes the demos and history, and derives the parser."""
    return {
        "name": "dspy_chat",
        "versions": {"kernel": lmcc.KERNEL_VERSION, "vocab": {"format/json": "0.1.0"}},
        "template": [
            {"role": "system", "text":
                "Your input fields are:\n"
                "{% for f in inputs %}- {f.name}: {f.desc} {f.schema}\n{% endfor %}"
                "Your output fields are:\n"
                "{% for f in outputs %}- {f.name}: {f.desc} {f.schema}\n{% endfor %}"
                "\nAll interactions will be structured in the following way, "
                "with the appropriate values filled in.\n\n"
                "{% for f in inputs %}[[ ## {f.name} ## ]]\n{{{f.name}}}\n\n{% endfor %}"
                "{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}"
                "[[ ## completed ## ]]\n\n"
                "In adhering to this structure, your objective is: {instruction}"},
            {"directive": "demos"},
            {"directive": "history"},
            {"role": "user", "text":
                "{% for f in inputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}"
                "Respond with the corresponding output fields, then end with the "
                "marker for `[[ ## completed ## ]]`."},
        ],
        "parse": {"kind": "derived"},
        "formats": {"*": {"use": "json", "options": {"indent": None}}},
    }


def adapter(registry: lmcc.Registry | None = None):
    """Load :func:`entry` against a registry with ``lmcc_std`` and the
    DSPy type bindings installed."""
    import lmcc_std
    registry = registry if registry is not None else lmcc.default_registry
    lmcc_std.install(registry)
    bind_dspy_types(registry)
    return lmcc.load(entry(), registry=registry)

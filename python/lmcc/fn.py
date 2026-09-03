"""The typed-function frontend: ``@lmcc.fn`` and ``Role`` (kernel §1).

Inputs come from the parameters, outputs from the return type (a
dataclass for several), instructions from the docstring. Nothing else is
inferred. ``Role["reasoning", str]`` marks what a field means to the
exchange. The result lowers to a SignatureCore like every other frontend.
"""

from __future__ import annotations

import dataclasses
import inspect
import typing

from . import core
from .errors import refuse


class One:
    """``One[Person]`` — return one structured value, not the dataclass's
    fields as several outputs (kernel §1)."""

    def __class_getitem__(cls, item):
        return typing.Annotated[item, cls()]


class Role:
    """``Role["reasoning", str]`` — a role name and the field's type."""

    def __class_getitem__(cls, item):
        if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)):
            refuse("unmapped-type", "Role takes [name, type], e.g. Role['reasoning', str]")
        return typing.Annotated[item[1], cls(item[0])]

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"Role({self.name!r})"


def _split_role(ann) -> tuple[object, str]:
    base, role, _one = _unwrap(ann)
    return base, role


def _unwrap(ann) -> tuple[object, str, bool]:
    role, one = "plain", False
    while typing.get_origin(ann) is typing.Annotated:
        ann, *extras = typing.get_args(ann)
        for extra in extras:
            if isinstance(extra, Role):
                role = extra.name
            elif isinstance(extra, One):
                one = True
    return ann, role, one


class Fn:
    """A signature with a typed-function feel: ``fn.bind(adapter, capabilities=...)``."""

    def __init__(self, func, *, registry=None):
        self.func = func
        self.registry = registry
        self.signature = _lower(func, registry)
        self.__doc__ = func.__doc__
        self.__name__ = getattr(func, "__name__", "fn")

    def bind(self, adapter, *, capabilities: dict | None = None, registry=None):
        from .registry import default_registry
        registry = registry or self.registry or default_registry
        return adapter.bind(self.signature, capabilities or {}, registry=registry)

    def __call__(self, *a, **kw):
        refuse("entry-malformed",
               f"{self.__name__} is a signature, not a callable: bind it to an adapter, "
               f"render, send with your client, then parse")


def fn(func=None, *, registry=None):
    """``@lmcc.fn`` — parameters are inputs, the return type is the output
    (a dataclass for several), the docstring is the instruction."""
    if func is None:
        return lambda f: Fn(f, registry=registry)
    return Fn(func, registry=registry)


def _lower(func, registry) -> core.SignatureCore:
    hints = typing.get_type_hints(func, include_extras=True)
    sig = inspect.signature(func)
    fields: list[core.Field] = []
    for name, param in sig.parameters.items():
        if name not in hints:
            refuse("unmapped-type", f"parameter {name!r} has no type annotation")
        ann, role = _split_role(hints[name])
        fields.append(core.Field(name, "input", core.annotation_to_shape(ann, registry, field_name=name),
                                 type=core.typename(ann), role=role, annotation=ann))
    if "return" not in hints:
        refuse("unmapped-type", f"{func.__name__}: no return annotation — the return type is the output")
    ret, role, one = _unwrap(hints["return"])
    if dataclasses.is_dataclass(ret) and isinstance(ret, type) and not one:
        for df in dataclasses.fields(ret):
            ann, r = _split_role(typing.get_type_hints(ret, include_extras=True)[df.name])
            fields.append(core.Field(df.name, "output",
                                     core.annotation_to_shape(ann, registry, field_name=df.name),
                                     type=core.typename(ann), role=r, annotation=ann))
    else:
        fields.append(core.Field(func.__name__, "output",
                                 core.annotation_to_shape(ret, registry, field_name=func.__name__),
                                 type=core.typename(ret), role=role, annotation=ret))
    instructions = inspect.cleandoc(func.__doc__ or "")
    return core._validated(core.SignatureCore(instructions, fields))

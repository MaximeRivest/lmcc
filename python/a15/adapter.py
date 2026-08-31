"""The Adapter: a signature-independent bundle of template + lens + bindings.

An adapter never knows a signature. It is the *how* of a conversation —
layout, spellings, strategies — and applies to any *what*. The two meet at
``adapter.bake(signature, capabilities)``, which produces a Baked plan.

Construction surfaces:
- ``a15.adapter(template=..., parse=..., strategies=..., codecs=...)``
- ``a15.load(entry_dict, registry=...)`` from serialized data (serde.py)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .errors import refuse
from .parse import validate_sections_spec
from .strategy import Strategy
from .template import compile_template


def message(role: str, text: str) -> dict:
    if role not in ("system", "user", "assistant"):
        refuse("entry-malformed", f"message role {role!r} must be system/user/assistant")
    return {"role": role, "text": text}


def directive(kind: str) -> dict:
    if kind not in ("demos", "history"):
        refuse("entry-malformed", f"directive {kind!r} must be 'demos' or 'history'")
    return {"directive": kind}


def template(messages: list[dict]) -> dict:
    return {"messages": list(messages)}


def codec(kind: str, **options) -> dict:
    """A codec binding by name: ``a15.codec("table", columns=[...])``."""
    return {"kind": kind, "options": options}


@dataclass
class StrategyBinding:
    """Either a named reference (travels as a ref) or inline data."""

    ref: str | None = None
    options: dict = dc_field(default_factory=dict)
    inline: Strategy | None = None

    def to_dict(self) -> dict:
        if self.ref is not None:
            out: dict = {"kind": self.ref}
            if self.options:
                out["options"] = dict(self.options)
            return out
        return self.inline.to_dict()


@dataclass
class CodecBinding:
    kind: str
    options: dict = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.options:
            out["options"] = dict(self.options)
        return out


@dataclass
class Adapter:
    template: dict                      # {"messages": [...]}
    parse: dict                         # {"kind": "sections", ...}
    strategies: dict[str, StrategyBinding] = dc_field(default_factory=dict)
    codecs: dict[str, CodecBinding] = dc_field(default_factory=dict)
    name: str = "adapter"

    def bake(self, signature, capabilities: dict | None = None, *, registry=None):
        from .plan import bake as _bake
        from .registry import default_registry
        return _bake(self, signature, capabilities or {},
                     registry or default_registry)

    def dump(self, *, registry=None) -> dict:
        from .serde import dump as _dump
        from .registry import default_registry
        return _dump(self, registry or default_registry)

    def compiled_messages(self) -> list[tuple[dict, list | None]]:
        """[(message dict, compiled AST or None for directives)]"""
        out = []
        for i, msg in enumerate(self.template.get("messages", [])):
            if "directive" in msg:
                out.append((msg, None))
            else:
                out.append((msg, compile_template(
                    msg["text"], where=f"template.messages[{i}]")))
        return out


def adapter(*, template: dict, parse: dict, strategies: dict | None = None,
            codecs: dict | None = None, name: str = "adapter") -> Adapter:
    """Build an adapter from parts. Values in ``strategies`` may be a name
    (``"reasoning_tags"``), a :class:`Strategy`, or a plain data dict.
    Values in ``codecs`` may be a name or an :func:`codec` binding dict."""
    s_bindings: dict[str, StrategyBinding] = {}
    for role, value in (strategies or {}).items():
        if isinstance(value, str):
            s_bindings[role] = StrategyBinding(ref=value)
        elif isinstance(value, Strategy):
            value.validate(where=f"strategies[{role!r}]")
            s_bindings[role] = StrategyBinding(inline=value)
        elif isinstance(value, dict):
            if "kind" in value:
                s_bindings[role] = StrategyBinding(
                    ref=value["kind"], options=value.get("options", {}))
            else:
                s_bindings[role] = StrategyBinding(inline=Strategy.from_dict(
                    value, where=f"strategies[{role!r}]"))
        else:
            refuse("entry-malformed",
                   f"strategies[{role!r}]: expected a name, Strategy, or dict")
    c_bindings: dict[str, CodecBinding] = {}
    for fname, value in (codecs or {}).items():
        if isinstance(value, str):
            c_bindings[fname] = CodecBinding(value)
        elif isinstance(value, dict) and "kind" in value:
            c_bindings[fname] = CodecBinding(value["kind"], value.get("options", {}))
        else:
            refuse("entry-malformed",
                   f"codecs[{fname!r}]: expected a codec name or a15.codec(...)")
    adp = Adapter(template=template, parse=parse, strategies=s_bindings,
                  codecs=c_bindings, name=name)
    _validate_parse_spec(parse)
    adp.compiled_messages()  # surface template syntax errors immediately
    return adp


def _validate_parse_spec(spec: dict) -> None:
    kind = spec.get("kind")
    if not isinstance(kind, str) or not kind:
        refuse("unknown-parse-kind", "parse.kind must name a lens")
    if kind == "sections":
        validate_sections_spec(spec)
    # "derived" is kernel grammar too: the lens is read out of the
    # template at bake. Other kinds resolve against the registry at
    # load/bake — the refusal point for vocabulary, same as codecs.

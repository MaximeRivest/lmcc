"""The Adapter: a template, a parse rule, strategies by role, formats by
type — never a field name. It meets a signature only at ``bind``.

Construction surfaces:
- ``lmcc.adapter(messages=[...], parse=..., strategies=..., formats=...)``
- ``lmcc.load(entry, registry=...)`` from serialized data (serde.py)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .errors import refuse
from .strategy import Strategy
from .template import compile_template


def system(text: str) -> dict:
    return {"role": "system", "text": text}


def user(text: str) -> dict:
    return {"role": "user", "text": text}


def assistant(text: str) -> dict:
    return {"role": "assistant", "text": text}


def message(role: str, text: str) -> dict:
    if role not in ("system", "user", "assistant"):
        refuse("entry-malformed", f"message role {role!r} must be system/user/assistant")
    return {"role": role, "text": text}


def demos() -> dict:
    return {"directive": "demos"}


def history() -> dict:
    return {"directive": "history"}


def directive(kind: str) -> dict:
    if kind not in ("demos", "history"):
        refuse("entry-malformed", f"directive {kind!r} must be 'demos' or 'history'")
    return {"directive": kind}


def use(name: str, **options) -> dict:
    """A reference to a named format or strategy: ``lmcc.use("table", columns=[...])``."""
    return {"use": name, "options": options}


@dataclass
class Adapter:
    template: list                          # [{role, text} | {directive}]
    parse: dict                             # {"kind": "derived", ...}
    strategies: dict[str, object] = dc_field(default_factory=dict)   # role -> Strategy | {"use", "options"}
    formats: dict[str, object] = dc_field(default_factory=dict)      # type/structural key -> {"use", "options"} | shipped dict | Format
    name: str = "adapter"

    def bind(self, signature, capabilities: dict | None = None, *, registry=None):
        from .plan import bind as _bind
        from .registry import default_registry
        return _bind(self, signature, capabilities or {}, registry or default_registry)


    def dump(self, *, registry=None) -> dict:
        from .serde import dump as _dump
        from .registry import default_registry
        return _dump(self, registry or default_registry)

    def compiled_messages(self) -> list[tuple[dict, list | None]]:
        out = []
        for i, msg in enumerate(self.template):
            if "directive" in msg:
                out.append((msg, None))
            else:
                out.append((msg, compile_template(msg["text"], where=f"template[{i}]")))
        return out


def adapter(*, messages: list[dict] | None = None, template: list[dict] | dict | None = None,
            parse: dict | None = None, strategies: dict | None = None,
            formats: dict | None = None, name: str = "adapter") -> Adapter:
    """Build an adapter. ``strategies`` values: a name, a :class:`Strategy`,
    a data dict, or ``use(...)``. ``formats`` keys: type names or structural
    keys; values: a name, ``use(...)``, a shipped dict, or a Format."""
    if messages is None:
        messages = template.get("messages") if isinstance(template, dict) else template
    if not isinstance(messages, list):
        refuse("entry-malformed", "template must be a list of messages and directives")
    for i, m in enumerate(messages):
        if not isinstance(m, dict) or not ({"role", "text"} <= set(m) or "directive" in m):
            refuse("entry-malformed", f"template[{i}]: a message is {{role, text}} or {{directive}}")
        if "directive" in m and m["directive"] not in ("demos", "history"):
            refuse("entry-malformed", f"template[{i}]: directive must be demos or history")
        if "role" in m and m["role"] not in ("system", "user", "assistant"):
            refuse("entry-malformed", f"template[{i}]: role must be system/user/assistant")
    parse = parse or {"kind": "derived"}
    kind = parse.get("kind")
    if not isinstance(kind, str) or not kind:
        refuse("unknown-parse-kind", "parse.kind must name a lens")
    s_bindings: dict[str, object] = {}
    for role, value in (strategies or {}).items():
        where = f"strategies[{role!r}]"
        if isinstance(value, str):
            s_bindings[role] = {"use": value, "options": {}}
        elif isinstance(value, Strategy):
            value.validate(where=where)
            s_bindings[role] = value
        elif isinstance(value, dict) and "use" in value:
            s_bindings[role] = {"use": value["use"], "options": dict(value.get("options", {}))}
        elif isinstance(value, dict):
            s_bindings[role] = Strategy.from_dict(value, where=where)
        else:
            refuse("entry-malformed", f"{where}: expected a name, Strategy, use(...), or dict")
    f_bindings: dict[str, object] = {}
    for key, value in (formats or {}).items():
        where = f"formats[{key!r}]"
        if isinstance(value, str):
            f_bindings[key] = {"use": value, "options": {}}
        elif isinstance(value, dict) and "use" in value:
            f_bindings[key] = {"use": value["use"], "options": dict(value.get("options", {}))}
        elif isinstance(value, dict) and "language" in value:
            f_bindings[key] = dict(value)
        elif hasattr(value, "write"):
            f_bindings[key] = value
        else:
            refuse("entry-malformed", f"{where}: expected a name, use(...), a shipped format, or a Format")
    adp = Adapter(template=list(messages), parse=dict(parse), strategies=s_bindings,
                  formats=f_bindings, name=name)
    adp.compiled_messages()  # surface template syntax errors immediately
    return adp

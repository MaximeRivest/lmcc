"""The Adapter: a template, a reader, transports by purpose, formats by
type — never a field name. It meets a signature only at ``bind``.

Construction surfaces:
- ``lmcc.adapter(messages=[...], reader=..., transports=..., formats=...)``
- ``lmcc.load(entry, registry=...)`` from serialized data (serde.py)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .errors import refuse
from .transport import Transport
from .template import RESERVED_SLOTS, compile_template, turn_slots

_SLOT_NAME = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REPLAY = ("recorded", "values")


def system(text: str) -> dict:
    return {"role": "system", "text": text}


def developer(text: str) -> dict:
    return {"role": "developer", "text": text}


def user(text: str) -> dict:
    return {"role": "user", "text": text}


def assistant(text: str) -> dict:
    return {"role": "assistant", "text": text}


def message(role: str, text: str) -> dict:
    if role not in ("system", "developer", "user", "assistant"):
        refuse("entry-malformed", f"message role {role!r} must be system/developer/user/assistant",
               fix={"action": "edit-entry", "path": "template"})
    return {"role": role, "text": text}


def turns(slot: str = "turns") -> dict:
    """A turn slot in messages form (kernel §3a): the slot's turns become
    ordinary messages here. ``lmcc.turns()`` is the slot ``turns``."""
    return {"directive": "turns"} if slot == "turns" else {"directive": "turns", "slot": slot}


def use(name: str, **options) -> dict:
    """A reference to a named format or transport: ``lmcc.use("table", columns=[...])``."""
    return {"use": name, "options": options}


@dataclass
class Adapter:
    template: list                          # [{role, text} | {directive}]
    reader: dict                            # {"kind": "derived", ...}
    transports: dict[str, object] = dc_field(default_factory=dict)   # purpose -> Transport | {"use", "options"}
    formats: dict[str, object] = dc_field(default_factory=dict)      # type/structural key -> {"use", "options"} | shipped dict | Format
    name: str = "adapter"
    extensions: dict[str, str] = dc_field(default_factory=dict)      # "<family>/<name>" -> version needed (kernel §10)
    replay: str = "recorded"                # how written model steps are spelled (kernel §3a)
    strict: bool = False                    # True: read replies exactly, no repairs (kernel §4a)

    def bind(self, signature, capabilities: dict | None = None, *, registry=None):
        from .plan import bind as _bind
        from .registry import default_registry
        return _bind(self, signature, capabilities or {}, registry or default_registry)


    def dump(self, *, registry=None) -> dict:
        from .serde import dump as _dump
        from .registry import default_registry
        return _dump(self, registry or default_registry)

    @property
    def prefill(self) -> str | None:
        """The template's last message when it is an assistant message: the
        beginning of the reply, written for the model (kernel §3)."""
        last = self.template[-1] if self.template else {}
        return last.get("text") if last.get("role") == "assistant" else None

    def compiled_messages(self) -> list[tuple[dict, list | None]]:
        cached = getattr(self, "_compiled", None)
        if cached is not None and cached[0] == self.template:
            return cached[1]
        out = []
        for i, msg in enumerate(self.template):
            if "directive" in msg:
                out.append((msg, None))
            else:
                out.append((msg, compile_template(msg["text"], where=f"template[{i}]")))
        object.__setattr__(self, "_compiled", ([dict(m) for m in self.template], out))
        return out

    def turn_slots(self) -> dict[str, tuple[str, int]]:
        """Every placed turn slot: name -> ("messages" | "text", template index)
        (kernel §3a). Placing one twice, or guarding an unplaced one, is
        ``template-syntax``."""
        slots: dict[str, tuple[str, int]] = {}
        guards: list[tuple[str, int]] = []
        for i, (msg, nodes) in enumerate(self.compiled_messages()):
            if nodes is None:
                placed, guarded = [msg.get("slot", "turns")], []
                form = "messages"
            else:
                placed, guarded = turn_slots(nodes)
                form = "text"
            for name in placed:
                if name in slots:
                    refuse("template-syntax",
                           f"template[{i}]: turn slot {name!r} is already placed at "
                           f"template[{slots[name][1]}]; a slot is placed once",
                           fix={"action": "edit-template", "path": f"template[{i}]"})
                slots[name] = (form, i)
            guards += [(g, i) for g in guarded]
        self._guards = guards    # checked at bind: a guard may name an input (kernel §3a)
        return slots


def adapter(*, messages: list[dict] | None = None, template: list[dict] | dict | None = None,
            reader: dict | None = None, transports: dict | None = None,
            formats: dict | None = None, name: str = "adapter",
            extensions: dict[str, str] | None = None, replay: str = "recorded",
            strict: bool = False, declare_defaults: bool = True) -> Adapter:
    """Build an adapter. ``transports`` values: a name, a :class:`Transport`,
    a data dict, or ``use(...)``. ``formats`` keys: type names or structural
    keys; values: a name, ``use(...)``, a shipped dict, or a Format.
    ``extensions``: ``{"<family>/<name>": version}`` the adapter needs
    (kernel §10); checked against the registry at bind. With
    ``declare_defaults`` (the constructor's convenience, not the loader's)
    an inline ``pattern`` rule declares ``pattern/legacy-re2`` for you;
    the dumped artifact carries the line either way. ``replay``:
    ``"recorded"`` writes a past model step's recorded reply when this plan
    reads it back into the same values, ``"values"`` always writes it from
    its values (kernel §3a). ``strict=True`` reads replies exactly as the
    template spells them: no marker, delimiter or value repairs (kernel §4a)."""
    if messages is None:
        messages = template.get("messages") if isinstance(template, dict) else template
    if not isinstance(messages, list):
        refuse("entry-malformed", "template must be a list of messages and directives",
               fix={"action": "edit-entry", "path": "template"})
    for i, m in enumerate(messages):
        if not isinstance(m, dict) or not ({"role", "text"} <= set(m) or "directive" in m):
            refuse("entry-malformed", f"template[{i}]: a message is {{role, text}} or {{directive}}",
                   fix={"action": "edit-entry", "path": f"template[{i}]"})
        if "directive" in m:
            slot = m.get("slot", "turns")
            if (m["directive"] != "turns" or set(m) - {"directive", "slot"}
                    or not isinstance(slot, str) or not _SLOT_NAME.match(slot)):
                refuse("entry-malformed",
                       f"template[{i}]: a directive is {{\"directive\": \"turns\", \"slot\"?: "
                       f"name}} (demos and history are turn slots since kernel 0.7)",
                       fix={"action": "edit-entry", "path": f"template[{i}]"})
            if slot in RESERVED_SLOTS:
                refuse("template-syntax", f"template[{i}]: {slot!r} is reserved, not a turn slot",
                       fix={"action": "edit-template", "path": f"template[{i}]"})
        if "role" in m and m["role"] not in ("system", "developer", "user", "assistant"):
            refuse("entry-malformed", f"template[{i}]: role must be system/developer/user/assistant",
                   fix={"action": "edit-entry", "path": f"template[{i}]"})
        if m.get("role") == "system" and any("role" in x and x["role"] != "system" or "directive" in x
                                             for x in messages[:i]):
            refuse("entry-malformed",
                   f"template[{i}]: system messages lead the template (they become the lm15 "
                   f"request's system field); put later instructions in a developer message",
                   fix={"action": "edit-entry", "path": f"template[{i}]"})
    if replay not in REPLAY:
        refuse("entry-malformed", f"replay must be one of {REPLAY}, not {replay!r}",
               fix={"action": "edit-entry", "path": "replay"})
    reader = reader or {"kind": "derived"}
    kind = reader.get("kind")
    if not isinstance(kind, str) or not kind:
        refuse("unknown-reader", "reader.kind must name a reader",
               fix={"action": "edit-entry", "path": "reader"})
    if kind == "derived" and set(reader) != {"kind"}:
        refuse("entry-malformed", f"reader: the derived reader takes only 'kind', not "
                                  f"{sorted(set(reader) - {'kind'})}",
               fix={"action": "edit-entry", "path": "reader"})
    if not isinstance(strict, bool):
        refuse("entry-malformed", f"strict must be true or false, not {strict!r}",
               fix={"action": "edit-entry", "path": "strict"})
    s_bindings: dict[str, object] = {}
    for purpose, value in (transports or {}).items():
        where = f"transports[{purpose!r}]"
        if isinstance(value, str):
            s_bindings[purpose] = {"use": value, "options": {}}
        elif isinstance(value, Transport):
            value.validate(where=where)
            s_bindings[purpose] = value
        elif isinstance(value, dict) and "use" in value:
            s_bindings[purpose] = {"use": value["use"], "options": dict(value.get("options", {}))}
        elif isinstance(value, dict):
            s_bindings[purpose] = Transport.from_dict(value, where=where)
        else:
            refuse("entry-malformed", f"{where}: expected a name, Transport, use(...), or dict",
                   fix={"action": "edit-entry", "path": where})
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
            refuse("entry-malformed", f"{where}: expected a name, use(...), a shipped format, or a Format",
                   fix={"action": "edit-entry", "path": where})
    from .extensions import default_declaration, validate_declaration
    declared = validate_declaration(extensions)
    if declare_defaults:
        declared = default_declaration(s_bindings, declared)
    adp = Adapter(template=list(messages), reader=dict(reader), transports=s_bindings,
                  formats=f_bindings, name=name, extensions=declared, replay=replay,
                  strict=strict)
    compiled = adp.compiled_messages()  # surface template syntax errors immediately
    last, nodes = compiled[-1] if compiled else ({}, None)
    if last.get("role") == "assistant" and nodes is not None and \
            any(type(n).__name__ != "Text" for n in nodes):
        refuse("template-syntax",
               f"template[{len(compiled) - 1}]: a last assistant message is the reply's prefill "
               f"(kernel §3) and holds literal text only, no slots, loops or guards",
               fix={"action": "edit-template", "path": f"template[{len(compiled) - 1}]"})
    adp.turn_slots()         # and turn-slot put errors
    return adp

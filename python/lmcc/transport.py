"""Transport: how a meaning travels (kernel §6), as data.

``{when?, requires?, in_template?, tell?, request_settings?, put?,
find?, spelling?, written_as?}`` or ``{choose: [{when, use}, …, {else}]}``. A find rule is
``{from: "text" | "part:<kind>", between | pattern | line_prefixed,
to: "@purpose" | "@purpose.<sub>", remove?, complete_reply?}``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from . import core
from .errors import refuse

_KEYS = ("when", "requires", "in_template", "tell", "request_settings", "put", "written_as", "find", "spelling")
_PREDICATE_KEYS = ("capability", "not", "all", "any")
_TO = re.compile(r"^@purpose(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_PUT = re.compile(r"^(request\.[a-z_][a-z0-9_.]*|message:(system|developer|user|assistant))$")

# The request settings are a partial lm15 request (kernel §3): the first path
# segment is `config` or `tools`; `config` keys are the pinned lm15 Config
# fields (contract/LM15_CONTRACT_PIN). Below that the value is opaque.
LM15_CONFIG_FIELDS = frozenset((
    "max_tokens", "temperature", "top_p", "top_k", "stop", "response_format", "tool_choice",
    "reasoning", "cache", "service_tier", "user_id", "store", "extensions"))


def validate_setting_path(path: str, *, where: str) -> None:
    """``where`` is the artifact path of the control, for the refusal."""
    segments = path.split(".")
    ok = segments[0] == "tools" or (segments[0] == "config" and len(segments) >= 2
                                    and segments[1] in LM15_CONFIG_FIELDS)
    if not ok:
        refuse("entry-malformed",
               f"{where}: {path!r} is not a field of an lm15 request — request settings "
               f"'config.<field>' ({', '.join(sorted(LM15_CONFIG_FIELDS))}) or 'tools'; "
               f"provider-native knobs go under config.extensions",
               fix={"action": "edit-entry", "path": where})


def setting_leaves(request_settings: dict, prefix: str = "") -> list[tuple[str, object]]:
    """Flatten a request_settings dict to (dotted path, value) at the depth the
    kernel validates (two levels), leaving deeper values opaque."""
    out = []
    for key, value in request_settings.items():
        path = f"{prefix}{key}"
        if key == "config" and not prefix and isinstance(value, dict):
            out.extend(setting_leaves(value, "config."))
        else:
            out.append((path, value))
    return out
_FROM = re.compile(r"^(text|part:[a-z_]+)$")
# outside the portable RE2 dialect (kernel §7a)


@dataclass
class Transport:
    when: dict | None = None
    requires: list[str] = dc_field(default_factory=list)
    in_template: bool = True
    tell: dict[str, str] = dc_field(default_factory=dict)
    request_settings: dict = dc_field(default_factory=dict)
    put: dict[str, str] = dc_field(default_factory=dict)
    find: list[dict] = dc_field(default_factory=list)
    spelling: dict = dc_field(default_factory=dict)   # call/result, input_format, probe (§6); value/position (§3a)
    written_as: dict[str, str] = dc_field(default_factory=dict)     # "@purpose" -> named format for its put (kernel §6)
    choose: list[dict] | None = None      # [{"when": P, "use": Transport}, {"else": Transport}]

    # ------------------------------------------------------------ data

    def to_dict(self) -> dict:
        if self.choose is not None:
            out = []
            for alt in self.choose:
                if "else" in alt:
                    out.append({"else": alt["else"].to_dict()})
                else:
                    out.append({"when": dict(alt["when"]), "use": alt["use"].to_dict()})
            return {"choose": out}
        d: dict = {}
        if self.when is not None:
            d["when"] = dict(self.when)
        if self.requires:
            d["requires"] = list(self.requires)
        if not self.in_template:
            d["in_template"] = False
        if self.tell:
            d["tell"] = dict(self.tell)
        if self.request_settings:
            d["request_settings"] = dict(self.request_settings)
        if self.put:
            d["put"] = dict(self.put)
        if self.written_as:
            d["written_as"] = dict(self.written_as)
        if self.find:
            d["find"] = [dict(r) for r in self.find]
        if self.spelling:
            d["spelling"] = dict(self.spelling)
        return d

    @classmethod
    def from_dict(cls, data: dict, *, where: str) -> "Transport":
        if not isinstance(data, dict):
            refuse("entry-malformed", f"{where}: a transport is an object",
                   fix={"action": "edit-entry", "path": where})
        if "choose" in data:
            if set(data) != {"choose"} or not isinstance(data["choose"], list) or not data["choose"]:
                refuse("entry-malformed", f"{where}: choose is a non-empty list and stands alone",
                       fix={"action": "edit-entry", "path": where})
            alts = []
            for i, alt in enumerate(data["choose"]):
                aw = f"{where}.choose[{i}]"
                if not isinstance(alt, dict):
                    refuse("entry-malformed", f"{aw}: an alternative is an object",
                           fix={"action": "edit-entry", "path": aw})
                if "else" in alt:
                    if set(alt) != {"else"} or i != len(data["choose"]) - 1:
                        refuse("entry-malformed", f"{aw}: else stands alone and comes last",
                               fix={"action": "edit-entry", "path": aw})
                    alts.append({"else": cls.from_dict(alt["else"], where=aw)})
                elif set(alt) == {"when", "use"}:
                    validate_predicate(alt["when"], where=f"{aw}.when")
                    alts.append({"when": alt["when"], "use": cls.from_dict(alt["use"], where=aw)})
                else:
                    refuse("entry-malformed", f"{aw}: an alternative is {{when, use}} or {{else}}",
                           fix={"action": "edit-entry", "path": aw})
            return cls(choose=alts)
        unknown = set(data) - set(_KEYS)
        if unknown:
            refuse("entry-malformed",
                   f"{where}: unknown transport key(s) {sorted(unknown)}; known keys are {list(_KEYS)}",
                   fix={"action": "edit-entry", "path": where})
        if "spelling" in data and not isinstance(data["spelling"], dict):
            refuse("entry-malformed", f"{where}.spelling: must be an object",
                   fix={"action": "edit-entry", "path": f"{where}.spelling"})
        s = cls(when=data.get("when"), requires=list(data.get("requires", [])),
                in_template=bool(data.get("in_template", True)),
                tell=dict(data.get("tell", {})), request_settings=dict(data.get("request_settings", {})),
                put=dict(data.get("put", {})),
                find=[dict(r) for r in data.get("find", [])],
                spelling=dict(data.get("spelling", {})), written_as=dict(data.get("written_as", {})))
        s.validate(where=where)
        return s

    def validate(self, *, where: str) -> None:
        if self.choose is not None:
            for i, alt in enumerate(self.choose):
                if "when" in alt:
                    validate_predicate(alt["when"], where=f"{where}.choose[{i}].when")
                (alt.get("else") or alt["use"]).validate(where=f"{where}.choose[{i}]")
            return
        if self.when is not None:
            validate_predicate(self.when, where=f"{where}.when")
        for i, fact in enumerate(self.requires):
            if fact not in core.CAPABILITY_FACTS:
                refuse("entry-malformed", f"{where}.requires: {fact!r} is not a capability fact; "
                                          f"known: {sorted(core.CAPABILITY_FACTS)}",
                       fix={"action": "edit-entry", "path": f"{where}.requires[{i}]"})
        for i, r in enumerate(self.find):
            validate_find_rule(r, where=f"{where}.find[{i}]")
        for target, place in self.put.items():
            if not _TO.match(target) or not isinstance(place, str) or not _PUT.match(place):
                refuse("entry-malformed",
                       f"{where}.put: {target!r}: {place!r} — a put is "
                       f"'@purpose' or '@purpose.<sub>' → 'request.<key>' or 'message:<role>'",
                       fix={"action": "edit-entry", "path": f"{where}.put"})
        for path, _ in setting_leaves(self.request_settings):
            validate_setting_path(path, where=f"{where}.request_settings[{path!r}]")
        for _, place in self.put.items():
            if place.startswith("request."):
                validate_setting_path(place[len("request."):], where=f"{where}.put")
        for target, name in self.written_as.items():
            if target not in self.put or not isinstance(name, str) or not name:
                refuse("entry-malformed", f"{where}.written_as: {target!r} must name a placed field and a format name",
                       fix={"action": "edit-entry", "path": f"{where}.written_as"})
        validate_spelling(self.spelling, where=f"{where}.spelling")
        for k, v in self.tell.items():
            if k not in ("system", "developer", "user", "assistant") or not isinstance(v, str):
                refuse("entry-malformed", f"{where}.tell: {k!r} must name a message role, text",
                       fix={"action": "edit-entry", "path": f"{where}.tell"})
        if not self.in_template and not self.find and not self.put:
            refuse("entry-malformed",
                   f"{where}: in_template=false but no rule or put serves the field — "
                   f"the value would be unrecoverable", fix={"action": "edit-entry", "path": where})

    # ------------------------------------------------------------ bind

    def select(self, capabilities: dict, *, purpose: str, name: str) -> "Transport":
        """Resolve ``choose`` against the declared facts; check ``when`` and
        ``requires`` of the chosen alternative."""
        s = self
        while s.choose is not None:
            chosen = None
            for alt in s.choose:
                if "else" in alt or eval_predicate(alt["when"], capabilities):
                    chosen = alt.get("else") or alt["use"]
                    break
            if chosen is None:
                refuse("capability-missing",
                       f"purpose {purpose!r}: transport {name!r}: no alternative of 'choose' "
                       f"holds for the declared capabilities and there is no else",
                       fix={"action": "satisfy-predicate", "purpose": purpose,
                            "predicate": {"any": [dict(alt["when"]) for alt in s.choose]}})
            s = chosen
        if s.when is not None and not eval_predicate(s.when, capabilities):
            refuse("capability-missing",
                   f"purpose {purpose!r}: transport {name!r}: 'when' {s.when!r} is false for the "
                   f"declared capabilities",
                   fix={"action": "satisfy-predicate", "purpose": purpose, "predicate": dict(s.when)})
        for fact in s.requires:
            if not capabilities.get(fact):
                refuse("capability-missing",
                       f"purpose {purpose!r}: transport {name!r} requires capability {fact!r}, "
                       f"which the model does not declare",
                       fix={"action": "declare-capability", "fact": fact})
        return s

    def bound(self, field_name: str) -> "Transport":
        """A copy with ``{field}`` in tell bound to the purpose's field."""
        return Transport(when=self.when, requires=list(self.requires), in_template=self.in_template,
                        tell={k: v.replace("{field}", field_name)
                                   for k, v in self.tell.items()},
                        request_settings=dict(self.request_settings), put=dict(self.put),
                        find=[dict(r) for r in self.find], spelling=dict(self.spelling),
                        written_as=dict(self.written_as))


def validate_spelling(spelling, *, where: str) -> None:
    valid = isinstance(spelling, dict)
    if valid:
        valid = not (set(spelling) - {"call", "result", "input_format", "probe", "value", "position"})
        valid &= all(isinstance(spelling[k], str) for k in ("call", "result") if k in spelling)
        if "value" in spelling:
            w = spelling["value"]
            valid &= w is None or (isinstance(w, str) and _write_slots(w) == ["value"])
        if "position" in spelling:
            valid &= spelling["position"] in ("before", "after")
        if "input_format" in spelling:
            ref = spelling["input_format"]
            valid &= ("call" in spelling and isinstance(ref, dict)
                      and not (set(ref) - {"use", "options"})
                      and isinstance(ref.get("use"), str) and bool(ref["use"])
                      and isinstance(ref.get("options", {}), dict))
        if "probe" in spelling:
            probe = spelling["probe"]
            valid &= ("call" in spelling and isinstance(probe, dict)
                      and not (set(probe) - {"id", "name", "input"})
                      and isinstance(probe.get("name"), str) and bool(probe["name"])
                      and isinstance(probe.get("input"), dict)
                      and isinstance(probe.get("id", "probe"), str) and bool(probe.get("id", "probe")))
    if not valid:
        refuse("entry-malformed", f"{where}: expected call/result text, input_format {{use, options?}}, "
               "probe {name, input: object, id?} (formatter and probe require call), "
               "value (text with one {value} slot, or null) and position (before|after)",
               fix={"action": "edit-entry", "path": where})


def spelling_format_refs(adapter, registry):
    """All referenced argument writers, including inactive choose branches."""
    def walk(transport, where):
        if transport.choose is not None:
            for i, alt in enumerate(transport.choose):
                yield from walk(alt.get("else") or alt["use"], f"{where}.choose[{i}]")
        else:
            validate_spelling(transport.spelling, where=f"{where}.spelling")
            if "input_format" in transport.spelling:
                yield f"{where}.spelling.input_format", transport.spelling["input_format"]
    for purpose, binding in adapter.transports.items():
        where = f"transports[{purpose!r}]"
        transport = (binding if isinstance(binding, Transport) else
                    registry.transport(binding["use"], binding.get("options"), where=where))
        yield from walk(transport, where)


def _write_slots(template: str) -> list[str]:
    """The slot names a ``spelling.value`` text uses (``{{``/``}}`` escapes)."""
    names, i = [], 0
    while i < len(template):
        if template.startswith(("{{", "}}"), i):
            i += 2
            continue
        if template[i] == "{":
            j = template.find("}", i)
            if j < 0:
                return ["?"]
            names.append(template[i + 1:j])
            i = j + 1
            continue
        if template[i] == "}":
            return ["?"]
        i += 1
    return names


def spell_turn(template: str, slots: dict[str, str]) -> str:
    """Kernel §6 spelling: the closed slot set, ``{{``/``}}`` escapes."""
    out, i = [], 0
    while i < len(template):
        c = template[i]
        if c == "{" and template.startswith("{{", i):
            out.append("{"); i += 2; continue
        if c == "}" and template.startswith("}}", i):
            out.append("}"); i += 2; continue
        if c == "{":
            j = template.find("}", i)
            name = template[i + 1:j] if j > i else ""
            if name in slots:
                out.append(slots[name]); i = j + 1; continue
        out.append(c); i += 1
    return "".join(out)


def validate_find_rule(r: dict, *, where: str) -> None:
    if not isinstance(r, dict):
        refuse("entry-malformed", f"{where}: a rule is an object",
               fix={"action": "edit-entry", "path": where})
    src, to = r.get("from"), r.get("to")
    if not isinstance(src, str) or not _FROM.match(src):
        refuse("entry-malformed", f"{where}: 'from' is 'text' or 'part:<part kind>'",
               fix={"action": "edit-entry", "path": where})
    if not isinstance(to, str) or not _TO.match(to):
        refuse("entry-malformed", f"{where}: 'to' is '@purpose' or '@purpose.<sub>'",
               fix={"action": "edit-entry", "path": where})
    unknown = set(r) - {"from", "to", "remove", "between", "pattern", "line_prefixed",
                        "complete_reply", "repair"}
    if unknown:
        refuse("entry-malformed", f"{where}: unknown rule key(s) {sorted(unknown)}",
               fix={"action": "edit-entry", "path": where})
    kinds = [k for k in ("between", "pattern", "line_prefixed") if k in r]
    if src == "text":
        if len(kinds) != 1:
            refuse("entry-malformed",
                   f"{where}: a text rule needs exactly one of between/pattern/line_prefixed",
                   fix={"action": "edit-entry", "path": where})
        k = kinds[0]
        v = r[k]
        if k == "between":
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and x for x in v)):
                refuse("entry-malformed", f"{where}: between is [open, close], non-empty strings",
                       fix={"action": "edit-entry", "path": where})
        elif not isinstance(v, str) or not v:
            refuse("entry-malformed", f"{where}: {k} is a non-empty string",
                   fix={"action": "edit-entry", "path": where})
    if "repair" in r and (r["repair"] is not True and r["repair"] is not False
                          or src != "text" or "between" not in r):
        refuse("entry-malformed", f"{where}: 'repair' is true or false, on a between rule only "
                                  f"(its delimiters are repaired like markers, kernel §4a)",
               fix={"action": "edit-entry", "path": where})
    if src == "text":
        pass
    elif kinds or r.get("remove"):
        refuse("entry-malformed", f"{where}: a channel rule takes no text extractor and no remove",
               fix={"action": "edit-entry", "path": where})


def validate_predicate(p: object, *, where: str) -> None:
    if not isinstance(p, dict) or len(p) != 1:
        refuse("entry-malformed", f"{where}: a predicate is one of {_PREDICATE_KEYS}, one key",
               fix={"action": "edit-entry", "path": where})
    key, value = next(iter(p.items()))
    if key == "capability":
        if isinstance(value, str) and value not in core.CAPABILITY_FACTS:
            refuse("entry-malformed", f"{where}: {value!r} is not a capability fact; known: "
                                      f"{sorted(core.CAPABILITY_FACTS)}",
                   fix={"action": "edit-entry", "path": where})
        if not isinstance(value, str):
            refuse("entry-malformed", f"{where}: 'capability' names a fact",
                   fix={"action": "edit-entry", "path": where})
    elif key == "not":
        validate_predicate(value, where=f"{where}.not")
    elif key in ("all", "any"):
        if not isinstance(value, list):
            refuse("entry-malformed", f"{where}: {key!r} takes a list",
                   fix={"action": "edit-entry", "path": where})
        for j, q in enumerate(value):
            validate_predicate(q, where=f"{where}.{key}[{j}]")
    else:
        refuse("entry-malformed", f"{where}: unknown predicate key {key!r}; known: {_PREDICATE_KEYS}",
               fix={"action": "edit-entry", "path": where})


def eval_predicate(p: dict, capabilities: dict) -> bool:
    key, value = next(iter(p.items()))
    if key == "capability":
        return bool(capabilities.get(value))
    if key == "not":
        return not eval_predicate(value, capabilities)
    if key == "all":
        return all(eval_predicate(q, capabilities) for q in value)
    return any(eval_predicate(q, capabilities) for q in value)

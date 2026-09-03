"""Strategy: how a meaning travels (kernel §6), as data.

``{when?, requires?, visible?, fragments?, controls?, placement?,
routings?}`` or ``{choose: [{when, use}, …, {else}]}``. A routing is
``{from: "text" | "channel:<kind>", between | pattern | line_prefixed,
to: "@role" | "@role.<sub>", consume?}``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from .errors import refuse

_KEYS = ("when", "requires", "visible", "fragments", "controls", "placement", "routings")
_PREDICATE_KEYS = ("capability", "not", "all", "any")
_TO = re.compile(r"^@role(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_PLACEMENT = re.compile(r"^(controls\.[A-Za-z_][A-Za-z0-9_.]*|message:(system|user|assistant))$")
_FROM = re.compile(r"^(text|channel:[a-z_]+)$")
# outside the portable RE2 dialect (kernel §7a)
_NON_RE2 = re.compile(r"\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+")


@dataclass
class Strategy:
    when: dict | None = None
    requires: list[str] = dc_field(default_factory=list)
    visible: bool = True
    fragments: dict[str, str] = dc_field(default_factory=dict)
    controls: dict = dc_field(default_factory=dict)
    placement: dict[str, str] = dc_field(default_factory=dict)
    routings: list[dict] = dc_field(default_factory=list)
    choose: list[dict] | None = None      # [{"when": P, "use": Strategy}, {"else": Strategy}]

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
        if not self.visible:
            d["visible"] = False
        if self.fragments:
            d["fragments"] = dict(self.fragments)
        if self.controls:
            d["controls"] = dict(self.controls)
        if self.placement:
            d["placement"] = dict(self.placement)
        if self.routings:
            d["routings"] = [dict(r) for r in self.routings]
        return d

    @classmethod
    def from_dict(cls, data: dict, *, where: str) -> "Strategy":
        if not isinstance(data, dict):
            refuse("entry-malformed", f"{where}: a strategy is an object")
        if "choose" in data:
            if set(data) != {"choose"} or not isinstance(data["choose"], list) or not data["choose"]:
                refuse("entry-malformed", f"{where}: choose is a non-empty list and stands alone")
            alts = []
            for i, alt in enumerate(data["choose"]):
                aw = f"{where}.choose[{i}]"
                if not isinstance(alt, dict):
                    refuse("entry-malformed", f"{aw}: an alternative is an object")
                if "else" in alt:
                    if set(alt) != {"else"} or i != len(data["choose"]) - 1:
                        refuse("entry-malformed", f"{aw}: else stands alone and comes last")
                    alts.append({"else": cls.from_dict(alt["else"], where=aw)})
                elif set(alt) == {"when", "use"}:
                    validate_predicate(alt["when"], where=f"{aw}.when")
                    alts.append({"when": alt["when"], "use": cls.from_dict(alt["use"], where=aw)})
                else:
                    refuse("entry-malformed", f"{aw}: an alternative is {{when, use}} or {{else}}")
            return cls(choose=alts)
        unknown = set(data) - set(_KEYS)
        if unknown:
            refuse("entry-malformed",
                   f"{where}: unknown strategy key(s) {sorted(unknown)}; known keys are {list(_KEYS)}")
        s = cls(when=data.get("when"), requires=list(data.get("requires", [])),
                visible=bool(data.get("visible", True)),
                fragments=dict(data.get("fragments", {})), controls=dict(data.get("controls", {})),
                placement=dict(data.get("placement", {})),
                routings=[dict(r) for r in data.get("routings", [])])
        s.validate(where=where)
        return s

    def validate(self, *, where: str) -> None:
        if self.choose is not None:
            return
        if self.when is not None:
            validate_predicate(self.when, where=f"{where}.when")
        for i, r in enumerate(self.routings):
            validate_routing(r, where=f"{where}.routings[{i}]")
        for target, place in self.placement.items():
            if not _TO.match(target) or not isinstance(place, str) or not _PLACEMENT.match(place):
                refuse("entry-malformed",
                       f"{where}.placement: {target!r}: {place!r} — a placement is "
                       f"'@role' or '@role.<sub>' → 'controls.<key>' or 'message:<role>'")
        for k, v in self.fragments.items():
            if k not in ("system", "user", "assistant") or not isinstance(v, str):
                refuse("entry-malformed", f"{where}.fragments: {k!r} must name a message role, text")
        if not self.visible and not self.routings and not self.placement:
            refuse("entry-malformed",
                   f"{where}: visible=false but no routing or placement serves the field — "
                   f"the value would be unrecoverable")

    # ------------------------------------------------------------ bind

    def select(self, capabilities: dict, *, role: str, name: str) -> "Strategy":
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
                       f"role {role!r}: strategy {name!r}: no alternative of 'choose' "
                       f"holds for the declared capabilities and there is no else")
            s = chosen
        if s.when is not None and not eval_predicate(s.when, capabilities):
            refuse("capability-missing",
                   f"role {role!r}: strategy {name!r}: 'when' {s.when!r} is false for the "
                   f"declared capabilities")
        for fact in s.requires:
            if not capabilities.get(fact):
                refuse("capability-missing",
                       f"role {role!r}: strategy {name!r} requires capability {fact!r}, "
                       f"which the model does not declare")
        return s

    def bound(self, field_name: str) -> "Strategy":
        """A copy with ``{field}`` in fragments bound to the role's field."""
        return Strategy(when=self.when, requires=list(self.requires), visible=self.visible,
                        fragments={k: v.replace("{field}", field_name)
                                   for k, v in self.fragments.items()},
                        controls=dict(self.controls), placement=dict(self.placement),
                        routings=[dict(r) for r in self.routings])


def validate_routing(r: dict, *, where: str) -> None:
    if not isinstance(r, dict):
        refuse("entry-malformed", f"{where}: a routing is an object")
    src, to = r.get("from"), r.get("to")
    if not isinstance(src, str) or not _FROM.match(src):
        refuse("entry-malformed", f"{where}: 'from' is 'text' or 'channel:<part kind>'")
    if not isinstance(to, str) or not _TO.match(to):
        refuse("entry-malformed", f"{where}: 'to' is '@role' or '@role.<sub>'")
    unknown = set(r) - {"from", "to", "consume", "between", "pattern", "line_prefixed"}
    if unknown:
        refuse("entry-malformed", f"{where}: unknown routing key(s) {sorted(unknown)}")
    kinds = [k for k in ("between", "pattern", "line_prefixed") if k in r]
    if src == "text":
        if len(kinds) != 1:
            refuse("entry-malformed",
                   f"{where}: a text routing needs exactly one of between/pattern/line_prefixed")
        k = kinds[0]
        v = r[k]
        if k == "between":
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and x for x in v)):
                refuse("entry-malformed", f"{where}: between is [open, close], non-empty strings")
        elif not isinstance(v, str) or not v:
            refuse("entry-malformed", f"{where}: {k} is a non-empty string")
        if k == "pattern":
            check_re2(v, where=where)
    elif kinds or r.get("consume"):
        refuse("entry-malformed", f"{where}: a channel routing takes no text extractor and no consume")


def check_re2(regex: str, *, where: str) -> None:
    unescaped = re.sub(r"\\[^1-9k]", "", regex)
    hit = _NON_RE2.search(unescaped)
    if hit:
        refuse("entry-malformed",
               f"{where}: regex {regex!r} uses {hit.group(0)!r}, which is outside the "
               f"portable RE2 dialect (no lookaround, backreferences, named groups, "
               f"atomic or possessive constructs)")
    try:
        re.compile(regex, re.DOTALL)
    except re.error as exc:
        refuse("entry-malformed", f"{where}: regex {regex!r} does not compile: {exc}")


def validate_predicate(p: object, *, where: str) -> None:
    if not isinstance(p, dict) or len(p) != 1:
        refuse("entry-malformed", f"{where}: a predicate is one of {_PREDICATE_KEYS}, one key")
    key, value = next(iter(p.items()))
    if key == "capability":
        if not isinstance(value, str):
            refuse("entry-malformed", f"{where}: 'capability' names a fact")
    elif key == "not":
        validate_predicate(value, where=where)
    elif key in ("all", "any"):
        if not isinstance(value, list):
            refuse("entry-malformed", f"{where}: {key!r} takes a list")
        for q in value:
            validate_predicate(q, where=where)
    else:
        refuse("entry-malformed", f"{where}: unknown predicate key {key!r}; known: {_PREDICATE_KEYS}")


def eval_predicate(p: dict, capabilities: dict) -> bool:
    key, value = next(iter(p.items()))
    if key == "capability":
        return bool(capabilities.get(value))
    if key == "not":
        return not eval_predicate(value, capabilities)
    if key == "all":
        return all(eval_predicate(q, capabilities) for q in value)
    return any(eval_predicate(q, capabilities) for q in value)

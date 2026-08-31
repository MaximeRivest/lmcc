"""Strategy: the per-role, per-model-family decision, as data.

A strategy has five faces, all plain data:

- ``predicate``: a boolean expression over declared capability facts —
  ``{"capability": f}``, ``{"not": p}``, ``{"all": [...]}``,
  ``{"any": [...]}``. This is what lets ``prefix_cot`` say
  *"when the model does NOT have native reasoning"*.
- ``requires``: capability facts the model must declare (sugar for an
  all-of predicate; both may be used together).
- ``fragments``: prompt text contributed per message role (``{field}``
  inside a fragment resolves to the name of the field bearing the role).
- ``controls``: request-side data merged into the patch (stop sequences,
  tool declarations, ...). Conflicting keys refuse loudly.
- ``routings``: how the served value is recovered — extractors over text
  or over native response parts. ``"field": "@role"`` resolves at bake to
  the field bearing the role.

``visible`` decides whether the role's field stays in the token stream
(a parsed section) or is served entirely by its routings.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .errors import refuse
from .parse import validate_extract

_KEYS = ("predicate", "requires", "fragments", "controls", "routings",
         "visible")
_PREDICATE_KEYS = ("capability", "not", "all", "any")


@dataclass
class Strategy:
    predicate: dict | None = None
    requires: list[str] = dc_field(default_factory=list)
    fragments: dict[str, str] = dc_field(default_factory=dict)
    controls: dict = dc_field(default_factory=dict)
    routings: list[dict] = dc_field(default_factory=list)
    visible: bool = True

    def to_dict(self) -> dict:
        out: dict = {}
        if self.predicate is not None:
            out["predicate"] = dict(self.predicate)
        if self.requires:
            out["requires"] = list(self.requires)
        if self.fragments:
            out["fragments"] = dict(self.fragments)
        if self.controls:
            out["controls"] = dict(self.controls)
        if self.routings:
            out["routings"] = [dict(r) for r in self.routings]
        if not self.visible:
            out["visible"] = False
        return out

    @classmethod
    def from_dict(cls, data: dict, *, where: str) -> "Strategy":
        unknown = set(data) - set(_KEYS)
        if unknown:
            refuse("entry-malformed",
                   f"{where}: unknown strategy key(s) {sorted(unknown)}; "
                   f"known keys are {list(_KEYS)}")
        s = cls(
            predicate=data.get("predicate"),
            requires=list(data.get("requires", [])),
            fragments=dict(data.get("fragments", {})),
            controls=dict(data.get("controls", {})),
            routings=[dict(r) for r in data.get("routings", [])],
            visible=bool(data.get("visible", True)),
        )
        s.validate(where=where)
        return s

    def validate(self, *, where: str) -> None:
        if self.predicate is not None:
            validate_predicate(self.predicate, where=f"{where}: predicate")
        for i, routing in enumerate(self.routings):
            r_where = f"{where}: routing[{i}]"
            if "extract" not in routing or "field" not in routing:
                refuse("entry-malformed", f"{r_where} needs 'extract' and 'field'")
            validate_extract(routing["extract"], where=r_where)
        if not self.visible and not self.routings:
            refuse("entry-malformed",
                   f"{where}: visible=false but no routing serves the field — "
                   f"the value would be unrecoverable")


def validate_predicate(p: object, *, where: str) -> None:
    if not isinstance(p, dict) or len(p) != 1:
        refuse("entry-malformed",
               f"{where}: a predicate is one of {_PREDICATE_KEYS}, one key")
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
        refuse("entry-malformed",
               f"{where}: unknown predicate key {key!r}; "
               f"known: {_PREDICATE_KEYS}")


def eval_predicate(p: dict, capabilities: dict) -> bool:
    key, value = next(iter(p.items()))
    if key == "capability":
        return bool(capabilities.get(value))
    if key == "not":
        return not eval_predicate(value, capabilities)
    if key == "all":
        return all(eval_predicate(q, capabilities) for q in value)
    return any(eval_predicate(q, capabilities) for q in value)


def check_predicate(strategy: Strategy, capabilities: dict, *, role: str,
                    name: str) -> None:
    if strategy.predicate is not None and not eval_predicate(
            strategy.predicate, capabilities):
        refuse("capability-missing",
               f"role {role!r}: strategy {name!r} predicate "
               f"{strategy.predicate!r} is false for the declared "
               f"capabilities")
    for fact in strategy.requires:
        if not capabilities.get(fact):
            refuse("capability-missing",
                   f"role {role!r}: strategy {name!r} requires capability "
                   f"{fact!r}, which the model does not declare")


def resolve_role_field(strategy: Strategy, field_name: str) -> Strategy:
    """Return a copy with ``@role`` placeholders bound to the actual field."""
    routings = []
    for r in strategy.routings:
        r = dict(r)
        if r.get("field") == "@role":
            r["field"] = field_name
        routings.append(r)
    fragments = {k: v.replace("{field}", field_name)
                 for k, v in strategy.fragments.items()}
    return Strategy(predicate=strategy.predicate,
                    requires=list(strategy.requires), fragments=fragments,
                    controls=dict(strategy.controls), routings=routings,
                    visible=strategy.visible)

"""Strategy: the per-role, per-model-family decision, as data.

A strategy has four faces, all plain data:

- ``requires``: capability facts the model must declare (the predicate).
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

_KEYS = ("requires", "fragments", "controls", "routings", "visible")


@dataclass
class Strategy:
    requires: list[str] = dc_field(default_factory=list)
    fragments: dict[str, str] = dc_field(default_factory=dict)
    controls: dict = dc_field(default_factory=dict)
    routings: list[dict] = dc_field(default_factory=list)
    visible: bool = True

    def to_dict(self) -> dict:
        out: dict = {}
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
            requires=list(data.get("requires", [])),
            fragments=dict(data.get("fragments", {})),
            controls=dict(data.get("controls", {})),
            routings=[dict(r) for r in data.get("routings", [])],
            visible=bool(data.get("visible", True)),
        )
        s.validate(where=where)
        return s

    def validate(self, *, where: str) -> None:
        for i, routing in enumerate(self.routings):
            r_where = f"{where}: routing[{i}]"
            if "extract" not in routing or "field" not in routing:
                refuse("entry-malformed", f"{r_where} needs 'extract' and 'field'")
            validate_extract(routing["extract"], where=r_where)
        if not self.visible and not self.routings:
            refuse("entry-malformed",
                   f"{where}: visible=false but no routing serves the field — "
                   f"the value would be unrecoverable")


def check_predicate(strategy: Strategy, capabilities: dict, *, role: str,
                    name: str) -> None:
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
    return Strategy(requires=list(strategy.requires), fragments=fragments,
                    controls=dict(strategy.controls), routings=routings,
                    visible=strategy.visible)

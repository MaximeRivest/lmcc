"""Helpers you can autocomplete (plan 13): ``lmcc.find``, ``lmcc.put``,
``lmcc.when``, ``lmcc.choose``.

Each returns the same plain data you could write by hand (kernel §6), so
the artifact, the corpus and the spec are unchanged; ``print`` any of them
to see the dict. A wrong argument is a host misuse (``TypeError``), not a
``Refusal``: the kernel validates the data they produce like any other.
"""

from __future__ import annotations

from .transport import Transport


def _to(to: str | None) -> str:
    if to is None:
        return "@purpose"
    if not isinstance(to, str) or not to or to.startswith("@"):
        raise TypeError("to= is a sub-purpose name like 'calls' (None means the purpose itself)")
    return f"@purpose.{to}"


class find:
    """Where an output is found in the reply (kernel §6 find rules)."""

    @staticmethod
    def between(open: str, close: str, *, to: str | None = None, remove: bool = False,
                repair: bool = False, whole_reply: bool = False) -> dict:
        """Text between two delimiters: ``find.between("<think>", "</think>", remove=True)``.
        ``repair`` reads misspelled delimiters (``<Think>``, kernel §4a);
        ``whole_reply`` makes a reply holding a match a whole reply (a tool call turn)."""
        if not (isinstance(open, str) and open and isinstance(close, str) and close):
            raise TypeError("find.between takes two non-empty strings")
        rule = {"from": "text", "between": [open, close], "to": _to(to)}
        if remove:
            rule["remove"] = True
        if repair:
            rule["repair"] = True
        if whole_reply:
            rule["complete_reply"] = True
        return rule

    @staticmethod
    def lines(prefix: str, *, to: str | None = None, remove: bool = False) -> dict:
        """Lines starting with ``prefix``: ``find.lines("NOTE: ")``."""
        if not isinstance(prefix, str) or not prefix:
            raise TypeError("find.lines takes a non-empty prefix")
        rule = {"from": "text", "line_prefixed": prefix, "to": _to(to)}
        if remove:
            rule["remove"] = True
        return rule

    @staticmethod
    def pattern(regex: str, *, to: str | None = None, remove: bool = False) -> dict:
        """A regular expression (needs a declared ``pattern/*`` extension, kernel §10)."""
        if not isinstance(regex, str) or not regex:
            raise TypeError("find.pattern takes a non-empty regex")
        rule = {"from": "text", "pattern": regex, "to": _to(to)}
        if remove:
            rule["remove"] = True
        return rule

    @staticmethod
    def part(type: str, *, to: str | None = None, whole_reply: bool = False) -> dict:
        """Reply parts of one lm15 type: ``find.part("thinking")``, ``find.part("tool_call", to="calls")``."""
        if not isinstance(type, str) or not type:
            raise TypeError("find.part takes an lm15 part type such as 'thinking'")
        rule = {"from": f"part:{type}", "to": _to(to)}
        if whole_reply:
            rule["complete_reply"] = True
        return rule


class put:
    """Where an input goes instead of a template slot (kernel §6 ``put``).
    Each returns the ``put`` dict for the purpose itself; pass ``field=`` a
    sub-purpose name for another field of the purpose."""

    @staticmethod
    def _at(place: str, field: str | None) -> dict:
        return {_to(field): place}

    @staticmethod
    def system(field: str | None = None) -> dict:
        return put._at("message:system", field)

    @staticmethod
    def developer(field: str | None = None) -> dict:
        return put._at("message:developer", field)

    @staticmethod
    def user(field: str | None = None) -> dict:
        return put._at("message:user", field)

    @staticmethod
    def request(path: str, field: str | None = None) -> dict:
        """Into the lm15 request: ``put.request("tools")``."""
        if not isinstance(path, str) or not path:
            raise TypeError("put.request takes a request path such as 'tools'")
        return put._at(f"request.{path}", field)


class when:
    """When a transport applies: predicates over declared capability facts."""

    @staticmethod
    def has(fact: str) -> dict:
        return {"capability": fact}

    @staticmethod
    def lacks(fact: str) -> dict:
        return {"not": {"capability": fact}}

    @staticmethod
    def all(*predicates: dict) -> dict:
        return {"all": list(predicates)}

    @staticmethod
    def any(*predicates: dict) -> dict:
        return {"any": list(predicates)}


def choose(*alternatives: tuple, otherwise=None, registry=None) -> Transport:
    """The first transport whose predicate holds:
    ``choose((when.has("native_reasoning"), "native_reasoning"), otherwise="reasoning_tags")``.
    A transport is a ``Transport``, a dict, or a name registered in ``registry``
    (default: the default registry)."""
    from .registry import default_registry
    registry = registry or default_registry

    def resolve(t):
        if isinstance(t, Transport):
            return t
        if isinstance(t, dict):
            return Transport.from_dict(t, where="choose")
        if isinstance(t, str):
            return registry.transport(t, {})
        raise TypeError("a choice is a Transport, a dict or a registered transport name")

    items = []
    for alt in alternatives:
        if not (isinstance(alt, tuple) and len(alt) == 2 and isinstance(alt[0], dict)):
            raise TypeError("choose takes (predicate, transport) pairs")
        items.append({"when": alt[0], "use": resolve(alt[1])})
    if otherwise is not None:
        items.append({"else": resolve(otherwise)})
    t = Transport(choose=items)
    t.validate(where="choose")
    return t

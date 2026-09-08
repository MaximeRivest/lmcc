"""Extensions: declared execution contracts (kernel §10, spec/portability.md).

The core is exact and mandatory; everything else is a named, versioned
contract the artifact *declares* (``entry.extensions``) and the host
*binds* (``Registry.extensions``) or refuses — at load, and again at
bind for adapters built in code, always before a plan exists.

Two things live here:

- the **binding** protocol per family (today one family, ``pattern``:
  how a text routing's ``pattern`` string is admitted and matched), and
  the kernel's native bindings for what this runtime can honestly do;
- ``resolve``: the declaration rules, in order — syntax, one per
  family, host support, version, undeclared use, admission.

A binding is a table entry. It runs no artifact code and starts nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import refuse

_NAME = re.compile(r"^[a-z][a-z0-9_]*/[a-z][a-z0-9_-]*$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def family_of(name: str) -> str:
    return name.split("/", 1)[0]


# ---------------------------------------------------------------- bindings


class ExtensionBinding:
    """What a host binds under an extension name: the contract it claims
    (``extension``, ``version``) and a label saying how (``binding``:
    ``python:re``, a library, a service — never a secret)."""

    extension: str = ""
    version: str = "0.0.0"
    binding: str = ""
    family: str = ""

    def describe(self) -> dict:
        return {"version": self.version, "binding": self.binding}


class PatternBinding(ExtensionBinding):
    """The ``pattern`` family: admit a regex at load/bind, find its spans
    at parse. ``spans`` returns ``(start, end, capture)`` triples in match
    order — the same shape the core scans produce."""

    family = "pattern"

    def admit(self, regex: str, *, where: str) -> None:
        raise NotImplementedError

    def spans(self, regex: str, text: str) -> list[tuple[int, int, str]]:
        raise NotImplementedError


_NON_RE2 = re.compile(r"\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+")


class LegacyRE2(PatternBinding):
    """``pattern/legacy-re2`` 0.1.0 through Python's ``re`` — exactly what
    kernel 0.2 did (spec/extensions/pattern-legacy-re2.md). Equivalence
    with other engines beyond the corpus cases is not claimed."""

    extension = "pattern/legacy-re2"
    version = "0.1.0"
    binding = "python:re"

    def __init__(self) -> None:
        self._compiled: dict[str, re.Pattern] = {}

    def admit(self, regex: str, *, where: str) -> None:
        unescaped = re.sub(r"\\[^1-9k]", "", regex)
        hit = _NON_RE2.search(unescaped)
        if hit:
            refuse("entry-malformed",
                   f"{where}: regex {regex!r} uses {hit.group(0)!r}, which is outside the "
                   f"pattern/legacy-re2 dialect (no lookaround, backreferences, named groups, "
                   f"atomic or possessive constructs)", fix={"action": "edit-entry", "path": where})
        try:
            self._compiled[regex] = re.compile(regex, re.DOTALL)
        except re.error as exc:
            refuse("entry-malformed", f"{where}: regex {regex!r} does not compile: {exc}",
                   fix={"action": "edit-entry", "path": where})

    def spans(self, regex: str, text: str) -> list[tuple[int, int, str]]:
        pattern = self._compiled.get(regex)
        if pattern is None:
            pattern = self._compiled[regex] = re.compile(regex, re.DOTALL)
        out: list[tuple[int, int, str]] = []
        for m in pattern.finditer(text):
            if m.end() == m.start():
                continue
            cap = m.group(1) if pattern.groups else m.group(0)
            out.append((m.start(), m.end(), cap if cap is not None else ""))
        return out


def native_extensions() -> list[ExtensionBinding]:
    """The bindings this runtime can honestly claim with its standard
    library alone. A ``Registry()`` binds them by default; a core-only
    registry (``Registry(extensions=())``) binds none."""
    return [LegacyRE2()]


# ----------------------------------------------------------------- resolve


@dataclass
class Resolved:
    name: str
    needs: str
    binding: ExtensionBinding

    def describe(self) -> dict:
        return {"needs": self.needs, "provides": self.binding.version,
                "binding": self.binding.binding}


def uses_family(strategies: dict, family: str) -> bool:
    """Whether any *inline* strategy (through ``choose`` branches) carries a
    routing of ``family``. Named strategies are resolved at bind with a
    registry and are not seen here."""
    from .strategy import Strategy

    def walk(s: Strategy) -> bool:
        if s.choose is not None:
            return any(walk(alt.get("else") or alt["use"]) for alt in s.choose)
        return any(family == "pattern" and "pattern" in r for r in s.routings)

    return any(isinstance(s, Strategy) and walk(s) for s in strategies.values())


def default_declaration(strategies: dict, declared: dict[str, str]) -> dict[str, str]:
    """The constructor's convenience (kernel §10): an inline ``pattern``
    routing with no ``pattern/*`` declared gets the default tier — the
    host's native engine, ``pattern/legacy-re2`` at the version this
    kernel binds. The declaration is written into the adapter, so the
    dumped artifact says it. Loading never defaults: an artifact on disk
    must speak for itself."""
    if uses_family(strategies, "pattern") and not any(family_of(n) == "pattern" for n in declared):
        return {**declared, LegacyRE2.extension: LegacyRE2.version}
    return declared


def validate_declaration(extensions: object) -> dict[str, str]:
    """Rules 1–2 of kernel §10: shape, names, versions, one per family."""
    if extensions is None:
        return {}
    if not isinstance(extensions, dict):
        refuse("entry-malformed", "extensions must be an object of '<family>/<name>': version",
               fix={"action": "edit-entry", "path": "extensions"})
    seen: dict[str, str] = {}
    for name, version in extensions.items():
        if not isinstance(name, str) or not _NAME.match(name):
            refuse("entry-malformed",
                   f"extensions: {name!r} is not an extension name ('<family>/<name>', lowercase)",
                   fix={"action": "edit-entry", "path": "extensions"})
        if not isinstance(version, str) or not _SEMVER.match(version):
            refuse("entry-malformed",
                   f"extensions: {name!r}: version {version!r} is not MAJOR.MINOR.PATCH",
                   fix={"action": "edit-entry", "path": "extensions"})
        fam = family_of(name)
        if fam in seen:
            refuse("entry-malformed",
                   f"extensions: {seen[fam]!r} and {name!r} both govern family {fam!r}; "
                   f"declare one contract per family",
                   fix={"action": "edit-entry", "path": "extensions"})
        seen[fam] = name
    return dict(extensions)


def resolve(adapter, registry) -> dict[str, Resolved]:
    """Kernel §10 rules 1–6. Returns {name: Resolved} for the declared
    extensions. Refuses, naming the offender, before any plan exists."""
    from .serde import check_compatible
    from .strategy import Strategy

    declared = validate_declaration(adapter.extensions)
    resolved: dict[str, Resolved] = {}
    for name, needs in declared.items():
        binding = registry.extensions.get(name)
        if binding is None:
            refuse("extension-unsupported",
                   f"the artifact declares extension {name!r} {needs}, and this runtime binds "
                   f"no implementation of it (registry.describe()['extensions'] lists what it "
                   f"binds)", fix={"action": "bind-extension", "name": name, "needs": needs})
        check_compatible(name, needs, binding.version)
        resolved[name] = Resolved(name, needs, binding)
    by_family = {family_of(n): r for n, r in resolved.items()}

    def walk(strategy: Strategy, where: str) -> None:
        if strategy.choose is not None:
            for i, alt in enumerate(strategy.choose):
                walk(alt.get("else") or alt["use"], f"{where}.choose[{i}]")
            return
        for i, r in enumerate(strategy.routings):
            if "pattern" not in r:
                continue
            path = f"{where}.routings[{i}]"
            pattern = by_family.get("pattern")
            if pattern is None:
                refuse("extension-undeclared",
                       f"{path}: 'pattern' needs a pattern/* extension and the artifact "
                       f"declares none (kernel §10; pattern/legacy-re2 is what 0.2 did)",
                       fix={"action": "declare-extension", "family": "pattern", "path": path})
            pattern.binding.admit(r["pattern"], where=path)

    for role, binding in adapter.strategies.items():
        where = f"strategies[{role!r}]"
        if isinstance(binding, Strategy):
            walk(binding, where)
        else:
            walk(registry.strategy(binding["use"], binding.get("options"), where=where), where)
    return resolved


__all__ = ["ExtensionBinding", "PatternBinding", "LegacyRE2", "Resolved", "default_declaration",
           "native_extensions", "resolve", "uses_family", "validate_declaration"]

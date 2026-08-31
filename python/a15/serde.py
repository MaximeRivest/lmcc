"""Serde: the artifact. Dump an adapter to plain data; load it back.

The entry format is the contract's file format (contract/schema/
entry.schema.json). Two rules with no exceptions:

- **Zero ambient state.** ``load`` resolves names only through the registry
  you hand it. A data-only entry (no named refs) loads with an empty one.
- **Loud refusal.** Unknown kinds, malformed structure, and incompatible
  versions refuse naming the exact reference and path.

Versioning: the kernel and each vocabulary entry are versioned separately.
While the kernel is 0.x, minor versions are treated as breaking (the usual
semver-0 convention).
"""

from __future__ import annotations

from .adapter import Adapter, CodecBinding, StrategyBinding, adapter as make_adapter
from .errors import refuse
from .strategy import Strategy

KERNEL_VERSION = "0.1.0"


def _parse_version(version: object, *, what: str) -> tuple[int, int, int]:
    if not isinstance(version, str):
        refuse("entry-malformed", f"{what}: version must be a string")
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        refuse("entry-malformed", f"{what}: version {version!r} is not MAJOR.MINOR.PATCH")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def _check_compatible(kind: str, theirs: str, ours: str) -> None:
    t, o = _parse_version(theirs, what=kind), _parse_version(ours, what=kind)
    ok = t[0] == o[0] and (t[1] <= o[1] if t[0] > 0 else t[1] == o[1])
    if not ok:
        refuse("version-incompatible",
               f"{kind}: entry needs {theirs}, this implementation provides {ours}")


# ---------------------------------------------------------------------- load


def load(entry: dict, *, registry=None) -> Adapter:
    from .registry import Registry, default_registry
    registry = registry if registry is not None else default_registry

    if not isinstance(entry, dict):
        refuse("entry-malformed", "entry must be a JSON object")
    for key in ("template", "parse", "versions"):
        if key not in entry:
            refuse("entry-malformed", f"entry is missing required key {key!r}")

    versions = entry["versions"]
    _check_compatible("kernel", versions.get("kernel", "0.0.0"), KERNEL_VERSION)
    vocab_versions = versions.get("vocab", {})

    messages = entry["template"].get("messages")
    if not isinstance(messages, list):
        refuse("entry-malformed", "template.messages must be a list")

    strategies: dict[str, object] = {}
    for role, s in (entry.get("strategies") or {}).items():
        where = f"strategies[{role!r}]"
        if not isinstance(s, dict):
            refuse("entry-malformed", f"{where}: must be an object")
        if "kind" in s:
            name = s["kind"]
            if name not in registry.strategies:
                refuse("unknown-strategy",
                       f"{where}: strategy {name!r} is not registered")
            _check_vocab_version(f"strategy/{name}", vocab_versions,
                                 registry.strategies[name].version)
            strategies[role] = {"kind": name, "options": s.get("options", {})}
        else:
            strategies[role] = Strategy.from_dict(s, where=where)

    codecs: dict[str, dict] = {}
    for fname, c in (entry.get("codecs") or {}).items():
        where = f"codecs[{fname!r}]"
        if not isinstance(c, dict) or "kind" not in c:
            refuse("entry-malformed", f"{where}: must be an object with 'kind'")
        name = c["kind"]
        if name not in registry.codecs:
            refuse("unknown-codec", f"{where}: codec {name!r} is not registered")
        _check_vocab_version(f"codec/{name}", vocab_versions,
                             registry.codecs[name].version)
        codecs[fname] = {"kind": name, "options": c.get("options", {})}

    return make_adapter(template={"messages": messages}, parse=entry["parse"],
                        strategies=strategies, codecs=codecs,
                        name=entry.get("name", "adapter"))


def _check_vocab_version(ref: str, declared: dict, provided: str) -> None:
    if ref in declared:
        _check_compatible(ref, declared[ref], provided)


# ---------------------------------------------------------------------- dump


def dump(adp: Adapter, registry) -> dict:
    vocab: dict[str, str] = {}
    strategies: dict[str, dict] = {}
    for role, binding in adp.strategies.items():
        strategies[role] = binding.to_dict()
        if binding.ref is not None:
            named = registry.strategies.get(binding.ref)
            if named is None:
                refuse("unknown-strategy",
                       f"cannot dump: strategy {binding.ref!r} is not registered "
                       f"(its version is part of the artifact)")
            vocab[f"strategy/{binding.ref}"] = named.version
    codecs: dict[str, dict] = {}
    for fname, binding in adp.codecs.items():
        codecs[fname] = binding.to_dict()
        named = registry.codecs.get(binding.kind)
        if named is None:
            refuse("unknown-codec",
                   f"cannot dump: codec {binding.kind!r} is not registered")
        vocab[f"codec/{binding.kind}"] = named.version

    entry: dict = {
        "name": adp.name,
        "versions": {"kernel": KERNEL_VERSION, "vocab": vocab},
        "template": {"messages": [dict(m) for m in adp.template["messages"]]},
        "parse": dict(adp.parse),
    }
    if strategies:
        entry["strategies"] = strategies
    if codecs:
        entry["codecs"] = codecs
    entry["requires"] = []
    return entry

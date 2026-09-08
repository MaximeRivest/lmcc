"""Serde: the artifact (kernel §5, §6; schema/entry.schema.json).

Two rules with no exceptions:

- **Zero ambient state.** ``load`` resolves names only through the registry
  you hand it. A data-only entry loads with an empty one.
- **Loud refusal.** Unknown names, malformed structure, incompatible
  versions, and shipped code this runtime will not place refuse, naming
  the exact reference and path. Loading never runs a UDF.
"""

from __future__ import annotations

from . import extensions as _extensions
from . import formats as _formats
from .adapter import Adapter, adapter as make_adapter
from .errors import refuse
from .strategy import Strategy

KERNEL_VERSION = "0.5.0"


def _parse_version(version: object, *, what: str) -> tuple[int, int, int]:
    if not isinstance(version, str):
        refuse("entry-malformed", f"{what}: version must be a string",
               fix={"action": "edit-entry", "path": "versions"})
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        refuse("entry-malformed", f"{what}: version {version!r} is not MAJOR.MINOR.PATCH",
               fix={"action": "edit-entry", "path": "versions"})
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def check_compatible(kind: str, theirs: str, ours: str) -> None:
    t, o = _parse_version(theirs, what=kind), _parse_version(ours, what=kind)
    ok = t[0] == o[0] and (t[1] <= o[1] if t[0] > 0 else t[1] == o[1])
    if not ok:
        refuse("version-incompatible",
               f"{kind}: artifact needs {theirs}, this implementation provides {ours}",
               fix={"action": "match-version", "entry": kind, "needs": theirs, "provides": ours})


def _check_vocab_version(ref: str, declared: dict, provided: str) -> None:
    if ref in declared:
        check_compatible(ref, declared[ref], provided)


# ---------------------------------------------------------------------- load


def load(entry: dict, *, registry=None) -> Adapter:
    from .registry import default_registry
    registry = registry if registry is not None else default_registry

    if not isinstance(entry, dict):
        refuse("entry-malformed", "entry must be a JSON object", fix={"action": "edit-entry", "path": ""})
    for key in ("template", "parse", "versions"):
        if key not in entry:
            refuse("entry-malformed", f"entry is missing required key {key!r}",
                   fix={"action": "edit-entry", "path": key})
    versions = entry["versions"]
    if not isinstance(versions, dict):
        refuse("entry-malformed", "versions must be an object", fix={"action": "edit-entry", "path": "versions"})
    check_compatible("kernel", versions.get("kernel", "0.0.0"), KERNEL_VERSION)
    vocab_versions = versions.get("vocab", {}) or {}

    template = entry["template"]
    if isinstance(template, dict) and "messages" in template:
        refuse("entry-malformed",
               "template is a list in kernel 0.2 (the 0.1 {\"messages\": [...]} form is gone)",
               fix={"action": "edit-entry", "path": "template"})
    if not isinstance(template, list):
        refuse("entry-malformed", "template must be a list", fix={"action": "edit-entry", "path": "template"})

    parse_spec = entry["parse"]
    if not isinstance(parse_spec, dict):
        refuse("entry-malformed", "entry.parse must be an object", fix={"action": "edit-entry", "path": "parse"})
    lens_kind = parse_spec.get("kind")
    if lens_kind != "derived":
        if lens_kind not in registry.lenses:
            refuse("unknown-parse-kind",
                   f"parse.kind {lens_kind!r} is neither the kernel lens 'derived' nor a "
                   f"registered lens",
                   fix={"action": "install-vocabulary", "kind": "lens", "name": str(lens_kind)})
        _check_vocab_version(f"lens/{lens_kind}", vocab_versions,
                             registry.lenses[lens_kind].version)

    strategies: dict[str, object] = {}
    for role, s in (entry.get("strategies") or {}).items():
        where = f"strategies[{role!r}]"
        if not isinstance(s, dict):
            refuse("entry-malformed", f"{where}: must be an object",
                   fix={"action": "edit-entry", "path": where})
        if "use" in s:
            name = s["use"]
            if name not in registry.strategies:
                refuse("unknown-strategy", f"{where}: strategy {name!r} is not registered",
                       fix={"action": "install-vocabulary", "kind": "strategy", "name": str(name)})
            _check_vocab_version(f"strategy/{name}", vocab_versions,
                                 registry.strategies[name].version)
            options = dict(s.get("options", {}))
            registry.strategy(name, options, where=where)  # resolve at load (§6)
            strategies[role] = {"use": name, "options": options}
        else:
            strategies[role] = Strategy.from_dict(s, where=where)

    formats: dict[str, object] = {}
    for key, f in (entry.get("formats") or {}).items():
        where = f"formats[{key!r}]"
        if not isinstance(f, dict):
            refuse("entry-malformed", f"{where}: must be an object",
                   fix={"action": "edit-entry", "path": where})
        if "use" in f:
            name = f["use"]
            if name not in registry.formats:
                refuse("unknown-format", f"{where}: format {name!r} is not registered",
                       fix={"action": "install-vocabulary", "kind": "format", "name": str(name)})
            _check_vocab_version(f"format/{name}", vocab_versions,
                                 registry.formats[name].version)
            options = dict(f.get("options", {}))
            registry.named_format(name, options, where=where)  # resolve at load (§5)
            formats[key] = {"use": name, "options": options}
        elif "language" in f:
            for req in ("write", "sha256"):
                if req not in f:
                    refuse("entry-malformed", f"{where}: a shipped format needs {req!r}",
                           fix={"action": "edit-entry", "path": f"{where}.{req}"})
            if not registry.allow_udf:
                refuse("format-untrusted",
                       f"{where}: the artifact ships a {f['language']} UDF and this runtime "
                       f"will not place code (Registry(allow_udf=True) to allow)",
                       fix={"action": "place-udf", "language": str(f["language"]), "path": where})
            formats[key] = _formats.load_udf(f, where=where)
            formats[key].shipped = dict(f)  # kept whole for dump
        else:
            refuse("entry-malformed", f"{where}: a format entry is {{use}} or a shipped UDF",
                   fix={"action": "edit-entry", "path": where})

    adp = make_adapter(messages=template, parse=parse_spec, strategies=strategies,
                        formats=formats, name=entry.get("name", "adapter"),
                        extensions=entry.get("extensions"), declare_defaults=False)
    _extensions.resolve(adp, registry)   # kernel §10: refuse here, before any plan
    return adp


# ---------------------------------------------------------------------- dump


def dump(adp: Adapter, registry) -> dict:
    vocab: dict[str, str] = {}
    strategies: dict[str, dict] = {}
    for role, binding in adp.strategies.items():
        if isinstance(binding, Strategy):
            strategies[role] = binding.to_dict()
        else:
            named = registry.strategies.get(binding["use"])
            if named is None:
                refuse("unknown-strategy",
                       f"cannot dump: strategy {binding['use']!r} is not registered "
                       f"(its version is part of the artifact)",
                       fix={"action": "install-vocabulary", "kind": "strategy", "name": binding["use"]})
            vocab[f"strategy/{binding['use']}"] = named.version
            strategies[role] = _ref(binding)
    formats: dict[str, dict] = {}
    for key, binding in adp.formats.items():
        if isinstance(binding, dict) and "use" in binding:
            named = registry.formats.get(binding["use"])
            if named is None:
                refuse("unknown-format", f"cannot dump: format {binding['use']!r} is not registered",
                       fix={"action": "install-vocabulary", "kind": "format", "name": binding["use"]})
            vocab[f"format/{binding['use']}"] = named.version
            formats[key] = _ref(binding)
        elif isinstance(binding, dict):
            formats[key] = dict(binding)
        elif getattr(binding, "shipped", None) is not None:
            formats[key] = dict(binding.shipped)
        else:
            formats[key] = _formats.ship(binding)
    lens_kind = adp.parse.get("kind")
    if lens_kind != "derived":
        named = registry.lenses.get(lens_kind)
        if named is None:
            refuse("unknown-parse-kind",
                   f"cannot dump: lens {lens_kind!r} is not registered (its version is "
                   f"part of the artifact)",
                   fix={"action": "install-vocabulary", "kind": "lens", "name": str(lens_kind)})
        vocab[f"lens/{lens_kind}"] = named.version
    entry: dict = {
        "name": adp.name,
        "versions": {"kernel": KERNEL_VERSION, "vocab": vocab},
        "template": [dict(m) for m in adp.template],
        "parse": dict(adp.parse),
    }
    if adp.extensions:
        entry = {**{k: v for k, v in entry.items() if k in ("name", "versions")},
                 "extensions": dict(adp.extensions),
                 **{k: v for k, v in entry.items() if k not in ("name", "versions")}}
    if strategies:
        entry["strategies"] = strategies
    if formats:
        entry["formats"] = formats
    return entry


def _ref(binding: dict) -> dict:
    out = {"use": binding["use"]}
    if binding.get("options"):
        out["options"] = dict(binding["options"])
    return out

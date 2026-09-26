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
from .transport import Transport, spelling_format_refs

KERNEL_VERSION = "0.8.3"


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
    for key in ("template", "reader", "versions"):
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

    reader_spec = entry["reader"]
    if not isinstance(reader_spec, dict):
        refuse("entry-malformed", "entry.reader must be an object", fix={"action": "edit-entry", "path": "reader"})
    reader_kind = reader_spec.get("kind")
    if reader_kind != "derived":
        if reader_kind not in registry.readers:
            refuse("unknown-reader",
                   f"reader.kind {reader_kind!r} is neither the kernel reader 'derived' nor a "
                   f"registered reader",
                   fix={"action": "install-vocabulary", "kind": "reader", "name": str(reader_kind)})
        _check_vocab_version(f"reader/{reader_kind}", vocab_versions,
                             registry.readers[reader_kind].version)

    transports: dict[str, object] = {}
    for purpose, s in (entry.get("transports") or {}).items():
        where = f"transports[{purpose!r}]"
        if not isinstance(s, dict):
            refuse("entry-malformed", f"{where}: must be an object",
                   fix={"action": "edit-entry", "path": where})
        if "use" in s:
            name = s["use"]
            if name not in registry.transports:
                refuse("unknown-transport", f"{where}: transport {name!r} is not registered",
                       fix={"action": "install-vocabulary", "kind": "transport", "name": str(name)})
            _check_vocab_version(f"transport/{name}", vocab_versions,
                                 registry.transports[name].version)
            options = dict(s.get("options", {}))
            registry.transport(name, options, where=where)  # resolve at load (§6)
            transports[purpose] = {"use": name, "options": options}
        else:
            transports[purpose] = Transport.from_dict(s, where=where)

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
            formats[key] = {**f, "options": options}   # the constructor checks the keys
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
        elif "describe" in f:
            formats[key] = dict(f)          # a description (§5); the constructor checks it
        else:
            refuse("entry-malformed", f"{where}: a format entry is {{use}}, a shipped UDF, "
                                      f"or a description {{describe}}",
                   fix={"action": "edit-entry", "path": where})

    adp = make_adapter(messages=template, reader=reader_spec, transports=transports,
                        formats=formats, name=entry.get("name", "adapter"),
                        extensions=entry.get("extensions"),
                        replay=entry.get("replay", "recorded"), strict=entry.get("strict", False),
                       declare_defaults=False)
    _extensions.resolve(adp, registry)   # kernel §10: refuse here, before any plan
    for where, ref in spelling_format_refs(adp, registry):
        registry.named_format(ref["use"], ref.get("options"), where=where)
        _check_vocab_version(f"format/{ref['use']}", vocab_versions, registry.formats[ref["use"]].version)
    return adp


# ---------------------------------------------------------------------- dump


def dump(adp: Adapter, registry) -> dict:
    vocab: dict[str, str] = {}
    transports: dict[str, dict] = {}
    for purpose, binding in adp.transports.items():
        if isinstance(binding, Transport):
            transports[purpose] = binding.to_dict()
        else:
            named = registry.transports.get(binding["use"])
            if named is None:
                refuse("unknown-transport",
                       f"cannot dump: transport {binding['use']!r} is not registered "
                       f"(its version is part of the artifact)",
                       fix={"action": "install-vocabulary", "kind": "transport", "name": binding["use"]})
            vocab[f"transport/{binding['use']}"] = named.version
            transports[purpose] = _ref(binding)
    for where, ref in spelling_format_refs(adp, registry):
        registry.named_format(ref["use"], ref.get("options"), where=where)
        vocab[f"format/{ref['use']}"] = registry.formats[ref["use"]].version
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
    reader_kind = adp.reader.get("kind")
    if reader_kind != "derived":
        named = registry.readers.get(reader_kind)
        if named is None:
            refuse("unknown-reader",
                   f"cannot dump: reader {reader_kind!r} is not registered (its version is "
                   f"part of the artifact)",
                   fix={"action": "install-vocabulary", "kind": "reader", "name": str(reader_kind)})
        vocab[f"reader/{reader_kind}"] = named.version
    entry: dict = {
        "name": adp.name,
        "versions": {"kernel": KERNEL_VERSION, "vocab": vocab},
        "template": [dict(m) for m in adp.template],
        "reader": dict(adp.reader),
    }
    if adp.extensions:
        entry = {**{k: v for k, v in entry.items() if k in ("name", "versions")},
                 "extensions": dict(adp.extensions),
                 **{k: v for k, v in entry.items() if k not in ("name", "versions")}}
    if adp.replay != "recorded":
        entry["replay"] = adp.replay
    if adp.strict:
        entry["strict"] = True
    if transports:
        entry["transports"] = transports
    if formats:
        entry["formats"] = formats
    return entry


def _ref(binding: dict) -> dict:
    out = {"use": binding["use"]}
    if binding.get("options"):
        out["options"] = dict(binding["options"])
    if "describe" in binding:
        out["describe"] = binding["describe"]
    return out

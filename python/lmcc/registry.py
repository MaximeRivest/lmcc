"""The sockets: where everything with an opinion plugs in.

The kernel ships no formats beyond its scalar/media defaults and no
transports. This module defines what a runtime registers:

- **named formats**: ``factory(options) -> Format`` under a name the
  artifact can reference (``{"use": "json"}``), with a version;
- **host types**: a host type → its format (or a named format), the
  shape it lowers to, and its JSON form both ways (``to_json``,
  ``from_json``), per runtime, never serialized — the
  ``lmcc.format(Person, ...)`` surface;
- **transports**: named factories ``factory(options) -> Transport``;
- **readers**: named factories ``factory(reader_spec) -> Reader``
  (``derived`` is kernel grammar, never registered).

``allow_udf`` decides whether this runtime will place shipped Python
UDFs from artifacts. ``extensions`` are the execution contracts this
runtime binds (kernel §10): by default the kernel's native ones, or
exactly the names you pass (``()`` for a core-only host). Registries are
explicit objects; nothing reads ``default_registry`` implicitly during
``load``.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import core
from .errors import Refusal, refuse
from .extensions import ExtensionBinding, native_extensions
from .formats import Format, make
from .reader import Reader
from .transport import Transport


@dataclass
class _Named:
    factory: object
    version: str


@dataclass
class HostType:
    """How one host type crosses in this runtime (never serialized): the
    format bound to it (``None``: its shape's format resolves as usual), the
    shape it lowers to (``None``: lowered as the language's own construct,
    else ``{}``), and its JSON form, both ways (kernel §3a: a turn holds
    JSON; a host lifts it back to its own types)."""
    host_type: object
    binding: "Format | dict | None" = None
    shape: dict | None = None
    to_json: object = None
    from_json: object = None


class Registry:
    def __init__(self, *, allow_udf: bool = False,
                 extensions: "list[str] | tuple[str, ...] | None" = None) -> None:
        self.formats: dict[str, _Named] = {}
        self.host_types: list[HostType] = []
        self.transports: dict[str, _Named] = {}
        self.readers: dict[str, _Named] = {}
        self.allow_udf = allow_udf
        self.extensions: dict[str, ExtensionBinding] = {}
        natives = {b.extension: b for b in native_extensions()}
        for name in (natives if extensions is None else extensions):
            if name not in natives:
                raise ValueError(f"no native binding for extension {name!r}; "
                                 f"use register_extension(...) with your own")
            self.extensions[name] = natives[name]

    # --------------------------------------------------------- extensions

    def register_extension(self, binding: ExtensionBinding, *, exist_ok: bool = False) -> None:
        """Bind an implementation of ``binding.extension`` in this runtime.
        A table entry: nothing runs, nothing starts."""
        if binding.extension in self.extensions and not exist_ok:
            refuse("already-registered", f"extension {binding.extension!r} is already bound")
        self.extensions[binding.extension] = binding

    # ------------------------------------------------------------ formats

    def register_format(self, name: str, factory, *, version: str = "0.1.0",
                        exist_ok: bool = False) -> None:
        if name in self.formats and not exist_ok:
            refuse("already-registered", f"format {name!r} is already registered")
        self.formats[name] = _Named(factory, version)

    def named_format(self, name: str, options: dict | None, *,
                     where: str | None = None) -> Format:
        """Resolve a ``{"use": name, "options"}`` reference. A factory that
        fails is a defect of the artifact (kernel §5): ``entry-malformed``
        at ``where`` (the reference's path), never a host exception."""
        entry = self.formats.get(name)
        if entry is None:
            refuse("unknown-format",
                   f"format {name!r} is not registered — install the package that "
                   f"provides it, or ship the format with the artifact",
                   fix={"action": "install-vocabulary", "kind": "format", "name": name})
        where = where or f"format {name!r}"
        try:
            fmt = entry.factory(options or {})
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001 — the socket owns this boundary
            refuse("entry-malformed", f"{where}: format {name!r} rejects its options: {exc}",
                   fix={"action": "edit-entry", "path": where})
        if not isinstance(fmt, Format):
            refuse("entry-malformed", f"{where}: format {name!r} returned {type(fmt).__name__}, not a Format",
                   fix={"action": "edit-entry", "path": where})
        fmt.name = name
        return fmt

    def format(self, host_type, *, write=None, read=None, describe=None,
               use: str | None = None, options: dict | None = None, shape: dict | None = None,
               to_json=None, from_json=None, **facts) -> Format | None:
        """Bind a host type, per runtime — ``lmcc.format(Person,
        write=..., read=...)`` or ``lmcc.format(pd.DataFrame, use="table",
        options={...})``. Never serialized; ``ship`` does that on request.

        ``shape``: the JSON-Schema dict the type lowers to in signatures
        built with this registry. Without it, a type the kernel lowers
        itself (a scalar, list, dict, Literal, Enum or dataclass) is lowered
        as usual, and any other type lowers to ``{}`` — structured, contents
        unknown, so the bound format carries it (kernel §1, §5).

        ``to_json(value) -> JSON`` and ``from_json(data) -> value``: the
        type's JSON form in that shape, both ways. A turn holds it
        (``lmcc.turn.to_json``), ``plan.load_turn`` rebuilds the value from
        it (``lmcc.turn.lift``), and every format but the one bound here
        receives it, so the format bound here always receives the type
        itself, live or replayed. Without them, a dataclass or a pydantic
        model (``model_dump``/``model_validate``) crosses as before.

        With neither ``write`` nor ``use``, no format is bound: the type
        crosses by the format its shape resolves (a media shape: the
        kernel's media default). Binding the same type again replaces its
        binding. Returns the bound format, or ``None``."""
        if shape is not None and not isinstance(shape, dict):
            refuse("unmapped-type", f"{core.typename(host_type)}: shape must be a JSON-Schema dict",
                   fix={"action": "edit-signature"})
        for name, hook in (("to_json", to_json), ("from_json", from_json)):
            if hook is not None and not callable(hook):
                refuse("entry-malformed", f"{core.typename(host_type)}: {name} must be a function",
                       fix={"action": "edit-entry", "path": name})
        binding: Format | dict | None
        if use is not None:
            binding = {"use": use, "options": options or {}}
        elif write is not None:
            binding = make(write=write, read=read, describe=describe, **facts)
        elif read is not None or describe is not None or facts or options is not None or (
                shape is None and to_json is None and from_json is None):
            refuse("entry-malformed", "a format needs at least write",
                   fix={"action": "edit-entry", "path": "write"})
        else:
            binding = None
        record = HostType(host_type, binding, dict(shape) if shape is not None else None,
                          to_json, from_json)
        for i, known in enumerate(self.host_types):
            if known.host_type is host_type:
                self.host_types[i] = record      # bound again: the new binding replaces it
                break
        else:
            self.host_types.append(record)
        if binding is None:
            return None
        return binding if isinstance(binding, Format) else self.named_format(use, options)

    @staticmethod
    def _matches(annotation: object, host_type: object) -> bool:
        return annotation is host_type or annotation == host_type or (
            isinstance(annotation, type) and isinstance(host_type, type)
            and issubclass(annotation, host_type))

    def host(self, annotation: object) -> HostType | None:
        """The binding of a host type (or of a class it derives from), or None."""
        if annotation is None:
            return None
        return next((h for h in self.host_types if self._matches(annotation, h.host_type)), None)

    def to_json_hook(self, value: object):
        """The ``to_json`` bound to a value's type (by ``isinstance``), or None."""
        if type(value) in _PLAIN:
            return None
        return next((h.to_json for h in self.host_types if h.to_json is not None
                     and isinstance(h.host_type, type) and isinstance(value, h.host_type)), None)

    def from_json_hook(self, annotation: object):
        """The ``from_json`` bound to a host type (or a class it derives from), or None."""
        if annotation is None:
            return None
        return next((h.from_json for h in self.host_types if h.from_json is not None
                     and self._matches(annotation, h.host_type)), None)

    def declared_shape(self, annotation: object) -> dict | None:
        """The shape a host type was bound with, or None when none was given."""
        h = self.host(annotation)
        return dict(h.shape) if h is not None and h.shape is not None else None

    def shape_of(self, annotation: object) -> dict | None:
        """The shape a bound host type lowers to (``{}`` when it was bound
        without one), or None when it is not bound."""
        h = self.host(annotation)
        if h is None:
            return None
        return dict(h.shape) if h.shape is not None else {}

    def type_binding(self, annotation: object) -> Format | None:
        h = next((h for h in self.host_types if h.binding is not None
                  and annotation is not None and self._matches(annotation, h.host_type)), None)
        if h is None:
            return None
        if isinstance(h.binding, dict):
            return self.named_format(h.binding["use"], h.binding.get("options"))
        return h.binding

    # ---------------------------------------------------------- transports

    def register_transport(self, name: str, factory, *, version: str = "0.1.0",
                          exist_ok: bool = False) -> None:
        if name in self.transports and not exist_ok:
            refuse("already-registered", f"transport {name!r} is already registered")
        self.transports[name] = _Named(factory, version)

    def transport(self, name: str, options: dict | None, *, where: str | None = None):
        """Resolve a ``{"use": name, "options"}`` reference. What the factory
        returns is checked by the kernel's own rules exactly as inline data
        (kernel §6): a pack has no privilege. A failing factory or a
        malformed result is ``entry-malformed`` at ``where``."""
        entry = self.transports.get(name)
        if entry is None:
            refuse("unknown-transport",
                   f"transport {name!r} is not registered — install the package that "
                   f"provides it, or inline the transport as data",
                   fix={"action": "install-vocabulary", "kind": "transport", "name": name})
        where = where or f"transport {name!r}"
        try:
            transport = entry.factory(options or {})
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001 — the socket owns this boundary
            refuse("entry-malformed", f"{where}: transport {name!r} rejects its options: {exc}",
                   fix={"action": "edit-entry", "path": where})
        if not isinstance(transport, Transport):
            refuse("entry-malformed",
                   f"{where}: transport {name!r} returned {type(transport).__name__}, not a Transport",
                   fix={"action": "edit-entry", "path": where})
        try:
            transport.validate(where=where)
        except Refusal as r:
            if r.code != "entry-malformed":
                raise
            refuse("entry-malformed", f"{where}: transport {name!r} built malformed data — {r.hint}",
                   fix={"action": "edit-entry", "path": where})
        return transport

    # -------------------------------------------------------------- readers

    def register_reader(self, name: str, factory, *, version: str = "0.1.0",
                      exist_ok: bool = False) -> None:
        if name == "derived":
            refuse("already-registered", "reader 'derived' is kernel grammar and cannot be replaced")
        if name in self.readers and not exist_ok:
            refuse("already-registered", f"reader {name!r} is already registered")
        self.readers[name] = _Named(factory, version)

    def reader(self, spec: dict) -> Reader:
        kind = spec.get("kind")
        entry = self.readers.get(kind)
        if entry is None:
            refuse("unknown-reader",
                   f"reader kind {kind!r} is neither the kernel reader 'derived' nor a "
                   f"registered reader — install the package that provides it",
                   fix={"action": "install-vocabulary", "kind": "reader", "name": str(kind)})
        try:
            reader = entry.factory(spec)
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001 — the socket owns this boundary
            refuse("entry-malformed", f"reader: {kind!r} rejects its spec: {exc}",
                   fix={"action": "edit-entry", "path": "reader"})
        if not isinstance(reader, Reader):
            refuse("entry-malformed", f"reader: {kind!r} built {type(reader).__name__}, not a Reader",
                   fix={"action": "edit-entry", "path": "reader"})
        return reader

    # ------------------------------------------------------------ describe

    def describe(self) -> dict:
        return {
            "formats": {n: e.version for n, e in sorted(self.formats.items())},
            "type_bindings": [
                {"type": core.typename(h.host_type),
                 "format": (None if h.binding is None else h.binding["use"]
                            if isinstance(h.binding, dict) else h.binding.name or "(inline)"),
                 "shape": h.shape if h.shape is not None else {},
                 "json": [k for k in ("to_json", "from_json") if getattr(h, k) is not None]}
                for h in self.host_types],
            "transports": {n: e.version for n, e in sorted(self.transports.items())},
            "readers": {"derived": "kernel",
                       **{n: e.version for n, e in sorted(self.readers.items())}},
            "allow_udf": self.allow_udf,
            "extensions": {n: b.describe() for n, b in sorted(self.extensions.items())},
        }


_PLAIN = (type(None), str, int, float, bool, list, dict, tuple)

default_registry = Registry()

__all__ = ["HostType", "Registry", "default_registry", "Format"]

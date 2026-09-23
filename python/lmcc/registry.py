"""The sockets: where everything with an opinion plugs in.

The kernel ships no formats beyond its scalar/media defaults and no
transports. This module defines what a runtime registers:

- **named formats**: ``factory(options) -> Format`` under a name the
  artifact can reference (``{"use": "json"}``), with a version;
- **type bindings**: a host type → a Format (or a named format), per
  runtime, never serialized — the ``lmcc.format(Person, ...)`` surface;
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


class Registry:
    def __init__(self, *, allow_udf: bool = False,
                 extensions: "list[str] | tuple[str, ...] | None" = None) -> None:
        self.formats: dict[str, _Named] = {}
        self.type_bindings: list[tuple[object, Format | dict]] = []
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
               use: str | None = None, options: dict | None = None, **facts) -> Format:
        """Bind a host type to a format, per runtime — ``lmcc.format(Person,
        write=..., read=...)`` or ``lmcc.format(pd.DataFrame, use="table",
        options={...})``. Never serialized; ``ship`` does that on request."""
        if use is not None:
            binding: Format | dict = {"use": use, "options": options or {}}
        else:
            if write is None:
                refuse("entry-malformed", "a format needs at least write",
                       fix={"action": "edit-entry", "path": "write"})
            binding = make(write=write, read=read, describe=describe, **facts)
        self.type_bindings.append((host_type, binding))
        return binding if isinstance(binding, Format) else self.named_format(use, options)

    def type_binding(self, annotation: object) -> Format | None:
        if annotation is None:
            return None
        for host_type, binding in self.type_bindings:
            if annotation is host_type or annotation == host_type or (
                    isinstance(annotation, type) and isinstance(host_type, type)
                    and issubclass(annotation, host_type)):
                if isinstance(binding, dict):
                    return self.named_format(binding["use"], binding.get("options"))
                return binding
        return None

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
        return entry.factory(spec)

    # ------------------------------------------------------------ describe

    def describe(self) -> dict:
        return {
            "formats": {n: e.version for n, e in sorted(self.formats.items())},
            "type_bindings": [
                {"type": core.typename(t), "format": (b["use"] if isinstance(b, dict)
                                                     else b.name or "(inline)")}
                for t, b in self.type_bindings],
            "transports": {n: e.version for n, e in sorted(self.transports.items())},
            "readers": {"derived": "kernel",
                       **{n: e.version for n, e in sorted(self.readers.items())}},
            "allow_udf": self.allow_udf,
            "extensions": {n: b.describe() for n, b in sorted(self.extensions.items())},
        }


default_registry = Registry()

__all__ = ["Registry", "default_registry", "Format"]

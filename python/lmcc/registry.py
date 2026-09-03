"""The sockets: where everything with an opinion plugs in.

The kernel ships no formats beyond its scalar/media defaults and no
strategies. This module defines what a runtime registers:

- **named formats**: ``factory(options) -> Format`` under a name the
  artifact can reference (``{"use": "json"}``), with a version;
- **type bindings**: a host type → a Format (or a named format), per
  runtime, never serialized — the ``lmcc.format(Person, ...)`` surface;
- **strategies**: named factories ``factory(options) -> Strategy``;
- **lenses**: named factories ``factory(parse_spec) -> Lens``
  (``derived`` is kernel grammar, never registered).

``allow_udf`` decides whether this runtime will place shipped Python
UDFs from artifacts. Registries are explicit objects; nothing reads
``default_registry`` implicitly during ``load``.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import core
from .errors import refuse
from .formats import Format, make
from .parse import Lens


@dataclass
class _Named:
    factory: object
    version: str


class Registry:
    def __init__(self, *, allow_udf: bool = False) -> None:
        self.formats: dict[str, _Named] = {}
        self.type_bindings: list[tuple[object, Format | dict]] = []
        self.strategies: dict[str, _Named] = {}
        self.lenses: dict[str, _Named] = {}
        self.allow_udf = allow_udf

    # ------------------------------------------------------------ formats

    def register_format(self, name: str, factory, *, version: str = "0.1.0",
                        exist_ok: bool = False) -> None:
        if name in self.formats and not exist_ok:
            refuse("already-registered", f"format {name!r} is already registered")
        self.formats[name] = _Named(factory, version)

    def named_format(self, name: str, options: dict | None) -> Format:
        entry = self.formats.get(name)
        if entry is None:
            refuse("unknown-format",
                   f"format {name!r} is not registered — install the package that "
                   f"provides it, or ship the format with the artifact")
        fmt = entry.factory(options or {})
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
                refuse("entry-malformed", "a format needs at least write")
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

    # ---------------------------------------------------------- strategies

    def register_strategy(self, name: str, factory, *, version: str = "0.1.0",
                          exist_ok: bool = False) -> None:
        if name in self.strategies and not exist_ok:
            refuse("already-registered", f"strategy {name!r} is already registered")
        self.strategies[name] = _Named(factory, version)

    def strategy(self, name: str, options: dict | None):
        entry = self.strategies.get(name)
        if entry is None:
            refuse("unknown-strategy",
                   f"strategy {name!r} is not registered — install the package that "
                   f"provides it, or inline the strategy as data")
        return entry.factory(options or {})

    # -------------------------------------------------------------- lenses

    def register_lens(self, name: str, factory, *, version: str = "0.1.0",
                      exist_ok: bool = False) -> None:
        if name == "derived":
            refuse("already-registered", "lens 'derived' is kernel grammar and cannot be replaced")
        if name in self.lenses and not exist_ok:
            refuse("already-registered", f"lens {name!r} is already registered")
        self.lenses[name] = _Named(factory, version)

    def lens(self, spec: dict) -> Lens:
        kind = spec.get("kind")
        entry = self.lenses.get(kind)
        if entry is None:
            refuse("unknown-parse-kind",
                   f"parse kind {kind!r} is neither the kernel lens 'derived' nor a "
                   f"registered lens — install the package that provides it")
        return entry.factory(spec)

    # ------------------------------------------------------------ describe

    def describe(self) -> dict:
        return {
            "formats": {n: e.version for n, e in sorted(self.formats.items())},
            "type_bindings": [
                {"type": core.typename(t), "format": (b["use"] if isinstance(b, dict)
                                                     else b.name or "(inline)")}
                for t, b in self.type_bindings],
            "strategies": {n: e.version for n, e in sorted(self.strategies.items())},
            "lenses": {"derived": "kernel",
                       **{n: e.version for n, e in sorted(self.lenses.items())}},
            "allow_udf": self.allow_udf,
        }


default_registry = Registry()

__all__ = ["Registry", "default_registry", "Format"]

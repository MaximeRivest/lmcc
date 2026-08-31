"""The sockets: where everything with an opinion plugs in.

The kernel ships zero codecs, zero strategies, zero host types. This module
defines the sockets they plug into:

- **codecs**: named factories ``factory(options) -> Codec`` with a version.
- **strategies**: named factories ``factory(options) -> Strategy``.
- **coercions**: named functions used by routings.
- **hosts**: your language's types ⇄ plain data (the native face).

Registries are explicit objects. ``default_registry`` exists for
convenience, but nothing in the kernel reads it implicitly during
``load`` — you always know which registry resolved a name.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import refuse


class Codec:
    """The codec protocol. Vocabulary packages subclass this.

    A codec spells one plain-data value into token text and reads it back.
    It never sees host types and never decides *where* it renders — the
    template owns position; the codec owns spelling.
    """

    def render_schema(self, shape: dict) -> str:
        """What the model is told about the expected form. Optional."""
        return ""

    def render_value(self, value: object, shape: dict) -> str:
        raise NotImplementedError

    def parse_value(self, text: str, shape: dict) -> object:
        raise NotImplementedError


@dataclass
class HostEntry:
    shape: dict
    lower: object  # callable(host_value) -> plain value
    lift: object | None = None  # callable(plain value) -> host value


@dataclass
class _Named:
    factory: object
    version: str


class Registry:
    def __init__(self) -> None:
        self.codecs: dict[str, _Named] = {}
        self.strategies: dict[str, _Named] = {}
        self.coercions: dict[str, object] = {}
        self.hosts: list[tuple[type, HostEntry]] = []

    # ------------------------------------------------------------- codecs

    def register_codec(self, name: str, factory, *, version: str = "0.1.0",
                       exist_ok: bool = False) -> None:
        if name in self.codecs and not exist_ok:
            refuse("already-registered", f"codec {name!r} is already registered")
        self.codecs[name] = _Named(factory, version)

    def codec(self, name: str, options: dict) -> Codec:
        entry = self.codecs.get(name)
        if entry is None:
            refuse("unknown-codec",
                   f"codec {name!r} is not registered — install the package "
                   f"that provides it, or bind another codec")
        return entry.factory(options or {})

    # ---------------------------------------------------------- strategies

    def register_strategy(self, name: str, factory, *, version: str = "0.1.0",
                          exist_ok: bool = False) -> None:
        if name in self.strategies and not exist_ok:
            refuse("already-registered", f"strategy {name!r} is already registered")
        self.strategies[name] = _Named(factory, version)

    def strategy(self, name: str, options: dict):
        entry = self.strategies.get(name)
        if entry is None:
            refuse("unknown-strategy",
                   f"strategy {name!r} is not registered — install the package "
                   f"that provides it, or inline the strategy as data")
        return entry.factory(options or {})

    # ----------------------------------------------------------- coercions

    def register_coercion(self, name: str, fn, *, exist_ok: bool = False) -> None:
        if name in self.coercions and not exist_ok:
            refuse("already-registered", f"coercion {name!r} is already registered")
        self.coercions[name] = fn

    # --------------------------------------------------------------- hosts

    def register_host(self, host_type: type, *, shape: dict, lower, lift=None) -> None:
        self.hosts.append((host_type, HostEntry(shape, lower, lift)))

    def host_for(self, annotation: object) -> HostEntry | None:
        for host_type, entry in self.hosts:
            if annotation is host_type or (
                    isinstance(annotation, type) and isinstance(host_type, type)
                    and issubclass(annotation, host_type)):
                return entry
        return None

    def lower_value(self, annotation: object, value: object) -> object:
        entry = self.host_for(annotation) if annotation is not None else None
        if entry is not None:
            return entry.lower(value)
        return value

    def lift_value(self, annotation: object, value: object) -> object:
        entry = self.host_for(annotation) if annotation is not None else None
        if entry is not None and entry.lift is not None:
            return entry.lift(value)
        return value


default_registry = Registry()

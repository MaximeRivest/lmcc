"""The sockets: where everything with an opinion plugs in.

The kernel ships zero codecs, zero strategies, zero host types. This module
defines the sockets they plug into:

- **codecs**: named factories ``factory(options) -> Codec`` with a version.
- **strategies**: named factories ``factory(options) -> Strategy``.
- **lenses**: named factories ``factory(parse_spec) -> Lens``. The kernel
  lens ``sections`` is grammar (always available, never registered);
  every other lens kind is vocabulary and plugs in here.
- **coercions**: named functions used by routings.
- **hosts**: your language's types ⇄ plain data (the native face).

Registries are explicit objects. ``default_registry`` exists for
convenience, but nothing in the kernel reads it implicitly during
``load`` — you always know which registry resolved a name.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

from .errors import refuse
from .parse import Lens, SectionsLens


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
    codec: dict | None = None  # default spelling: {"kind": ..., "options": {}}


@dataclass
class _Named:
    factory: object
    version: str


class Registry:
    def __init__(self) -> None:
        self.codecs: dict[str, _Named] = {}
        self.strategies: dict[str, _Named] = {}
        self.lenses: dict[str, _Named] = {}
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

    # -------------------------------------------------------------- lenses

    def register_lens(self, name: str, factory, *, version: str = "0.1.0",
                      exist_ok: bool = False) -> None:
        if name == "sections":
            refuse("already-registered",
                   "lens 'sections' is kernel grammar and cannot be replaced")
        if name in self.lenses and not exist_ok:
            refuse("already-registered", f"lens {name!r} is already registered")
        self.lenses[name] = _Named(factory, version)

    def lens(self, spec: dict) -> Lens:
        kind = spec.get("kind")
        if kind == "sections":
            return SectionsLens(spec)
        entry = self.lenses.get(kind)
        if entry is None:
            refuse("unknown-parse-kind",
                   f"parse kind {kind!r} is neither the kernel lens "
                   f"'sections' nor a registered lens — install the package "
                   f"that provides it")
        return entry.factory(spec)

    # ----------------------------------------------------------- coercions

    def register_coercion(self, name: str, fn, *, exist_ok: bool = False) -> None:
        if name in self.coercions and not exist_ok:
            refuse("already-registered", f"coercion {name!r} is already registered")
        self.coercions[name] = fn

    # --------------------------------------------------------------- hosts

    def register_host(self, host_type: type, *, shape: dict, lower, lift=None,
                      codec: str | dict | None = None) -> None:
        """Bind a native type: its neutral shape, how a value lowers to
        plain data (and lifts back), and optionally its default codec —
        the renderer that spells it for the model when the entry binds
        none. Host bindings are per-runtime code and are never
        serialized; only shapes and codec names travel in artifacts."""
        if isinstance(codec, str):
            codec = {"kind": codec, "options": {}}
        elif isinstance(codec, dict) and "kind" not in codec:
            refuse("entry-malformed",
                   f"host {host_type!r}: codec binding needs a 'kind'")
        self.hosts.append((host_type, HostEntry(shape, lower, lift, codec)))

    def host_for(self, annotation: object) -> HostEntry | None:
        for host_type, entry in self.hosts:
            if annotation is host_type or (
                    isinstance(annotation, type) and isinstance(host_type, type)
                    and issubclass(annotation, host_type)):
                return entry
        return None

    @staticmethod
    def _item_annotation(annotation: object) -> object | None:
        """The element annotation of ``list[X]``, else None."""
        if typing.get_origin(annotation) in (list, typing.List):
            args = typing.get_args(annotation)
            if args:
                return args[0]
        return None

    def lower_value(self, annotation: object, value: object) -> object:
        item = self._item_annotation(annotation)
        if item is not None and isinstance(value, list):
            return [self.lower_value(item, v) for v in value]
        entry = self.host_for(annotation) if annotation is not None else None
        if entry is not None:
            return entry.lower(value)
        return value

    def lift_value(self, annotation: object, value: object) -> object:
        item = self._item_annotation(annotation)
        if item is not None and isinstance(value, list):
            return [self.lift_value(item, v) for v in value]
        entry = self.host_for(annotation) if annotation is not None else None
        if entry is not None and entry.lift is not None:
            return entry.lift(value)
        return value

    def default_codec_for(self, annotation: object) -> dict | None:
        """The registered type's default codec binding, looking through
        ``list[X]`` to the element type."""
        entry = self.host_for(annotation) if annotation is not None else None
        if entry is None:
            item = self._item_annotation(annotation)
            if item is not None:
                entry = self.host_for(item)
        return entry.codec if entry is not None else None


default_registry = Registry()

"""Formats: how a type is written and read (kernel §5).

A format is ``write(value, field) → parts`` (text is a part),
``read(capture, field) → value``, and optionally ``describe(field) → text``.
It declares what it ``accepts`` (type names, structural keys, ``*``), its
``direction``, what it ``writes`` (``text`` or ``parts``), and whether it
round-trips.

This module holds the protocol, the **kernel defaults** (scalars, enums,
nullables by §7a; media parts pass-through), the structural-key
derivation used by resolution, and the shipping/admission machinery for
UDF formats (source carried whole with language, deps, hash, author;
never run by the loader — see ``Registry.allow_udf``).
"""

from __future__ import annotations

import builtins
import dis
import enum
import hashlib
import inspect
import textwrap
import types

from . import core
from .errors import refuse

STRUCTURAL_SCALARS = core.STRUCTURAL_SCALARS


class Format:
    """The format protocol. Subclass, or build one with :func:`make`."""

    name: str | None = None          # the registered name, for named formats
    accepts: tuple[str, ...] = ("*",)
    direction: str = "both"          # "in" | "out" | "both"
    writes: str = "text"              # "text" | "parts"
    round_trip: bool = True
    reads: tuple[str, ...] = ("text",)   # capture kinds `read` accepts

    def describe(self, field: core.Field) -> str | None:
        return None

    def write(self, value: object, field: core.Field) -> object:
        raise NotImplementedError

    def read(self, capture: core.Capture, field: core.Field) -> object:
        raise NotImplementedError

    # -- introspection ----------------------------------------------------
    def describe_self(self) -> dict:
        return {"name": self.name, "accepts": list(self.accepts),
                "direction": self.direction, "writes": self.writes,
                "round_trip": self.round_trip}


def make(*, write, read=None, describe=None, accepts=("*",), direction=None,
         writes="text", round_trip=True, reads=("text",), name=None) -> Format:
    """Build a format from functions — the ``lmcc.format(...)`` surface."""
    if direction is None:
        direction = "both" if read is not None else "in"

    class _Fn(Format):
        pass

    f = _Fn()
    f.name = name
    f.accepts = tuple(accepts) if not isinstance(accepts, str) else (accepts,)
    f.direction, f.writes, f.round_trip, f.reads = direction, writes, round_trip, tuple(reads)
    f._write, f._read, f._describe = write, read, describe
    f.write = lambda value, field: write(value) if _arity(write) == 1 else write(value, field)
    if read is not None:
        f.read = lambda capture, field: read(capture) if _arity(read) == 1 else read(capture, field)
    if describe is not None:
        f.describe = lambda field: describe(field) if _arity(describe) == 1 else describe()
    return f


def _arity(fn) -> int:
    try:
        return len([p for p in inspect.signature(fn).parameters.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
    except (TypeError, ValueError):
        return 1


# ---------------------------------------------------------- kernel defaults


class ScalarFormat(Format):
    """Kernel §7b: scalars, enums and nullables by the §7a text rules. It
    reads any capture that carries text (text parts, thinking parts)."""

    name = "kernel-scalar"
    accepts = STRUCTURAL_SCALARS + ("enum",)
    reads = ("*",)

    def describe(self, field):
        return core.shape_summary(field.shape) or None

    def write(self, value, field):
        if isinstance(value, enum.Enum):      # the language's own construct
            value = value.value
        return core.spell_value(field.shape, value, where=f"field {field.name!r}", field=field.name)

    def read(self, capture, field):
        value = core.read_value(field.shape, capture.text, where=f"field {field.name!r}")
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, enum.Enum) and value is not None:
            return ann(value)
        return value


class MediaFormat(Format):
    """Kernel §7b: a media value that is already a part passes through as
    that part; reading takes the first part of the field's media kind."""

    name = "kernel-media"
    accepts = ("media:*",)
    writes = "parts"
    reads = ("*",)

    def describe(self, field):
        return f"({field.shape.get('media')})"

    def write(self, value, field):
        kind = field.shape.get("media")
        if not isinstance(value, dict):
            refuse("value-invalid",
                   f"field {field.name!r}: a media value must be a plain dict of part data")
        if "type" in value and value["type"] != kind:
            refuse("value-invalid",
                   f"field {field.name!r}: a {value['type']!r} part given where a {kind!r} "
                   f"part is declared")
        return [{"type": kind, **{k: v for k, v in value.items() if k != "type"}}]

    def read(self, capture, field):
        parts = capture.of(field.shape.get("media"))
        if not parts:
            refuse("parse-value", f"field {field.name!r}: no {field.shape.get('media')} part in the capture")
        return {k: v for k, v in parts[0].items() if k != "type"}


SCALAR_DEFAULT = ScalarFormat()
MEDIA_DEFAULT = MediaFormat()


def kernel_default(shape: dict) -> Format | None:
    base, _ = core.nullable_base(shape)
    if core.is_media(base):
        return MEDIA_DEFAULT
    if "enum" in base or base.get("type") in STRUCTURAL_SCALARS:
        return SCALAR_DEFAULT
    return None


# --------------------------------------------------------- structural keys


structural_keys = core.structural_keys


def accepts(fmt: Format, field: core.Field) -> bool:
    keys = set(structural_keys(field.shape)) | {"*"}
    if field.type:
        keys.add(field.type)
    return any(a in keys for a in fmt.accepts)


# ------------------------------------------------------------- shipping


def ship(fmt: Format, *, language: str = "python", deps: list[str] | None = None,
         authored_by: str = "") -> dict:
    """Serialize a function-built format as a UDF entry: source carried
    whole with language, deps, hash, author. Self-containment is checked
    here as well as on load."""
    sources = {}
    for face in ("write", "read", "describe"):
        fn = getattr(fmt, f"_{face}", None)
        if fn is None:
            continue
        src = _source_of(fn, face)
        check_self_contained(src, face)
        sources[face] = src
    if "write" not in sources:
        refuse("entry-malformed", "a shipped format needs a write function",
               fix={"action": "edit-entry", "path": "write"})
    entry = {"language": language, "deps": list(deps or []), **sources,
             "sha256": digest(sources), "authored_by": authored_by,
             "accepts": list(fmt.accepts), "writes": fmt.writes, "round_trip": fmt.round_trip,
             "reads": list(fmt.reads)}
    return entry


def digest(sources: dict) -> str:
    h = hashlib.sha256()
    for face in ("write", "read", "describe"):
        if face in sources:
            h.update(face.encode()); h.update(b"\0"); h.update(sources[face].encode()); h.update(b"\0")
    return h.hexdigest()


def _source_of(fn, face: str) -> str:
    try:
        src = textwrap.dedent(inspect.getsource(fn)).strip()
    except (OSError, TypeError):
        refuse("format-not-self-contained", f"{face}: source is not retrievable; define it as a def",
               fix={"action": "reship-udf", "path": face})
    if not src.startswith("def "):
        refuse("format-not-self-contained", f"{face}: ship needs a named def, not a lambda",
               fix={"action": "reship-udf", "path": face})
    return src


def check_self_contained(src: str, face: str) -> None:
    """No free variables except imports and builtins; the function must
    define itself and nothing else."""
    try:
        code = compile(src, f"<{face}>", "exec")
    except SyntaxError as exc:
        refuse("entry-malformed", f"{face}: source does not compile: {exc}",
               fix={"action": "edit-entry", "path": face})
    fn_code = next((c for c in code.co_consts if isinstance(c, types.CodeType)), None)
    if fn_code is None:
        refuse("format-not-self-contained", f"{face}: no function defined in source",
               fix={"action": "reship-udf", "path": face})
    if fn_code.co_freevars:
        refuse("format-not-self-contained",
               f"{face}: closes over {sorted(fn_code.co_freevars)}; pass values as arguments",
               fix={"action": "reship-udf", "path": face})
    imported: set[str] = set()
    for ins in dis.get_instructions(fn_code):
        if ins.opname in ("IMPORT_NAME",):
            imported.add(ins.argval.split(".")[0])
        if ins.opname in ("STORE_FAST", "STORE_NAME"):
            imported.add(ins.argval)
    for ins in dis.get_instructions(fn_code):
        if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
            name = ins.argval
            if name not in imported and not hasattr(builtins, name):
                refuse("format-not-self-contained",
                       f"{face}: reaches into global {name!r}; import it inside the function",
                       fix={"action": "reship-udf", "path": face})


def load_udf(entry: dict, *, where: str) -> Format:
    """Admit and materialize a shipped UDF in this Python runtime. The
    caller has already decided put is allowed here."""
    if entry.get("language") != "python":
        refuse("udf-unplaceable", f"{where}: this host places python only, not {entry.get('language')!r}",
               fix={"action": "place-udf", "language": str(entry.get("language")), "path": where})
    sources = {k: entry[k] for k in ("write", "read", "describe") if k in entry}
    if digest(sources) != entry.get("sha256"):
        refuse("udf-tampered", f"{where}: sha256 does not match the shipped source",
               fix={"action": "reship-udf", "path": where})
    fns = {}
    for face, src in sources.items():
        check_self_contained(src, f"{where}.{face}")
        ns: dict = {}
        exec(compile(src, f"<{where}.{face}>", "exec"), ns)  # noqa: S102 — admitted above
        fn = next((v for v in ns.values() if callable(v) and not isinstance(v, type)), None)
        if fn is None:
            refuse("entry-malformed", f"{where}.{face}: source defines no function",
                   fix={"action": "edit-entry", "path": f"{where}.{face}"})
        fns[face] = fn
    fmt = make(write=fns["write"], read=fns.get("read"), describe=fns.get("describe"),
               accepts=tuple(entry.get("accepts", ["*"])), writes=entry.get("writes", "text"),
               round_trip=entry.get("round_trip", True), reads=tuple(entry.get("reads", ["text"])))
    fmt.name = f"udf:{where}"
    return fmt

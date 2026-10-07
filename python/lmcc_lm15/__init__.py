"""lmcc × lm15: typed convenience over a shared wire.

The kernel already speaks lm15's canonical JSON (kernel §3; the contract
commit in ``contract/LM15_CONTRACT_PIN``). This package is the thin,
typed face on top: it imports lm15 — the kernel never does — and uses
lm15's own serde in both directions, so there is no translation and
nothing here can drift from what lm15 says a request or a response is.

- ``request(rendered, model=..., config=...)`` → ``lm15.Request``: the
  plan's request_settings (what the adapter *needs*: ``config.reasoning`` for a
  native thinking transport, ``config.response_format`` for a JSON reader,
  ``tools`` for a put) is the base; the caller's ``Config`` fills
  the rest. A caller value that *contradicts* the request settings raises — the
  request_settings is part of the calling convention, not a suggestion — unless
  ``override=True`` says the caller knows better.
- ``parse(plan, response)`` → typed values from an ``lm15.Response`` (or
  ``Message``).
- ``stream(plan, events)`` → drive a plan's sans-I/O stream from
  ``lm.stream(...)`` events; returns the events lmcc emitted and the
  typed values.
- ``step(rendered, response)`` → the turn that was rendered, with the
  ``lm15.Response`` (or ``Message``) recorded as its next model step
  (kernel §3a): the typed values and the message exactly as it came.
- lm15's media parts are types a signature can use: ``picture:
  lm15.ImagePart`` is a ``{"media": "image"}`` field (likewise
  ``AudioPart``, ``VideoPart``, ``DocumentPart``, ``BinaryPart``), and an
  lm15 part is a value for any media field of its kind. Its JSON form is
  its lm15 part data (lm15's own serde), which a turn
  holds and ``plan.load_turn`` rebuilds into the part. A part given by
  ``path`` keeps its path: lm15 reads the file when it sends the request,
  lmcc never does. Importing this module binds them in lmcc's default
  registry; ``install(registry)`` binds them in another.
"""

from __future__ import annotations

from collections.abc import Iterable

import functools

from lm15 import (AudioPart, BinaryPart, Config, DocumentPart, ImagePart, Message, Request, Response,
                  StreamDeltaEvent, StreamEndEvent, VideoPart)
from lm15.serde import (config_to_dict, delta_to_dict, message_to_dict, part_from_dict, part_to_dict,
                        request_from_dict, response_to_dict)

from lmcc.errors import refuse
from lmcc.plan import Plan, Reading, RenderResult
from lmcc.registry import Registry, default_registry
from lmcc.stream import StreamResult
from lmcc.turn import Turn

__all__ = ["request", "parse", "stream", "step", "install", "MEDIA_PARTS", "ConfigConflict"]


# ------------------------------------------------------------ media parts

MEDIA_PARTS = {ImagePart: "image", AudioPart: "audio", VideoPart: "video",
               DocumentPart: "document", BinaryPart: "binary"}


def _part_data(part) -> dict:
    """An lm15 media part's JSON form: lm15's canonical part data, ``type``
    included, so a part of another kind given to a media field refuses
    (kernel §7b) instead of being sent as the field's kind."""
    return part_to_dict(part)


def _part(kind: str, data: object):
    if not isinstance(data, dict) or data.get("type", kind) != kind:
        refuse("turn-invalid", f"an lm15 {kind} part is rebuilt from {kind} part data, got {data!r}")
    return part_from_dict({**data, "type": kind})


def install(registry: Registry) -> Registry:
    """Bind lm15's media part types in ``registry``: each lowers to its
    media shape, crosses by the format that shape resolves (the kernel's
    media default unless the artifact binds one), and has its part data as
    its JSON form (``type`` included). A later ``registry.format(ImagePart, ...)`` replaces it."""
    for cls, kind in MEDIA_PARTS.items():
        registry.format(cls, shape={"media": kind}, to_json=_part_data,
                        from_json=functools.partial(_part, kind))
    return registry


install(default_registry)


class ConfigConflict(ValueError):
    """The caller's Config contradicts what the plan's request_settings requires."""


def _merge(base: dict, extra: dict, *, path: str, override: bool) -> dict:
    out = dict(base)
    for key, value in extra.items():
        here = f"{path}.{key}" if path else key
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value, path=here, override=override)
        elif key in out and out[key] != value and not override:
            raise ConfigConflict(
                f"{here}: the plan's request_settings requires {out[key]!r} (a transport or reader asked for it) "
                f"but the caller's Config says {value!r}; pass override=True to insist")
        else:
            out[key] = value
    return out


def request(rendered: RenderResult, *, model: str, config: Config | None = None,
            override: bool = False) -> Request:
    """The lm15 ``Request`` for a rendered plan. ``rendered.request(model)``
    is already an lm15 request as canonical JSON; the caller's ``Config``
    is merged into its ``config`` (lm15's omission rule drops empties)."""
    d = rendered.request(model)
    if config is not None:
        d["config"] = _merge(d.get("config", {}), config_to_dict(config), path="config", override=override)
    return request_from_dict(d)


def parse(plan: Plan, response: Response | Message) -> dict:
    """Typed values from an lm15 ``Response`` or assistant ``Message``."""
    return read(plan, response).values


def read(plan: Plan, response: Response | Message) -> Reading:
    """Typed values and repairs (kernel §4a) from an lm15 ``Response`` or
    ``Message``; a response cut at its length limit refuses ``parse-truncated``,
    and one the provider stopped (``finish_reason: "content_filter"``, or a
    ``RefusalPart``) refuses ``parse-filtered``."""
    if isinstance(response, Message):
        return plan.read(message_to_dict(response))
    return plan.read(response_to_dict(response))


def stream(plan: Plan, events: Iterable[object]) -> tuple[list[dict], StreamResult]:
    """Feed lm15 stream events into ``plan.stream()``: every delta as its
    canonical JSON (``{"type", "text"?, …}`` — kernel §8 coalesces
    same-type text deltas into logical parts). Returns (all lmcc events
    in order, the ``StreamResult`` from ``finish``)."""
    s = plan.stream()
    out: list[dict] = []
    finish_reason = None
    for event in events:
        if isinstance(event, StreamEndEvent):
            finish_reason = event.finish_reason
        if not isinstance(event, StreamDeltaEvent):
            continue
        out.extend(s.feed(delta_to_dict(event.delta)))
    result = s.finish(finish_reason)
    out.extend(result.events)
    return out, result


def step(rendered: RenderResult, response: Response | Message) -> Turn:
    """The rendered turn with this reply recorded as its next model step:
    ``rendered.step`` over lm15's own canonical JSON of the message."""
    if isinstance(response, Message):
        return rendered.step(message_to_dict(response))
    return rendered.step(response_to_dict(response))   # finish_reason: truncation (§4a)

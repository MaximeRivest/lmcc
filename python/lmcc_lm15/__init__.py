"""lmcc × lm15: typed convenience over a shared wire.

The kernel already speaks lm15's canonical JSON (kernel §3; the contract
commit in ``contract/LM15_CONTRACT_PIN``). This package is the thin,
typed face on top: it imports lm15 — the kernel never does — and uses
lm15's own serde in both directions, so there is no translation and
nothing here can drift from what lm15 says a request or a response is.

- ``request(rendered, model=..., config=...)`` → ``lm15.Request``: the
  plan's patch (what the adapter *needs*: ``config.reasoning`` for a
  native thinking strategy, ``config.response_format`` for a JSON lens,
  ``tools`` for a placement) is the base; the caller's ``Config`` fills
  the rest. A caller value that *contradicts* the patch raises — the
  patch is part of the calling convention, not a suggestion — unless
  ``override=True`` says the caller knows better.
- ``parse(plan, response)`` → typed values from an ``lm15.Response`` (or
  ``Message``).
- ``stream(plan, events)`` → drive a plan's sans-I/O stream from
  ``lm.stream(...)`` events; returns the events lmcc emitted and the
  typed values.
"""

from __future__ import annotations

from collections.abc import Iterable

from lm15 import Config, Message, Request, Response, StreamDeltaEvent
from lm15.serde import config_to_dict, delta_to_dict, message_to_dict, request_from_dict, response_to_dict

from lmcc.plan import Plan, RenderResult
from lmcc.stream import StreamResult

__all__ = ["request", "parse", "stream", "ConfigConflict"]


class ConfigConflict(ValueError):
    """The caller's Config contradicts what the plan's patch requires."""


def _merge(base: dict, extra: dict, *, path: str, override: bool) -> dict:
    out = dict(base)
    for key, value in extra.items():
        here = f"{path}.{key}" if path else key
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value, path=here, override=override)
        elif key in out and out[key] != value and not override:
            raise ConfigConflict(
                f"{here}: the plan's patch requires {out[key]!r} (a strategy or lens asked for it) "
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
    if isinstance(response, Message):
        return plan.parse(message_to_dict(response))
    return plan.parse(response_to_dict(response))


def stream(plan: Plan, events: Iterable[object]) -> tuple[list[dict], StreamResult]:
    """Feed lm15 stream events into ``plan.stream()``: every delta as its
    canonical JSON (``{"type", "text"?, …}`` — kernel §8 coalesces
    same-type text deltas into logical parts). Returns (all lmcc events
    in order, the ``StreamResult`` from ``finish``)."""
    s = plan.stream()
    out: list[dict] = []
    for event in events:
        if not isinstance(event, StreamDeltaEvent):
            continue
        out.extend(s.feed(delta_to_dict(event.delta)))
    result = s.finish()
    out.extend(result.events)
    return out, result

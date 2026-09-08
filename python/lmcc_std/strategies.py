"""Standard reasoning strategies: three ways to serve one role.

The point of shipping three is the point of the whole design: the same
signature, the same program, three inference behaviors — chosen at bake
by the model's declared facts, never by editing the program.

- ``prefix_cot``: the classic. The reasoning field stays a visible section
  the model writes before the others.
- ``reasoning_tags``: interleaved thinking on any instruct model — pure
  prompt + parse data. The field leaves the sections; ``<think>`` spans
  are routed to it and stripped from the visible text.
- ``native_reasoning``: models with a native thinking channel. The field
  leaves the token stream entirely and is read from response parts.
"""

from __future__ import annotations

from lmcc.strategy import Strategy

VERSION = "0.1.0"


def prefix_cot(options: dict) -> Strategy:
    return Strategy(
        requires=["instruct"],
        fragments={"system": "Reason step by step in the '{field}' section "
                             "before writing any other section."},
        visible=True,
    )


def reasoning_tags(options: dict) -> Strategy:
    open_tag = options.get("open", "<think>")
    close_tag = options.get("close", "</think>")
    return Strategy(
        requires=["instruct"],
        fragments={"system": f"After every sentence of output, add your "
                             f"thinking inside {open_tag}...{close_tag} tags."},
        routings=[{"from": "text", "between": [open_tag, close_tag],
                   "to": "@role", "consume": True}],
        visible=False,
    )


def native_reasoning(options: dict) -> Strategy:
    """Options: ``effort`` (lm15 ``Reasoning.effort`` word; default
    ``medium``) and optional ``thinking_budget`` (int). The strategy both
    *asks* for thinking (``config.reasoning`` in the request patch) and
    *reads* it back (``channel:thinking``)."""
    reasoning: dict = {"effort": options.get("effort", "medium")}
    if "thinking_budget" in options:
        reasoning["thinking_budget"] = options["thinking_budget"]
    return Strategy(
        requires=["native_reasoning"],
        controls={"config": {"reasoning": reasoning}},
        routings=[{"from": "channel:thinking", "to": "@role"}],
        visible=False,
    )


def install(registry, *, exist_ok: bool = True) -> None:
    registry.register_strategy("prefix_cot", prefix_cot, version=VERSION,
                               exist_ok=exist_ok)
    registry.register_strategy("reasoning_tags", reasoning_tags, version=VERSION,
                               exist_ok=exist_ok)
    registry.register_strategy("native_reasoning", native_reasoning,
                               version=VERSION, exist_ok=exist_ok)

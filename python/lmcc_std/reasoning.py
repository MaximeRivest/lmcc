"""Standard reasoning transports: three ways to serve one purpose.

The point of shipping three is the point of the whole design: the same
signature, the same program, three inference behaviors — chosen at bake
by the model's declared facts, never by editing the program.

- ``prefix_cot``: the classic. The reasoning field stays a visible section
  the model writes before the others.
- ``reasoning_tags``: interleaved thinking on any instruct model — pure
  prompt + parse data. The field leaves the sections; ``<think>`` captures
  are found to it and stripped from the in_template text.
- ``native_reasoning``: models with a native thinking channel. The field
  leaves the token stream entirely and is read from response parts.
"""

from __future__ import annotations

from lmcc.transport import Transport

VERSION = "0.1.0"
# 0.2.0: past reasoning is written before the answer in turns (kernel 0.7 §3a).
REASONING_TAGS_VERSION = "0.3.0"   # 0.3: tags repaired like markers (kernel §4a)


def prefix_cot(options: dict) -> Transport:
    return Transport(
        requires=["instruct"],
        tell={"system": "Reason step by step in the '{field}' section "
                             "before writing any other section."},
        in_template=True,
    )


def reasoning_tags(options: dict) -> Transport:
    open_tag = options.get("open", "<think>")
    close_tag = options.get("close", "</think>")
    return Transport(
        requires=["instruct"],
        tell={"system": f"After every sentence of output, add your "
                             f"thinking inside {open_tag}...{close_tag} tags."},
        find=[{"from": "text", "between": [open_tag, close_tag],
                   "to": "@purpose", "remove": True, "repair": True}],
        spelling={"position": "before"},
        in_template=False,
    )


def native_reasoning(options: dict) -> Transport:
    """Options: ``effort`` (lm15 ``Reasoning.effort`` word; default
    ``medium``) and optional ``thinking_budget`` (int). The transport both
    *asks* for thinking (``config.reasoning`` in the request settings) and
    *reads* it back (``part:thinking``)."""
    reasoning: dict = {"effort": options.get("effort", "medium")}
    if "thinking_budget" in options:
        reasoning["thinking_budget"] = options["thinking_budget"]
    return Transport(
        requires=["native_reasoning"],
        request_settings={"config": {"reasoning": reasoning}},
        find=[{"from": "part:thinking", "to": "@purpose"}],
        in_template=False,
    )


def install(registry, *, exist_ok: bool = True) -> None:
    registry.register_transport("prefix_cot", prefix_cot, version=VERSION,
                               exist_ok=exist_ok)
    registry.register_transport("reasoning_tags", reasoning_tags, version=REASONING_TAGS_VERSION,
                               exist_ok=exist_ok)
    registry.register_transport("native_reasoning", native_reasoning,
                               version=VERSION, exist_ok=exist_ok)

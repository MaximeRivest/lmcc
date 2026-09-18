"""Raw-code argument spelling and heredoc calls (spec/vocab/format-code.md).

No execution. Arguments and capture bodies stay exact, including indentation
and trailing newlines. The envelope is owned by the strategy.
"""

import dataclasses

from lmcc import core
from lmcc.errors import refuse
from lmcc.formats import Format
from lmcc.strategy import Strategy

from .formats import lift

VERSION = "0.1.0"


def _options(options, *, calls=False):
    allowed = {"marker", "tool"} if calls else {"marker"}
    if set(options) - allowed:
        raise ValueError(f"unknown options: {sorted(set(options) - allowed)}")
    marker, tool = options.get("marker", "PY_END"), options.get("tool", "run_python")
    for key, value in (("marker", marker), ("tool", tool)):
        if (not isinstance(value, str) or not value or not value.isascii()
                or value[0] not in "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                or any(c not in "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in value)):
            raise ValueError(f"{key} must be a nonempty ASCII identifier")
    return marker, tool


class CodeArguments(Format):
    accepts = ("object",)

    def __init__(self, options):
        self.marker, _ = _options(options)

    def describe(self, field):
        return "raw code"

    def _code(self, value):
        if not isinstance(value, dict) or set(value) != {"code"} or not isinstance(value["code"], str):
            raise ValueError("code arguments must be exactly {code: string}")
        return value["code"]

    def write(self, value, field):
        code = self._code(value)
        if self.marker in code:
            refuse("value-collides", f"code contains heredoc marker {self.marker!r}; choose another marker")
        return code

    def read(self, span, field):
        if any(p.get("type") != "text" or not isinstance(p.get("text"), str) for p in span.parts):
            raise ValueError("code arguments need text parts")
        code = "".join(p["text"] for p in span.parts)  # NOT span.text: code whitespace is data
        if self.marker in code:
            raise ValueError(f"code contains heredoc marker {self.marker!r}")
        return {"code": code}


class CodeCalls(Format):
    accepts = ("list[*]", "*")
    emits = "parts"
    reads = ("text", "tool_call")

    def __init__(self, options):
        marker, self.tool = _options(options, calls=True)
        self.arguments = CodeArguments({"marker": marker})

    def describe(self, field):
        return "heredoc tool calls"

    def _native(self, call, field):
        call = dataclasses.asdict(call) if dataclasses.is_dataclass(call) else call
        if (not isinstance(call, dict) or call.get("name") != self.tool
                or not isinstance(call.get("id"), str) or not call["id"]):
            raise ValueError(f"expected a {self.tool!r} call with a nonempty id")
        body = self.arguments._code(call.get("input"))
        # Read-side validation raises a format error, not a render refusal.
        self.arguments.read(core.Span.of_text(body), field)
        return {"id": call["id"], "name": self.tool, "input": {"code": body}}

    def write(self, value, field):
        if not isinstance(value, list):
            raise ValueError("calls must be a list")
        return [{"type": "tool_call", **self._native(c, field)} for c in value]

    def read(self, span, field):
        calls = []
        for part in span.parts:
            if part.get("type") == "tool_call":
                calls.append(self._native(part, field))
            else:
                args = self.arguments.read(core.Span([part]), field)
                calls.append({"id": f"call_{len(calls) + 1}", "name": self.tool, "input": args})
        return lift(field.annotation, calls)


def heredoc_tools(options):
    marker, tool = _options(options, calls=True)
    opening, closing = f"{tool} <<'{marker}'\n", f"\n{marker}"
    return Strategy(
        requires=["instruct"], visible=False,
        placement={"@role": "message:system"}, via={"@role": "tool_catalog"},
        fragments={"system": f"To request {tool}, emit this heredoc and wait for its result:\n"
                   f"{opening}<code>{closing}\n"
                   f"Do not put {marker} anywhere in the code. Otherwise reply normally."},
        routings=[{"from": "text", "between": [opening, closing], "to": "@role.calls",
                   "consume": True, "suffices": True}],
        turns={"call": "{name} <<'" + marker + "'\n{input}" + closing,
               "result": "Result of {name} ({id}):\n{output}",
               "input_format": {"use": "code_arguments", "options": {"marker": marker}},
               "probe": {"name": tool, "input": {"code": "print(6 * 7)\n"}}})


def install(registry, *, exist_ok=True):
    registry.register_format("code_arguments", CodeArguments, version=VERSION, exist_ok=exist_ok)
    registry.register_format("code_calls", CodeCalls, version=VERSION, exist_ok=exist_ok)
    registry.register_strategy("heredoc_tools", heredoc_tools, version=VERSION, exist_ok=exist_ok)

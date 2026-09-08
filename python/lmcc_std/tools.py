"""Tools and citations: formats and strategies (spec/vocab/strategy-tools.md,
strategy-citations.md). Every value shape is lm15's; the program never
changes between the native and the text tier."""

from __future__ import annotations

import dataclasses

from lmcc.errors import refuse
from lmcc.formats import Format
from lmcc.strategy import Strategy

from . import jsontext
from .formats import lift

VERSION = "0.1.0"


# The host types a Python program spells; formats resolve by type, never
# by role (kernel §5), so ``tools`` and ``calls`` are different types.
# ``install`` binds them at runtime; an artifact names them under
# ``formats`` ("list[Tool]": {"use": "function_tool"}) to travel.

@dataclasses.dataclass
class Tool:
    name: str
    description: str | None = None
    parameters: dict | None = None


@dataclasses.dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclasses.dataclass
class Citation:
    url: str | None = None
    title: str | None = None
    text: str | None = None
    source: int | None = None


@dataclasses.dataclass
class Source:
    text: str
    title: str | None = None
    url: str | None = None

_TOOL_KEYS = {"name", "description", "parameters"}
_DEFAULT_PARAMETERS = {"type": "object", "properties": {}}


def _tool_items(value, field):
    items = value if isinstance(value, list) else [value]
    out = []
    for i, item in enumerate(items):
        spec = item if isinstance(item, dict) else {
            k: getattr(item, k) for k in _TOOL_KEYS if getattr(item, k, None) is not None}
        if not isinstance(spec.get("name"), str) or not spec["name"]:
            refuse("format-write-error", f"field {field.name!r}: tools[{i}] needs a string 'name'")
        unknown = set(spec) - _TOOL_KEYS - {"type"}
        if unknown:
            refuse("format-write-error",
                   f"field {field.name!r}: tools[{i}] has keys {sorted(unknown)}; a tool is "
                   f"name, description, parameters (lm15 FunctionTool)")
        out.append(spec)
    return out


class FunctionToolFormat(Format):
    """lm15 ``FunctionTool`` parts, for ``Request.tools``."""
    accepts = ("list[Tool]", "Tool", "list[*]", "object", "*")
    direction = "in"
    emits = "parts"
    reads = ("function",)

    def __init__(self, options: dict):
        pass

    def describe(self, field):
        return "tools"

    def write(self, value, field):
        parts = []
        for spec in _tool_items(value, field):
            part = {"type": "function", "name": spec["name"]}
            if spec.get("description"):
                part["description"] = spec["description"]
            part["parameters"] = spec.get("parameters") or dict(_DEFAULT_PARAMETERS)
            parts.append(part)
        return parts

    def read(self, span, field):
        return [{k: v for k, v in p.items() if k != "type"} for p in span.of("function")]


class ToolCatalogFormat(Format):
    """The same tools as text, for a model without native calling."""
    accepts = ("list[Tool]", "Tool", "list[*]", "object", "*")
    direction = "in"
    emits = "text"

    def __init__(self, options: dict):
        pass

    def describe(self, field):
        return "tools"

    def write(self, value, field):
        lines = []
        for spec in _tool_items(value, field):
            params = jsontext.dumps(spec.get("parameters") or _DEFAULT_PARAMETERS, indent=None)
            desc = f": {spec['description']}" if spec.get("description") else ""
            lines.append(f"- {spec['name']}({params}){desc}")
        return "\n".join(lines)


class ToolCallsFormat(Format):
    """Calls read from ``tool_call`` parts (id, name, input verbatim) or
    from text (fenced JSON; ids assigned ``call_1``… in reply order)."""
    accepts = ("list[ToolCall]", "list[*]", "*")
    direction = "both"
    emits = "parts"
    reads = ("tool_call", "text")

    def __init__(self, options: dict):
        pass

    def describe(self, field):
        return "tool calls"

    def write(self, value, field):
        out = []
        for c in value or []:
            c = dataclasses.asdict(c) if dataclasses.is_dataclass(c) else c
            out.append({"type": "tool_call", "id": c["id"], "name": c["name"], "input": c.get("input", {})})
        return out

    def read(self, span, field):
        calls = []
        n = 0
        for p in span.parts:
            if p.get("type") == "tool_call":
                calls.append({k: v for k, v in p.items() if k not in ("type", "continuation")})
            elif isinstance(p.get("text"), str):
                try:
                    obj = jsontext.loads(p["text"])
                except Exception as exc:  # noqa: BLE001
                    refuse("format-read-error", f"field {field.name!r}: a fenced call is not JSON: {exc}")
                if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
                    refuse("format-read-error", f"field {field.name!r}: a fenced call is {{name, input}}")
                n += 1
                calls.append({"id": f"call_{n}", "name": obj["name"], "input": obj.get("input") or {}})
        return lift(field.annotation, calls)


class CitationsFormat(Format):
    """From ``citation`` parts: url/title/text verbatim. From text markers:
    ``{"source": n}`` per distinct bracketed integer, order kept."""
    accepts = ("list[Citation]", "list[*]", "*")
    direction = "out"
    emits = "parts"
    reads = ("citation", "text")

    def __init__(self, options: dict):
        pass

    def read(self, span, field):
        out, seen = [], set()
        for p in span.parts:
            if p.get("type") == "citation":
                out.append({k: v for k, v in p.items() if k not in ("type", "continuation")})
            elif isinstance(p.get("text"), str):
                t = p["text"].strip()
                if t.isdigit() and t not in seen:
                    seen.add(t)
                    out.append({"source": int(t)})
        return lift(field.annotation, out)


class SourceListFormat(Format):
    """Numbered sources as text: ``[n] title: text``."""
    accepts = ("list[Source]", "list[*]", "*")
    direction = "in"
    emits = "text"

    def __init__(self, options: dict):
        pass

    def describe(self, field):
        return "numbered sources"

    def write(self, value, field):
        lines = []
        for i, s in enumerate(value or [], 1):
            s = dataclasses.asdict(s) if dataclasses.is_dataclass(s) else s
            if not isinstance(s, dict) or not isinstance(s.get("text"), str):
                refuse("format-write-error", f"field {field.name!r}: sources[{i - 1}] needs 'text'")
            title = s.get("title") or s.get("url") or f"source {i}"
            lines.append(f"[{i}] {title}: {s['text']}")
        return "\n".join(lines)


# ------------------------------------------------------------ strategies

def native_tools(options: dict) -> Strategy:
    return Strategy(
        requires=["native_function_calling"], visible=False,
        placement={"@role": "controls.tools"},
        routings=[{"from": "channel:tool_call", "to": "@role.calls", "suffices": True}])


FENCE_OPEN, FENCE_CLOSE = "```tool\n", "\n```"


def fenced_tools(options: dict) -> Strategy:
    return Strategy(
        requires=["instruct"], visible=False,
        placement={"@role": "message:system"}, via={"@role": "tool_catalog"},
        fragments={"system": "You may call a tool by replying with exactly one fenced block:\n"
                             "```tool\n{\"name\": \"<tool>\", \"input\": {...}}\n```\n"
                             "and nothing else; you will be given the result and asked again."},
        routings=[{"from": "text", "between": [FENCE_OPEN, FENCE_CLOSE], "to": "@role.calls",
                   "consume": True, "suffices": True}],
        turns={"call": "```tool\n{\"name\": \"{name}\", \"input\": {input}}\n```",
               "result": "Result of {name} ({id}):\n{output}"})


def native_citations(options: dict) -> Strategy:
    s = Strategy(requires=["native_citations"], visible=False,
                 routings=[{"from": "channel:citation", "to": "@role"}])
    if options.get("search", True):
        s.controls = {"tools": [{"type": "builtin", "name": "web_search"}]}
    return s


def inline_citations(options: dict) -> Strategy:
    return Strategy(
        requires=["instruct"], visible=False,
        placement={"@role.sources": "message:user"},
        fragments={"system": "Cite the numbered sources inline as [n] after each claim they support."},
        routings=[{"from": "text", "between": ["[", "]"], "to": "@role", "consume": False}])


def install(registry, *, exist_ok: bool = True) -> None:
    for name, fmt in (("function_tool", FunctionToolFormat), ("tool_catalog", ToolCatalogFormat),
                      ("tool_calls", ToolCallsFormat), ("citations", CitationsFormat),
                      ("source_list", SourceListFormat)):
        registry.register_format(name, fmt, version=VERSION, exist_ok=exist_ok)
    for name, factory in (("native_tools", native_tools), ("fenced_tools", fenced_tools),
                          ("native_citations", native_citations),
                          ("inline_citations", inline_citations)):
        registry.register_strategy(name, factory, version=VERSION, exist_ok=exist_ok)
    # runtime type bindings for Python programs (kernel §5 step 3); an
    # artifact that must travel names the same formats under its `formats`
    registry.format(list[Tool], use="function_tool")
    registry.format(list[ToolCall], use="tool_calls")
    registry.format(list[Citation], use="citations")
    registry.format(list[Source], use="source_list")

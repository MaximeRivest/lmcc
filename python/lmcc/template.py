"""The template DSL: compile and render.

The template language is deliberately *not* a programming language. It has
exactly three constructs, so every template stays diffable, printable, and
serializable:

- slots: ``{instruction}``, ``{format}`` (the lens's reply skeleton),
  ``{field_name}`` (an input's value, or an output's placeholder), and
  ``{f.attr}`` inside loops
- loops: ``{% for f in inputs %} ... {% endfor %}`` (also ``outputs``),
  iterating the *visible* fields of the baked plan, in signature order
- escapes: ``{{`` renders ``{``, ``}}`` renders ``}``

A bare ``{`` or ``}`` outside these constructs is a syntax error (code
``template-syntax``) — strictness is what keeps templates analyzable.

Loop variables expose: ``f.name``, ``f.desc`` (empty when absent), ``f.type``
(empty when absent), ``f.schema`` (the format's describe, or a mechanical
hint), ``f.role``, ``f.value`` (the written value — parts land at the
slot; an output's value is its placeholder).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import refuse

# ASCII-explicit on purpose: \w and \s are Unicode in Python and ASCII in
# RE2/Go, and the template grammar must be one grammar everywhere.
_TOKEN = re.compile(
    r"(?P<escape>\{\{|\}\})"
    r"|(?P<loop>\{%\s*for\s+(?P<var>[A-Za-z_]\w*)\s+in\s+(?P<source>[A-Za-z_]\w*)\s*%\})"
    r"|(?P<end>\{%\s*endfor\s*%\})"
    r"|(?P<slot>\{(?P<path>[A-Za-z_][\w.]*)\})",
    re.ASCII,
)

LOOP_SOURCES = ("inputs", "outputs")
LOOP_ATTRS = ("name", "desc", "type", "schema", "role", "value")


@dataclass
class Text:
    text: str


@dataclass
class Slot:
    path: str  # "instruction" | "<field name>" | "<var>.<attr>"


@dataclass
class Loop:
    var: str
    source: str  # "inputs" | "outputs"
    body: list


Node = Text | Slot | Loop


def compile_template(text: str, *, where: str = "template") -> list[Node]:
    """Compile template text to an AST, refusing loudly on any bad syntax."""
    root: list[Node] = []
    stack: list[tuple[Loop, list[Node]]] = []
    current = root
    pos = 0
    for m in _TOKEN.finditer(text):
        literal = text[pos:m.start()]
        _check_literal(literal, where)
        if literal:
            current.append(Text(literal))
        if m.group("escape"):
            current.append(Text(m.group("escape")[0]))
        elif m.group("loop"):
            source = m.group("source")
            if source not in LOOP_SOURCES:
                refuse("template-syntax",
                       f"{where}: loop source {source!r} is not one of {LOOP_SOURCES}")
            loop = Loop(m.group("var"), source, [])
            current.append(loop)
            stack.append((loop, current))
            current = loop.body
        elif m.group("end"):
            if not stack:
                refuse("template-syntax", f"{where}: {{% endfor %}} without an open loop")
            _, current = stack.pop()
        else:
            current.append(Slot(m.group("path")))
        pos = m.end()
    tail = text[pos:]
    _check_literal(tail, where)
    if tail:
        current.append(Text(tail))
    if stack:
        refuse("template-syntax", f"{where}: unclosed {{% for %}} loop")
    return root


def _check_literal(literal: str, where: str) -> None:
    for ch in ("{", "}"):
        if ch in literal:
            refuse("template-syntax",
                   f"{where}: bare {ch!r} — use {ch * 2!r} to render a literal brace")


def validate_nodes(nodes: list[Node], *, known_fields: set[str],
                   input_fields: set[str], where: str,
                   in_loop_var: str | None = None) -> set[str]:
    """Check every slot resolves against the signature. Returns the set of
    input field names this template covers directly (bare slots)."""
    covered: set[str] = set()
    for node in nodes:
        if isinstance(node, Slot):
            path = node.path
            if in_loop_var and path.startswith(in_loop_var + "."):
                attr = path[len(in_loop_var) + 1:]
                if attr not in LOOP_ATTRS:
                    refuse("unknown-slot",
                           f"{where}: {{{path}}} — loop attributes are {LOOP_ATTRS}")
                continue
            if path in ("instruction", "format"):
                continue  # reserved slots; they shadow same-named fields
            if "." in path:
                refuse("unknown-slot",
                       f"{where}: {{{path}}} — dotted slots are only valid inside "
                       f"their loop")
            if path in input_fields:
                covered.add(path)
                continue
            if path in known_fields:
                continue  # an output slot: renders its placeholder (kernel §2)
            refuse("unknown-slot",
                   f"{where}: {{{path}}} names no field in the signature")
        elif isinstance(node, Loop):
            covered |= validate_nodes(
                node.body, known_fields=known_fields, input_fields=input_fields,
                where=where, in_loop_var=node.var)
            if node.source == "inputs":
                covered |= input_fields
    return covered


def render_nodes(nodes: list[Node], env, out: list[dict], buf: list[str],
                 loop_ctx: dict | None = None) -> None:
    """Render an AST into message parts.

    ``env`` must provide: ``instruction`` (str), ``loop_fields(source)``
    (visible fields for a loop), ``value_of(field)`` returning
    ``("text", str)`` or ``("part", dict)``, ``schema_of(field)`` and
    ``field_named(name)``.
    """
    for node in nodes:
        if isinstance(node, Text):
            buf.append(node.text)
        elif isinstance(node, Slot):
            _render_slot(node, env, out, buf, loop_ctx)
        elif isinstance(node, Loop):
            for f in env.loop_fields(node.source):
                render_nodes(node.body, env, out, buf,
                             loop_ctx={**(loop_ctx or {}), node.var: f})


def _render_slot(node: Slot, env, out: list[dict], buf: list[str],
                 loop_ctx: dict | None) -> None:
    path = node.path
    if loop_ctx:
        var, _, attr = path.partition(".")
        if attr and var in loop_ctx:
            f = loop_ctx[var]
            if attr == "name":
                buf.append(f.name)
            elif attr == "desc":
                buf.append(f.desc or "")
            elif attr == "role":
                buf.append(f.role)
            elif attr == "type":
                buf.append(f.type or "")
            elif attr == "schema":
                buf.append(env.schema_of(f))
            elif attr == "value":
                _emit_value(env.value_of(f), out, buf)
            return
    if path == "instruction":
        buf.append(env.instruction)
        return
    if path == "format":
        buf.append(env.reply_format)
        return
    f = env.field_named(path)
    _emit_value(env.value_of(f), out, buf)


def _emit_value(rendered: tuple[str, object], out: list[dict], buf: list[str]) -> None:
    """Parts land at the slot in order; text parts join the running text."""
    kind, payload = rendered
    if kind == "text":
        buf.append(payload)
        return
    for part in payload:
        if part.get("kind") == "text":
            buf.append(part.get("text", ""))
            continue
        if buf:
            out.append({"kind": "text", "text": "".join(buf)})
            buf.clear()
        out.append(part)

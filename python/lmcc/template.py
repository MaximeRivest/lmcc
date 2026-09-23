"""The template DSL: compile and render.

The template language is deliberately *not* a programming language. It has
exactly four constructs, so every template stays diffable, printable, and
serializable:

- slots: ``{instruction}``, ``{format}`` (the reader's reply skeleton),
  ``{field_name}`` (an input's value, or an output's placeholder), and
  ``{f.attr}`` inside loops
- loops: ``{% for f in inputs %} ... {% endfor %}`` (also ``outputs``),
  iterating the *in_template* fields of the baked plan, in signature order;
  any other source is a turn slot (kernel §3a), iterating the messages its
  turns write, with ``m.role``, ``m.kind`` and ``m.text``
- guards: ``{% if slot %} ... {% endif %}``, the body only when the turn
  slot is not empty
- escapes: ``{{`` renders ``{``, ``}}`` renders ``}``

A bare ``{`` or ``}`` outside these constructs is a syntax error (code
``template-syntax``) — strictness is what keeps templates analyzable.

Loop variables expose: ``f.name``, ``f.desc`` (empty when absent), ``f.type``
(empty when absent), ``f.schema`` (the format's describe, or a mechanical
hint), ``f.purpose``, ``f.value`` (the written value — parts land at the
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
    r"|(?P<guard>\{%\s*if\s+(?P<gname>[A-Za-z_]\w*)\s*%\})"
    r"|(?P<endif>\{%\s*endif\s*%\})"
    r"|(?P<slot>\{(?P<path>[A-Za-z_][\w.]*)\})",
    re.ASCII,
)

LOOP_SOURCES = ("inputs", "outputs")          # field loops; any other source is a turn slot
LOOP_ATTRS = ("name", "desc", "type", "schema", "purpose", "value")
TURN_ATTRS = ("role", "kind", "text")
RESERVED_SLOTS = ("inputs", "outputs", "instruction", "format")


@dataclass
class Text:
    text: str


@dataclass
class Slot:
    path: str  # "instruction" | "<field name>" | "<var>.<attr>"


@dataclass
class Loop:
    var: str
    source: str  # "inputs" | "outputs" | a turn slot name
    body: list

    @property
    def over_turns(self) -> bool:
        return self.source not in LOOP_SOURCES


@dataclass
class Guard:
    slot: str    # a turn slot name
    body: list


Node = Text | Slot | Loop | Guard


def compile_template(text: str, *, where: str = "template") -> list[Node]:
    """Compile template text to an AST, refusing loudly on any bad syntax."""
    root: list[Node] = []
    stack: list[tuple[Loop | Guard, list[Node]]] = []
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
            if source in ("instruction", "format"):
                refuse("template-syntax",
                       f"{where}: {source!r} is reserved; a loop runs over inputs, outputs, "
                       f"or a turn slot", fix={"action": "edit-template", "path": where})
            if any(isinstance(n, Loop) and n.over_turns for n, _ in stack):
                refuse("template-syntax", f"{where}: a turn loop's body holds text and "
                       f"m.role/m.kind/m.text only; no nested loop",
                       fix={"action": "edit-template", "path": where})
            loop = Loop(m.group("var"), source, [])
            current.append(loop)
            stack.append((loop, current))
            current = loop.body
        elif m.group("guard"):
            name = m.group("gname")
            if name in RESERVED_SLOTS:
                refuse("template-syntax", f"{where}: a guard names a turn slot, not {name!r}",
                       fix={"action": "edit-template", "path": where})
            if any(isinstance(n, Loop) and n.over_turns for n, _ in stack):
                refuse("template-syntax", f"{where}: no guard inside a turn loop",
                       fix={"action": "edit-template", "path": where})
            guard = Guard(name, [])
            current.append(guard)
            stack.append((guard, current))
            current = guard.body
        elif m.group("end") or m.group("endif"):
            want, word = (Loop, "endfor") if m.group("end") else (Guard, "endif")
            if not stack or not isinstance(stack[-1][0], want):
                refuse("template-syntax", f"{where}: {{% {word} %}} without an open "
                       f"{'loop' if want is Loop else 'guard'}",
                       fix={"action": "edit-template", "path": where})
            _, current = stack.pop()
        else:
            current.append(Slot(m.group("path")))
        pos = m.end()
    tail = text[pos:]
    _check_literal(tail, where)
    if tail:
        current.append(Text(tail))
    if stack:
        what = "{% for %} loop" if isinstance(stack[-1][0], Loop) else "{% if %} guard"
        refuse("template-syntax", f"{where}: unclosed {what}",
               fix={"action": "edit-template", "path": where})
    _check_turn_loops(root, where)
    return root


def _check_turn_loops(nodes: list[Node], where: str) -> None:
    for node in nodes:
        if isinstance(node, Loop) and node.over_turns:
            for n in node.body:
                if isinstance(n, Slot):
                    var, _, attr = n.path.partition(".")
                    if var != node.var or attr not in TURN_ATTRS:
                        refuse("template-syntax",
                               f"{where}: in a loop over turn slot {node.source!r} only "
                               f"{{{node.var}.role}}, {{{node.var}.kind}} and "
                               f"{{{node.var}.text}} exist; got {{{n.path}}}",
                               fix={"action": "edit-template", "path": where})
        elif isinstance(node, (Loop, Guard)):
            _check_turn_loops(node.body, where)


def turn_slots(nodes: list[Node]) -> tuple[list[str], list[str]]:
    """(slots placed as text by turn loops, slots named by guards), in order."""
    placed: list[str] = []
    guarded: list[str] = []
    for node in nodes:
        if isinstance(node, Loop) and node.over_turns:
            placed.append(node.source)
        elif isinstance(node, Guard):
            guarded.append(node.slot)
            p, g = turn_slots(node.body)
            placed += p
            guarded += g
        elif isinstance(node, Loop):
            p, g = turn_slots(node.body)
            placed += p
            guarded += g
    return placed, guarded


def _check_literal(literal: str, where: str) -> None:
    for ch in ("{", "}"):
        if ch in literal:
            refuse("template-syntax",
                   f"{where}: bare {ch!r} — use {ch * 2!r} to render a literal brace",
                   fix={"action": "edit-template", "path": where})


def validate_nodes(nodes: list[Node], *, known_fields: set[str],
                   input_fields: set[str], where: str,
                   in_loop_var: str | None = None, slots=frozenset()) -> set[str]:
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
                           f"{where}: {{{path}}} — loop attributes are {LOOP_ATTRS}",
                           fix={"action": "edit-template", "path": where, "slot": path})
                continue
            if path in ("instruction", "format"):
                continue  # reserved slots; they shadow same-named fields
            if "." in path:
                refuse("unknown-slot",
                       f"{where}: {{{path}}} — dotted slots are only valid inside "
                       f"their loop", fix={"action": "edit-template", "path": where, "slot": path})
            if path in input_fields:
                covered.add(path)
                continue
            if path in known_fields:
                continue  # an output slot: renders its placeholder (kernel §2)
            refuse("unknown-slot",
                   f"{where}: {{{path}}} names no field in the signature",
                   fix={"action": "edit-template", "path": where, "slot": path})
        elif isinstance(node, Loop) and node.over_turns:
            continue     # checked at compile: text and m.role/m.kind/m.text only
        elif isinstance(node, Guard):
            if node.slot not in slots and node.slot not in input_fields:
                refuse("unknown-slot",
                       f"{where}: {{% if {node.slot} %}} names neither a turn slot this template "
                       f"places nor an input field",
                       fix={"action": "edit-template", "path": where, "slot": node.slot})
            covered |= validate_nodes(node.body, known_fields=known_fields, slots=slots,
                                      input_fields=input_fields, where=where,
                                      in_loop_var=in_loop_var)
        elif isinstance(node, Loop):
            covered |= validate_nodes(
                node.body, known_fields=known_fields, input_fields=input_fields,
                where=where, in_loop_var=node.var, slots=slots)
            if node.source == "inputs":
                covered |= input_fields
    return covered


def render_nodes(nodes: list[Node], env, out: list[dict], buf: list[str],
                 loop_ctx: dict | None = None) -> None:
    """Render an AST into message parts.

    ``env`` must provide: ``instruction`` (str), ``loop_fields(source)``
    (in_template fields for a loop), ``value_of(field)`` returning
    ``("text", str)`` or ``("part", dict)``, ``schema_of(field)``,
    ``field_named(name)``, ``turn_messages(slot)`` (the slot's written
    messages as ``(role, kind, text)``) and ``slot_filled(slot)``.
    """
    for node in nodes:
        if isinstance(node, Text):
            buf.append(node.text)
        elif isinstance(node, Slot):
            _render_slot(node, env, out, buf, loop_ctx)
        elif isinstance(node, Guard):
            if env.slot_filled(node.slot):
                render_nodes(node.body, env, out, buf, loop_ctx)
        elif isinstance(node, Loop) and node.over_turns:
            for role, kind, text in env.turn_messages(node.source):
                attrs = {"role": role, "kind": kind, "text": text}
                for n in node.body:
                    buf.append(n.text if isinstance(n, Text) else attrs[n.path.partition(".")[2]])
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
            elif attr == "purpose":
                buf.append(f.purpose)
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
        if part.get("type") == "text":
            buf.append(part.get("text", ""))
            continue
        if buf:
            out.append({"type": "text", "text": "".join(buf)})
            buf.clear()
        out.append(part)

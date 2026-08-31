"""Bake: where the adapter, the signature, and the model's facts meet.

``bake(adapter, signature, capabilities, registry)`` resolves every
decision *before* any money is spent:

- strategy predicates check declared capability facts (refuse by name),
- fields become visible (token stream) or routed (native/strategy channel),
- fragments are appended, controls merge into the request patch,
- codecs are instantiated, structured-shape fields without codecs refuse,
- template slots are validated and input coverage is checked.

The result, :class:`Baked`, does exactly two pure things: ``render`` and
``parse``. No network, no clock, no globals. ``explain()`` prints the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from . import core
from .adapter import Adapter
from .errors import refuse
from .parse import Lens, apply_routings
from .strategy import Strategy, check_predicate, resolve_role_field
from .template import render_nodes, validate_nodes


@dataclass
class _ResolvedRole:
    role: str
    field: core.Field
    strategy: Strategy
    name: str  # strategy ref name, or "(inline)"


@dataclass
class RenderResult:
    messages: list[dict]
    patch: dict = dc_field(default_factory=dict)

    def request(self) -> dict:
        return {"messages": self.messages, **self.patch}


class _Env:
    """The template's window onto the plan during one render."""

    def __init__(self, baked: "Baked", values: dict):
        self.baked = baked
        self.values = values

    @property
    def instruction(self) -> str:
        return self.baked.signature.instructions

    def loop_fields(self, source: str) -> list[core.Field]:
        return (self.baked.visible_inputs if source == "inputs"
                else self.baked.visible_outputs)

    def field_named(self, name: str) -> core.Field:
        return self.baked.signature.field_named(name)

    def schema_of(self, f: core.Field) -> str:
        codec = self.baked.codecs.get(f.name)
        if codec is not None:
            return codec.render_schema(f.shape)
        return core.shape_summary(f.shape)

    def value_of(self, f: core.Field) -> tuple[str, object]:
        if f.name not in self.values:
            refuse("missing-input", f"no value supplied for field {f.name!r}")
        value = self.baked.registry.lower_value(f.annotation, self.values[f.name])
        if core.is_media(f.shape):
            if not isinstance(value, dict):
                refuse("value-invalid",
                       f"field {f.name!r}: a media value must be a plain dict "
                       f"of part data")
            return ("part", {"kind": f.shape["media"], **value})
        return ("text", self.baked.spell(f, value))


@dataclass
class Baked:
    adapter: Adapter
    signature: core.SignatureCore
    capabilities: dict
    registry: object
    visible_inputs: list[core.Field] = dc_field(default_factory=list)
    visible_outputs: list[core.Field] = dc_field(default_factory=list)
    resolved: list[_ResolvedRole] = dc_field(default_factory=list)
    routings: list[dict] = dc_field(default_factory=list)
    fragments: dict[str, str] = dc_field(default_factory=dict)  # msg role -> text
    patch: dict = dc_field(default_factory=dict)
    codecs: dict[str, object] = dc_field(default_factory=dict)
    lens: Lens | None = None

    # ---------------------------------------------------------------- spell

    def spell(self, f: core.Field, value: object) -> str:
        codec = self.codecs.get(f.name)
        if codec is not None:
            try:
                return codec.render_value(value, f.shape)
            except Exception as exc:  # noqa: BLE001 — wrap, naming the field
                if hasattr(exc, "code"):
                    raise
                refuse("codec-render-error",
                       f"field {f.name!r}: codec failed to render: {exc}")
        return core.spell_scalar(f, value)

    def _coerce(self, f: core.Field, text: str) -> object:
        codec = self.codecs.get(f.name)
        if codec is not None:
            try:
                value = codec.parse_value(text, f.shape)
            except Exception as exc:  # noqa: BLE001
                if hasattr(exc, "code"):
                    raise
                refuse("codec-parse-error",
                       f"field {f.name!r}: codec failed to parse: {exc}")
        else:
            value = core.parse_scalar(f, text)
        return self.registry.lift_value(f.annotation, value)

    # --------------------------------------------------------------- render

    def render(self, *, inputs: dict, demos: list[dict] | None = None,
               history: list[dict] | None = None) -> RenderResult:
        messages: list[dict] = []
        fragments_done = "system" not in self.fragments
        for msg, nodes in self.adapter.compiled_messages():
            if nodes is None:
                if msg["directive"] == "demos":
                    for demo in demos or []:
                        messages.extend(self._render_demo(demo))
                else:
                    messages.extend(self._render_history(history or []))
                continue
            parts = self._render_message(nodes, inputs)
            if msg["role"] == "system" and not fragments_done:
                parts = core.merge_text_parts(
                    parts + [core.text_part("\n\n" + self.fragments["system"])])
                fragments_done = True
            if parts:
                messages.append(core.make_message(msg["role"], parts))
        if not fragments_done:
            messages.insert(0, core.make_message(
                "system", [core.text_part(self.fragments["system"])]))
        return RenderResult(messages=messages, patch=dict(self.patch))

    def _render_message(self, nodes, values: dict) -> list[dict]:
        out: list[dict] = []
        buf: list[str] = []
        render_nodes(nodes, _Env(self, values), out, buf)
        if buf:
            out.append(core.text_part("".join(buf)))
        return core.merge_text_parts(out)

    def _render_demo(self, demo: dict) -> list[dict]:
        """A demo becomes one user turn (the entry's user templates) and one
        assistant turn written BY THE LENS — the same spec that parses."""
        turns: list[dict] = []
        for msg, nodes in self.adapter.compiled_messages():
            if nodes is not None and msg["role"] == "user":
                parts = self._render_message(nodes, demo)
                if parts:
                    turns.append(core.make_message("user", parts))
        spelled = [(f.name, self.spell(f, self.registry.lower_value(
            f.annotation, demo[f.name])))
            for f in self.visible_outputs if f.name in demo]
        turns.append(core.make_message(
            "assistant", [core.text_part(self.lens.join(spelled))]))
        return turns

    def _render_history(self, history: list[dict]) -> list[dict]:
        turns = []
        for turn in history:
            role = turn.get("role")
            if role not in ("user", "assistant"):
                refuse("value-invalid",
                       f"history turn role {role!r} must be user/assistant")
            content = turn.get("content")
            parts = content if isinstance(content, list) else [core.text_part(
                str(content))]
            turns.append(core.make_message(role, parts))
        return turns

    # ---------------------------------------------------------------- parse

    def parse(self, response: object) -> dict:
        text, parts = core.response_text_and_parts(response)
        text, routed = apply_routings(text, parts, self.routings,
                                      self.registry.coercions)
        try:
            raw = self.lens.split(text, [f.name for f in self.visible_outputs])
        except Exception as exc:  # noqa: BLE001 — wrap, naming the lens
            if hasattr(exc, "code"):
                raise
            refuse("lens-parse-error",
                   f"lens {self.adapter.parse.get('kind')!r} failed to read "
                   f"the reply: {exc}")
        values: dict = {}
        for f in self.visible_outputs:
            values[f.name] = self._coerce(f, raw[f.name])
        for name, value in routed.items():
            f = self.signature.field_named(name)
            values[name] = self.registry.lift_value(
                f.annotation if f else None, value)
        return values

    # -------------------------------------------------------------- explain

    def explain(self) -> str:
        p = self.adapter.parse
        parse_line = f"parse: {p['kind']}"
        if p["kind"] == "sections":
            parse_line += f" open={p['open']!r}" + (
                f" tail={p['tail']!r}" if p.get("tail") else "")
        lines = [f"adapter: {self.adapter.name}", parse_line]
        for f in self.signature.inputs:
            note = "image/document part" if core.is_media(f.shape) else "text slot"
            lines.append(f"input  {f.name:<20} {note}")
        routed_fields = {r["field"] for r in self.routings}
        for f in self.signature.outputs:
            codec = self.adapter.codecs.get(f.name)
            if f.name in routed_fields:
                res = next((r for r in self.resolved if r.field.name == f.name), None)
                via = res.name if res else "routing"
                lines.append(f"output {f.name:<20} routed via strategy {via}"
                             f" (hidden from sections)"
                             if res and not res.strategy.visible else
                             f"output {f.name:<20} section + routing via {via}")
            else:
                spell = f"codec {codec.kind}" if codec else "kernel scalar"
                lines.append(f"output {f.name:<20} section ({spell})")
        if self.patch:
            lines.append(f"patch: {self.patch}")
        return "\n".join(lines)


# -------------------------------------------------------------------- bake


def bake(adapter: Adapter, sig: core.SignatureCore, capabilities: dict,
         registry) -> Baked:
    baked = Baked(adapter=adapter, signature=sig, capabilities=capabilities,
                  registry=registry)

    # 0. resolve the lens (refuses unknown kinds before any money is spent).
    baked.lens = registry.lens(adapter.parse)

    # 1. resolve strategies per role, in signature order.
    seen_roles: dict[str, str] = {}
    hidden: set[str] = set()
    for f in sig.fields:
        if f.role == "plain":
            continue
        if f.role in seen_roles:
            refuse("role-ambiguous",
                   f"role {f.role!r} appears on both {seen_roles[f.role]!r} and "
                   f"{f.name!r}; a role may bind to one field")
        seen_roles[f.role] = f.name
        binding = adapter.strategies.get(f.role)
        if binding is None:
            continue  # unbound role renders as a plain visible field
        if binding.ref is not None:
            strategy = registry.strategy(binding.ref, binding.options)
            name = binding.ref
        else:
            strategy, name = binding.inline, "(inline)"
        check_predicate(strategy, capabilities, role=f.role, name=name)
        strategy = resolve_role_field(strategy, f.name)
        baked.resolved.append(_ResolvedRole(f.role, f, strategy, name))
        if not strategy.visible:
            hidden.add(f.name)
        baked.routings.extend(strategy.routings)
        for msg_role, text in strategy.fragments.items():
            existing = baked.fragments.get(msg_role)
            baked.fragments[msg_role] = (existing + "\n" + text) if existing else text
        for key, value in strategy.controls.items():
            if key in baked.patch and baked.patch[key] != value:
                refuse("control-conflict",
                       f"strategies disagree on request control {key!r}")
            baked.patch[key] = value

    # 2. visibility.
    baked.visible_inputs = [f for f in sig.inputs if f.name not in hidden]
    baked.visible_outputs = [f for f in sig.outputs if f.name not in hidden]

    # 3. codecs: instantiate bindings; refuse structured shapes with none.
    for fname, binding in adapter.codecs.items():
        if sig.field_named(fname) is None:
            continue  # adapters are signature-independent; unused bindings rest
        baked.codecs[fname] = registry.codec(binding.kind, binding.options)
        baked.codecs[fname].kind = binding.kind
    for f in baked.visible_outputs + baked.visible_inputs:
        if core.is_structured(f.shape) and f.name not in baked.codecs:
            refuse("no-codec",
                   f"field {f.name!r} has a structured shape "
                   f"({f.shape.get('type')}) and no codec bound — the kernel "
                   f"only spells scalars")

    # 4. template validation + input coverage.
    known = {f.name for f in sig.fields}
    input_names = {f.name for f in baked.visible_inputs}
    covered: set[str] = set()
    for i, (msg, nodes) in enumerate(adapter.compiled_messages()):
        if nodes is None:
            continue
        covered |= validate_nodes(nodes, known_fields=known,
                                  input_fields=input_names,
                                  where=f"template.messages[{i}]")
    uncovered = input_names - covered
    if uncovered:
        refuse("field-uncovered",
               "input field(s) never rendered by the template: "
               + ", ".join(sorted(repr(n) for n in uncovered)))

    # 5. routed-but-also-visible is ambiguous; refuse.
    for r in baked.routings:
        if r["field"] in {f.name for f in baked.visible_outputs}:
            refuse("field-double-covered",
                   f"field {r['field']!r} is both a parsed section and a "
                   f"routing target — hide it (visible: false) or drop the "
                   f"routing")
    return baked

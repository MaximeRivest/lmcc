"""Bind: where the adapter, the signature, and the model's facts meet.

``bind(adapter, signature, capabilities, registry)`` resolves every
decision before any money is spent — strategies by role (``choose``,
``when``, ``requires``), visibility and placement, one format per field
by the resolution order of kernel §5, the lens, template coverage — and
refuses by name. The result, :class:`Plan`, does pure things only:
``render``, ``parse``, ``describe``, ``skeleton``, ``prefix``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from . import core, formats as _formats
from .adapter import Adapter
from .errors import Refusal, refuse
from .parse import DerivedLens, Lens, apply_routings
from .serde import KERNEL_VERSION
from .strategy import Strategy
from .template import Loop, Slot, Text, render_nodes, validate_nodes


@dataclass
class _Resolved:
    role: str
    field: core.Field
    strategy: Strategy
    name: str


@dataclass
class _FormatChoice:
    format: _formats.Format
    resolved_by: str      # "artifact:<key>" | "runtime:<type>" | "kernel"


@dataclass
class RenderResult:
    messages: list[dict]
    patch: dict = dc_field(default_factory=dict)

    def request(self) -> dict:
        return {"messages": self.messages, **self.patch}


class _Env:
    """The template's window onto the plan during one render."""

    def __init__(self, plan: "Plan", values: dict, *, partial: bool = False):
        self.plan, self.values, self.partial = plan, values, partial

    @property
    def instruction(self) -> str:
        return self.plan.signature.instructions

    @property
    def reply_format(self) -> str:
        return self.plan.reply_format()

    def loop_fields(self, source: str) -> list[core.Field]:
        if source != "inputs":
            return self.plan.visible_outputs
        if self.partial:
            return [f for f in self.plan.visible_inputs if f.name in self.values]
        return self.plan.visible_inputs

    def field_named(self, name: str) -> core.Field:
        return self.plan.signature.field_named(name)

    def schema_of(self, f: core.Field) -> str:
        return self.plan.schema_hint(f)

    def value_of(self, f: core.Field) -> tuple[str, object]:
        if f.direction == "output":
            return ("text", self.plan.placeholder(f))
        if f.name not in self.values:
            refuse("missing-input", f"no value supplied for field {f.name!r}")
        parts = self.plan.write(f, self.values[f.name])
        if len(parts) == 1 and parts[0].get("kind") == "text":
            return ("text", parts[0]["text"])
        return ("parts", parts)


@dataclass
class Plan:
    adapter: Adapter
    signature: core.SignatureCore
    capabilities: dict
    registry: object
    visible_inputs: list[core.Field] = dc_field(default_factory=list)
    visible_outputs: list[core.Field] = dc_field(default_factory=list)
    resolved: list[_Resolved] = dc_field(default_factory=list)
    routings: list[tuple[str, dict]] = dc_field(default_factory=list)   # (field, routing)
    placements: list[tuple[str, str]] = dc_field(default_factory=list)  # (field, place)
    fragments: dict[str, str] = dc_field(default_factory=dict)
    patch: dict = dc_field(default_factory=dict)
    formats: dict[str, _FormatChoice] = dc_field(default_factory=dict)
    lens: Lens | None = None

    # ---------------------------------------------------------- formats

    def format_for(self, f: core.Field) -> _formats.Format:
        return self.formats[f.name].format

    def schema_hint(self, f: core.Field) -> str:
        described = self.format_for(f).describe(f)
        if described:
            return described
        return core.shape_summary(f.shape)

    def placeholder(self, f: core.Field) -> str:
        """desc, else the format's describe, else the mechanical hint, else
        a non-kernel format's type name, else ``...`` (kernel §2, §5)."""
        if f.desc:
            return f.desc
        fmt = self.format_for(f)
        described = fmt.describe(f)
        if described:
            return described
        if self.formats[f.name].resolved_by != "kernel" and f.type:
            return f.type
        return core.shape_summary(f.shape) or "..."

    def reply_format(self) -> str:
        return self.lens.format([(f.name, self.placeholder(f)) for f in self.visible_outputs])

    def write(self, f: core.Field, value: object) -> list[dict]:
        fmt = self.format_for(f)
        try:
            written = fmt.write(value, f)
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001 — wrap, naming the field
            refuse("format-write-error", f"field {f.name!r}: format failed to write: {exc}")
        return core.as_parts(written, where=f"field {f.name!r}")

    def read(self, f: core.Field, span: core.Span) -> object:
        fmt = self.format_for(f)
        try:
            return fmt.read(span, f)
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001
            refuse("format-read-error", f"field {f.name!r}: format failed to read: {exc}")

    def _spelled_text(self, f: core.Field, value: object) -> str:
        fmt = self.format_for(f)
        if not fmt.round_trip:
            refuse("demo-not-renderable",
                   f"field {f.name!r}: format {fmt.name or '(inline)'} does not round-trip, "
                   f"so a demo written with it could not be read back")
        parts = self.write(f, value)
        if any(p.get("kind") != "text" for p in parts):
            refuse("demo-not-renderable",
                   f"field {f.name!r}: its format emits non-text parts, which a text "
                   f"pattern cannot hold")
        return "".join(p["text"] for p in parts)

    # ----------------------------------------------------------- render

    def render(self, inputs: dict | None = None, *, demos: list[dict] | None = None,
               history: list[dict] | None = None, **kw) -> RenderResult:
        inputs = {**(inputs or {}), **kw}
        return self._render(inputs, demos, history)

    def _render(self, inputs: dict, demos, history, *, stop_at: int | None = None) -> RenderResult:
        messages: list[dict] = []
        sys_fragment = self.fragments.get("system")
        fragments_done = sys_fragment is None
        sys_index = None
        for i, (msg, nodes) in enumerate(self.adapter.compiled_messages()):
            if stop_at is not None and i >= stop_at:
                break
            if nodes is None:
                if msg["directive"] == "demos":
                    for demo in demos or []:
                        messages.extend(self._render_turns(demo))
                else:
                    messages.extend(self._render_history(history or []))
                continue
            parts = self._render_message(nodes, inputs)
            if msg["role"] == "system" and not fragments_done:
                parts = core.merge_text_parts(parts + [core.text_part("\n\n" + sys_fragment)])
                fragments_done = True
            if parts:
                if msg["role"] == "system" and sys_index is None:
                    sys_index = len(messages)
                messages.append(core.make_message(msg["role"], parts))
        if not fragments_done:
            messages.insert(0, core.make_message("system", [core.text_part(sys_fragment)]))
            sys_index = 0
        for role, text in self.fragments.items():
            if role != "system":
                target = next((m for m in messages if m["role"] == role), None)
                if target is None:
                    messages.append(core.make_message(role, [core.text_part(text)]))
                else:
                    target["content"] = core.merge_text_parts(
                        target["content"] + [core.text_part("\n\n" + text)])
        patch = _deep_copy(self.patch)
        for fname, place in self.placements:
            f = self.signature.field_named(fname)
            if f.direction != "input" or fname not in inputs:
                continue
            parts = self.write(f, inputs[fname])
            if place.startswith("controls."):
                _set_path(patch, place[len("controls."):], parts)
            else:
                role = place.split(":", 1)[1]
                target = next((m for m in messages if m["role"] == role), None)
                if target is None:
                    messages.append(core.make_message(role, parts))
                else:
                    target["content"] = core.merge_text_parts(target["content"] + parts)
        return RenderResult(messages=messages, patch=patch)

    def _render_message(self, nodes, values: dict, *, partial: bool = False) -> list[dict]:
        out: list[dict] = []
        buf: list[str] = []
        render_nodes(nodes, _Env(self, values, partial=partial), out, buf)
        if buf:
            out.append(core.text_part("".join(buf)))
        return core.merge_text_parts(out)

    def _render_turns(self, example: dict) -> list[dict]:
        """A demo or history field turn: the user templates over its inputs,
        then one assistant turn written BY THE LENS — the same object that
        parses (kernel §3)."""
        turns: list[dict] = []
        for msg, nodes in self.adapter.compiled_messages():
            if nodes is not None and msg["role"] == "user":
                parts = self._render_message(nodes, example, partial=True)
                if parts:
                    turns.append(core.make_message("user", parts))
        spelled = [(f.name, self._spelled_text(f, example[f.name]))
                   for f in self.visible_outputs if f.name in example]
        turns.append(core.make_message("assistant", [core.text_part(self.lens.join(spelled))]))
        return turns

    def _render_history(self, history: list[dict]) -> list[dict]:
        turns = []
        for turn in history:
            if not isinstance(turn, dict):
                refuse("value-invalid", "history items must be objects")
            if "fields" in turn and "role" not in turn:
                if not isinstance(turn["fields"], dict):
                    refuse("value-invalid", "history field turn: 'fields' must be an object")
                turns.extend(self._render_turns(turn["fields"]))
                continue
            role = turn.get("role")
            if role not in ("user", "assistant"):
                refuse("value-invalid",
                       f"history item must be {{role: user|assistant, content}} or "
                       f"{{fields: {{...}}}}; got keys {sorted(turn)}")
            content = turn.get("content")
            parts = content if isinstance(content, list) else [core.text_part(str(content))]
            turns.append(core.make_message(role, parts))
        return turns

    def prefix(self, *, demos: list[dict] | None = None,
               history: list[dict] | None = None) -> list[dict]:
        """The rendered messages that do not depend on inputs (kernel §3):
        everything before the first message with an input slot or inputs
        loop — the cache-stable bytes."""
        stop = None
        input_names = {f.name for f in self.visible_inputs}
        for i, (msg, nodes) in enumerate(self.adapter.compiled_messages()):
            if nodes is not None and _depends_on_inputs(nodes, input_names):
                stop = i
                break
        return self._render({}, demos, history, stop_at=stop).messages

    def skeleton(self) -> dict:
        return self.lens.skeleton()

    # ------------------------------------------------------------ parse

    def parse(self, response: object) -> dict:
        text, parts = core.response_text_and_parts(response)
        text, routed = apply_routings(text, parts, self.routings)
        try:
            raw = self.lens.split(text, [f.name for f in self.visible_outputs])
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001
            refuse("lens-parse-error",
                   f"lens {self.adapter.parse.get('kind')!r} failed to read the reply: {exc}")
        values: dict = {}
        for f in self.visible_outputs:
            values[f.name] = self.read(f, core.Span.of_text(raw[f.name]))
        for name, span in routed.items():
            values[name] = self.read(self.signature.field_named(name), span)
        return values

    # ---------------------------------------------------------- describe

    def describe(self) -> dict:
        routed = {name for name, _ in self.routings}
        placed = {name for name, _ in self.placements}
        out: dict = {
            "adapter": self.adapter.name,
            "lens": {"kind": self.adapter.parse.get("kind")},
            "capabilities": dict(self.capabilities),
            "inputs": [{"name": f.name, "type": f.type, "shape": f.shape,
                        "format": self.formats[f.name].format.name or "(inline)",
                        "resolved_by": self.formats[f.name].resolved_by}
                       for f in self.visible_inputs],
            "outputs": [{"name": f.name, "type": f.type, "shape": f.shape,
                         "format": self.formats[f.name].format.name or "(inline)",
                         "resolved_by": self.formats[f.name].resolved_by,
                         "routed": f.name in routed}
                        for f in self.visible_outputs],
            "hidden": [f.name for f in self.signature.fields
                       if f not in self.visible_inputs and f not in self.visible_outputs],
            "strategies": {r.role: r.name for r in self.resolved},
            "routings": [{"field": name, **r} for name, r in self.routings],
            "placements": [{"field": name, "at": place} for name, place in self.placements],
            "fragments": dict(self.fragments),
            "patch": _deep_copy(self.patch),
            "skeleton": self.skeleton(),
        }
        if isinstance(self.lens, DerivedLens):
            out["lens"]["anchors"] = [list(a) for a in self.lens.anchors]
            if self.lens.tail:
                out["lens"]["tail"] = self.lens.tail
        elif hasattr(self.lens, "spec"):
            out["lens"].update({k: v for k, v in self.lens.spec.items() if k != "kind"})
        vocab: dict[str, str] = {}
        for choice in self.formats.values():
            named = self.registry.formats.get(choice.format.name)
            if named is not None:
                vocab[f"format/{choice.format.name}"] = named.version
        for r in self.resolved:
            named = self.registry.strategies.get(r.name)
            if named is not None:
                vocab[f"strategy/{r.name}"] = named.version
        named = self.registry.lenses.get(self.adapter.parse.get("kind"))
        if named is not None:
            vocab[f"lens/{self.adapter.parse.get('kind')}"] = named.version
        out["versions"] = {"kernel": KERNEL_VERSION, "vocab": vocab}
        _ = placed
        return out

    def explain(self) -> str:
        d = self.describe()
        lines = [f"adapter: {d['adapter']}", f"lens: {d['lens']['kind']}"]
        for f in d["inputs"]:
            lines.append(f"input  {f['name']:<20} {f['format']} ({f['resolved_by']})")
        for f in d["outputs"]:
            via = " + routing" if f["routed"] else ""
            lines.append(f"output {f['name']:<20} {f['format']} ({f['resolved_by']}){via}")
        for h in d["hidden"]:
            lines.append(f"hidden {h:<20} served by strategy/placement")
        if d["patch"]:
            lines.append(f"patch: {d['patch']}")
        return "\n".join(lines)


def _depends_on_inputs(nodes, input_names: set[str]) -> bool:
    for n in nodes:
        if isinstance(n, Slot) and (n.path in input_names):
            return True
        if isinstance(n, Loop) and (n.source == "inputs" or _depends_on_inputs(n.body, input_names)):
            return True
    return False


def _set_path(target: dict, path: str, value: object) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        target = target.setdefault(k, {})
    target[keys[-1]] = value


def _deep_copy(v):
    if isinstance(v, dict):
        return {k: _deep_copy(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_deep_copy(x) for x in v]
    return v


# ---------------------------------------------------------- derived lens


def _output_holes(nodes, sig: core.SignatureCore, holes: list) -> None:
    """Collect output holes in order: (kind, node) where kind is 'loop'
    (an outputs loop containing {var.value}) or 'slot' (a bare output)."""
    for node in nodes:
        if isinstance(node, Loop):
            if node.source == "outputs" and any(
                    isinstance(n, Slot) and n.path == f"{node.var}.value" for n in node.body):
                holes.append(("loop", node))
            else:
                _output_holes(node.body, sig, holes)
        elif isinstance(node, Slot):
            f = sig.field_named(node.path)
            if f is not None and f.direction == "output":
                holes.append(("slot", node))


def _derive_lens(plan: Plan) -> DerivedLens:
    sig = plan.signature
    found: list[tuple[int, list, list]] = []   # (message index, nodes, holes)
    for i, (_msg, nodes) in enumerate(plan.adapter.compiled_messages()):
        if nodes is None:
            continue
        holes: list = []
        _output_holes(nodes, sig, holes)
        if holes:
            found.append((i, nodes, holes))
    if not found:
        refuse("not-lensable",
               "parse kind 'derived' needs an output pattern — an outputs loop containing "
               "{f.value}, or output slots — and the template has none")
    if len(found) > 1:
        refuse("not-lensable",
               f"the output pattern must live in one message; found holes in messages "
               f"{[i for i, _, _ in found]}")
    _, nodes, holes = found[0]
    loops = [h for h in holes if h[0] == "loop"]
    if len(loops) > 1:
        refuse("not-lensable", f"the template has {len(loops)} output-pattern loops; one pattern")
    anchors: list[tuple[str, str, str]] = []
    tail = ""
    if loops:
        if len(holes) != 1:
            refuse("not-lensable", "an outputs loop and bare output slots cannot both form the pattern")
        loop = loops[0][1]
        for f in plan.visible_outputs:
            pre, post = _instantiate(loop, f, plan)
            anchors.append((f.name, pre, post))
        tail = _tail_after(nodes, loop)
    else:
        # bare output slots: the literal text between consecutive holes
        texts = _literal_segments(nodes, sig)
        for i, (_k, slot) in enumerate(holes):
            f = sig.field_named(slot.path)
            if f not in plan.visible_outputs:
                continue
            pre = texts.get(("before", slot.path), "")
            post = texts.get(("after", slot.path), "")
            anchors.append((f.name, pre, post))
    for name, prefix, _suffix in anchors:
        if not core.rstrip(prefix):
            refuse("not-lensable",
                   f"field {name!r}: no literal text before its hole — nothing anchors the "
                   f"parser; put the field's marker before the hole")
    seen: dict[str, str] = {}
    for name, prefix, _suffix in anchors:
        key = core.rstrip(prefix)
        if key in seen:
            refuse("not-lensable",
                   f"fields {seen[key]!r} and {name!r} share the anchor {key!r}; anchors "
                   f"must tell fields apart")
        seen[key] = name
    return DerivedLens(anchors, tail)


def _instantiate(loop: Loop, f: core.Field, plan: Plan) -> tuple[str, str]:
    pre: list[str] = []
    post: list[str] = []
    target = pre
    for node in loop.body:
        if isinstance(node, Text):
            target.append(node.text)
        elif isinstance(node, Slot):
            attr = node.path.partition(".")[2]
            if attr == "value":
                if target is post:
                    refuse("not-lensable",
                           "the output-pattern block has two {f.value} holes per field; "
                           "one value, one hole")
                target = post
            elif attr == "name":
                target.append(f.name)
            elif attr == "desc":
                target.append(f.desc or "")
            elif attr == "type":
                target.append(f.type or "")
            elif attr == "schema":
                target.append(plan.schema_hint(f))
            elif attr == "role":
                target.append(f.role)
            else:
                refuse("not-lensable", f"slot {{{node.path}}} inside the output pattern is not invertible")
        else:
            refuse("not-lensable", "nested loops inside the output-pattern block are not invertible")
    return "".join(pre), "".join(post)


def _tail_after(nodes, loop: Loop) -> str:
    """The literal after the outputs loop, up to the next slot and to the
    end of its line (kernel §4): the marker that ends the pattern, never
    the prose that may follow it."""
    seen = False
    out: list[str] = []
    for node in nodes:
        if node is loop:
            seen = True
            continue
        if not seen:
            continue
        if isinstance(node, Text):
            out.append(node.text)
        else:
            break
    literal = "".join(out)
    stripped = literal.lstrip("\n")
    if "\n" in stripped:
        return literal[:len(literal) - len(stripped)] + stripped.split("\n", 1)[0] + "\n"
    return literal


def _literal_segments(nodes, sig: core.SignatureCore) -> dict:
    """For bare output slots at the top level of one message: the literal
    before each hole from the later of its line start / the previous hole,
    and after it up to the earlier of the next hole / its line end (kernel
    §4: the lines whose holes are outputs are the pattern)."""
    out: dict = {}
    prev_text = ""
    last_slot: str | None = None
    for node in nodes:
        if isinstance(node, Text):
            prev_text += node.text
            continue
        if last_slot is not None:
            out[("after", last_slot)] = prev_text.split("\n", 1)[0] if "\n" in prev_text else prev_text
        if isinstance(node, Slot) and (f := sig.field_named(node.path)) and f.direction == "output":
            before = prev_text if last_slot is not None else prev_text.rsplit("\n", 1)[-1]
            out[("before", node.path)] = before
            last_slot = node.path
        else:
            last_slot = None
        prev_text = ""
    if last_slot is not None:
        out[("after", last_slot)] = prev_text.split("\n", 1)[0] if "\n" in prev_text else prev_text
    return out


# -------------------------------------------------------------- resolve


_STRUCTURAL_ORDER = ["list[object]", "list[string]", "list[integer]", "list[number]",
                     "list[boolean]", "list[enum]", "list[*]", "object", "media:*"]


def _resolve_format(plan: Plan, f: core.Field) -> _FormatChoice:
    adp, reg = plan.adapter, plan.registry

    def materialize(binding, key) -> _formats.Format:
        if isinstance(binding, dict) and "use" in binding:
            return reg.named_format(binding["use"], binding.get("options"))
        if isinstance(binding, dict):  # a shipped dict kept raw (allow_udf path already loaded)
            return _formats.load_udf(binding, where=f"formats[{key!r}]")
        return binding

    def check(fmt: _formats.Format, by: str) -> _FormatChoice:
        if not _formats.accepts(fmt, f):
            refuse("format-shape-mismatch",
                   f"field {f.name!r}: format {fmt.name or by} accepts {list(fmt.accepts)}, "
                   f"but the field's type/shape is {f.type or f.shape}")
        if fmt.direction == "in" and f.direction == "output" or (
                fmt.direction == "out" and f.direction == "input"):
            refuse("format-direction",
                   f"field {f.name!r}: format {fmt.name or by} is {fmt.direction}-only, "
                   f"but the field is an {f.direction}")
        return _FormatChoice(fmt, by)

    if f.type and f.type in adp.formats:
        return check(materialize(adp.formats[f.type], f.type), f"artifact:{f.type}")
    for key in _formats.structural_keys(f.shape):
        if key in adp.formats:
            return check(materialize(adp.formats[key], key), f"artifact:{key}")
    bound = reg.type_binding(f.annotation)
    if bound is not None:
        return check(bound, f"runtime:{f.type or core.typename(f.annotation)}")
    default = _formats.kernel_default(f.shape)
    if default is not None:
        return _FormatChoice(default, "kernel")
    if "*" in adp.formats:
        return check(materialize(adp.formats["*"], "*"), "artifact:*")
    refuse("no-format",
           f"field {f.name!r} ({f.type or f.shape}) has a structured shape and no format — "
           f"bind one in the artifact under its type name or a structural key, register "
           f"one for its type at runtime, or ship one")


# ------------------------------------------------------------------ bind


def bind(adapter: Adapter, sig: core.SignatureCore, capabilities: dict, registry) -> Plan:
    plan = Plan(adapter=adapter, signature=sig, capabilities=capabilities, registry=registry)

    # 1. strategies per role, in signature order.
    by_role: dict[str, core.Field] = {}
    for f in sig.fields:
        if f.role == "plain":
            continue
        if f.role in by_role:
            refuse("role-ambiguous",
                   f"role {f.role!r} appears on both {by_role[f.role].name!r} and {f.name!r}; "
                   f"a role may bind to one field")
        by_role[f.role] = f
    hidden: set[str] = set()
    for f in sig.fields:
        if f.role == "plain":
            continue
        binding = adapter.strategies.get(f.role)
        if binding is None:
            continue
        if isinstance(binding, Strategy):
            strategy, name = binding, "(inline)"
        else:
            name = binding["use"]
            strategy = registry.strategy(name, binding.get("options"))
        strategy = strategy.select(capabilities, role=f.role, name=name).bound(f.name)
        plan.resolved.append(_Resolved(f.role, f, strategy, name))

        def target(ref: str, what: str) -> core.Field:
            if ref == "@role":
                return f
            sub = ref[len("@role."):]
            t = by_role.get(f"{f.role}.{sub}")
            if t is None:
                refuse("unknown-slot",
                       f"role {f.role!r}: strategy {name!r} {what} targets {ref!r}, but no "
                       f"field bears the role {f.role + '.' + sub!r}")
            return t

        if not strategy.visible or strategy.placement:
            hidden.add(f.name)
        for r in strategy.routings:
            t = target(r["to"], "routing")
            plan.routings.append((t.name, {k: v for k, v in r.items() if k != "to"}))
            if t is not f:
                hidden.add(t.name)
        for ref, place in strategy.placement.items():
            t = target(ref, "placement")
            plan.placements.append((t.name, place))
            hidden.add(t.name)
        for msg_role, text in strategy.fragments.items():
            existing = plan.fragments.get(msg_role)
            plan.fragments[msg_role] = (existing + "\n" + text) if existing else text
        for key, value in strategy.controls.items():
            if key in plan.patch and plan.patch[key] != value:
                refuse("control-conflict", f"strategies disagree on request control {key!r}")
            plan.patch[key] = value

    # 2. visibility.
    plan.visible_inputs = [f for f in sig.inputs if f.name not in hidden]
    plan.visible_outputs = [f for f in sig.outputs if f.name not in hidden]

    # 3. one format per field, by the resolution order (kernel §5).
    for f in sig.fields:
        plan.formats[f.name] = _resolve_format(plan, f)
    routed_kinds: dict[str, set[str]] = {}
    for fname, r in plan.routings:
        kind = r["from"].split(":", 1)[1] if r["from"].startswith("channel:") else "text"
        routed_kinds.setdefault(fname, set()).add(kind)
    for fname, kinds in routed_kinds.items():
        fmt = plan.formats[fname].format
        if "*" not in fmt.reads and not kinds <= set(fmt.reads):
            refuse("format-span-mismatch",
                   f"field {fname!r}: routings deliver {sorted(kinds)} parts, but its format "
                   f"{fmt.name or '(inline)'} reads {list(fmt.reads)}")
    for fname, place in plan.placements:
        fmt = plan.formats[fname].format
        if place.startswith("controls.") and fmt.emits != "parts":
            refuse("format-placement-mismatch",
                   f"field {fname!r}: placement {place!r} needs parts, but its format "
                   f"{fmt.name or '(inline)'} emits text")

    # 4. the lens: derived from the template, or vocabulary; its gate and patch.
    if adapter.parse.get("kind") == "derived":
        plan.lens = _derive_lens(plan)
    else:
        plan.lens = registry.lens(adapter.parse)
    for fact in plan.lens.requires():
        if not capabilities.get(fact):
            refuse("capability-missing",
                   f"lens {adapter.parse.get('kind')!r} requires capability {fact!r}, which "
                   f"the model does not declare — use an invertible pattern instead")
    for key, value in (plan.lens.patch(plan.visible_outputs) or {}).items():
        if key in plan.patch and plan.patch[key] != value:
            refuse("control-conflict", f"lens and strategies disagree on request control {key!r}")
        plan.patch[key] = value

    # 5. template validation + input coverage.
    known = {f.name for f in sig.fields}
    input_names = {f.name for f in plan.visible_inputs}
    covered: set[str] = set()
    for i, (msg, nodes) in enumerate(adapter.compiled_messages()):
        if nodes is not None:
            covered |= validate_nodes(nodes, known_fields=known, input_fields=input_names,
                                      where=f"template[{i}]")
    uncovered = input_names - covered
    if uncovered:
        refuse("field-uncovered",
               "input field(s) never rendered by the template: "
               + ", ".join(sorted(repr(n) for n in uncovered)))

    # 6. a routed field that is also a visible section is ambiguous.
    visible_out = {f.name for f in plan.visible_outputs}
    for fname, _ in plan.routings:
        if fname in visible_out:
            refuse("field-double-covered",
                   f"field {fname!r} is both a parsed section and a routing target — hide "
                   f"it (visible: false) or drop the routing")
    return plan


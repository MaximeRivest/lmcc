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
from . import extensions as _extensions
from .parse import DerivedLens, Lens, apply_routings
from .serde import KERNEL_VERSION
import json

from .strategy import Strategy, control_leaves, spell_turn, validate_control_path
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
    """An lm15 request minus its model (kernel §3): ``system`` (text, a
    part list, or None), ``messages`` (lm15 messages), and ``patch`` (the
    partial request: ``config``, ``tools``). ``request()`` is the whole
    thing as one lm15 canonical dict, feedable to any lm15 implementation."""
    messages: list[dict]
    patch: dict = dc_field(default_factory=dict)
    system: object = None

    def request(self, model: str | None = None) -> dict:
        out: dict = {}
        if model is not None:
            out["model"] = model
        if self.system is not None:
            out["system"] = self.system
        out["messages"] = self.messages
        out.update(_deep_copy(self.patch))
        return out


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
        if len(parts) == 1 and parts[0].get("type") == "text":
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
    via: dict[str, _formats.Format] = dc_field(default_factory=dict)      # field -> the placement's own format (kernel §6)
    fragments: dict[str, str] = dc_field(default_factory=dict)
    patch: dict = dc_field(default_factory=dict)
    formats: dict[str, _FormatChoice] = dc_field(default_factory=dict)
    lens: Lens | None = None
    extensions: dict = dc_field(default_factory=dict)   # name -> extensions.Resolved (kernel §10)

    def pattern_binding(self):
        """The bound ``pattern/*`` binding, or None when the artifact declares none."""
        for r in self.extensions.values():
            if r.binding.family == "pattern":
                return r.binding
        return None

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

    def write(self, f: core.Field, value: object, *, fmt: _formats.Format | None = None) -> list[dict]:
        fmt = fmt or self.format_for(f)
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
        if any(p.get("type") != "text" for p in parts):
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
                    target["parts"] = core.merge_text_parts(
                        target["parts"] + [core.text_part("\n\n" + text)])
        patch = _deep_copy(self.patch)
        for fname, place in self.placements:
            f = self.signature.field_named(fname)
            if f.direction != "input" or fname not in inputs:
                continue
            parts = self.write(f, inputs[fname], fmt=self.via.get(fname))
            if place.startswith("controls."):
                _set_path(patch, place[len("controls."):], parts)
            else:
                role = place.split(":", 1)[1]
                target = next((m for m in messages if m["role"] == role), None)
                if target is None:
                    messages.append(core.make_message(role, parts))
                else:   # after a blank line, like a fragment (kernel §6)
                    target["parts"] = core.merge_text_parts(
                        target["parts"] + [core.text_part("\n\n")] + parts)
        system_parts = [p for m in messages if m["role"] == "system" for p in m["parts"]]
        system = None
        if system_parts:
            system = (system_parts[0]["text"] if len(system_parts) == 1
                      and system_parts[0].get("type") == "text" else system_parts)
        return RenderResult(messages=[m for m in messages if m["role"] != "system"],
                            patch=patch, system=system)

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
            role, parts = turn.get("role"), turn.get("parts")
            if role not in ("user", "assistant", "tool", "developer") or not isinstance(parts, list):
                refuse("value-invalid",
                       f"history item must be an lm15 message {{role, parts}} or a "
                       f"{{fields: {{...}}}} turn; got keys {sorted(turn)}")
            turns.append(self._spell_turn(role, list(parts)))
        return turns

    def _turns(self) -> dict[str, str]:
        for r in self.resolved:
            if r.strategy.turns:
                return r.strategy.turns
        return {}

    def _spell_turn(self, role: str, parts: list[dict]) -> dict:
        """Kernel §6 turns: a strategy with ``turns`` spells tool_call /
        tool_result parts as text; without one they pass verbatim."""
        turns = self._turns()
        if not turns:
            return core.make_message(role, parts)
        out: list[dict] = []
        for p in parts:
            if p.get("type") == "tool_call" and "call" in turns:
                out.append(core.text_part(spell_turn(turns["call"], {
                    "id": str(p.get("id", "")), "name": str(p.get("name", "")),
                    "input": _canonical_json(p.get("input", {}))})))
            elif p.get("type") == "tool_result" and "result" in turns:
                output = "\n".join(c.get("text", "") for c in p.get("content", [])
                                   if isinstance(c, dict) and isinstance(c.get("text"), str))
                out.append(core.text_part(spell_turn(turns["result"], {
                    "id": str(p.get("id", "")), "name": str(p.get("name", "")), "output": output})))
            else:
                out.append(p)
        if role == "tool" and "result" in turns:
            role = "user"
        return core.make_message(role, core.merge_text_parts(out))

    def prefix(self, *, demos: list[dict] | None = None,
               history: list[dict] | None = None) -> dict:
        """The rendered request prefix that does not depend on inputs
        (kernel §3): ``{"system"?, "messages"}`` up to the first message
        with an input slot or inputs loop — the cache-stable bytes."""
        stop = None
        input_names = {f.name for f in self.visible_inputs}
        for i, (msg, nodes) in enumerate(self.adapter.compiled_messages()):
            if nodes is not None and _depends_on_inputs(nodes, input_names):
                stop = i
                break
        rendered = self._render({}, demos, history, stop_at=stop)
        out: dict = {}
        if rendered.system is not None:
            out["system"] = rendered.system
        out["messages"] = rendered.messages
        return out

    def skeleton(self) -> dict:
        return self.lens.skeleton()

    def stream(self):
        """Create a pure, sans-I/O streaming parser (kernel §8)."""
        from .stream import Stream
        return Stream(self)

    # ------------------------------------------------------------ parse

    def _parse_with_spans(self, response: object) -> tuple[dict, dict[str, core.Span]]:
        """The one batch parse path, shared by ``parse`` and stream EOF.

        Returning spans internally lets streaming prove that its emitted
        raw deltas equal the batch captures without inventing another parser.
        """
        text, parts = core.response_text_and_parts(response)
        text, routed = apply_routings(text, parts, self.routings, self.pattern_binding())
        sufficed = any(r.get("suffices") and routed.get(name) is not None and routed[name].parts
                       for name, r in self.routings)
        try:
            raw = self.lens.split(text, [f.name for f in self.visible_outputs])
        except Refusal as err:
            if sufficed and err.code == "parse-missing-fields" and isinstance(err.partial, dict):
                raw = err.partial   # a call turn: what was found is read, the rest omitted (§6)
            else:
                raise
        except Exception as exc:  # noqa: BLE001
            refuse("lens-parse-error",
                   f"lens {self.adapter.parse.get('kind')!r} failed to read the reply: {exc}")
        spans: dict[str, core.Span] = {
            f.name: core.Span.of_text(raw[f.name]) for f in self.visible_outputs if f.name in raw}
        spans.update(routed)
        values: dict = {}
        for f in self.visible_outputs:
            if f.name in spans:
                values[f.name] = self.read(f, spans[f.name])
        for name, span in routed.items():
            values[name] = self.read(self.signature.field_named(name), span)
        return values, spans

    def parse(self, response: object) -> dict:
        values, _spans = self._parse_with_spans(response)
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
            "extensions": {n: r.describe() for n, r in sorted(self.extensions.items())},
            "routings": [{"field": name, **r} for name, r in self.routings],
            "placements": [{"field": name, "at": place} for name, place in self.placements],
            "fragments": dict(self.fragments),
            "patch": _deep_copy(self.patch),
            "skeleton": self.skeleton(),
        }
        from .stream import describe_streaming
        out["streaming"] = describe_streaming(self)
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


def _canonical_json(value) -> str:
    """Kernel §6 turns: insertion order, ``, `` and ``: `` separators,
    non-ASCII verbatim — the spelling both kernels produce."""
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _get_path(target: dict, path: str):
    for k in path.split("."):
        if not isinstance(target, dict) or k not in target:
            return _MISSING
        target = target[k]
    return target


_MISSING = object()


def _merge_control(plan, path: str, value, *, owner: str, patch_owner: dict, conflict_path: str):
    """Deep-merge one control leaf into the patch (kernel §3): the same
    value from two sources is fine; a different one is `control-conflict`,
    fixed at the later source's path."""
    existing = _get_path(plan.patch, path)
    if existing is not _MISSING and existing != value:
        refuse("control-conflict",
               f"{owner!r} and {patch_owner.get(path)!r} disagree on request control {path!r}",
               fix={"action": "edit-entry", "path": conflict_path})
    _set_path(plan.patch, path, value)
    patch_owner.setdefault(path, owner)


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
               "{f.value}, or output slots — and the template has none",
               fix={"action": "edit-template", "path": "template"})
    if len(found) > 1:
        refuse("not-lensable",
               f"the output pattern must live in one message; found holes in messages "
               f"{[i for i, _, _ in found]}",
               fix={"action": "edit-template", "path": f"template[{found[1][0]}]"})
    index, nodes, holes = found[0]
    here = {"action": "edit-template", "path": f"template[{index}]"}
    loops = [h for h in holes if h[0] == "loop"]
    if len(loops) > 1:
        refuse("not-lensable", f"the template has {len(loops)} output-pattern loops; one pattern",
               fix=here)
    anchors: list[tuple[str, str, str]] = []
    tail = ""
    if loops:
        if len(holes) != 1:
            refuse("not-lensable", "an outputs loop and bare output slots cannot both form the pattern",
                   fix=here)
        loop = loops[0][1]
        for f in plan.visible_outputs:
            pre, post = _instantiate(loop, f, plan, fix=here)
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
        # one bare slot may own the whole reply (§4) — only when it is the last
        # thing in its message; a slot with prose after it has no anchor and
        # is refused as before, never quietly reinterpreted
        whole = (not loops and len(anchors) == 1
                 and not core.strip(texts.get(("rest", holes[0][1].path), "x")))
        if not core.rstrip(prefix) and not whole:
            refuse("not-lensable",
                   f"field {name!r}: no literal text before its hole — nothing anchors the "
                   f"parser; put the field's marker before the hole",
                   fix={**here, "field": name})
    seen: dict[str, str] = {}
    for name, prefix, _suffix in anchors:
        key = core.rstrip(prefix)
        if key in seen:
            refuse("not-lensable",
                   f"fields {seen[key]!r} and {name!r} share the anchor {key!r}; anchors "
                   f"must tell fields apart",
                   fix={**here, "field": name})
        seen[key] = name
    return DerivedLens(anchors, tail)


def _instantiate(loop: Loop, f: core.Field, plan: Plan, *, fix: dict) -> tuple[str, str]:
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
                           "one value, one hole", fix=fix)
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
                refuse("not-lensable", f"slot {{{node.path}}} inside the output pattern is not invertible",
                       fix={**fix, "slot": node.path})
        else:
            refuse("not-lensable", "nested loops inside the output-pattern block are not invertible",
                   fix=fix)
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
        out[("rest", last_slot)] = prev_text      # everything to the end of the message
    return out


# -------------------------------------------------------------- resolve


_STRUCTURAL_ORDER = ["list[object]", "list[string]", "list[integer]", "list[number]",
                     "list[boolean]", "list[enum]", "list[*]", "object", "media:*"]


def _resolve_format(plan: Plan, f: core.Field) -> _FormatChoice:
    adp, reg = plan.adapter, plan.registry

    def materialize(binding, key) -> _formats.Format:
        if isinstance(binding, dict) and "use" in binding:
            return reg.named_format(binding["use"], binding.get("options"), where=f"formats[{key!r}]")
        if isinstance(binding, dict):  # a shipped dict kept raw (allow_udf path already loaded)
            return _formats.load_udf(binding, where=f"formats[{key!r}]")
        return binding

    def check(fmt: _formats.Format, by: str, key: str) -> _FormatChoice:
        rebind = {"action": "bind-format", "field": f.name, "key": key}
        if not _formats.accepts(fmt, f):
            refuse("format-shape-mismatch",
                   f"field {f.name!r}: format {fmt.name or by} accepts {list(fmt.accepts)}, "
                   f"but the field's type/shape is {f.type or f.shape}", fix=rebind)
        if fmt.direction == "in" and f.direction == "output" or (
                fmt.direction == "out" and f.direction == "input"):
            refuse("format-direction",
                   f"field {f.name!r}: format {fmt.name or by} is {fmt.direction}-only, "
                   f"but the field is an {f.direction}", fix=rebind)
        return _FormatChoice(fmt, by)

    if f.type and f.type in adp.formats:
        return check(materialize(adp.formats[f.type], f.type), f"artifact:{f.type}", f.type)
    for key in _formats.structural_keys(f.shape):
        if key in adp.formats:
            return check(materialize(adp.formats[key], key), f"artifact:{key}", key)
    bound = reg.type_binding(f.annotation)
    if bound is not None:
        return check(bound, f"runtime:{f.type or core.typename(f.annotation)}",
                     core.format_key(f.type, f.shape))
    default = _formats.kernel_default(f.shape)
    if default is not None:
        return _FormatChoice(default, "kernel")
    if "*" in adp.formats:
        return check(materialize(adp.formats["*"], "*"), "artifact:*", "*")
    refuse("no-format",
           f"field {f.name!r} ({f.type or f.shape}) has a structured shape and no format — "
           f"bind one in the artifact under its type name or a structural key, register "
           f"one for its type at runtime, or ship one",
           fix={"action": "bind-format", "field": f.name, "key": core.format_key(f.type, f.shape)})


# ------------------------------------------------------------------ bind


def bind(adapter: Adapter, sig: core.SignatureCore, capabilities: dict, registry) -> Plan:
    plan = Plan(adapter=adapter, signature=sig, capabilities=capabilities, registry=registry)
    plan.extensions = _extensions.resolve(adapter, registry)   # kernel §10, before anything else

    # 1. strategies per role, in signature order.
    by_role: dict[str, core.Field] = {}
    for f in sig.fields:
        if f.role == "plain":
            continue
        if f.role in by_role:
            refuse("role-ambiguous",
                   f"role {f.role!r} appears on both {by_role[f.role].name!r} and {f.name!r}; "
                   f"a role may bind to one field",
                   fix={"action": "edit-signature", "field": f.name, "role": f.role})
        by_role[f.role] = f
    hidden: set[str] = set()
    patch_owner: dict[str, str] = {}   # control key -> the role whose strategy set it
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
            strategy = registry.strategy(name, binding.get("options"), where=f"strategies[{f.role!r}]")
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
                       f"field bears the role {f.role + '.' + sub!r}",
                       fix={"action": "assign-role", "role": f"{f.role}.{sub}"})
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
            if ref in strategy.via:
                plan.via[t.name] = registry.named_format(
                    strategy.via[ref], {}, where=f"strategies[{f.role!r}].via")
        for msg_role, text in strategy.fragments.items():
            existing = plan.fragments.get(msg_role)
            plan.fragments[msg_role] = (existing + "\n" + text) if existing else text
        for path, value in control_leaves(strategy.controls):
            _merge_control(plan, path, value, owner=f.role, patch_owner=patch_owner,
                           conflict_path=f"strategies[{f.role!r}].controls[{path!r}]")

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
                   f"{fmt.name or '(inline)'} reads {list(fmt.reads)}",
                   fix={"action": "bind-format", "field": fname,
                        "key": core.format_key(sig.field_named(fname).type, sig.field_named(fname).shape)})
    for fname, place in plan.placements:
        fmt = plan.via.get(fname) or plan.formats[fname].format
        if place.startswith("controls.") and fmt.emits != "parts":
            refuse("format-placement-mismatch",
                   f"field {fname!r}: placement {place!r} needs parts, but its format "
                   f"{fmt.name or '(inline)'} emits text",
                   fix={"action": "bind-format", "field": fname,
                        "key": core.format_key(sig.field_named(fname).type, sig.field_named(fname).shape)})

    # 4. the lens: derived from the template, or vocabulary; its gate and patch.
    if adapter.parse.get("kind") == "derived":
        plan.lens = _derive_lens(plan)
    else:
        plan.lens = registry.lens(adapter.parse)
    for fact in plan.lens.requires():
        if not capabilities.get(fact):
            refuse("capability-missing",
                   f"lens {adapter.parse.get('kind')!r} requires capability {fact!r}, which "
                   f"the model does not declare — use an invertible pattern instead",
                   fix={"action": "declare-capability", "fact": fact})
    for path, value in control_leaves(plan.lens.patch(plan.visible_outputs) or {}):
        validate_control_path(path, where="parse")
        _merge_control(plan, path, value, owner="(lens)", patch_owner=patch_owner,
                       conflict_path=f"strategies[{patch_owner.get(path)!r}].controls[{path!r}]")
    stops = plan.lens.skeleton().get("stops") or []
    if capabilities.get("stop_sequences") and stops:
        _merge_control(plan, "config.stop", list(stops), owner="(skeleton)", patch_owner=patch_owner,
                       conflict_path=f"strategies[{patch_owner.get('config.stop')!r}].controls['config.stop']")

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
               + ", ".join(sorted(repr(n) for n in uncovered)),
               fix={"action": "edit-template", "path": "template", "field": min(uncovered)})

    # 6. a routed field that is also a visible section is ambiguous.
    visible_out = {f.name for f in plan.visible_outputs}
    for fname, _ in plan.routings:
        if fname in visible_out:
            refuse("field-double-covered",
                   f"field {fname!r} is both a parsed section and a routing target — hide "
                   f"it (visible: false) or drop the routing",
                   fix={"action": "edit-entry",
                        "path": f"strategies[{sig.field_named(fname).role!r}].visible"})

    # 7. the turns probe (kernel §6): a strategy that spells calls as text
    # must read its own spelling back through its own routing and format.
    for r in plan.resolved:
        if "call" not in r.strategy.turns:
            continue
        calls_field = next((name for name, _ in plan.routings
                            if sig.field_named(name).role == f"{r.role}.calls"), None)
        if calls_field is None:
            continue
        probe = {"id": "probe", "name": "probe", "input": {"probe": True}}
        spelled = spell_turn(r.strategy.turns["call"], {
            "id": probe["id"], "name": probe["name"], "input": _canonical_json(probe["input"])})
        own = [(name, rt) for name, rt in plan.routings if name == calls_field and rt["from"] == "text"]
        _, routed = apply_routings(spelled, [], own, plan.pattern_binding())
        read_back = None
        if routed.get(calls_field) is not None and routed[calls_field].parts:
            try:
                read_back = plan.read(sig.field_named(calls_field), routed[calls_field])
            except Refusal:
                read_back = None
        first = read_back[0] if isinstance(read_back, list) and len(read_back) == 1 else None
        if first is not None and not isinstance(first, dict) and hasattr(first, "__dataclass_fields__"):
            first = {k: getattr(first, k) for k in first.__dataclass_fields__}
        ok = (isinstance(first, dict) and first.get("name") == "probe"
              and first.get("input") == {"probe": True})
        if not ok:
            refuse("turns-drift",
                   f"role {r.role!r}: strategy {r.name!r}: turns.call spells a call as "
                   f"{spelled!r}, and its own routing/format read back {read_back!r} — the "
                   f"spelling and the reader disagree",
                   fix={"action": "edit-entry", "path": f"strategies[{r.role!r}].turns"})
    return plan


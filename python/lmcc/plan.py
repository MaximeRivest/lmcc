"""Bind: where the adapter, the signature, and the model's facts meet.

``bind(adapter, signature, capabilities, registry)`` resolves every
decision before any money is spent — transports by purpose (``choose``,
``when``, ``requires``), visibility and put, one format per field
by the resolution order of kernel §5, the reader, template coverage — and
refuses by name. The result, :class:`Plan`, does pure things only:
``render``, ``parse``, ``describe``, ``skeleton``, ``prefix``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from . import core, formats as _formats
from .adapter import Adapter
from .errors import Refusal, refuse
from . import extensions as _extensions
from .reader import (DerivedReader, Reader, apply_find_rules, refuse_missing,
                     repair_markers, repairable_markers)
from .serde import KERNEL_VERSION
import enum
import json

from .transport import Transport, setting_leaves, spell_turn, validate_setting_path
from .template import Guard, Loop, Slot, Text, render_nodes, validate_nodes
from .turn import (ModelStep, ToolStep, Turn, as_message, call_id, lift as lift_value,
                    sha256, signature_fingerprint, to_json)


@dataclass
class _Resolved:
    purpose: str
    field: core.Field
    transport: Transport
    name: str


@dataclass
class _FormatChoice:
    format: _formats.Format
    resolved_by: str      # "artifact:<key>" | "runtime:<type>" | "kernel"


@dataclass
class RenderResult:
    """An lm15 request minus its model (kernel §3): ``system`` (text, a
    part list, or None), ``messages`` (lm15 messages), and ``request_settings`` (the
    partial request: ``config``, ``tools``). ``request()`` is the whole
    thing as one lm15 canonical dict, feedable to any lm15 implementation."""
    messages: list[dict]
    request_settings: dict = dc_field(default_factory=dict)
    system: object = None
    plan: "Plan | None" = dc_field(default=None, repr=False, compare=False)
    turn: Turn | None = dc_field(default=None, repr=False, compare=False)

    def request(self, model: str | None = None) -> dict:
        out: dict = {}
        if model is not None:
            out["model"] = model
        if self.system is not None:
            out["system"] = self.system
        out["messages"] = self.messages
        out.update(_deep_copy(self.request_settings))
        return out

    def step(self, reply: object) -> Turn:
        """The reply to this request, parsed and recorded as the turn's next
        model step: values, the message as it came, and the request's hash
        (kernel §3a). Pure."""
        message = as_message(reply)
        values = self.plan.parse(reply)   # a response's finish_reason counts (§4a)
        return self.turn.with_step(ModelStep(values, message, sha256(self.request()),
                                             self.plan.calls_field))


@dataclass
class Reading:
    """A reply, read (kernel §4a): the typed ``values`` and the ``repairs``
    the reader made — misspelled markers, unclosed fields, ignored text —
    in a fixed order. ``clean`` is True when nothing was repaired."""
    values: dict
    repairs: list = dc_field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.repairs


class _WriteContext:
    """Per-render counter of model steps written as messages (kernel §3a ids)."""

    def __init__(self):
        self.model_steps = 0


class _Env:
    """The template's window onto the plan during one render."""

    def __init__(self, plan: "Plan", values: dict, *, partial: bool = False,
                 texts: dict | None = None, filled: set | None = None):
        self.plan, self.values, self.partial = plan, values, partial
        self.texts, self.filled = texts or {}, filled or set()

    def turn_messages(self, slot: str) -> list:
        return self.texts.get(slot, [])

    def slot_filled(self, slot: str) -> bool:
        """A guard's condition (kernel §3a): a placed slot with turns, or an
        input with a value (not null, "" or [])."""
        if slot in self.filled:
            return True
        if slot in self.values and self.plan.signature.field_named(slot).direction == "input":
            return self.values[slot] not in (None, "", [])
        return False

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
    find_rules: list[tuple[str, dict]] = dc_field(default_factory=list)   # (field, rule)
    puts: list[tuple[str, str]] = dc_field(default_factory=list)  # (field, place)
    written_as: dict[str, _formats.Format] = dc_field(default_factory=dict)      # field -> the put's own format (kernel §6)
    tell: dict[str, str] = dc_field(default_factory=dict)
    request_settings: dict = dc_field(default_factory=dict)
    formats: dict[str, _FormatChoice] = dc_field(default_factory=dict)
    reader: Reader | None = None
    find_repairable: list = dc_field(default_factory=list)   # §4a pass 1 delimiters
    find_unrepaired: list = dc_field(default_factory=list)
    extensions: dict = dc_field(default_factory=dict)   # name -> extensions.Resolved (kernel §10)
    turn_input_formats: dict = dc_field(default_factory=dict)   # purpose -> bound argument writer
    rule_owner: list = dc_field(default_factory=list)       # parallel to find_rules: _Resolved
    slots: dict = dc_field(default_factory=dict)               # turn slot -> (form, template index)
    calls_field: str | None = None                             # the hidden @purpose.calls output
    calls_owner: _Resolved | None = None                       # the transport that owns it
    turn_writers: dict = dc_field(default_factory=dict)        # hidden found output -> writer (§3a)
    replay_types: frozenset = frozenset()                      # part types replayed from a recorded reply

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
        return self.reader.format([(f.name, self.placeholder(f)) for f in self.visible_outputs])

    def write(self, f: core.Field, value: object, *, fmt: _formats.Format | None = None) -> list[dict]:
        fmt = fmt or self.format_for(f)
        try:
            written = fmt.write(value, f)
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001 — wrap, naming the field
            refuse("format-write-error", f"field {f.name!r}: format failed to write: {exc}")
        return core.as_parts(written, where=f"field {f.name!r}")

    def read_field(self, f: core.Field, capture: core.Capture) -> object:
        fmt = self.format_for(f)
        try:
            return fmt.read(capture, f)
        except Refusal:
            raise
        except Exception as exc:  # noqa: BLE001
            refuse("format-read-error", f"field {f.name!r}: format failed to read: {exc}")

    def _spelled_text(self, f: core.Field, value: object) -> str:
        fmt = self.format_for(f)
        if not fmt.round_trip:
            refuse("turn-not-renderable",
                   f"field {f.name!r}: format {fmt.name or '(inline)'} does not round-trip, "
                   f"so a turn written with it could not be read back")
        parts = self.write(f, value)
        if any(p.get("type") != "text" for p in parts):
            refuse("turn-not-renderable",
                   f"field {f.name!r}: its format writes non-text parts, which a text "
                   f"pattern cannot hold")
        return "".join(p["text"] for p in parts)

    # ----------------------------------------------------------- turns

    def turn(self, inputs: dict | None = None, **kw) -> Turn:
        """A new turn of this plan's signature, with no steps (kernel §3a)."""
        inputs = {**(inputs or {}), **kw}
        self._check_names(inputs, "input", "inputs")
        return Turn(self.fingerprint, dict(inputs))

    def example(self, inputs: dict, outputs: dict) -> Turn:
        """A turn that did not happen here: inputs and outputs, no steps."""
        self._check_names(inputs, "input", "inputs")
        self._check_names(outputs, "output", "outputs")
        return Turn(self.fingerprint, dict(inputs), (), dict(outputs))

    def load_turn(self, data: dict) -> Turn:
        """A turn from JSON, its values lifted to this signature's host types."""
        t = Turn.from_dict(data)
        self._check_turn(t, "turn", past=False, pending_ok=True)

        def lift_all(values: dict) -> dict:
            return {k: lift_value(self.signature.field_named(k).annotation, v)
                    for k, v in values.items()}

        steps = tuple(ModelStep(lift_all(s.outputs), s.message, s.request, s.calls_field)
                      if isinstance(s, ModelStep) else s for s in t.steps)
        return Turn(t.signature, lift_all(t.inputs), steps,
                    None if t.outputs is None else lift_all(t.outputs), t.score, dict(t.meta))

    @property
    def fingerprint(self) -> str:
        return signature_fingerprint(self.signature)

    def _check_names(self, values: object, direction: str, where: str) -> None:
        if not isinstance(values, dict):
            refuse("turn-invalid", f"{where}: an object of {direction} field values")
        known = {f.name for f in self.signature.fields if f.direction == direction}
        for k in values:
            if k not in known:
                refuse("turn-invalid", f"{where}.{k}: not an {direction} field of this signature")

    def _check_turn(self, t: object, where: str, *, past: bool, pending_ok: bool = False) -> Turn:
        if isinstance(t, dict):
            t = Turn.from_dict(t, where=where)
        if not isinstance(t, Turn):
            refuse("turn-invalid", f"{where}: expected a turn, got {type(t).__name__}")
        if t.signature != self.fingerprint:
            refuse("turn-invalid", f"{where}: recorded for signature {t.signature}, but this "
                                   f"plan's is {self.fingerprint}")
        self._check_names(t.inputs, "input", f"{where}.inputs")
        if t.outputs is not None:
            self._check_names(t.outputs, "output", f"{where}.outputs")
        pending: list = []
        for i, s in enumerate(t.steps):
            at = f"{where}.steps[{i}]"
            if isinstance(s, ModelStep):
                if pending:
                    refuse("turn-invalid", f"{at}: call {call_id(pending[0])!r} has no tool step")
                self._check_names(s.outputs, "output", f"{at}.outputs")
                pending = s.calls
            else:
                if not pending or call_id(pending[0]) != s.id:
                    refuse("turn-invalid", f"{at}: tool step {s.id!r} answers no pending call")
                pending = pending[1:]
        if pending and not pending_ok:
            refuse("turn-invalid", f"{where}: call {call_id(pending[0])!r} has no tool step"
                   + ("" if past else "; answer it with turn.tool(id, output) first"))
        return t

    # ----------------------------------------------------------- render

    def render(self, inputs: "dict | Turn | None" = None, *, turns=None, **kw) -> "RenderResult":
        """This turn, in the context of those turns (kernel §3a). ``inputs``:
        an input dict or a :class:`Turn`; ``turns``: ``{slot: [turn]}`` or a
        list for the slot ``turns``."""
        if isinstance(inputs, Turn):
            if kw:
                refuse("turn-invalid", "render a turn, or inputs — not both")
            current = self._check_turn(inputs, "turn", past=False)
        else:
            current = self.turn({**(inputs or {}), **kw})
        return self._render(current, self._slot_values(turns))

    def _slot_values(self, turns) -> dict[str, list[Turn]]:
        if turns is None:
            return {}
        if isinstance(turns, (list, tuple)):
            turns = {"turns": turns}
        if not isinstance(turns, dict):
            refuse("turn-invalid", "turns is {slot: [turn]} or a list for the slot 'turns'")
        out: dict[str, list[Turn]] = {}
        for name, ts in turns.items():
            if not ts:
                continue
            if name == "steps" or name not in self.slots:
                refuse("turns-unplaced",
                       f"turns given for slot {name!r}, which "
                       + ("is the current turn's own steps" if name == "steps"
                          else "the template does not place")
                       + f"; placed slots: {sorted(self.slots) or 'none'}")
            out[name] = [self._check_turn(t, f"turns[{name!r}][{i}]", past=True)
                         for i, t in enumerate(ts)]
        return out

    def _render(self, current: Turn, slot_values: dict, *, stop_at: int | None = None) -> "RenderResult":
        if current.steps and not self.slots:
            refuse("turns-unplaced", "the current turn has steps, but the template places no "
                                     "turn slot to write them; add lmcc.turns()")
        ctx = _WriteContext()
        # Text-form slots are spelled first: they may sit in the system message.
        text_slots = {name for name, (form, _) in self.slots.items() if form == "text"}
        texts: dict[str, list[tuple[str, str, str]]] = {}
        for name in text_slots:
            msgs = self._slot_messages(name, current, slot_values, _WriteContext())
            texts[name] = [(m["role"], kind, self._text_of(m, name)) for m, kind in msgs]
        filled = {name for name in self.slots
                  if (current.steps if name == "steps" else slot_values.get(name))}

        messages: list[dict] = []
        own: list[dict] = []    # the template's own messages: tell and puts land here
        sys_tell = self.tell.get("system")
        tell_done = sys_tell is None
        for i, (msg, nodes) in enumerate(self.adapter.compiled_messages()):
            if stop_at is not None and i >= stop_at:
                break
            if nodes is None:
                messages.extend(m for m, _ in self._slot_messages(
                    msg.get("slot", "turns"), current, slot_values, ctx))
                continue
            parts = self._render_message(nodes, current.inputs, texts=texts, filled=filled)
            if msg["role"] == "system" and not tell_done:
                parts = core.merge_text_parts(parts + [core.text_part("\n\n" + sys_tell)])
                tell_done = True
            if parts:
                messages.append(core.make_message(msg["role"], parts))
                own.append(messages[-1])
        if stop_at is None and "steps" not in self.slots and self.slots:
            messages.extend(m for m, _ in self._write_steps(current, ctx))
        if not tell_done:
            messages.insert(0, core.make_message("system", [core.text_part(sys_tell)]))
            own.append(messages[0])
        for msg_role, text in self.tell.items():
            if msg_role != "system":
                target = next((m for m in own if m["role"] == msg_role), None)
                if target is None:
                    messages.append(core.make_message(msg_role, [core.text_part(text)]))
                    own.append(messages[-1])
                else:
                    target["parts"] = core.merge_text_parts(
                        target["parts"] + [core.text_part("\n\n" + text)])
        request_settings = _deep_copy(self.request_settings)
        for fname, place in self.puts:
            f = self.signature.field_named(fname)
            if f.direction != "input" or fname not in current.inputs:
                continue
            parts = self.write(f, current.inputs[fname], fmt=self.written_as.get(fname))
            if place.startswith("request."):
                _set_path(request_settings, place[len("request."):], parts)
            else:
                role = place.split(":", 1)[1]
                target = next((m for m in own if m["role"] == role), None)
                if target is None:
                    messages.append(core.make_message(role, parts))
                    own.append(messages[-1])
                else:   # after a blank line, like tell text (kernel §6)
                    target["parts"] = core.merge_text_parts(
                        target["parts"] + [core.text_part("\n\n")] + parts)
        system_parts = [p for m in messages if m["role"] == "system" for p in m["parts"]]
        system = None
        if system_parts:
            system = (system_parts[0]["text"] if len(system_parts) == 1
                      and system_parts[0].get("type") == "text" else system_parts)
        return RenderResult(messages=[m for m in messages if m["role"] != "system"],
                            request_settings=request_settings, system=system, plan=self, turn=current)

    def _render_message(self, nodes, values: dict, *, partial: bool = False,
                        texts: dict | None = None, filled: set | None = None) -> list[dict]:
        out: list[dict] = []
        buf: list[str] = []
        render_nodes(nodes, _Env(self, values, partial=partial, texts=texts or {},
                                 filled=filled or set()), out, buf)
        if buf:
            out.append(core.text_part("".join(buf)))
        return core.merge_text_parts(out)

    @staticmethod
    def _text_of(message: dict, slot: str) -> str:
        for p in message["parts"]:
            if p.get("type") != "text":
                refuse("turn-not-renderable",
                       f"slot {slot!r} is placed as text, but a {message['role']} message of its "
                       f"turns holds a {p.get('type')!r} part, which text cannot hold; place the "
                       f"slot as messages (lmcc.turns({slot!r})) or use a text transport")
        return "".join(p["text"] for p in message["parts"])

    def _slot_messages(self, name: str, current: Turn, slot_values: dict,
                       ctx: "_WriteContext") -> list[tuple[dict, str]]:
        if name == "steps":
            return self._write_steps(current, ctx)
        out: list[tuple[dict, str]] = []
        for t in slot_values.get(name, []):
            out += [(m, "input") for m in self._user_side(t.inputs)]
            if t.steps:
                out += self._write_steps(t, ctx)
            elif t.outputs:
                message = self._model_message(ModelStep(t.outputs), ctx)
                if message is not None:
                    out.append((message, "model"))
        return out

    def _user_side(self, inputs: dict) -> list[dict]:
        """A past turn's user side: every template user message over its
        inputs (turn loops and guards render empty there)."""
        out = []
        for msg, nodes in self.adapter.compiled_messages():
            if nodes is not None and msg["role"] == "user":
                parts = self._render_message(nodes, inputs, partial=True)
                if parts:
                    out.append(core.make_message("user", parts))
        return out

    def _write_steps(self, t: Turn, ctx: "_WriteContext") -> list[tuple[dict, str]]:
        out: list[tuple[dict, str]] = []
        ids: dict = {}
        for step in t.steps:
            if isinstance(step, ModelStep):
                message, ids = self._model_message(step, ctx, with_ids=True)
                if message is not None:
                    out.append((message, "model"))
            else:
                out.append((self._tool_message(step, ids.get(step.id, step.id)), "tool"))
        return out

    def _model_message(self, step: ModelStep, ctx: "_WriteContext", *, with_ids: bool = False):
        """Kernel §3a: the recorded reply when this plan reads it back into
        the same values; else the message written from the values."""
        written = None
        if self.adapter.replay == "recorded" and step.message is not None:
            try:
                reading = self.read(step.message)
                same = to_json(reading.values) == to_json(step.outputs) and not any(
                    r["repair"] in ("marker", "unclosed", "value") for r in reading.repairs)
            except Refusal:
                same = False
            if same:
                written = core.make_message("assistant", [dict(p) for p in step.message["parts"]])
                ctx.model_steps += 1
                return (written, {}) if with_ids else written
        written, ids = self._write_model_step(step, ctx)
        return (written, ids) if with_ids else written

    def _write_model_step(self, step: ModelStep, ctx: "_WriteContext"):
        outputs = step.outputs
        recorded = (step.message or {}).get("parts", [])
        parts: list[dict] = [dict(p) for p in recorded if p.get("type") in self.replay_types]
        before: list[str] = []
        after: list[str] = []
        for fname, w in self.turn_writers.items():
            value = outputs.get(fname)
            if w["by"] in ("dropped", "projection", "replayed", "spelling.call", "format:parts") \
                    or value is None or value == "" or value == []:
                continue
            f = self.signature.field_named(fname)
            text = self._spelled_text(f, value)
            if w["by"] == "derived:between":
                open_, close = w["between"]
                if close in text:
                    refuse("value-collides", f"field {fname!r}: its written value contains "
                                             f"{close!r}, the marker that ends it")
                piece = open_ + text + close
            elif w["by"] == "derived:line_prefixed":
                piece = "\n".join(w["prefix"] + line for line in text.split("\n"))
            else:   # spelling.value
                piece = spell_turn(w["template"], {"value": text})
            (before if w["position"] == "before" else after).append(piece)
        spelled = [(f.name, self._spelled_text(f, outputs[f.name]))
                   for f in self.visible_outputs if f.name in outputs]
        body = self.reader.join(spelled) if spelled else ""
        text = "\n".join(p for p in before + [body] + after if p)
        ids: dict = {}
        calls = outputs.get(self.calls_field) if self.calls_field else None
        call_parts: list[dict] = []
        if calls:
            f = self.signature.field_named(self.calls_field)
            try:
                written = self.write(f, calls)
            except Refusal as err:
                if err.code != "format-write-error":
                    raise
                refuse("turn-not-renderable", f"field {self.calls_field!r}: {err.hint}")
            for p in written:
                if (p.get("type") != "tool_call" or not isinstance(p.get("id"), str)
                        or not isinstance(p.get("name"), str) or not isinstance(p.get("input"), dict)):
                    refuse("turn-not-renderable",
                           f"field {self.calls_field!r}: its format must write lm15 tool_call "
                           f"parts {{type, id, name, input}}; got {p!r}")
            owner = self.calls_owner
            if owner is not None and "call" in owner.transport.spelling:
                call_text = "\n".join(self._call_text(owner, p) for p in written)
                text = text + "\n" + call_text if text else call_text
            else:
                assigned = not any(p.get("type") == "tool_call" for p in recorded)
                k = ctx.model_steps
                for p in written:
                    if assigned:
                        ids[p["id"]] = f"s{k}_{p['id']}"
                        p = {**p, "id": ids[p["id"]]}
                    call_parts.append(p)
        if text:
            parts.append(core.text_part(text))
        parts += call_parts
        if not parts:
            return None, ids
        ctx.model_steps += 1
        return core.make_message("assistant", parts), ids

    def _tool_message(self, step: ToolStep, written_id: str) -> dict:
        owner = self.calls_owner
        if owner is not None and "result" in owner.transport.spelling:
            output = "\n".join(p["text"] for p in step.output
                               if p.get("type") == "text" and isinstance(p.get("text"), str))
            text = spell_turn(owner.transport.spelling["result"],
                              {"id": step.id, "name": step.name, "output": output})
            media = [dict(p) for p in step.output if p.get("type") != "text"]
            return core.make_message("user", [core.text_part(text)] + media)
        return core.make_message("tool", [{"type": "tool_result", "id": written_id,
                                           "name": step.name,
                                           "content": [dict(p) for p in step.output]}])

    def _call_text(self, resolved, call: dict) -> str:
        """One call writer, used for written turns and the bind-time sample."""
        fmt = self.turn_input_formats.get(resolved.purpose)
        if fmt is None:
            body = _canonical_json(call.get("input", {}))
        else:
            try:
                parts = core.as_parts(fmt.write(call.get("input", {}),
                    core.Field("input", "input", {"type": "object"})), where="spelling.input_format")
                if any(p.get("type") != "text" or not isinstance(p.get("text"), str) for p in parts):
                    raise ValueError("argument writer must return only text parts")
                body = "".join(p["text"] for p in parts)
            except Refusal:
                raise
            except Exception as exc:
                refuse("format-write-error", f"spelling.input_format on purpose {resolved.purpose!r}: {exc}")
        return spell_turn(resolved.transport.spelling["call"], {
            "id": str(call.get("id", "")), "name": str(call.get("name", "")), "input": body})

    def prefix(self, *, turns=None) -> dict:
        """The rendered request prefix that does not depend on inputs
        (kernel §3): ``{"system"?, "messages"}`` up to the first message
        that renders an input — the cache-stable bytes."""
        stop = None
        input_names = {f.name for f in self.visible_inputs}
        compiled = self.adapter.compiled_messages()
        for i, (msg, nodes) in enumerate(compiled):
            if nodes is not None and _depends_on_inputs(nodes, input_names):
                stop = i
                break
        # an input put into a message makes that message depend on inputs too
        put_roles = {place.split(":", 1)[1] for fname, place in self.puts
                     if place.startswith("message:")
                     and self.signature.field_named(fname).direction == "input"}
        for i, (msg, nodes) in enumerate(compiled):
            if nodes is not None and msg["role"] in put_roles:
                stop = i if stop is None else min(stop, i)
                break
        system_varies = "system" in put_roles or (stop is not None and any(
            nodes is not None and msg["role"] == "system" for msg, nodes in compiled[stop:]))
        if system_varies:        # the system leads the request: nothing before it is stable
            return {"messages": []}
        rendered = self._render(Turn(self.fingerprint, {}), self._slot_values(turns), stop_at=stop)
        out: dict = {}
        if rendered.system is not None:
            out["system"] = rendered.system
        out["messages"] = rendered.messages
        return out

    def skeleton(self) -> dict:
        return self.reader.skeleton()

    def stream(self):
        """Create a pure, sans-I/O streaming parser (kernel §8)."""
        from .stream import Stream
        return Stream(self)

    # ------------------------------------------------------------ parse

    def _parse_with_captures(self, response: object) -> tuple[dict, dict[str, core.Capture], list[dict]]:
        """The one batch parse path, shared by ``read``, ``parse`` and
        stream EOF: (values, captures, repairs).

        Returning captures internally lets streaming prove that its emitted
        raw deltas equal the batch captures without inventing another parser.
        """
        cut = core.finish_reason(response) == "length"
        text, parts = core.response_text_and_parts(response)
        repairs: list[dict] = []
        if self.find_repairable:        # §4a, pass 1: delimiters of repairing find rules
            text, repairs = repair_markers(text, self.find_repairable)
        text, found = apply_find_rules(text, parts, self.find_rules, self.pattern_binding())
        complete = any(r.get("complete_reply") and found.get(name) is not None and found[name].parts
                       for name, r in self.find_rules)
        names = [f.name for f in self.visible_outputs]
        derived = isinstance(self.reader, DerivedReader)
        to_end: set[str] = set()
        missing_err: Refusal | None = None
        try:
            if derived:
                result = self.reader.read(text, names, allow_missing=True)
                raw, to_end = result.raw, result.to_end
                repairs += result.repairs
            else:
                raw = self.reader.split(text, names)
        except Refusal as err:
            if cut and not derived:
                self._refuse_cut("", {}, why=err.hint)
            if not (err.code == "parse-missing-fields" and isinstance(err.partial, dict)):
                raise
            raw, missing_err = dict(err.partial), err
        except Exception as exc:  # noqa: BLE001
            if cut and not derived:
                self._refuse_cut("", {}, why=str(exc))
            refuse("reader-error",
                   f"reader {self.adapter.reader.get('kind')!r} failed to read the reply: {exc}")
        missing = [n for n in names if n not in raw]
        if cut:
            ended = {k: v for k, v in raw.items() if k not in to_end}
            if missing:
                self._refuse_cut(f"before field {missing[0]!r}", ended)
            if to_end:
                self._refuse_cut(f"inside field {next(n for n in names if n in to_end)!r}", ended)
            if not derived:
                self._refuse_cut("", ended)
        if missing and not complete:   # a call turn omits what it did not write (§6)
            if missing_err is not None:
                raise missing_err
            refuse_missing(raw, names)
        captures: dict[str, core.Capture] = {
            f.name: core.Capture.of_text(raw[f.name]) for f in self.visible_outputs if f.name in raw}
        captures.update(found)
        values: dict = {}
        for f in self.visible_outputs:
            if f.name in captures:
                values[f.name] = self._read_forgiving(f, captures[f.name], repairs)
        for name, capture in found.items():
            values[name] = self._read_forgiving(self.signature.field_named(name), capture, repairs)
        return values, captures, repairs

    def _read_forgiving(self, f: core.Field, capture: core.Capture, repairs: list) -> object:
        """Read one field; a kernel-default scalar read that refuses gets
        the §7a forgiving read, reported as a ``value`` repair."""
        try:
            return self.read_field(f, capture)
        except Refusal as err:
            if (self.adapter.strict or err.code != "parse-value"
                    or not isinstance(self.format_for(f), _formats.ScalarFormat)):
                raise
            value = core.forgive_value(f.shape, capture.text, where=f"field {f.name!r}")
            repairs.append({"repair": "value", "field": f.name, "saw": core.strip(capture.text),
                            "as": core.spell_value(f.shape, value, where=f"field {f.name!r}")})
            ann = f.annotation
            if isinstance(ann, type) and issubclass(ann, enum.Enum) and value is not None:
                value = ann(value)
            return value

    def _refuse_cut(self, where: str, partial: dict, *, why: str = "") -> None:
        """Kernel §4a: the provider cut the reply; say where, keep what ended."""
        if where:
            hint = f"the provider cut the reply at its length limit {where}"
        else:
            hint = (f"the provider cut the reply at its length limit; reader "
                    f"{self.adapter.reader.get('kind')!r} cannot tell which outputs ended before it")
            if why:
                hint += f" ({why})"
        refuse("parse-truncated", hint + "; raise max_tokens or ask for less", partial=partial)

    def read(self, response: object) -> Reading:
        """The typed values of a reply and every repair the reader made to
        read them (kernel §4a). Pure."""
        values, _captures, repairs = self._parse_with_captures(response)
        return Reading(values, repairs)

    def parse(self, response: object) -> dict:
        """The typed values of a reply: ``read(response).values``."""
        return self.read(response).values

    # ---------------------------------------------------------- describe

    def describe(self) -> dict:
        found = {name for name, _ in self.find_rules}
        placed = {name for name, _ in self.puts}
        out: dict = {
            "adapter": self.adapter.name,
            "reader": {"kind": self.adapter.reader.get("kind")},
            "capabilities": dict(self.capabilities),
            "inputs": [{"name": f.name, "type": f.type, "shape": f.shape,
                        "format": self.formats[f.name].format.name or "(inline)",
                        "resolved_by": self.formats[f.name].resolved_by}
                       for f in self.visible_inputs],
            "outputs": [{"name": f.name, "type": f.type, "shape": f.shape,
                         "format": self.formats[f.name].format.name or "(inline)",
                         "resolved_by": self.formats[f.name].resolved_by,
                         "found": f.name in found}
                        for f in self.visible_outputs],
            "hidden": [f.name for f in self.signature.fields
                       if f not in self.visible_inputs and f not in self.visible_outputs],
            "transports": {r.purpose: r.name for r in self.resolved},
            "extensions": {n: r.describe() for n, r in sorted(self.extensions.items())},
            "find": [{"field": name, **r} for name, r in self.find_rules],
            "puts": [{"field": name, "at": place} for name, place in self.puts],
            "tell": dict(self.tell),
            "request_settings": _deep_copy(self.request_settings),
            "strict": self.adapter.strict,
            "skeleton": self.skeleton(),
        }
        from .stream import describe_streaming
        out["streaming"] = describe_streaming(self)
        if isinstance(self.reader, DerivedReader):
            out["reader"]["anchors"] = [list(a) for a in self.reader.anchors]
            if self.reader.unrepaired:
                out["reader"]["unrepaired"] = list(self.reader.unrepaired)
            if self.reader.tail:
                out["reader"]["tail"] = self.reader.tail
        elif hasattr(self.reader, "spec"):
            out["reader"].update({k: v for k, v in self.reader.spec.items() if k != "kind"})
        vocab: dict[str, str] = {}
        for choice in self.formats.values():
            named = self.registry.formats.get(choice.format.name)
            if named is not None:
                vocab[f"format/{choice.format.name}"] = named.version
        for r in self.resolved:
            named = self.registry.transports.get(r.name)
            if named is not None:
                vocab[f"transport/{r.name}"] = named.version
        named = self.registry.readers.get(self.adapter.reader.get("kind"))
        if named is not None:
            vocab[f"reader/{self.adapter.reader.get('kind')}"] = named.version
        turn_info = {}
        for r in self.resolved:
            if r.purpose in self.turn_input_formats:
                ref = r.transport.spelling["input_format"]
                version = self.registry.formats[ref["use"]].version
                vocab[f"format/{ref['use']}"] = version
                turn_info[r.purpose] = {"input_format": _deep_copy(ref), "version": version}
        writers = {k: _deep_copy(v) for k, v in self.turn_writers.items()
                   if v["by"] not in ("projection", "replayed")}
        out["turns"] = {
            "slots": [{"name": n, "form": form} for n, (form, _) in self.slots.items()],
            "steps": (None if not self.slots else
                      "placed" if "steps" in self.slots else "after the template"),
            "replay": self.adapter.replay,
            "writers": writers,
            "projections": {k: v["of"] for k, v in self.turn_writers.items()
                            if v["by"] == "projection"},
            "replayed": sorted(k for k, v in self.turn_writers.items() if v["by"] == "replayed"),
            "input_formats": turn_info,
        }
        out["versions"] = {"kernel": KERNEL_VERSION, "vocab": vocab}
        _ = placed
        return out

    def explain(self) -> str:
        d = self.describe()
        lines = [f"adapter: {d['adapter']}", f"reader: {d['reader']['kind']}"]
        for f in d["inputs"]:
            lines.append(f"input  {f['name']:<20} {f['format']} ({f['resolved_by']})")
        for f in d["outputs"]:
            written_as = " + rule" if f["found"] else ""
            lines.append(f"output {f['name']:<20} {f['format']} ({f['resolved_by']}){written_as}")
        for h in d["hidden"]:
            lines.append(f"hidden {h:<20} served by transport/put")
        if d["request_settings"]:
            lines.append(f"request_settings: {d['request_settings']}")
        return "\n".join(lines)


def _bare_slots(nodes) -> set[str]:
    """Field names placed by bare slots, including inside guards."""
    out: set[str] = set()
    for n in nodes:
        if isinstance(n, Slot) and "." not in n.path:
            out.add(n.path)
        elif isinstance(n, Guard):
            out |= _bare_slots(n.body)
    return out


def _depends_on_inputs(nodes, input_names: set[str]) -> bool:
    for n in nodes:
        if isinstance(n, Slot) and (n.path in input_names):
            return True
        if isinstance(n, Loop) and not n.over_turns and (
                n.source == "inputs" or _depends_on_inputs(n.body, input_names)):
            return True
        if isinstance(n, Guard) and (n.slot in input_names or _depends_on_inputs(n.body, input_names)):
            return True
    return False


def _canonical_json(value) -> str:
    """Kernel §6 turns: insertion order, ``, `` and ``: `` separators,
    non-ASCII verbatim — the spelling every implementation produces."""
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _get_path(target: dict, path: str):
    for k in path.split("."):
        if not isinstance(target, dict) or k not in target:
            return _MISSING
        target = target[k]
    return target


_MISSING = object()


def _merge_setting(plan, path: str, value, *, owner: str, setting_owner: dict, conflict_path: str):
    """Deep-merge one control leaf into the request_settings (kernel §3): the same
    value from two sources is fine; a different one is `setting-conflict`,
    fixed at the later source's path."""
    existing = _get_path(plan.request_settings, path)
    if existing is not _MISSING and existing != value:
        refuse("setting-conflict",
               f"{owner!r} and {setting_owner.get(path)!r} disagree on request control {path!r}",
               fix={"action": "edit-entry", "path": conflict_path})
    _set_path(plan.request_settings, path, value)
    setting_owner.setdefault(path, owner)


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


# ---------------------------------------------------------- derived reader


def _output_holes(nodes, sig: core.SignatureCore, holes: list) -> None:
    """Collect output holes in order: (kind, node) where kind is 'loop'
    (an outputs loop containing {var.value}) or 'slot' (a bare output)."""
    for node in nodes:
        if isinstance(node, Guard):
            inner: list = []
            _output_holes(node.body, sig, inner)
            if inner:
                refuse("not-readable", "the output pattern cannot sit inside a {% if %} guard: "
                       "the reply's shape must not depend on which turns were given",
                       fix={"action": "edit-template", "path": "template"})
        elif isinstance(node, Loop) and node.over_turns:
            continue
        elif isinstance(node, Loop):
            if node.source == "outputs" and any(
                    isinstance(n, Slot) and n.path == f"{node.var}.value" for n in node.body):
                holes.append(("loop", node))
            else:
                _output_holes(node.body, sig, holes)
        elif isinstance(node, Slot):
            f = sig.field_named(node.path)
            if f is not None and f.direction == "output":
                holes.append(("slot", node))


def _derive_reader(plan: Plan) -> DerivedReader:
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
        refuse("not-readable",
               "parse kind 'derived' needs an output pattern — an outputs loop containing "
               "{f.value}, or output slots — and the template has none",
               fix={"action": "edit-template", "path": "template"})
    if len(found) > 1:
        refuse("not-readable",
               f"the output pattern must live in one message; found holes in messages "
               f"{[i for i, _, _ in found]}",
               fix={"action": "edit-template", "path": f"template[{found[1][0]}]"})
    index, nodes, holes = found[0]
    here = {"action": "edit-template", "path": f"template[{index}]"}
    loops = [h for h in holes if h[0] == "loop"]
    if len(loops) > 1:
        refuse("not-readable", f"the template has {len(loops)} output-pattern loops; one pattern",
               fix=here)
    anchors: list[tuple[str, str, str]] = []
    tail = ""
    if loops:
        if len(holes) != 1:
            refuse("not-readable", "an outputs loop and bare output slots cannot both form the pattern",
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
            hint = (f"field {name!r}: no literal text before its hole — nothing anchors the "
                    f"parser; put the field's marker before the hole")
            if not loops:
                hint += (f", on the same line: a bare slot's marker is the text on its own "
                         f"line (write 'Answer: {{{name}}}' or '<{name}>{{{name}}}</{name}>', "
                         f"not a marker on the line above), or use an outputs loop")
            refuse("not-readable", hint, fix={**here, "field": name})
    seen: dict[str, str] = {}
    for name, prefix, _suffix in anchors:
        key = core.rstrip(prefix)
        if key in seen:
            refuse("not-readable",
                   f"fields {seen[key]!r} and {name!r} share the anchor {key!r}; anchors "
                   f"must tell fields apart",
                   fix={**here, "field": name})
        seen[key] = name
    return DerivedReader(anchors, tail, repair=not plan.adapter.strict)


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
                    refuse("not-readable",
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
            elif attr == "purpose":
                target.append(f.purpose)
            else:
                refuse("not-readable", f"slot {{{node.path}}} inside the output pattern is not invertible",
                       fix={**fix, "slot": node.path})
        else:
            refuse("not-readable", "nested loops inside the output-pattern block are not invertible",
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

    # 1. transports per purpose, in signature order.
    by_purpose: dict[str, core.Field] = {}
    for f in sig.fields:
        if f.purpose == "plain":
            continue
        if f.purpose in by_purpose:
            refuse("purpose-ambiguous",
                   f"purpose {f.purpose!r} appears on both {by_purpose[f.purpose].name!r} and {f.name!r}; "
                   f"a purpose may bind to one field",
                   fix={"action": "edit-signature", "field": f.name, "purpose": f.purpose})
        by_purpose[f.purpose] = f
    hidden: set[str] = set()
    setting_owner: dict[str, str] = {}   # setting key -> the purpose whose transport set it
    for f in sig.fields:
        if f.purpose == "plain":
            continue
        binding = adapter.transports.get(f.purpose)
        if binding is None:
            continue
        if isinstance(binding, Transport):
            transport, name = binding, "(inline)"
        else:
            name = binding["use"]
            transport = registry.transport(name, binding.get("options"), where=f"transports[{f.purpose!r}]")
        transport = transport.select(capabilities, purpose=f.purpose, name=name).bound(f.name)
        res = _Resolved(f.purpose, f, transport, name)
        plan.resolved.append(res)

        def target(ref: str, what: str) -> core.Field:
            if ref == "@purpose":
                return f
            sub = ref[len("@purpose."):]
            t = by_purpose.get(f"{f.purpose}.{sub}")
            if t is None:
                refuse("unknown-slot",
                       f"purpose {f.purpose!r}: transport {name!r} {what} targets {ref!r}, but no "
                       f"field bears the purpose {f.purpose + '.' + sub!r}",
                       fix={"action": "assign-purpose", "purpose": f"{f.purpose}.{sub}"})
            return t

        if not transport.in_template or transport.put:
            hidden.add(f.name)
        for r in transport.find:
            t = target(r["to"], "rule")
            plan.find_rules.append((t.name, {k: v for k, v in r.items() if k != "to"}))
            plan.rule_owner.append(res)
            if t is not f:
                hidden.add(t.name)
            if r["to"] == "@purpose.calls" and t.direction == "output":
                plan.calls_field, plan.calls_owner = t.name, res
        for ref, place in transport.put.items():
            t = target(ref, "put")
            plan.puts.append((t.name, place))
            hidden.add(t.name)
            if ref in transport.written_as:
                plan.written_as[t.name] = registry.named_format(
                    transport.written_as[ref], {}, where=f"transports[{f.purpose!r}].written_as")
        for msg_role, text in transport.tell.items():
            existing = plan.tell.get(msg_role)
            plan.tell[msg_role] = (existing + "\n" + text) if existing else text
        for path, value in setting_leaves(transport.request_settings):
            _merge_setting(plan, path, value, owner=f.purpose, setting_owner=setting_owner,
                           conflict_path=f"transports[{f.purpose!r}].request_settings[{path!r}]")

    # 2. visibility.
    plan.visible_inputs = [f for f in sig.inputs if f.name not in hidden]
    plan.visible_outputs = [f for f in sig.outputs if f.name not in hidden]

    # 3. one format per field, by the resolution order (kernel §5).
    for f in sig.fields:
        plan.formats[f.name] = _resolve_format(plan, f)
    routed_kinds: dict[str, set[str]] = {}
    for fname, r in plan.find_rules:
        kind = r["from"].split(":", 1)[1] if r["from"].startswith("part:") else "text"
        routed_kinds.setdefault(fname, set()).add(kind)
    for fname, kinds in routed_kinds.items():
        fmt = plan.formats[fname].format
        if "*" not in fmt.reads and not kinds <= set(fmt.reads):
            refuse("format-capture-mismatch",
                   f"field {fname!r}: its find rules deliver {sorted(kinds)} parts, but its format "
                   f"{fmt.name or '(inline)'} reads {list(fmt.reads)}",
                   fix={"action": "bind-format", "field": fname,
                        "key": core.format_key(sig.field_named(fname).type, sig.field_named(fname).shape)})
    for fname, place in plan.puts:
        fmt = plan.written_as.get(fname) or plan.formats[fname].format
        if place.startswith("request.") and fmt.writes != "parts":
            refuse("format-put-mismatch",
                   f"field {fname!r}: put {place!r} needs parts, but its format "
                   f"{fmt.name or '(inline)'} writes text",
                   fix={"action": "bind-format", "field": fname,
                        "key": core.format_key(sig.field_named(fname).type, sig.field_named(fname).shape)})

    # 4. the reader: derived from the template, or vocabulary; its gate and request_settings.
    if adapter.reader.get("kind") == "derived":
        plan.reader = _derive_reader(plan)
    else:
        plan.reader = registry.reader(adapter.reader)
    # §4a pass 1: delimiters of find rules that ask to be repaired
    delimiters = [d for _, r in plan.find_rules if r.get("repair") for d in r["between"]]
    plan.find_repairable, plan.find_unrepaired = ([], []) if adapter.strict else \
        repairable_markers(delimiters)
    for fact in plan.reader.requires():
        if not capabilities.get(fact):
            refuse("capability-missing",
                   f"reader {adapter.reader.get('kind')!r} requires capability {fact!r}, which "
                   f"the model does not declare — use an invertible pattern instead",
                   fix={"action": "declare-capability", "fact": fact})
    for path, value in setting_leaves(plan.reader.request_settings(plan.visible_outputs) or {}):
        validate_setting_path(path, where="parse")
        _merge_setting(plan, path, value, owner="(reader)", setting_owner=setting_owner,
                       conflict_path=f"transports[{setting_owner.get(path)!r}].request_settings[{path!r}]")
    stops = plan.reader.skeleton().get("stops") or []
    if capabilities.get("stop_sequences") and stops:
        _merge_setting(plan, "config.stop", list(stops), owner="(skeleton)", setting_owner=setting_owner,
                       conflict_path=f"transports[{setting_owner.get('config.stop')!r}].request_settings['config.stop']")

    # 4b. a put into the request may not share a path with a fixed setting
    # or another put: the later write would silently win (plan 09 G15).
    def overlaps(a: str, b: str) -> bool:
        return a == b or a.startswith(b + ".") or b.startswith(a + ".")
    fixed = [path for path, _ in setting_leaves(plan.request_settings)]
    seen: list[tuple[str, str]] = []
    for fname, place in plan.puts:
        if not place.startswith("request."):
            continue
        path = place[len("request."):]
        where = f"transports[{sig.field_named(fname).purpose.split('.')[0]!r}].put"
        clash = next((q for q in fixed if overlaps(path, q)), None)
        other = next((g for g, q in seen if overlaps(path, q)), None)
        if clash is not None or other is not None:
            refuse("setting-conflict",
                   f"field {fname!r} is put at request {path!r}, which "
                   + (f"the request setting {clash!r} also sets" if clash is not None
                      else f"field {other!r} is also put at")
                   + " — one would silently overwrite the other",
                   fix={"action": "edit-entry", "path": where})
        seen.append((fname, path))

    # 5. template validation + input coverage.
    known = {f.name for f in sig.fields}
    input_names = {f.name for f in plan.visible_inputs}
    covered: set[str] = set()
    for i, (msg, nodes) in enumerate(adapter.compiled_messages()):
        if nodes is not None:
            covered |= validate_nodes(nodes, known_fields=known, input_fields=input_names,
                                      where=f"template[{i}]", slots=set(adapter.turn_slots()))
    uncovered = input_names - covered
    if uncovered:
        refuse("field-uncovered",
               "input field(s) never rendered by the template: "
               + ", ".join(sorted(repr(n) for n in uncovered)),
               fix={"action": "edit-template", "path": "template", "field": min(uncovered)})

    # 6. a field the template writes and a transport also carries is ambiguous:
    # an output both read from its section and found; an input both in a
    # slot and put elsewhere (it would be sent twice; plan 09 F14).
    put_inputs = {fname for fname, _ in plan.puts
                  if sig.field_named(fname).direction == "input"}
    for i, (msg, nodes) in enumerate(adapter.compiled_messages()):
        if nodes is None:
            continue
        for fname in sorted(_bare_slots(nodes) & put_inputs):
            refuse("field-double-covered",
                   f"template[{i}]: input {fname!r} has a slot here and is also put by its "
                   f"transport — it would be sent twice; drop the slot or the put",
                   fix={"action": "edit-template", "path": f"template[{i}]", "field": fname})
    visible_out = {f.name for f in plan.visible_outputs}
    for fname, _ in plan.find_rules:
        if fname in visible_out:
            refuse("field-double-covered",
                   f"field {fname!r} is both a parsed section and a rule target — hide "
                   f"it (in_template: false) or drop the rule",
                   fix={"action": "edit-entry",
                        "path": f"transports[{sig.field_named(fname).purpose!r}].in_template"})

    # 7. the turns probe (kernel §6): a transport that spells calls as text
    # must read its own spelling back through its own rule and format.
    if plan.calls_owner is not None:
        for r in plan.resolved:
            if r is not plan.calls_owner and ({"call", "result"} & set(r.transport.spelling)):
                where = f"transports[{r.purpose!r}].spelling"
                refuse("entry-malformed",
                       f"{where}: spelling.call/spelling.result belong to the transport that owns the "
                       f"calls field ({plan.calls_owner.purpose!r}); here they would be a second "
                       f"spelling of one call, or a spelling nothing uses",
                       fix={"action": "edit-entry", "path": where})
    for r in plan.resolved:
        if "call" not in r.transport.spelling:
            continue
        calls_field = next((name for name, _ in plan.find_rules
                            if sig.field_named(name).purpose == f"{r.purpose}.calls"), None)
        ref = r.transport.spelling.get("input_format")
        if ref is not None:
            where = f"transports[{r.purpose!r}].spelling.input_format"
            fmt = registry.named_format(ref["use"], ref.get("options"), where=where)
            if (fmt.writes != "text" or fmt.direction not in ("in", "both")
                    or not _formats.accepts(fmt, core.Field("input", "input", {"type": "object"}))):
                refuse("entry-malformed", f"{where}: must write an object as text",
                       fix={"action": "edit-entry", "path": where})
            plan.turn_input_formats[r.purpose] = fmt
        if calls_field is None:
            if ref is not None or "probe" in r.transport.spelling:
                refuse("spelling-drift", f"purpose {r.purpose!r}: formatted turns need an @purpose.calls target",
                       fix={"action": "edit-entry", "path": f"transports[{r.purpose!r}].spelling"})
            continue
        probe = {"id": "probe", **r.transport.spelling.get("probe", {
            "name": "probe", "input": {"probe": True}})}
        own = [(name, rt) for name, rt in plan.find_rules if name == calls_field and rt["from"] == "text"]
        read_back, spelled = None, "(writer refused)"
        try:
            spelled = plan._call_text(r, probe)
            _, found = apply_find_rules(spelled, [], own, plan.pattern_binding())
            if found.get(calls_field) is not None and found[calls_field].parts:
                read_back = plan.read_field(sig.field_named(calls_field), found[calls_field])
        except Refusal:
            read_back = None
        first = read_back[0] if isinstance(read_back, list) and len(read_back) == 1 else None
        if first is not None and not isinstance(first, dict) and hasattr(first, "__dataclass_fields__"):
            first = {k: getattr(first, k) for k in first.__dataclass_fields__}
        ok = (isinstance(first, dict) and first.get("name") == probe["name"]
              and first.get("input") == probe["input"])
        if not ok:
            refuse("spelling-drift",
                   f"purpose {r.purpose!r}: transport {r.name!r}: spelling.call spells a call as "
                   f"{spelled!r}, and its own find rule and format read back {read_back!r} — the "
                   f"spelling and the reader disagree",
                   fix={"action": "edit-entry", "path": f"transports[{r.purpose!r}].spelling"})

    # 8. turn slots (kernel §3a): layout, then a writer for every hidden output.
    plan.slots = adapter.turn_slots()
    _bind_turns(plan)
    return plan


def _bind_turns(plan: Plan) -> None:
    sig, adapter = plan.signature, plan.adapter
    compiled = adapter.compiled_messages()
    for name, (_form, i) in plan.slots.items():
        if sig.field_named(name) is not None:
            refuse("turns-layout", f"template[{i}]: turn slot {name!r} has the name of a "
                                   f"signature field; rename the slot",
                   fix={"action": "edit-template", "path": f"template[{i}]"})
    inputs = {f.name for f in plan.visible_inputs}
    live = next((i for i, (msg, nodes) in enumerate(compiled)
                 if nodes is not None and msg["role"] != "system"
                 and _depends_on_inputs(nodes, inputs)), None)
    for name, (form, i) in plan.slots.items():
        if form != "messages" or live is None:
            continue
        if name != "steps" and i > live:
            refuse("turns-layout", f"template[{i}]: turn slot {name!r} comes after the message "
                                   f"that renders the live input (template[{live}]); past turns "
                                   f"go before it",
                   fix={"action": "edit-template", "path": f"template[{i}]"})
        if name == "steps" and i < live:
            refuse("turns-layout", f"template[{i}]: the current turn's steps come after the "
                                   f"message that renders its input (template[{live}])",
                   fix={"action": "edit-template", "path": f"template[{i}]"})
    if not plan.slots:
        return

    def drift(field: str, owner: _Resolved, why: str) -> None:
        refuse("spelling-drift", f"field {field!r}: {why}",
               fix={"action": "edit-entry", "path": f"transports[{owner.purpose!r}].spelling"})

    groups: dict[tuple, list[tuple[str, dict, _Resolved]]] = {}
    replay_types: set[str] = set()
    for (fname, r), owner in zip(plan.find_rules, plan.rule_owner):
        if sig.field_named(fname).direction != "output":
            continue
        if r["from"].startswith("part:"):
            key = ("channel", r["from"])
        else:
            key = next((k, json.dumps(r[k])) for k in ("between", "line_prefixed", "pattern") if k in r)
        groups.setdefault(key, []).append((fname, r, owner))
    for key, members in groups.items():
        names = [m[0] for m in members]
        if key[0] != "channel":
            continue
        if plan.calls_field in names:       # read from the calls' own parts: projections
            plan.turn_writers[plan.calls_field] = {"by": "format:parts"}
            for other in names:
                if other != plan.calls_field:
                    plan.turn_writers[other] = {"by": "projection", "of": plan.calls_field}
        else:                               # opaque: replayed from the recorded message
            replay_types.add(key[1].split(":", 1)[1])
            for name in names:
                plan.turn_writers[name] = {"by": "replayed"}
    plan.replay_types = frozenset(replay_types)
    for key, members in groups.items():
        if key[0] == "channel":
            continue
        names = [m[0] for m in members]
        if plan.calls_field in names:
            owner = plan.calls_owner
            if "call" not in owner.transport.spelling:
                drift(plan.calls_field, owner, "calls are read from text, but the transport "
                      "has no spelling.call to write past calls")
            plan.turn_writers[plan.calls_field] = {"by": "spelling.call", "position": "after"}
            for other in names:
                if other != plan.calls_field:
                    plan.turn_writers[other] = {"by": "projection", "of": plan.calls_field}
            continue
        if len(set(names)) > 1:
            drift(names[1], members[1][2], f"fields {sorted(set(names))} read the same capture "
                  f"and none of them is the calls field; which writes it is ambiguous")
        fname, r, owner = members[0]
        spelling = owner.transport.spelling
        position = spelling.get("position", "after")
        if "value" in spelling:
            plan.turn_writers[fname] = ({"by": "dropped"} if spelling["value"] is None else
                                        {"by": "spelling.value", "template": spelling["value"],
                                         "position": position})
        elif not r.get("remove"):
            plan.turn_writers[fname] = {"by": "projection", "of": "the reader body"}
            continue
        elif "between" in r:
            plan.turn_writers[fname] = {"by": "derived:between", "between": list(r["between"]),
                                        "position": position}
        elif "line_prefixed" in r:
            plan.turn_writers[fname] = {"by": "derived:line_prefixed",
                                        "prefix": r["line_prefixed"], "position": position}
        else:
            drift(fname, owner, "a pattern rule has a reader but no writer; declare "
                  "spelling.value (text with {value}) or spelling.value: null to drop it on purpose")
        if plan.turn_writers[fname]["by"] != "dropped":
            fmt = plan.format_for(sig.field_named(fname))
            if not fmt.round_trip or fmt.writes != "text" or fmt.direction not in ("both", "in"):
                drift(fname, owner, f"its format {fmt.name or '(inline)'} cannot write the value "
                      f"back as text (it reads only, is lossy, or writes parts), so a past value "
                      f"cannot be written into a turn; give it a write, or spelling.value: null")
    if plan.calls_field is not None:
        fmt = plan.format_for(sig.field_named(plan.calls_field))
        if fmt.direction not in ("both", "in"):
            drift(plan.calls_field, plan.calls_owner,
                  f"its format {fmt.name or '(inline)'} only reads, so past calls cannot be written")


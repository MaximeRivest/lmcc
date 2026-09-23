"""The turn record (kernel §3a): one record for examples, past exchanges, and the
exchange in progress.

A :class:`Turn` is one call of one signature: its inputs, its steps (model
replies and tool results, in order) and, once finished, its outputs — all
kept as values. The plan writes turns into requests with its own writers
(``plan.render``); this module is only the record: construction,
validation that needs no plan, and JSON.

Records are immutable: every operation returns a new turn.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import typing
from dataclasses import dataclass, field as dc_field, replace

from . import core
from .errors import refuse

__all__ = ["Turn", "ModelStep", "ToolStep", "canonical_json", "sha256",
           "signature_fingerprint"]


# ------------------------------------------------------------------ identity

def canonical_json(value: object) -> str:
    """Kernel §3a: keys sorted by code point, no whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def signature_fingerprint(sig: core.SignatureCore) -> str:
    """Which signature a turn belongs to: each field's direction, name,
    purpose, shape and type, in order. Instructions and descriptions are left
    out, so editing or optimizing prose does not orphan recorded turns."""
    return sha256([{"direction": f.direction, "name": f.name, "purpose": f.purpose or "plain",
                    "shape": f.shape, "type": f.type or ""} for f in sig.fields])


# ------------------------------------------------------------------ values

def to_json(value: object, *, where: str = "turn") -> object:
    """A host value as the JSON its field's shape describes."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name), where=f"{where}.{f.name}")
                for f in dataclasses.fields(value)}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                refuse("turn-invalid", f"{where}: object keys must be strings, got {k!r}")
            out[k] = to_json(v, where=f"{where}.{k}")
        return out
    if isinstance(value, (list, tuple)):
        return [to_json(v, where=f"{where}[{i}]") for i, v in enumerate(value)]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            refuse("turn-invalid", f"{where}: {value!r} has no JSON form")
        return value
    refuse("turn-invalid", f"{where}: a {type(value).__name__} has no JSON form; "
                           f"a turn holds JSON values in their fields' shapes")


def lift(annotation: object, data: object) -> object:
    """JSON → a host value, guided by a field's annotation (Python host
    side; unknown annotations return the data unchanged)."""
    if annotation is None or data is None:
        return data
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return lift(args[0], data)
    if origin is typing.Union or getattr(origin, "__name__", "") == "UnionType":
        real = [a for a in args if a is not type(None)]
        return lift(real[0], data) if len(real) == 1 else data
    if origin in (list, typing.List) and isinstance(data, list) and args:
        return [lift(args[0], v) for v in data]
    if origin in (dict, typing.Dict) and isinstance(data, dict) and len(args) == 2:
        return {k: lift(args[1], v) for k, v in data.items()}
    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            return annotation(data)
        if dataclasses.is_dataclass(annotation) and isinstance(data, dict):
            hints = typing.get_type_hints(annotation)
            return annotation(**{f.name: lift(hints.get(f.name), data[f.name])
                                 for f in dataclasses.fields(annotation) if f.name in data})
        validate = getattr(annotation, "model_validate", None)
        if callable(validate) and isinstance(data, (dict, str)):
            return validate(data)
    return data


def _get(obj: object, key: str) -> object:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def call_id(call: object) -> object:
    return _get(call, "id")


def call_name(call: object) -> object:
    return _get(call, "name")


def as_message(reply: object) -> dict:
    """Parse input (a text, an lm15 message or response) as an lm15 message."""
    if isinstance(reply, str):
        return {"role": "assistant", "parts": [core.text_part(reply)]}
    if isinstance(reply, dict) and isinstance(reply.get("message"), dict):
        reply = reply["message"]
    if isinstance(reply, dict) and isinstance(reply.get("parts"), list):
        return {"role": reply.get("role", "assistant"), "parts": [dict(p) if isinstance(p, dict) else p
                                                                   for p in reply["parts"]]}
    refuse("response-malformed",
           "a reply is text, an lm15 message {role, parts}, or an lm15 response {message: ...}")


# ------------------------------------------------------------------ records

@dataclass(frozen=True)
class ModelStep:
    """One model reply: the values the plan parsed, the message as it came
    (for verbatim replay and opaque parts), the hash of the request it
    answered, and which output holds its calls."""
    outputs: dict
    message: dict | None = None
    request: str | None = None
    calls_field: str | None = None
    kind: str = dc_field(default="model", init=False)

    @property
    def calls(self) -> list:
        value = self.outputs.get(self.calls_field) if self.calls_field else None
        return list(value) if isinstance(value, (list, tuple)) else []

    def to_dict(self) -> dict:
        out: dict = {"kind": "model", "outputs": to_json(self.outputs, where="step.outputs")}
        if self.message is not None:
            out["message"] = self.message
        if self.request is not None:
            out["request"] = self.request
        if self.calls_field is not None:
            out["calls_field"] = self.calls_field
        return out


@dataclass(frozen=True)
class ToolStep:
    """One tool result, answering one call: lm15 parts (text, images, …),
    and the turns made while producing it (never written into a prompt)."""
    id: str
    name: str
    output: tuple
    children: tuple = ()
    kind: str = dc_field(default="tool", init=False)

    def to_dict(self) -> dict:
        out: dict = {"kind": "tool", "id": self.id, "name": self.name, "output": list(self.output)}
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out


def _output_parts(output: object) -> tuple:
    if isinstance(output, str):
        return (core.text_part(output),)
    if not isinstance(output, (list, tuple)):
        refuse("turn-invalid", "a tool output is a text or a list of lm15 parts")
    for p in output:
        if not isinstance(p, dict) or not isinstance(p.get("type"), str):
            refuse("turn-invalid", f"a tool output part must be an lm15 part with a type, got {p!r}")
    return tuple(dict(p) for p in output)


@dataclass(frozen=True)
class Turn:
    """One call of one signature (kernel §3a). Build with ``plan.turn`` or
    ``plan.example``; advance with ``rendered.step``, ``tool`` and
    ``finish``."""
    signature: str
    inputs: dict
    steps: tuple = ()
    outputs: dict | None = None
    score: float | None = None
    meta: dict = dc_field(default_factory=dict)

    # -- progress
    def pending_calls(self) -> list:
        """Calls of the last model step that no tool step has answered yet."""
        pending: list = []
        for step in self.steps:
            if isinstance(step, ModelStep):
                pending = step.calls
            elif pending and call_id(pending[0]) == step.id:
                pending = pending[1:]
        return pending

    def tool(self, id: str, output, *, children=()) -> "Turn":
        """Answer the next pending call. ``output``: a text or lm15 parts."""
        pending = self.pending_calls()
        if not pending:
            refuse("turn-invalid", f"tool result {id!r} answers no pending call")
        if call_id(pending[0]) != id:
            refuse("turn-invalid", f"tool result {id!r} is out of order: the next pending "
                                   f"call is {call_id(pending[0])!r}")
        for c in children:
            if not isinstance(c, Turn):
                refuse("turn-invalid", "tool step children are turns")
        step = ToolStep(str(id), str(call_name(pending[0])), _output_parts(output), tuple(children))
        return replace(self, steps=self.steps + (step,))

    def finish(self) -> "Turn":
        """Close the turn: its outputs are the last model step's."""
        if self.pending_calls():
            refuse("turn-invalid", f"cannot finish with unanswered call "
                                   f"{call_id(self.pending_calls()[0])!r}")
        last = next((s for s in reversed(self.steps) if isinstance(s, ModelStep)), None)
        if last is None:
            refuse("turn-invalid", "cannot finish a turn with no model step")
        return replace(self, outputs=dict(last.outputs))

    @property
    def done(self) -> bool:
        return self.outputs is not None

    def with_step(self, step: ModelStep | ToolStep) -> "Turn":
        return replace(self, steps=self.steps + (step,))

    # -- JSON (schema/turn.schema.json)
    def to_dict(self) -> dict:
        out: dict = {"signature": self.signature,
                     "inputs": to_json(self.inputs, where="turn.inputs"),
                     "steps": [s.to_dict() for s in self.steps]}
        if self.outputs is not None:
            out["outputs"] = to_json(self.outputs, where="turn.outputs")
        if self.score is not None:
            out["score"] = self.score
        if self.meta:
            out["meta"] = to_json(self.meta, where="turn.meta")
        return out

    @classmethod
    def from_dict(cls, data: object, *, where: str = "turn") -> "Turn":
        """JSON → a turn with JSON values. ``plan.load_turn`` also lifts the
        values to the signature's host types."""
        if not isinstance(data, dict):
            refuse("turn-invalid", f"{where}: a turn is an object")
        unknown = set(data) - {"signature", "inputs", "steps", "outputs", "score", "meta"}
        if unknown:
            refuse("turn-invalid", f"{where}: unknown key(s) {sorted(unknown)}")
        sig, inputs = data.get("signature"), data.get("inputs")
        if not isinstance(sig, str) or not isinstance(inputs, dict):
            refuse("turn-invalid", f"{where}: a turn needs a signature fingerprint and an "
                                   f"inputs object")
        outputs = data.get("outputs")
        if outputs is not None and not isinstance(outputs, dict):
            refuse("turn-invalid", f"{where}.outputs: an object or null")
        steps = []
        for i, s in enumerate(data.get("steps") or []):
            at = f"{where}.steps[{i}]"
            if not isinstance(s, dict) or s.get("kind") not in ("model", "tool"):
                refuse("turn-invalid", f"{at}: a step is {{kind: model|tool, ...}}")
            if s["kind"] == "model":
                if set(s) - {"kind", "outputs", "message", "request", "calls_field"} or \
                        not isinstance(s.get("outputs"), dict):
                    refuse("turn-invalid", f"{at}: a model step is {{kind, outputs, message?, "
                                           f"request?, calls_field?}}")
                message = s.get("message")
                if message is not None:
                    message = as_message(message)
                    for p in message["parts"]:
                        core.validate_response_part(p)
                steps.append(ModelStep(dict(s["outputs"]), message, s.get("request"),
                                       s.get("calls_field")))
            else:
                if set(s) - {"kind", "id", "name", "output", "children"} or not all(
                        isinstance(s.get(k), str) and s[k] for k in ("id", "name")):
                    refuse("turn-invalid", f"{at}: a tool step is {{kind, id, name, output, "
                                           f"children?}}")
                children = tuple(cls.from_dict(c, where=f"{at}.children[{j}]")
                                 for j, c in enumerate(s.get("children") or []))
                steps.append(ToolStep(s["id"], s["name"], _output_parts(s.get("output", [])),
                                      children))
        meta = data.get("meta") or {}
        if not isinstance(meta, dict):
            refuse("turn-invalid", f"{where}.meta: an object")
        return cls(sig, dict(inputs), tuple(steps), None if outputs is None else dict(outputs),
                   data.get("score"), dict(meta))

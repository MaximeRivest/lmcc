"""Standard readers: json_object.

A reader is one *document form* for the whole reply. ``json_object`` reads
the reply as a single JSON object keyed by field name — the JSON-adapter
style. Normative behavior (fences, the embed rule, re-serialization) lives
in contract/spec/vocab/reader-json_object.md and is pinned by corpus cases.
"""

from __future__ import annotations

from lmcc import core
from lmcc.errors import refuse
from lmcc.reader import Reader

from . import jsontext

VERSION = "0.2.0"
PROBABILITY_POLICIES = ("off", "if_available", "required")   # lm15 ProbabilityPolicy


class JsonObjectReader(Reader):
    """The reply is one JSON object; each in_template output field is a member.

    **This is a mode, not a template style.** A JSON object is a meaning
    with many spellings, so this document form is only honest when the
    provider itself enforces it: baking refuses without the declared
    ``native_structured_output`` capability, and the reader patches the
    request with ``response_format`` + a schema built from the in_template
    output fields. Without that capability, use invertible markers and
    put JSON *inside* typed fields written_as codecs.

    Reading:
    - The document is the whole text, else the body of one markdown fence,
      else the first ``{`` … last ``}`` substring. Anything else refuses
      ``reader-error``; so does a document that is not a JSON object.
    - A string member is the field's raw text verbatim. Any other member
      is handed over as its **source text** — the field's codec or scalar
      rule then parses that raw text, so ``{"rows": [1, 2]}`` feeds a json
      codec ``[1, 2]`` and ``{"score": 9}`` feeds the kernel integer rule
      ``9``, digits and spacing exactly as the model wrote them.
    - Unknown members are ignored; a field's key appearing twice refuses
      ``parse-ambiguous``. Missing fields refuse ``parse-missing-fields``
      with the recovered raw values in ``.partial``.

    Writing (turns): spelled text that parses as **non-string** JSON embeds
    as that JSON value; anything else embeds as a JSON string. The document
    is the object with two-space indentation, members in field order.
    The non-string guard makes write∘read the identity on raw text.
    """

    def __init__(self, spec: dict):
        extra = set(spec) - {"kind", "probabilities"}
        policy = spec.get("probabilities")
        if extra or (policy is not None and policy not in PROBABILITY_POLICIES):
            refuse("entry-malformed",
                   f"reader: json_object takes 'probabilities' ({' | '.join(PROBABILITY_POLICIES)})"
                   + (f", not {sorted(extra)}" if extra else f", not {policy!r}"),
                   fix={"action": "edit-entry", "path": "reader"})
        self.spec = dict(spec)

    # ---------------------------------------------------------------- mode

    def requires(self) -> list[str]:
        return ["native_structured_output"]

    def request_settings(self, fields: list) -> dict:
        policy = self.spec.get("probabilities")
        extra = {"probabilities": policy} if policy is not None else {}
        return {"config": {**self._response_format(fields), **extra}}

    def _response_format(self, fields: list) -> dict:
        return {"response_format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {f.name: dict(f.shape) for f in fields},
                "required": [f.name for f in fields],
                "additionalProperties": False,
            },
        }}

    # ---------------------------------------------------------------- read

    def split(self, text: str, field_names: list[str]) -> dict[str, str]:
        members = self._document(text)
        wanted = set(field_names)
        raw: dict[str, str] = {}
        for key, value, source in members:
            if key not in wanted:
                continue
            if key in raw:
                refuse("parse-ambiguous",
                       f"json_object: member {key!r} appears more than once "
                       f"in the reply — refusing to guess which one is real")
            raw[key] = value if isinstance(value, str) else core.strip(source)
        missing = [n for n in field_names if n not in raw]
        if missing:
            refuse("parse-missing-fields",
                   "reply object is missing key(s): "
                   + ", ".join(repr(n) for n in missing), partial=raw)
        return raw

    def _document(self, text: str) -> list[tuple[str, object, str]]:
        t = core.strip(text)
        if t.startswith("```"):
            first_nl = t.find("\n")
            closing = t.rfind("```")
            if first_nl >= 0 and closing > first_nl:
                t = core.strip(t[first_nl + 1:closing])
        try:
            return jsontext.members(t)
        except ValueError as first:
            start, end = t.find("{"), t.rfind("}")
            if not (0 <= start < end):
                refuse("reader-error",
                       f"json_object: reply contains no JSON object ({first})")
            try:
                return jsontext.members(t[start:end + 1])
            except ValueError as exc:
                refuse("reader-error",
                       f"json_object: reply is not a JSON object: {exc}")

    # --------------------------------------------------------------- write

    def join(self, spelled: list[tuple[str, str]]) -> str:
        obj: dict[str, object] = {}
        for name, text in spelled:
            value: object = text
            try:
                parsed = jsontext.loads(text)
            except ValueError:
                pass
            else:
                if not isinstance(parsed, str):
                    value = parsed
            obj[name] = value
        return jsontext.dumps(obj, indent=2)


def install(registry, *, exist_ok: bool = True) -> None:
    registry.register_reader("json_object", JsonObjectReader, version=VERSION,
                           exist_ok=exist_ok)

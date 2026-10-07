"""A host type's JSON form, both ways (kernel §3a: a turn holds JSON; a host
lifts it back to its own types): ``lmcc.format(T, to_json=..., from_json=...)``,
``lmcc.turn.to_json`` and ``lmcc.turn.lift``, ``plan.load_turn``. The rule
under test: the format bound to a type receives the type itself, live or
replayed; every other format receives its JSON form."""

import base64
import dataclasses

import pytest

import lmcc
import lmcc_std
from lmcc.turn import lift, to_json

TAGS = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.turns(),
    lmcc.user("{% for f in inputs %}{f.value}\n{% endfor %}")])


class Pages(list):
    """A document converter's result: pages of {"text": str, "png": bytes}.
    Raw bytes have no JSON form; the binding gives it one."""


def pages_to_json(pages):
    return [{"text": p["text"], "png": base64.b64encode(p["png"]).decode()} for p in pages]


def pages_from_json(data):
    return Pages({"text": p["text"], "png": base64.b64decode(p["png"])} for p in data)


def registry_with_pages(seen):
    reg = lmcc.Registry()

    def write(pages):
        seen.append(type(pages))
        return [{"type": "text", "text": p["text"]} for p in pages] + \
               [{"type": "image", "media_type": "image/png", "data": base64.b64encode(p["png"]).decode()}
                for p in pages]

    reg.format(Pages, write=write, writes="parts", to_json=pages_to_json, from_json=pages_from_json)
    return reg


DOC = Pages([{"text": "page 1", "png": b"\x89PNG"}])


def test_a_registered_type_is_written_saved_lifted_and_written_again_the_same():
    seen: list = []
    reg = registry_with_pages(seen)

    @lmcc.fn(registry=reg)
    def summary(document: Pages) -> str:
        """Summarize."""

    plan = summary.bind(TAGS, capabilities={"instruct": True}, registry=reg)
    live = plan.render(document=DOC)
    turn = live.step("<summary>\nOne page.\n</summary>").finish()
    data = turn.to_dict(registry=reg)
    assert data["inputs"] == {"document": [{"text": "page 1", "png": "iVBORw=="}]}

    replayed = plan.load_turn(data)
    assert type(replayed.inputs["document"]) is Pages and replayed.inputs["document"] == DOC
    # the same turn, live or replayed from its JSON, writes the same request
    assert plan.render(document=DOC, turns=[turn]).request("m") == \
        plan.render(document=DOC, turns=[replayed]).request("m")
    assert seen and set(seen) == {Pages}   # its own format never saw a list of base64


def test_without_a_registry_argument_the_default_registry_is_used():
    lmcc.format(Pages, write=lambda v: "x", to_json=pages_to_json, from_json=pages_from_json)
    try:
        assert to_json(DOC) == [{"text": "page 1", "png": "iVBORw=="}]
        assert type(lift(Pages, to_json(DOC))) is Pages
    finally:
        lmcc.default_registry.host_types[:] = [h for h in lmcc.default_registry.host_types
                                               if h.host_type is not Pages]


def test_lift_rebuilds_a_model_from_any_json_kind():
    """Issue #4: model_validate was tried only for an object or a text."""

    class Tags(list):
        @classmethod
        def model_validate(cls, data):
            return cls(data)

    class Celsius(float):
        @classmethod
        def model_validate(cls, data):
            return cls(data)

    assert type(lift(Tags, ["a", "b"])) is Tags
    assert type(lift(Celsius, 21.5)) is Celsius
    assert lift(Tags, None) is None


def test_other_formats_receive_the_json_form():
    """A type bound with only its shape and JSON form crosses by the format
    its shape resolves, which receives the JSON form."""

    @dataclasses.dataclass
    class Picture:
        png: bytes

    reg = lmcc.Registry()
    reg.format(Picture, shape={"media": "image"},
               to_json=lambda p: {"media_type": "image/png", "data": base64.b64encode(p.png).decode()},
               from_json=lambda d: Picture(base64.b64decode(d["data"])))

    @lmcc.fn(registry=reg)
    def colour(picture: Picture) -> str:
        """The main colour."""

    assert colour.signature.fields[0].shape == {"media": "image"}   # the declared shape wins
    plan = colour.bind(TAGS, capabilities={"instruct": True}, registry=reg)
    assert plan.describe()["inputs"][0]["resolved_by"] == "kernel"
    parts = plan.render(picture=Picture(b"\x89PNG")).request("m")["messages"][0]["parts"]
    assert parts[0] == {"type": "image", "media_type": "image/png", "data": "iVBORw=="}

    # an artifact's format gets the JSON form too: std json for the object shape
    std = lmcc.Registry()
    lmcc_std.install(std)
    std.format(Picture, shape={"type": "object"}, to_json=lambda p: {"bytes": len(p.png)})
    j = lmcc.adapter(messages=TAGS.template, formats={"object": {"use": "json"}})

    @lmcc.fn(registry=std)
    def size(picture: Picture) -> str:
        """Say the size."""

    text = size.bind(j, capabilities={"instruct": True}, registry=std).render(
        picture=Picture(b"abc")).request("m")["messages"][0]["parts"][0]["text"]
    assert '"bytes": 3' in text


def test_binding_a_type_again_replaces_it_and_a_binding_needs_something():
    reg = lmcc.Registry()
    reg.format(Pages, write=lambda v: "one")
    reg.format(Pages, write=lambda v: "two", to_json=pages_to_json)
    assert len(reg.host_types) == 1
    assert reg.type_binding(Pages).write(DOC, None) == "two"
    assert reg.describe()["type_bindings"] == [
        {"type": "Pages", "format": "(inline)", "shape": {}, "json": ["to_json"]}]
    with pytest.raises(lmcc.Refusal) as err:
        reg.format(Pages)
    assert err.value.code == "entry-malformed"
    with pytest.raises(lmcc.Refusal) as err:
        reg.format(Pages, read=lambda c: c, shape={})
    assert err.value.code == "entry-malformed"
    with pytest.raises(lmcc.Refusal) as err:
        reg.format(Pages, write=lambda v: "", to_json="not a function")
    assert err.value.code == "entry-malformed" and err.value.fix == {"action": "edit-entry", "path": "to_json"}


def test_failures_name_the_value():
    def broken(_):
        raise ValueError("boom")

    reg = lmcc.Registry()
    reg.format(Pages, shape={"media": "image"}, to_json=broken, from_json=broken)

    @lmcc.fn(registry=reg)
    def summary(document: Pages) -> str:
        """Summarize."""

    plan = summary.bind(TAGS, capabilities={"instruct": True}, registry=reg)
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(document=DOC)
    assert err.value.code == "format-write-error" and "boom" in err.value.hint
    with pytest.raises(lmcc.Refusal) as err:
        to_json(DOC, registry=reg)
    assert err.value.code == "turn-invalid" and "Pages's to_json failed" in err.value.hint
    data = plan.example({"document": {"media_type": "image/png", "data": "AA=="}}, {"summary": "s"}).to_dict(
        registry=reg)
    with pytest.raises(lmcc.Refusal) as err:
        plan.load_turn(data)
    assert err.value.code == "turn-invalid" and "turn.inputs.document" in err.value.hint

    reg.format(Pages, shape={}, to_json=lambda p: Pages(p))
    with pytest.raises(lmcc.Refusal) as err:
        to_json(DOC, registry=reg)
    assert err.value.code == "turn-invalid" and "again" in err.value.hint

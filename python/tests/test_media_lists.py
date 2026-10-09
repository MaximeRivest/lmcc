"""Lists of pictures and nullable pictures (kernel §5, §7b; D-64, GitHub
issue #7): their kernel defaults, and the rule that a key written for every
value never writes media as text."""

import dataclasses

import pytest

import lmcc
import lmcc_std
from lmcc import core
from lmcc import formats as F

IMAGE = {"media": "image"}
IMAGES = {"type": "array", "items": IMAGE}
A = {"media_type": "image/png", "data": "AAAA"}
B = {"media_type": "image/jpeg", "url": "https://example.com/b.jpg"}
TEMPLATE = [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
            lmcc.turns(), lmcc.user("{% for f in inputs %}[[ ## {f.name} ## ]]\n{f.value}\n{% endfor %}")]


def registry(**kw) -> lmcc.Registry:
    reg = lmcc.Registry(**kw)
    lmcc_std.install(reg)
    return reg


def sig(**inputs) -> core.SignatureCore:
    fields = [{"name": k, "direction": "input", "shape": v} for k, v in inputs.items()]
    return core.signature_from_dict({"instructions": "Compare.", "fields": fields + [
        {"name": "answer", "direction": "output", "shape": {"type": "string"}}]})


def resolved(plan) -> dict:
    return {f["name"]: f["resolved_by"] for f in plan.describe()["inputs"]}


# ------------------------------------------------------------ shapes


def test_holds_media_looks_in_every_subschema_of_a_value():
    assert core.holds_media(IMAGE) and core.holds_media(IMAGES)
    for where in ({"type": "array", "items": [IMAGE]}, {"prefixItems": [{"type": "string"}, IMAGE]},
                  {"type": "object", "additionalProperties": IMAGE},
                  {"type": "object", "properties": {"shot": {"type": "object", "properties": {"p": IMAGE}}}},
                  {"patternProperties": {"^p": IMAGE}}, {"anyOf": [IMAGE, {"type": "null"}]},
                  {"oneOf": [{"type": "string"}, IMAGE]}, {"allOf": [IMAGE]},
                  {"$defs": {"Photo": IMAGE}, "$ref": "#/$defs/Photo"}):
        assert core.holds_media(where), where
    # a member named "media" is a name, not the keyword; "not" says what a value is not
    assert not core.holds_media({"type": "object", "properties": {"media": {"type": "string"}}})
    assert not core.holds_media({"not": IMAGE})
    assert not core.holds_media({"type": "array", "items": {"type": "string"}})


def test_structural_keys_name_lists_of_media_before_list_star():
    assert core.structural_keys(IMAGES) == ["list[media:image]", "list[media:*]", "list[*]"]
    assert core.structural_keys({"anyOf": [IMAGE, {"type": "null"}]}) == ["media:image", "media:*"]
    assert core.structural_keys({"anyOf": [{"type": "null"}, IMAGE]}) == ["media:image", "media:*"]
    assert all(core.names_media(k) for k in ("media:image", "media:*", "list[media:image]", "list[list[media:*]]"))
    assert not any(core.names_media(k) for k in ("*", "object", "list[*]", "list[object]", "image"))


def test_kernel_defaults_for_a_list_of_media_and_a_nullable_media_only():
    assert F.kernel_default(IMAGES) is F.MEDIA_LIST_DEFAULT
    assert F.kernel_default({"anyOf": [IMAGE, {"type": "null"}]}) is F.MEDIA_DEFAULT
    for none in ({"type": "array", "items": {"anyOf": [IMAGE, {"type": "null"}]}},   # an item null
                 {"anyOf": [IMAGES, {"type": "null"}]},                              # null or []
                 {"type": "array", "items": IMAGES},
                 {"type": "object", "properties": {"photo": IMAGE}}):
        assert F.kernel_default(none) is None, none


# ------------------------------------------------- the list default


def test_a_list_writes_its_parts_in_order_and_reads_every_part_of_its_kind():
    plan = lmcc.adapter(messages=TEMPLATE).bind(sig(pictures=IMAGES), registry=registry())
    assert resolved(plan) == {"pictures": "kernel"}
    parts = plan.render(pictures=[A, B]).request("m")["messages"][0]["parts"]
    assert parts == [{"type": "text", "text": "[[ ## pictures ## ]]\n"},
                     {"type": "image", **A}, {"type": "image", **B}, {"type": "text", "text": "\n"}]
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(pictures=[A, {"media_type": "image/png", "alt": "x"}])
    assert err.value.code == "value-invalid" and "'pictures'[1]" in err.value.hint and "'alt'" in err.value.hint
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(pictures=A)
    assert err.value.code == "value-invalid" and "must be a list" in err.value.hint
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(pictures=[A, {"type": "audio", "media_type": "audio/wav", "data": "UklG"}])
    assert err.value.code == "value-invalid" and "'pictures'[1]" in err.value.hint


def test_a_list_of_pictures_round_trips_through_a_turn_and_a_stream():
    s = core.signature_from_dict({"instructions": "Draw.", "fields": [
        {"name": "q", "direction": "input", "shape": {"type": "string"}},
        {"name": "pictures", "direction": "output", "shape": IMAGES}]})
    plan = lmcc.adapter(messages=TEMPLATE).bind(s, registry=registry())
    assert "<pictures>\n(image, ...)\n</pictures>" in plan.render(q="x").system
    for value in ([A, B], [A], []):
        turn = plan.example({"q": "cats"}, {"pictures": value})
        reply = plan.render(q="dogs", turns=[turn]).request("m")["messages"][1]
        assert plan.parse(reply) == {"pictures": value}
        stream = plan.stream()
        for p in reply["parts"]:
            stream.feed(p["text"] if p["type"] == "text" else p)
        assert stream.finish().values == {"pictures": value}


# ------------------------------------- a key written for every value


def test_a_wildcard_or_list_star_that_writes_text_is_passed_over_for_media():
    s = sig(pictures=IMAGES, tags={"type": "array", "items": {"type": "string"}},
            photo={"anyOf": [IMAGE, {"type": "null"}]})
    for formats in ({"*": lmcc.use("json")}, {"list[*]": lmcc.use("json"), "*": lmcc.use("json")}):
        plan = lmcc.adapter(messages=TEMPLATE, formats=formats).bind(s, registry=registry())
        tags_by = "artifact:list[*]" if "list[*]" in formats else "artifact:*"
        assert resolved(plan) == {"pictures": "kernel", "tags": tags_by, "photo": "kernel"}
        parts = plan.render(pictures=[A], tags=["t"], photo=None).request("m")["messages"][0]["parts"]
        assert [p["type"] for p in parts] == ["text", "image", "text"]
        assert parts[2]["text"] == '\n[[ ## tags ## ]]\n[\n  "t"\n]\n[[ ## photo ## ]]\nnull\n'


def test_a_record_holding_a_picture_refuses_no_format_naming_the_media():
    @dataclasses.dataclass
    class Shot:
        photo: dict
        caption: str

    s = sig(shot={"type": "object", "properties": {"photo": IMAGE, "caption": {"type": "string"}}})
    s.field_named("shot").type = "Shot"
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=TEMPLATE, formats={"*": lmcc.use("json"), "object": lmcc.use("json")}).bind(
            s, registry=registry())
    assert err.value.code == "no-format" and "holds media" in err.value.hint
    assert err.value.fix == {"action": "bind-format", "field": "shot", "key": "Shot"}


def test_the_authors_choices_are_taken_text_or_not():
    reg = registry()
    caption = F.make(write=lambda v: f"a photo of {v['caption']}", accepts=("Shot",), direction="in")
    parts = F.make(write=lambda v: [{"type": "text", "text": v["caption"]}, {"type": "image", **v["photo"]}],
                        accepts=("object",), writes="parts", direction="in")
    s = sig(shot={"type": "object", "properties": {"photo": IMAGE, "caption": {"type": "string"}}},
            pictures=IMAGES)
    s.field_named("shot").type = "Shot"
    value = {"shot": {"photo": A, "caption": "dusk"}, "pictures": [B]}
    # the field's type name: a text format is the author's choice
    plan = lmcc.adapter(messages=TEMPLATE, formats={"Shot": caption, "*": lmcc.use("json")}).bind(s, registry=reg)
    assert resolved(plan) == {"shot": "artifact:Shot", "pictures": "kernel"}
    assert "a photo of dusk" in plan.render(**value).request("m")["messages"][0]["parts"][0]["text"]
    # a key written for every value that writes parts is taken
    plan = lmcc.adapter(messages=TEMPLATE, formats={"object": parts, "*": lmcc.use("json")}).bind(s, registry=reg)
    assert resolved(plan)["shot"] == "artifact:object"
    # a key naming media, even one that writes text
    plan = lmcc.adapter(messages=TEMPLATE, formats={"list[media:*]": lmcc.use("json"), "Shot": caption}).bind(
        s, registry=reg)
    assert resolved(plan)["pictures"] == "artifact:list[media:*]"


def test_a_shipped_format_is_judged_by_what_it_declares_without_running_it():
    def write(v, f):
        return str(v)

    shipped = F.ship(F.make(write=write, direction="in"))
    assert shipped["writes"] == "text"
    reg = registry(allow_udf=True)
    s = sig(pictures=IMAGES, n={"type": "array", "items": {"type": "integer"}})
    entry = lmcc.adapter(messages=TEMPLATE).dump()
    entry["formats"] = {"list[*]": shipped}
    plan = lmcc.load(entry, registry=reg).bind(s, registry=reg)
    assert resolved(plan) == {"pictures": "kernel", "n": "artifact:list[*]"}
    del shipped["writes"]          # declaring nothing is declaring text
    entry["formats"] = {"list[*]": shipped}
    assert resolved(lmcc.load(entry, registry=reg).bind(s, registry=reg))["pictures"] == "kernel"

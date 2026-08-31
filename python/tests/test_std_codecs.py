"""The standard codec pack, exercised through the kernel (not in isolation:
codecs must work where they live — bound to fields, spelled into demos,
parsed out of sections)."""

import pytest

import a15
import a15_std
from a15 import A15Error


@pytest.fixture
def registry():
    r = a15.Registry()
    a15_std.install(r)
    return r


def build(sig, codecs, registry):
    adp = a15.adapter(
        template=a15.template([
            a15.message("system", "{instruction}\n"
                        "{% for f in outputs %}<{f.name}>  {f.schema}\n{% endfor %}"),
            a15.directive("demos"),
            a15.message("user", "{q}"),
        ]),
        parse={"kind": "sections", "open": "<{name}>"},
        codecs=codecs)
    return adp.bake(sig, {}, registry=registry)


def test_json_codec_roundtrip(registry):
    sig = a15.signature("Extract.", inputs={"q": str},
                        outputs={"items": list[str]})
    baked = build(sig, {"items": "json"}, registry)
    system = baked.render(inputs={"q": "x"}).messages[0]["content"][0]["text"]
    assert "JSON matching this schema" in system
    assert baked.parse('<items>\n["a", "b"]') == {"items": ["a", "b"]}
    assert baked.parse('<items>\n```json\n["a"]\n```') == {"items": ["a"]}


def test_table_codec_roundtrip_with_escaping(registry):
    shape = {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "score": {"type": "integer"},
        "note": {"type": "string"}}}}
    sig = a15.signature("Rank.", inputs={"q": str}, outputs={"rows": shape})
    baked = build(sig, {"rows": a15.codec(
        "table", columns=["name", "score", "note"])}, registry)

    demo_rows = [{"name": "a|b", "score": 3, "note": None}]
    demo = {"q": "?", "rows": demo_rows}
    result = baked.render(inputs={"q": "?"}, demos=[demo])
    demo_reply = result.messages[2]["content"][0]["text"]
    assert "a\\|b" in demo_reply                      # delimiter escaped
    assert baked.parse(demo_reply) == {"rows": demo_rows}  # lens roundtrip

    # header rows are skipped; typed cells coerce via the item schema
    values = baked.parse(
        "<rows>\n| name | score | note |\n| carol | 9 | fine |")
    assert values == {"rows": [{"name": "carol", "score": 9, "note": "fine"}]}


def test_table_codec_bad_row_refuses_naming_field(registry):
    shape = {"type": "array", "items": {"type": "object"}}
    sig = a15.signature("x", inputs={"q": str}, outputs={"rows": shape})
    baked = build(sig, {"rows": a15.codec("table", columns=["a", "b"])}, registry)
    with pytest.raises(A15Error) as err:
        baked.parse("<rows>\n| only-one-cell |")
    assert err.value.code == "codec-parse-error"
    assert "'rows'" in str(err.value)


def test_scaled_number(registry):
    sig = a15.signature("x", inputs={"q": str}, outputs={"confidence": float})
    baked = build(sig, {"confidence": a15.codec(
        "scaled_number", scale=100, suffix="%", round=0)}, registry)
    demo = {"q": "?", "confidence": 0.78}
    reply = baked.render(inputs={"q": "?"}, demos=[demo]) \
        .messages[2]["content"][0]["text"]
    assert "78%" in reply
    assert baked.parse("<confidence>\n83%") == {"confidence": 0.83}


def test_explain_names_every_decision(registry):
    sig = a15.signature(
        "Answer.", inputs={"q": str},
        outputs={"reasoning": a15.field(str, role="reasoning"), "answer": str})
    adp = a15.adapter(
        template=a15.template([
            a15.message("system", "{instruction}\n"
                        "{% for f in outputs %}<{f.name}>\n{% endfor %}"),
            a15.message("user", "{q}")]),
        parse={"kind": "sections", "open": "<{name}>"},
        strategies={"reasoning": "reasoning_tags"})
    baked = adp.bake(sig, {"instruct": True}, registry=registry)
    text = baked.explain()
    assert "reasoning_tags" in text
    assert "answer" in text

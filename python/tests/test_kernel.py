"""Kernel mechanics: template, bake, render, parse, refusals."""

from typing import Literal

import pytest

import lmcc
from lmcc import LMCCError


def sections_adapter(**kw):
    return lmcc.adapter(
        template=lmcc.template([
            lmcc.message("system",
                        "{instruction}\n\nReply with EXACTLY these sections:\n"
                        "{% for f in outputs %}<{f.name}>  {f.desc}\n{% endfor %}"
                        "Close with </done>."),
            lmcc.directive("demos"),
            lmcc.directive("history"),
            lmcc.message("user",
                        "{% for f in inputs %}== {f.name} ==\n{f.value}\n{% endfor %}"),
        ]),
        parse={"kind": "sections", "open": "<{name}>", "tail": "</done>"},
        **kw,
    )


@pytest.fixture
def sig():
    return lmcc.signature(
        "Answer the question.",
        inputs={"question": str},
        outputs={"answer": lmcc.field(str, desc="short answer"),
                 "score": int},
    )


def test_render_basic(sig):
    baked = sections_adapter().bake(sig, {})
    result = baked.render(inputs={"question": "Why is the sky blue?"})
    assert [m["role"] for m in result.messages] == ["system", "user"]
    system = result.messages[0]["content"][0]["text"]
    assert "<answer>  short answer" in system
    assert "<score>  " in system
    user = result.messages[1]["content"][0]["text"]
    assert user == "== question ==\nWhy is the sky blue?\n"
    assert result.patch == {}


def test_parse_basic(sig):
    baked = sections_adapter().bake(sig, {})
    values = baked.parse("<answer>\nRayleigh scattering.\n<score>\n9\n</done>")
    assert values == {"answer": "Rayleigh scattering.", "score": 9}


def test_lens_demo_roundtrips(sig):
    baked = sections_adapter().bake(sig, {})
    demo = {"question": "2+2?", "answer": "4", "score": 10}
    result = baked.render(inputs={"question": "3+3?"}, demos=[demo])
    roles = [m["role"] for m in result.messages]
    assert roles == ["system", "user", "assistant", "user"]
    demo_reply = result.messages[2]["content"][0]["text"]
    # the lens wrote the demo; the lens must read it back identically
    assert baked.parse(demo_reply) == {"answer": "4", "score": 10}


def test_history_directive(sig):
    baked = sections_adapter().bake(sig, {})
    result = baked.render(inputs={"question": "and now?"},
                          history=[{"role": "user", "content": "hi"},
                                   {"role": "assistant", "content": "hello"}])
    assert [m["role"] for m in result.messages] == \
        ["system", "user", "assistant", "user"]


def test_escapes_and_syntax_errors():
    nodes = lmcc.adapter(
        template=lmcc.template([lmcc.message("user", "a {{literal}} brace")]),
        parse={"kind": "sections", "open": "<{name}>"})
    sig = lmcc.signature("x", inputs={}, outputs={"out": str})
    baked = nodes.bake(sig, {})
    # template with no input slots is fine when there are no inputs
    txt = baked.render(inputs={}).messages[0]["content"][0]["text"]
    assert txt == "a {literal} brace"

    with pytest.raises(LMCCError) as err:
        lmcc.adapter(template=lmcc.template([lmcc.message("user", "bad { brace")]),
                    parse={"kind": "sections", "open": "<{name}>"})
    assert err.value.code == "template-syntax"


def test_unknown_slot_refuses(sig):
    adp = lmcc.adapter(
        template=lmcc.template([lmcc.message("user", "{quesion}")]),  # typo
        parse={"kind": "sections", "open": "<{name}>"})
    with pytest.raises(LMCCError) as err:
        adp.bake(sig, {})
    assert err.value.code == "unknown-slot"
    assert "quesion" in str(err.value)


def test_uncovered_input_refuses():
    sig = lmcc.signature("x", inputs={"a": str, "b": str}, outputs={"out": str})
    adp = lmcc.adapter(template=lmcc.template([lmcc.message("user", "{a}")]),
                      parse={"kind": "sections", "open": "<{name}>"})
    with pytest.raises(LMCCError) as err:
        adp.bake(sig, {})
    assert err.value.code == "field-uncovered"
    assert "'b'" in str(err.value)


def test_structured_shape_without_codec_refuses():
    sig = lmcc.signature("x", inputs={"q": str}, outputs={"items": list[str]})
    with pytest.raises(LMCCError) as err:
        sections_adapter().bake(sig, {})
    assert err.value.code == "no-codec"


def test_missing_section_refuses_with_partial(sig):
    baked = sections_adapter().bake(sig, {})
    with pytest.raises(LMCCError) as err:
        baked.parse("<answer>\nonly this\n</done>")
    assert err.value.code == "parse-missing-fields"
    assert err.value.partial == {"answer": "only this"}


def test_enum_and_scalars():
    sig = lmcc.signature("x", inputs={"q": str},
                        outputs={"risk": Literal["low", "high"], "ok": bool})
    baked = sections_adapter().bake(sig, {})
    values = baked.parse("<risk>\nhigh\n<ok>\ntrue\n</done>")
    assert values == {"risk": "high", "ok": True}
    with pytest.raises(LMCCError) as err:
        baked.parse("<risk>\nmedium\n<ok>\ntrue\n</done>")
    assert err.value.code == "value-invalid"


def test_media_part_emission():
    sig = lmcc.signature("Describe.", inputs={
        "photo": {"media": "image"}, "question": str}, outputs={"answer": str})
    adp = lmcc.adapter(
        template=lmcc.template([
            lmcc.message("user", "{question}\n{photo}\nthanks")]),
        parse={"kind": "sections", "open": "<{name}>"})
    baked = adp.bake(sig, {})
    result = baked.render(inputs={
        "question": "what is this?",
        "photo": {"data": "AAAA", "media_type": "image/png"}})
    parts = result.messages[0]["content"]
    assert [p["kind"] for p in parts] == ["text", "image", "text"]
    assert parts[1] == {"kind": "image", "data": "AAAA",
                        "media_type": "image/png"}


def test_missing_input_refuses(sig):
    baked = sections_adapter().bake(sig, {})
    with pytest.raises(LMCCError) as err:
        baked.render(inputs={})
    assert err.value.code == "missing-input"

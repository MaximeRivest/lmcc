"""Transports (kernel §6) and the artifact (serde)."""

import pytest

import lmcc
from lmcc.transport import Transport

XML = [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
       lmcc.user("{q}")]
SIG = lmcc.signature("Solve.", inputs={"q": str},
                     outputs={"reasoning": lmcc.field(str, purpose="reasoning"), "answer": int})

tags = Transport(tell={"system": "Think inside <think>…</think> before you answer."},
                find=[{"from": "text", "between": ["<think>", "</think>"], "to": "@purpose", "remove": True}],
                in_template=False)
native = Transport(requires=["native_reasoning"], in_template=False,
                  request_settings={"config": {"reasoning": {"effort": "medium"}}},
                  find=[{"from": "part:thinking", "to": "@purpose"}])


def test_tags_and_native_serve_one_role_without_touching_the_signature():
    a = lmcc.adapter(messages=XML, transports={"reasoning": tags})
    plan = a.bind(SIG, {"instruct": True})
    sys_text = plan.render(q="2+2").system
    assert "<reasoning>" not in sys_text and "Think inside" in sys_text
    assert plan.parse("<think>easy</think><answer>\n4\n</answer>") == {"answer": 4, "reasoning": "easy"}

    b = lmcc.adapter(messages=XML, transports={"reasoning": native})
    with pytest.raises(lmcc.Refusal) as err:
        b.bind(SIG, {"instruct": True})
    assert err.value.code == "capability-missing"
    plan = b.bind(SIG, {"native_reasoning": True})
    assert plan.render(q="x").request_settings == {"config": {"reasoning": {"effort": "medium"}}}
    assert plan.parse({"role": "assistant", "parts": [{"type": "thinking", "text": "hm"}, {"type": "text", "text": "<answer>\n4\n</answer>"}]}) == \
        {"answer": 4, "reasoning": "hm"}


def test_choose_picks_by_capability():
    auto = Transport(choose=[{"when": {"capability": "native_reasoning"}, "use": native}, {"else": tags}])
    a = lmcc.adapter(messages=XML, transports={"reasoning": auto})
    assert a.bind(SIG, {}).describe()["find"][0]["from"] == "text"
    assert a.bind(SIG, {"native_reasoning": True}).describe()["find"][0]["from"] == "part:thinking"
    no_else = Transport(choose=[{"when": {"capability": "native_reasoning"}, "use": native}])
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, transports={"reasoning": no_else}).bind(SIG, {})
    assert err.value.code == "capability-missing"


@pytest.mark.parametrize("data", [
    {"find": [{"from": "nowhere", "to": "@purpose"}]},
    {"find": [{"from": "text", "to": "@purpose"}]},                       # no extractor
    {"find": [{"from": "text", "between": ["<a>"], "to": "@purpose"}]},
    {"find": [{"from": "part:thinking", "remove": True, "to": "@purpose"}]},
    {"find": [{"from": "text", "between": ["a", "b"], "to": "answer"}]},
    {"put": {"@purpose": "nowhere"}},
    {"in_template": False},
    {"when": {"nope": 1}},
    {"choose": []},
    {"choose": [{"else": {}}, {"when": {"capability": "x"}, "use": {}}]},
    {"unknown": 1},
])
def test_malformed_transports_refuse_at_construct(data):
    with pytest.raises(lmcc.Refusal) as err:
        Transport.from_dict(data, where="s")
    assert err.value.code == "entry-malformed"


def test_double_covered_and_role_ambiguous():
    visible_and_routed = Transport(find=[{"from": "text", "between": ["<t>", "</t>"], "to": "@purpose"}])
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, transports={"reasoning": visible_and_routed}).bind(SIG, {})
    assert err.value.code == "field-double-covered"
    twice = lmcc.signature("x", inputs={"q": str},
                           outputs={"a": lmcc.field(str, purpose="reasoning"), "b": lmcc.field(str, purpose="reasoning")})
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML).bind(twice, {})
    assert err.value.code == "purpose-ambiguous"


def test_artifact_round_trips_and_loads_with_zero_ambient_state():
    a = lmcc.adapter(messages=XML, transports={"reasoning": Transport(
        choose=[{"when": {"capability": "native_reasoning"}, "use": native}, {"else": tags}])}, name="xml")
    entry = a.dump(registry=lmcc.Registry())
    assert entry["template"] == XML and entry["reader"] == {"kind": "derived"}
    assert entry["transports"]["reasoning"]["choose"][1] == {"else": tags.to_dict()}
    assert "formats" not in entry and "codecs" not in entry
    again = lmcc.load(entry, registry=lmcc.Registry())
    assert again.dump(registry=lmcc.Registry()) == entry
    assert again.bind(SIG, {}).parse("<think>a</think><answer>\n1\n</answer>") == {"answer": 1, "reasoning": "a"}


@pytest.mark.parametrize("entry, code", [
    ({"versions": {"kernel": "0.7.0"}, "template": {"messages": []}, "reader": {"kind": "derived"}}, "entry-malformed"),
    ({"versions": {"kernel": "9.0.0"}, "template": [], "reader": {"kind": "derived"}}, "version-incompatible"),
    ({"versions": {"kernel": "0.7.0"}, "template": [], "reader": {"kind": "nope"}}, "unknown-reader"),
    ({"versions": {"kernel": "0.7.0"}, "template": [], "reader": {"kind": "derived"}, "formats": {"X": {"use": "nope"}}}, "unknown-format"),
    ({"versions": {"kernel": "0.7.0"}, "template": [], "reader": {"kind": "derived"}, "transports": {"r": {"use": "nope"}}}, "unknown-transport"),
    ({"versions": {"kernel": "0.7.0"}, "template": [], "reader": {"kind": "derived"}, "formats": {"X": {"language": "python"}}}, "entry-malformed"),
])
def test_load_refuses_by_name(entry, code):
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.load(entry, registry=lmcc.Registry())
    assert err.value.code == code

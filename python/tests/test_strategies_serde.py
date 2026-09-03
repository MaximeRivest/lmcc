"""Strategies (kernel §6) and the artifact (serde)."""

import pytest

import lmcc
from lmcc.strategy import Strategy

XML = [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
       lmcc.user("{q}")]
SIG = lmcc.signature("Solve.", inputs={"q": str},
                     outputs={"reasoning": lmcc.field(str, role="reasoning"), "answer": int})

tags = Strategy(fragments={"system": "Think inside <think>…</think> before you answer."},
                routings=[{"from": "text", "between": ["<think>", "</think>"], "to": "@role", "consume": True}],
                visible=False)
native = Strategy(requires=["native_reasoning"], visible=False,
                  controls={"reasoning": {"effort": "medium"}},
                  routings=[{"from": "channel:thinking", "to": "@role"}])


def test_tags_and_native_serve_one_role_without_touching_the_signature():
    a = lmcc.adapter(messages=XML, strategies={"reasoning": tags})
    plan = a.bind(SIG, {"instruct": True})
    sys_text = plan.render(q="2+2").messages[0]["content"][0]["text"]
    assert "<reasoning>" not in sys_text and "Think inside" in sys_text
    assert plan.parse("<think>easy</think><answer>\n4\n</answer>") == {"answer": 4, "reasoning": "easy"}

    b = lmcc.adapter(messages=XML, strategies={"reasoning": native})
    with pytest.raises(lmcc.Refusal) as err:
        b.bind(SIG, {"instruct": True})
    assert err.value.code == "capability-missing"
    plan = b.bind(SIG, {"native_reasoning": True})
    assert plan.render(q="x").patch == {"reasoning": {"effort": "medium"}}
    assert plan.parse({"content": [{"kind": "thinking", "text": "hm"}, {"kind": "text", "text": "<answer>\n4\n</answer>"}]}) == \
        {"answer": 4, "reasoning": "hm"}


def test_choose_picks_by_capability():
    auto = Strategy(choose=[{"when": {"capability": "native_reasoning"}, "use": native}, {"else": tags}])
    a = lmcc.adapter(messages=XML, strategies={"reasoning": auto})
    assert a.bind(SIG, {}).describe()["routings"][0]["from"] == "text"
    assert a.bind(SIG, {"native_reasoning": True}).describe()["routings"][0]["from"] == "channel:thinking"
    no_else = Strategy(choose=[{"when": {"capability": "native_reasoning"}, "use": native}])
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, strategies={"reasoning": no_else}).bind(SIG, {})
    assert err.value.code == "capability-missing"


@pytest.mark.parametrize("data", [
    {"routings": [{"from": "nowhere", "to": "@role"}]},
    {"routings": [{"from": "text", "to": "@role"}]},                       # no extractor
    {"routings": [{"from": "text", "between": ["<a>"], "to": "@role"}]},
    {"routings": [{"from": "text", "pattern": "(?=x)", "to": "@role"}]},   # outside RE2
    {"routings": [{"from": "channel:thinking", "consume": True, "to": "@role"}]},
    {"routings": [{"from": "text", "between": ["a", "b"], "to": "answer"}]},
    {"placement": {"@role": "nowhere"}},
    {"visible": False},
    {"when": {"nope": 1}},
    {"choose": []},
    {"choose": [{"else": {}}, {"when": {"capability": "x"}, "use": {}}]},
    {"unknown": 1},
])
def test_malformed_strategies_refuse_at_construct(data):
    with pytest.raises(lmcc.Refusal) as err:
        Strategy.from_dict(data, where="s")
    assert err.value.code == "entry-malformed"


def test_double_covered_and_role_ambiguous():
    visible_and_routed = Strategy(routings=[{"from": "text", "between": ["<t>", "</t>"], "to": "@role"}])
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, strategies={"reasoning": visible_and_routed}).bind(SIG, {})
    assert err.value.code == "field-double-covered"
    twice = lmcc.signature("x", inputs={"q": str},
                           outputs={"a": lmcc.field(str, role="reasoning"), "b": lmcc.field(str, role="reasoning")})
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML).bind(twice, {})
    assert err.value.code == "role-ambiguous"


def test_artifact_round_trips_and_loads_with_zero_ambient_state():
    a = lmcc.adapter(messages=XML, strategies={"reasoning": Strategy(
        choose=[{"when": {"capability": "native_reasoning"}, "use": native}, {"else": tags}])}, name="xml")
    entry = a.dump(registry=lmcc.Registry())
    assert entry["template"] == XML and entry["parse"] == {"kind": "derived"}
    assert entry["strategies"]["reasoning"]["choose"][1] == {"else": tags.to_dict()}
    assert "formats" not in entry and "codecs" not in entry
    again = lmcc.load(entry, registry=lmcc.Registry())
    assert again.dump(registry=lmcc.Registry()) == entry
    assert again.bind(SIG, {}).parse("<think>a</think><answer>\n1\n</answer>") == {"answer": 1, "reasoning": "a"}


@pytest.mark.parametrize("entry, code", [
    ({"versions": {"kernel": "0.2.0"}, "template": {"messages": []}, "parse": {"kind": "derived"}}, "entry-malformed"),
    ({"versions": {"kernel": "9.0.0"}, "template": [], "parse": {"kind": "derived"}}, "version-incompatible"),
    ({"versions": {"kernel": "0.2.0"}, "template": [], "parse": {"kind": "nope"}}, "unknown-parse-kind"),
    ({"versions": {"kernel": "0.2.0"}, "template": [], "parse": {"kind": "derived"}, "formats": {"X": {"use": "nope"}}}, "unknown-format"),
    ({"versions": {"kernel": "0.2.0"}, "template": [], "parse": {"kind": "derived"}, "strategies": {"r": {"use": "nope"}}}, "unknown-strategy"),
    ({"versions": {"kernel": "0.2.0"}, "template": [], "parse": {"kind": "derived"}, "formats": {"X": {"language": "python"}}}, "entry-malformed"),
])
def test_load_refuses_by_name(entry, code):
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.load(entry, registry=lmcc.Registry())
    assert err.value.code == code

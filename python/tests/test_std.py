"""The std pack: formats json/table/scaled_number, lens json_object,
reasoning strategies — through the sockets, against the spec."""

import dataclasses
import enum

import pytest

import lmcc
import lmcc_std
from lmcc_std.lenses import JsonObjectLens

PATTERN = [lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
           lmcc.demos(), lmcc.user("{text}")]


def _registry():
    r = lmcc.Registry()
    lmcc_std.install(r)
    return r


@dataclasses.dataclass
class Person:
    name: str
    age: int


class Color(enum.Enum):
    RED = "red"


def test_json_format_lowers_and_lifts_native_values():
    sig = lmcc.signature("x", inputs={"text": str},
                         outputs={"people": list[Person], "color": Color, "n": int})
    plan = lmcc.adapter(messages=PATTERN, formats={"list[object]": "json"}).bind(sig, registry=_registry())
    req = plan.render(text="t", demos=[{"text": "d", "people": [Person("Ann", 41)], "color": Color.RED, "n": 1}])
    assert req.messages[2]["content"][0]["text"] == \
        '<people>\n[\n  {\n    "name": "Ann",\n    "age": 41\n  }\n]\n</people>\n<color>\nred\n</color>\n<n>\n1\n</n>'
    values = plan.parse('<people>\n```json\n[{"name": "Bo", "age": 7}]\n```\n</people>\n<color>\nred\n</color>\n<n>\n2\n</n>')
    assert values == {"people": [Person("Bo", 7)], "color": Color.RED, "n": 2}


def test_json_format_refuses_bad_json_as_read_error():
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"rows": list[int]})
    plan = lmcc.adapter(messages=PATTERN, formats={"list[*]": "json"}).bind(sig, registry=_registry())
    with pytest.raises(lmcc.Refusal) as err:
        plan.parse("<rows>\n[1,]\n</rows>")
    assert err.value.code == "format-read-error"


def test_table_format_escaping_and_coercion():
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"rows": {
        "type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "ok": {"type": "boolean"}}}}})
    plan = lmcc.adapter(messages=PATTERN, formats={"list[object]": lmcc.use("table", columns=["name", "ok"])}
                        ).bind(sig, registry=_registry())
    demo = plan.render(text="t", demos=[{"text": "d", "rows": [{"name": "a|b", "ok": True}]}]).messages[2]["content"][0]["text"]
    assert demo == "<rows>\n| a\\|b | true |\n</rows>"
    assert plan.parse(demo) == {"rows": [{"name": "a|b", "ok": True}]}
    with pytest.raises(lmcc.Refusal) as err:
        plan.parse("<rows>\n| a | maybe |\n</rows>")
    assert err.value.code == "format-read-error"


def test_scaled_number_rounding_and_spelling():
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"p": float})
    plan = lmcc.adapter(messages=PATTERN, formats={"number": lmcc.use("scaled_number", scale=100, suffix="%", round=1)}
                        ).bind(sig, registry=_registry())
    demo = plan.render(text="t", demos=[{"text": "d", "p": 0.12345}]).messages[2]["content"][0]["text"]
    assert demo == "<p>\n12.3%\n</p>"
    assert plan.parse("<p>\n83%\n</p>") == {"p": 0.83}


def test_json_object_lens_is_a_gated_mode():
    sig = lmcc.signature("Answer.", inputs={"q": str}, outputs={"answer": str, "score": int})
    adp = lmcc.adapter(messages=[lmcc.system("{instruction}\n{format}"), lmcc.user("{q}")],
                       parse={"kind": "json_object"})
    with pytest.raises(lmcc.Refusal) as err:
        adp.bind(sig, {}, registry=_registry())
    assert err.value.code == "capability-missing"
    plan = adp.bind(sig, {"native_structured_output": True}, registry=_registry())
    req = plan.render(q="?")
    assert req.patch["response_format"]["schema"]["required"] == ["answer", "score"]
    assert req.messages[0]["content"][0]["text"] == 'Answer.\n{\n  "answer": "...",\n  "score": "(integer)"\n}'
    assert plan.parse('```json\n{"answer": "A", "score": 9, "extra": 1}\n```') == {"answer": "A", "score": 9}
    with pytest.raises(lmcc.Refusal) as err:
        plan.parse('{"answer": "A", "answer": "B", "score": 1}')
    assert err.value.code == "parse-ambiguous"


def test_json_object_join_embed_rule_is_raw_text_identity():
    lens = JsonObjectLens({"kind": "json_object"})
    spelled = [("s", "plain"), ("n", "9"), ("b", "true"), ("quoted", '"hi"'), ("arr", "[1, 2]")]
    raw = lens.split(lens.join(spelled), [n for n, _ in spelled])
    assert raw == {"s": "plain", "n": "9", "b": "true", "quoted": '"hi"', "arr": "[\n    1,\n    2\n  ]"}


def test_reasoning_strategies_by_name():
    sig = lmcc.signature("Solve.", inputs={"q": str},
                         outputs={"reasoning": lmcc.field(str, role="reasoning"), "answer": int})
    adp = lmcc.adapter(messages=[lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
                                 lmcc.user("{q}")], strategies={"reasoning": "reasoning_tags"})
    plan = adp.bind(sig, {"instruct": True}, registry=_registry())
    assert plan.parse("<think>a</think><answer>\n1\n</answer>") == {"answer": 1, "reasoning": "a"}
    entry = adp.dump(registry=_registry())
    assert entry["versions"]["vocab"] == {"strategy/reasoning_tags": "0.1.0"}
    assert entry["strategies"]["reasoning"] == {"use": "reasoning_tags"}

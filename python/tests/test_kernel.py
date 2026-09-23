"""The kernel surface: @lmcc.fn, the template, the derived reader, bind,
render, parse, plan faces. Kernel only — empty registry."""

import dataclasses

import pytest

import lmcc

XML = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.turns(),
    lmcc.user("{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
])


@lmcc.fn
def answer(question: str) -> str:
    """Answer the question in one sentence."""


@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Purpose["reasoning", str]
    answer: int


@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve it."""


@dataclasses.dataclass
class Person:
    name: str
    age: int


@lmcc.fn
def extract(text: str) -> lmcc.One[Person]:
    """Extract the person mentioned."""


def test_one_marks_a_single_structured_output():
    f = extract.signature.outputs[0]
    assert (f.name, f.type, f.shape["type"], list(f.shape["properties"])) == ("extract", "Person", "object", ["name", "age"])
    with pytest.raises(lmcc.Refusal) as err:
        extract.bind(XML, registry=lmcc.Registry())
    assert err.value.code == "no-format"


def test_fn_lowers_parameters_return_and_docstring():
    sig = answer.signature
    assert sig.instructions == "Answer the question in one sentence."
    assert [(f.name, f.direction, f.type) for f in sig.fields] == [
        ("question", "input", "str"), ("answer", "output", "str")]
    s2 = solve.signature
    assert [(f.name, f.purpose, f.type) for f in s2.outputs] == [
        ("reasoning", "reasoning", "str"), ("answer", "plain", "int")]
    with pytest.raises(TypeError, match="not a callable"):   # host API misuse, not a refusal
        answer("x")


def test_bind_render_parse_round_trip():
    plan = answer.bind(XML, capabilities={"instruct": True})
    req = plan.render(question="Why is the sky blue?")
    assert req.messages[-1]["parts"][0]["text"] == "<question>\nWhy is the sky blue?\n</question>\n"
    assert req.request_settings == {}
    assert plan.parse("<answer>\nRayleigh scattering.\n</answer>") == {"answer": "Rayleigh scattering."}


def test_the_template_is_the_parser():
    renamed = lmcc.adapter(messages=[
        lmcc.system("{% for f in outputs %}<reply-{f.name}>\n{f.value}\n</reply-{f.name}>\n{% endfor %}"),
        lmcc.user("{question}")])
    plan = answer.bind(renamed)
    assert plan.parse("<reply-answer>\nyes\n</reply-answer>") == {"answer": "yes"}
    assert plan.describe()["reader"]["anchors"] == [["answer", "<reply-answer>\n", "\n</reply-answer>\n"]]


def test_examples_are_written_by_the_reader():
    plan = answer.bind(XML)
    req = plan.render(question="q", turns=[plan.example({"question": "d"}, {"answer": "a"})])
    demo_turn = req.messages[1]["parts"][0]["text"]
    assert demo_turn == "<answer>\na\n</answer>"
    assert plan.parse(demo_turn) == {"answer": "a"}


def test_bare_output_slots_form_a_pattern():
    spelled = lmcc.adapter(messages=[
        lmcc.system('Reply exactly like this:\n{{"answer": "{answer}", "n": {n}}}'),
        lmcc.user("{q}")])

    sig = lmcc.signature("x", inputs={"q": str}, outputs={"answer": str, "n": int})
    plan = spelled.bind(sig)
    assert plan.render(q="?").system == 'Reply exactly like this:\n{"answer": "...", "n": (integer)}'
    assert plan.parse('{"answer": "Paris", "n": 9}') == {"answer": "Paris", "n": 9}
    assert plan.skeleton() == {"prefill": '{"answer": "', "stops": ["}"]}


@pytest.mark.parametrize("template, code", [
    ("{% for f in outputs %}{f.value}\n{% endfor %}", "not-readable"),        # no anchor
    ("{% for f in outputs %}x {f.value} {f.value}{% endfor %}", "not-readable"),  # two holes
    ("{% for f in outputs %}<a>{f.value}{% endfor %}", "not-readable"),      # anchors coincide
    ("no pattern at all", "not-readable"),
    ("{% for f in outputs %}<{f.name}>{f.value}{% for g in inputs %}{g.name}{% endfor %}{% endfor %}", "not-readable"),
    ("{bad brace", "template-syntax"),
    ("{% for f in outputs %}<{f.name}>{f.value}{% endfor %}{nope}", "unknown-slot"),
])
def test_refusals_fire_at_bind_by_name(template, code):
    sig = lmcc.signature("x", inputs={"q": str}, outputs={"a": str, "b": str})
    try:
        adp = lmcc.adapter(messages=[lmcc.system(template), lmcc.user("{q}")])
        adp.bind(sig)
    except lmcc.Refusal as err:
        assert err.code == code
    else:
        raise AssertionError(f"expected {code}")


def test_parse_refusals_carry_partial_and_never_guess():
    plan = solve.bind(XML)
    with pytest.raises(lmcc.Refusal) as err:
        plan.parse("<reasoning>\nhm\n</reasoning>")
    assert err.value.code == "parse-missing-fields" and err.value.partial == {"reasoning": "hm"}
    with pytest.raises(lmcc.Refusal) as err:
        plan.parse("<answer>\n<answer>\n1\n</answer>")
    assert err.value.code == "parse-ambiguous"
    with pytest.raises(lmcc.Refusal) as err:
        plan.parse("<reasoning>\nhm\n</reasoning>\n<answer>\nnine\n</answer>")
    assert err.value.code == "parse-value" and "nine" in err.value.hint


def test_plan_faces_are_data():
    import json
    plan = solve.bind(XML)
    d = plan.describe()
    json.dumps(d)
    assert d["outputs"][0]["format"] == "kernel-scalar" and d["outputs"][0]["resolved_by"] == "kernel"
    assert d["skeleton"] == {"prefill": "<reasoning>\n", "stops": ["</answer>"]}
    assert "system" in plan.prefix(turns=[plan.example({"problem": "p"}, {"reasoning": "r", "answer": 1})])
    assert "kernel-scalar" in plan.explain()


def test_field_uncovered_and_missing_input():
    sig = lmcc.signature("x", inputs={"q": str, "extra": str}, outputs={"a": str})
    adp = lmcc.adapter(messages=[lmcc.system("{% for f in outputs %}<{f.name}>{f.value}{% endfor %}"),
                                 lmcc.user("{q}")])
    with pytest.raises(lmcc.Refusal) as err:
        adp.bind(sig)
    assert err.value.code == "field-uncovered"
    plan = answer.bind(XML)
    with pytest.raises(lmcc.Refusal) as err:
        plan.render()
    assert err.value.code == "missing-input"


def test_turns_partial_examples_and_refusals():
    plan = answer.bind(XML)
    req = plan.render(question="third", turns=[
        plan.example({"question": "first"}, {"answer": "one"}), plan.example({}, {"answer": "raw"})])
    roles = [m["role"] for m in req.messages]
    assert roles == ["user", "assistant", "assistant", "user"] and req.system
    with pytest.raises(lmcc.Refusal) as err:
        plan.example({"q": "flat"}, {})
    assert err.value.code == "turn-invalid"
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(question="x", turns={"examples": [plan.example({}, {"answer": "a"})]})
    assert err.value.code == "turns-unplaced"

"""The kernel surface: @lmcc.fn, the template, the derived lens, bind,
render, parse, plan faces. Kernel only — empty registry."""

import dataclasses

import pytest

import lmcc

XML = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.demos(),
    lmcc.user("{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
])


@lmcc.fn
def answer(question: str) -> str:
    """Answer the question in one sentence."""


@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Role["reasoning", str]
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
    assert [(f.name, f.role, f.type) for f in s2.outputs] == [
        ("reasoning", "reasoning", "str"), ("answer", "plain", "int")]
    with pytest.raises(lmcc.Refusal) as err:
        answer("x")
    assert err.value.code == "entry-malformed"


def test_bind_render_parse_round_trip():
    plan = answer.bind(XML, capabilities={"instruct": True})
    req = plan.render(question="Why is the sky blue?")
    assert req.messages[-1]["content"][0]["text"] == "<question>\nWhy is the sky blue?\n</question>\n"
    assert req.patch == {}
    assert plan.parse("<answer>\nRayleigh scattering.\n</answer>") == {"answer": "Rayleigh scattering."}


def test_the_template_is_the_parser():
    renamed = lmcc.adapter(messages=[
        lmcc.system("{% for f in outputs %}<reply-{f.name}>\n{f.value}\n</reply-{f.name}>\n{% endfor %}"),
        lmcc.user("{question}")])
    plan = answer.bind(renamed)
    assert plan.parse("<reply-answer>\nyes\n</reply-answer>") == {"answer": "yes"}
    assert plan.describe()["lens"]["anchors"] == [["answer", "<reply-answer>\n", "\n</reply-answer>\n"]]


def test_demos_are_written_by_the_lens():
    plan = answer.bind(XML)
    req = plan.render(question="q", demos=[{"question": "d", "answer": "a"}])
    demo_turn = req.messages[2]["content"][0]["text"]
    assert demo_turn == "<answer>\na\n</answer>"
    assert plan.parse(demo_turn) == {"answer": "a"}


def test_bare_output_slots_form_a_pattern():
    spelled = lmcc.adapter(messages=[
        lmcc.system('Reply exactly like this:\n{{"answer": "{answer}", "n": {n}}}'),
        lmcc.user("{q}")])

    sig = lmcc.signature("x", inputs={"q": str}, outputs={"answer": str, "n": int})
    plan = spelled.bind(sig)
    assert plan.render(q="?").messages[0]["content"][0]["text"] == 'Reply exactly like this:\n{"answer": "...", "n": (integer)}'
    assert plan.parse('{"answer": "Paris", "n": 9}') == {"answer": "Paris", "n": 9}
    assert plan.skeleton() == {"prefill": '{"answer": "', "stops": ["}"]}


@pytest.mark.parametrize("template, code", [
    ("{% for f in outputs %}{f.value}\n{% endfor %}", "not-lensable"),        # no anchor
    ("{% for f in outputs %}x {f.value} {f.value}{% endfor %}", "not-lensable"),  # two holes
    ("{% for f in outputs %}<a>{f.value}{% endfor %}", "not-lensable"),      # anchors coincide
    ("no pattern at all", "not-lensable"),
    ("{% for f in outputs %}<{f.name}>{f.value}{% for g in inputs %}{g.name}{% endfor %}{% endfor %}", "not-lensable"),
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
    assert plan.prefix(demos=[{"problem": "p", "reasoning": "r", "answer": 1}])[0]["role"] == "system"
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


def test_history_field_turns_and_partial_examples():
    with_history = lmcc.adapter(messages=[XML.template[0], lmcc.history(), XML.template[2]])
    plan = answer.bind(with_history)
    req = plan.render(question="third", history=[
        {"fields": {"question": "first", "answer": "one"}},
        {"role": "assistant", "content": "raw"}])
    roles = [m["role"] for m in req.messages]
    assert roles == ["system", "user", "assistant", "assistant", "user"]
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(question="x", history=[{"question": "flat"}])
    assert err.value.code == "value-invalid"

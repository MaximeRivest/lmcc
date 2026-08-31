"""The derived lens (template read backwards) + the predicate algebra."""

import pytest

import a15
from a15.strategy import eval_predicate

PATTERN_TEMPLATE = a15.template([
    a15.message("system", "{instruction}\n\nAnswer in exactly this form:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n"
                "{% endfor %}"),
    a15.directive("demos"),
    a15.message("user", "{q}"),
])


def _sig():
    return a15.signature(
        "Answer.", inputs={"q": str},
        outputs={"answer": a15.field(str, desc="short answer"), "score": int})


def _baked(template=PATTERN_TEMPLATE):
    return a15.adapter(template=template,
                       parse={"kind": "derived"}).bake(_sig(), {})


def test_template_is_the_lens():
    """One description, two directions: the pattern block renders the
    prompt AND derives the parser; the demo written by it reads back."""
    baked = _baked()
    r = baked.render(inputs={"q": "3+3?"},
                     demos=[{"q": "2+2?", "answer": "4", "score": 10}])
    system = r.messages[0]["content"][0]["text"]
    assert "<answer>\nshort answer\n</answer>" in system
    demo_turn = r.messages[2]["content"][0]["text"]
    assert baked.parse(demo_turn) == {"answer": "4", "score": 10}


def test_derived_parse_ignores_prose():
    baked = _baked()
    values = baked.parse("Sure!\n<answer>\nParis\n</answer>\n"
                         "<score>\n9\n</score>\nDone.")
    assert values == {"answer": "Paris", "score": 9}


def test_ambiguity_refuses_never_guesses():
    baked = _baked()
    with pytest.raises(a15.A15Error) as err:
        baked.parse("quoting <answer> here\n<answer>\nParis\n</answer>\n"
                    "<score>\n9\n</score>")
    assert err.value.code == "parse-ambiguous"


def test_unanchored_hole_refuses_at_bake():
    template = a15.template([
        a15.message("system", "{% for f in outputs %}{f.value}\n{% endfor %}"),
        a15.message("user", "{q}"),
    ])
    with pytest.raises(a15.A15Error) as err:
        _baked(template)
    assert err.value.code == "not-lensable"


def test_indistinct_anchors_refuse_at_bake():
    template = a15.template([
        a15.message("system", "{% for f in outputs %}Value: {f.value}\n"
                    "{% endfor %}"),
        a15.message("user", "{q}"),
    ])
    with pytest.raises(a15.A15Error) as err:
        _baked(template)
    assert err.value.code == "not-lensable"


def test_no_pattern_block_refuses():
    template = a15.template([a15.message("user", "{q}")])
    with pytest.raises(a15.A15Error) as err:
        _baked(template)
    assert err.value.code == "not-lensable"


def test_derived_lens_tracks_hidden_fields():
    import a15_std
    registry = a15.Registry()
    a15_std.install(registry)
    sig = a15.signature(
        "Answer.", inputs={"q": str},
        outputs={"reasoning": a15.field(str, role="reasoning"),
                 "answer": str})
    adp = a15.adapter(template=PATTERN_TEMPLATE.copy()
                      if hasattr(PATTERN_TEMPLATE, "copy") else PATTERN_TEMPLATE,
                      parse={"kind": "derived"},
                      strategies={"reasoning": "reasoning_tags"})
    baked = adp.bake(sig, {"instruct": True}, registry=registry)
    system = baked.render(inputs={"q": "x"}).messages[0]["content"][0]["text"]
    assert "<reasoning>" not in system
    values = baked.parse("<think>easy</think><answer>\nParis\n</answer>")
    assert values == {"reasoning": "easy", "answer": "Paris"}


# ---------------------------------------------------------------- predicate


def test_predicate_algebra():
    assert eval_predicate({"capability": "instruct"}, {"instruct": True})
    assert not eval_predicate({"capability": "instruct"}, {})
    assert eval_predicate({"not": {"capability": "native_reasoning"}}, {})
    assert eval_predicate(
        {"all": [{"capability": "instruct"},
                 {"not": {"capability": "native_reasoning"}}]},
        {"instruct": True})
    assert eval_predicate(
        {"any": [{"capability": "a"}, {"capability": "b"}]}, {"b": True})


def test_predicate_gates_bake():
    strategy = a15.Strategy(
        predicate={"not": {"capability": "native_reasoning"}},
        fragments={"system": "Think step by step."})
    sig = a15.signature(
        "x", inputs={"q": str},
        outputs={"reasoning": a15.field(str, role="reasoning"), "answer": str})
    adp = a15.adapter(
        template=a15.template([a15.message("system", "{instruction}"),
                               a15.message("user", "{q}")]),
        parse={"kind": "sections", "open": "<{name}>"},
        strategies={"reasoning": strategy})
    baked = adp.bake(sig, {})  # predicate true: fragment lands
    text = baked.render(inputs={"q": "x"}).messages[0]["content"][0]["text"]
    assert "Think step by step." in text
    with pytest.raises(a15.A15Error) as err:
        adp.bake(sig, {"native_reasoning": True})  # predicate false: refuse
    assert err.value.code == "capability-missing"


def test_predicate_roundtrips_in_the_artifact():
    strategy = a15.Strategy(
        predicate={"not": {"capability": "native_reasoning"}},
        fragments={"system": "Think."})
    adp = a15.adapter(
        template=a15.template([a15.message("user", "{q}")]),
        parse={"kind": "sections", "open": "<{name}>"},
        strategies={"reasoning": strategy})
    entry = a15.dump(adp, a15.Registry())
    loaded = a15.load(entry, registry=a15.Registry())
    assert loaded.strategies["reasoning"].inline.predicate == {
        "not": {"capability": "native_reasoning"}}


def test_malformed_predicate_refuses():
    with pytest.raises(a15.A15Error) as err:
        a15.Strategy.from_dict({"predicate": {"nope": 1}}, where="test")
    assert err.value.code == "entry-malformed"

"""Plan 13: each helper is the plain data it replaces."""

import dataclasses

import pytest

import lmcc
import lmcc_std
from lmcc import find, put, when


def test_find_helpers_are_their_dicts():
    assert find.between("<think>", "</think>", remove=True, repair=True) == \
        {"from": "text", "between": ["<think>", "</think>"], "to": "@purpose", "remove": True, "repair": True}
    assert find.between("```tool\n", "\n```", to="calls", remove=True, whole_reply=True) == \
        {"from": "text", "between": ["```tool\n", "\n```"], "to": "@purpose.calls", "remove": True,
         "complete_reply": True}
    assert find.lines("NOTE: ") == {"from": "text", "line_prefixed": "NOTE: ", "to": "@purpose"}
    assert find.pattern("T: (.*)") == {"from": "text", "pattern": "T: (.*)", "to": "@purpose"}
    assert find.part("thinking") == {"from": "part:thinking", "to": "@purpose"}
    assert find.part("tool_call", to="calls", whole_reply=True) == \
        {"from": "part:tool_call", "to": "@purpose.calls", "complete_reply": True}


def test_put_and_when_helpers_are_their_dicts():
    assert put.system() == {"@purpose": "message:system"}
    assert put.user("sources") == {"@purpose.sources": "message:user"}
    assert put.request("tools") == {"@purpose": "request.tools"}
    assert when.has("instruct") == {"capability": "instruct"}
    assert when.lacks("native_reasoning") == {"not": {"capability": "native_reasoning"}}
    assert when.all(when.has("a"), when.lacks("b")) == \
        {"all": [{"capability": "a"}, {"not": {"capability": "b"}}]}


def test_a_transport_built_both_ways_dumps_the_same():
    by_hand = lmcc.Transport(when={"not": {"capability": "native_reasoning"}},
                             tell={"system": "Think in <think> tags."},
                             find=[{"from": "text", "between": ["<think>", "</think>"], "to": "@purpose",
                                    "remove": True}], in_template=False)
    helped = lmcc.Transport(when=when.lacks("native_reasoning"), tell={"system": "Think in <think> tags."},
                            find=[find.between("<think>", "</think>", remove=True)], in_template=False)
    assert helped.to_dict() == by_hand.to_dict()


def test_choose_resolves_names_and_binds():
    reg = lmcc.Registry()
    lmcc_std.install(reg)
    t = lmcc.choose((when.has("native_reasoning"), "native_reasoning"), otherwise="reasoning_tags",
                    registry=reg)

    @dataclasses.dataclass
    class O:
        reasoning: lmcc.Purpose["reasoning", str]
        a: str

    @lmcc.fn
    def f(q: str) -> O:
        """Do."""
    ad = lmcc.adapter(messages=[lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")],
                      transports={"reasoning": t})
    assert f.bind(ad, capabilities={"instruct": True}, registry=reg).parse("<think>x</think>A: 1") == \
        {"a": "1", "reasoning": "x"}


def test_misuse_is_a_type_error():
    with pytest.raises(TypeError):
        find.between("", "x")
    with pytest.raises(TypeError):
        find.part("thinking", to="@purpose")
    with pytest.raises(TypeError):
        lmcc.choose(("not a predicate", "reasoning_tags"))

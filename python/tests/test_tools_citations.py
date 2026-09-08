"""Tools and citations (spec/vocab/strategy-tools.md, strategy-citations.md)
and the kernel mechanics they rely on: `suffices`, `via`, `turns` + probe."""

import dataclasses

import pytest

import lmcc
import lmcc_std
from lmcc_std.tools import Citation, Source, Tool, ToolCall

REG = lmcc.Registry()
lmcc_std.install(REG)
XML = [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
       lmcc.history(), lmcc.user("{question}")]
WEATHER = Tool("get_weather", "Weather for a city.",
               {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})
CALL = {"type": "tool_call", "id": "c1", "name": "get_weather", "input": {"city": "Paris"}}
RESULT = {"type": "tool_result", "id": "c1", "name": "get_weather", "content": [{"type": "text", "text": "Sunny"}]}


@dataclasses.dataclass
class Out:
    calls: lmcc.Role["tools.calls", list[ToolCall]]
    answer: str


@lmcc.fn
def ask(question: str, tools: lmcc.Role["tools", list[Tool]]) -> Out:
    """Answer, using tools when needed."""


AUTO = lmcc.Strategy(choose=[
    {"when": {"capability": "native_function_calling"}, "use": lmcc_std.tools.native_tools({})},
    {"else": lmcc_std.tools.fenced_tools({})}])


def plan(caps, strategy=AUTO):
    return ask.bind(lmcc.adapter(messages=XML, strategies={"tools": strategy}), capabilities=caps, registry=REG)


def test_same_program_native_and_fenced():
    native = plan({"native_function_calling": True})
    fenced = plan({"instruct": True})
    rn = native.render(question="q", tools=[WEATHER])
    rf = fenced.render(question="q", tools=[WEATHER])
    assert rn.patch["tools"][0] == {"type": "function", "name": "get_weather", "description": "Weather for a city.",
                                    "parameters": WEATHER.parameters}
    assert "get_weather(" in rf.system and rf.patch == {}          # via: tool_catalog, not function_tool
    assert native.describe()["hidden"] == fenced.describe()["hidden"] == ["tools", "calls"]


def test_call_turn_omits_the_answer_and_answer_turn_has_empty_calls():
    native = plan({"native_function_calling": True})
    assert native.parse({"role": "assistant", "parts": [CALL]}) == {
        "calls": [ToolCall("c1", "get_weather", {"city": "Paris"})]}
    assert native.parse("<answer>\nSunny.\n</answer>") == {"calls": [], "answer": "Sunny."}
    fenced = plan({"instruct": True})
    assert fenced.parse('```tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n```') == {
        "calls": [ToolCall("call_1", "get_weather", {"city": "Paris"})]}
    # a reply with neither is still a missing-fields refusal: suffices needs a capture
    with pytest.raises(lmcc.Refusal) as err:
        native.parse("nothing here")
    assert err.value.code == "parse-missing-fields"


def test_streaming_call_turn_matches_batch():
    native = plan({"native_function_calling": True})
    s = native.stream()
    s.feed({"type": "tool_call", "id": "c1", "name": "get_weather", "input": {"city": "Paris"}})
    result = s.finish()
    assert result.values == native.parse({"role": "assistant", "parts": [CALL]})
    assert [e["field"] for e in result.events if e["kind"] == "field_done"] == ["calls"]


def test_history_native_verbatim_fenced_spelled():
    hist = [{"role": "assistant", "parts": [CALL]}, {"role": "tool", "parts": [RESULT]}]
    native = plan({"native_function_calling": True}).render(question="q", tools=[WEATHER], history=hist)
    assert native.messages[0]["parts"] == [CALL] and native.messages[1]["role"] == "tool"
    fenced = plan({"instruct": True}).render(question="q", tools=[WEATHER], history=hist)
    assert fenced.messages[0] == {"role": "assistant", "parts": [{"type": "text", "text":
        '```tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n```'}]}
    assert fenced.messages[1] == {"role": "user", "parts": [{"type": "text", "text": "Result of get_weather (c1):\nSunny"}]}


def test_turns_probe_refuses_a_spelling_the_routing_cannot_read():
    bad = lmcc_std.tools.fenced_tools({})
    bad.turns = {"call": "CALL {name} {input}"}
    with pytest.raises(lmcc.Refusal) as err:
        plan({"instruct": True}, bad)
    assert err.value.code == "turns-drift"
    assert err.value.fix == {"action": "edit-entry", "path": "strategies['tools'].turns"}
    escaped = lmcc_std.tools.fenced_tools({})
    escaped.turns["call"] = "```tool\n{{\"name\": \"{name}\", \"input\": {input}}}\n```"   # {{ }} escape, same bytes
    plan({"instruct": True}, escaped)


def test_via_needs_a_placed_field_and_a_registered_format():
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.Strategy(visible=False, placement={"@role": "message:system"}, via={"@role.x": "tool_catalog"},
                      routings=[{"from": "channel:tool_call", "to": "@role.calls"}]).validate(where="s")
    assert err.value.code == "entry-malformed" and err.value.fix["path"] == "s.via"
    s = lmcc_std.tools.fenced_tools({})
    s.via = {"@role": "nope"}
    with pytest.raises(lmcc.Refusal) as err:
        plan({"instruct": True}, s)
    assert err.value.code == "unknown-format"


def test_tool_calls_format_refuses_non_json_fenced_call_and_dump_roundtrips():
    fenced = plan({"instruct": True})
    with pytest.raises(lmcc.Refusal) as err:
        fenced.parse("```tool\nnot json\n```")
    assert err.value.code == "format-read-error"
    entry = lmcc.adapter(messages=XML, strategies={"tools": "fenced_tools"}).dump(registry=REG)
    assert entry["versions"]["vocab"]["strategy/fenced_tools"] == "0.1.0"
    assert lmcc.load(entry, registry=REG).strategies["tools"]["use"] == "fenced_tools"


# ---------------------------------------------------------------- citations

@dataclasses.dataclass
class Grounded:
    answer: str
    citations: lmcc.Role["citations", list[Citation]]


@lmcc.fn
def grounded(question: str, sources: lmcc.Role["citations.sources", list[Source]]) -> Grounded:
    """Answer from the sources."""


@lmcc.fn
def searched(question: str) -> Grounded:
    """Answer with sources."""


CX = [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"), lmcc.user("{question}")]


def test_inline_citations_spell_sources_and_read_markers():
    p = grounded.bind(lmcc.adapter(messages=CX, strategies={"citations": "inline_citations"}),
                      capabilities={"instruct": True}, registry=REG)
    r = p.render(question="Capital?", sources=[Source("Paris is the capital.", title="Atlas"), Source("Lyon.", url="u")])
    assert r.messages[0]["parts"][0]["text"] == "Capital?\n\n[1] Atlas: Paris is the capital.\n[2] u: Lyon."
    v = p.parse("<answer>\nParis [1], not Lyon [2] [1] [see].\n</answer>")
    assert v["citations"] == [Citation(source=1), Citation(source=2)]
    assert v["answer"] == "Paris [1], not Lyon [2] [1] [see]."      # consume: false keeps the prose


def test_native_citations_ask_for_search_and_read_citation_parts():
    p = searched.bind(lmcc.adapter(messages=CX, strategies={"citations": "native_citations"}),
                      capabilities={"native_citations": True}, registry=REG)
    assert p.render(question="q").patch == {"tools": [{"type": "builtin", "name": "web_search"}]}
    v = p.parse({"role": "assistant", "parts": [{"type": "text", "text": "<answer>\nParis\n</answer>"},
                                                 {"type": "citation", "url": "https://x", "title": "X", "text": "t"}]})
    assert v == {"answer": "Paris", "citations": [Citation(url="https://x", title="X", text="t")]}
    quiet = lmcc.use("native_citations", search=False)
    assert searched.bind(lmcc.adapter(messages=CX, strategies={"citations": quiet}),
                         capabilities={"native_citations": True}, registry=REG).render(question="q").patch == {}

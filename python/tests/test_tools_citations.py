"""Tools and citations (spec/vocab/transport-tools.md, transport-citations.md)
and the kernel mechanics they rely on: `complete_reply`, `written_as`, `turns` + probe."""

import dataclasses

import pytest

import lmcc
import lmcc_std
from lmcc_std.tools import Citation, Source, Tool, ToolCall

REG = lmcc.Registry()
lmcc_std.install(REG)
XML = [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
       lmcc.turns(), lmcc.user("{question}")]
WEATHER = Tool("get_weather", "Weather for a city.",
               {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})
CALL = {"type": "tool_call", "id": "c1", "name": "get_weather", "input": {"city": "Paris"}}
RESULT = {"type": "tool_result", "id": "c1", "name": "get_weather", "content": [{"type": "text", "text": "Sunny"}]}


@dataclasses.dataclass
class Out:
    calls: lmcc.Purpose["tools.calls", list[ToolCall]]
    answer: str


@lmcc.fn
def ask(question: str, tools: lmcc.Purpose["tools", list[Tool]]) -> Out:
    """Answer, using tools when needed."""


AUTO = lmcc.Transport(choose=[
    {"when": {"capability": "native_function_calling"}, "use": lmcc_std.tools.native_tools({})},
    {"else": lmcc_std.tools.fenced_tools({})}])


def plan(caps, transport=AUTO):
    return ask.bind(lmcc.adapter(messages=XML, transports={"tools": transport}), capabilities=caps, registry=REG)


def test_same_program_native_and_fenced():
    native = plan({"native_function_calling": True})
    fenced = plan({"instruct": True})
    rn = native.render(question="q", tools=[WEATHER])
    rf = fenced.render(question="q", tools=[WEATHER])
    assert rn.request_settings["tools"][0] == {"type": "function", "name": "get_weather", "description": "Weather for a city.",
                                    "parameters": WEATHER.parameters}
    assert "get_weather(" in rf.system and rf.request_settings == {}          # written_as: tool_catalog, not function_tool
    assert native.describe()["hidden"] == fenced.describe()["hidden"] == ["tools", "calls"]


def test_call_turn_omits_the_answer_and_answer_turn_has_empty_calls():
    native = plan({"native_function_calling": True})
    assert native.parse({"role": "assistant", "parts": [CALL]}) == {
        "calls": [ToolCall("c1", "get_weather", {"city": "Paris"})]}
    assert native.parse("<answer>\nSunny.\n</answer>") == {"calls": [], "answer": "Sunny."}
    fenced = plan({"instruct": True})
    assert fenced.parse('```tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n```') == {
        "calls": [ToolCall("call_1", "get_weather", {"city": "Paris"})]}
    # a reply with neither is still a missing-fields refusal: complete_reply needs a capture
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


def test_one_recorded_turn_native_verbatim_fenced_respelled():
    native_plan = plan({"native_function_calling": True})
    rendered = native_plan.render(native_plan.turn(question="q", tools=[WEATHER]))
    current = rendered.step({"role": "assistant", "parts": [CALL]}).tool("c1", "Sunny")
    native = native_plan.render(current)
    assert native.messages[1]["parts"] == [CALL] and native.messages[2]["role"] == "tool"
    fenced_plan = plan({"instruct": True})
    fenced = fenced_plan.render(current)    # the same record, the other adapter: re-spelled
    assert fenced.messages[1] == {"role": "assistant", "parts": [{"type": "text", "text":
        '```tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n```'}]}
    assert fenced.messages[2] == {"role": "user", "parts": [{"type": "text", "text": "Result of get_weather (c1):\nSunny"}]}


def test_spelling_probe_refuses_what_the_find_rule_cannot_read():
    bad = lmcc_std.tools.fenced_tools({})
    bad.spelling = {"call": "CALL {name} {input}"}
    with pytest.raises(lmcc.Refusal) as err:
        plan({"instruct": True}, bad)
    assert err.value.code == "spelling-drift"
    assert err.value.fix == {"action": "edit-entry", "path": "transports['tools'].spelling"}
    escaped = lmcc_std.tools.fenced_tools({})
    escaped.spelling["call"] = "```tool\n{{\"name\": \"{name}\", \"input\": {input}}}\n```"   # {{ }} escape, same bytes
    plan({"instruct": True}, escaped)


def test_via_needs_a_placed_field_and_a_registered_format():
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.Transport(in_template=False, put={"@purpose": "message:system"}, written_as={"@purpose.x": "tool_catalog"},
                      find=[{"from": "part:tool_call", "to": "@purpose.calls"}]).validate(where="s")
    assert err.value.code == "entry-malformed" and err.value.fix["path"] == "s.written_as"
    s = lmcc_std.tools.fenced_tools({})
    s.written_as = {"@purpose": "nope"}
    with pytest.raises(lmcc.Refusal) as err:
        plan({"instruct": True}, s)
    assert err.value.code == "unknown-format"


def test_tool_calls_format_refuses_non_json_fenced_call_and_dump_roundtrips():
    fenced = plan({"instruct": True})
    with pytest.raises(lmcc.Refusal) as err:
        fenced.parse("```tool\nnot json\n```")
    assert err.value.code == "format-read-error"
    entry = lmcc.adapter(messages=XML, transports={"tools": "fenced_tools"}).dump(registry=REG)
    assert entry["versions"]["vocab"]["transport/fenced_tools"] == "0.1.0"
    assert lmcc.load(entry, registry=REG).transports["tools"]["use"] == "fenced_tools"


# ---------------------------------------------------------------- citations

@dataclasses.dataclass
class Grounded:
    answer: str
    citations: lmcc.Purpose["citations", list[Citation]]


@lmcc.fn
def grounded(question: str, sources: lmcc.Purpose["citations.sources", list[Source]]) -> Grounded:
    """Answer from the sources."""


@lmcc.fn
def searched(question: str) -> Grounded:
    """Answer with sources."""


CX = [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"), lmcc.user("{question}")]


def test_inline_citations_spell_sources_and_read_markers():
    p = grounded.bind(lmcc.adapter(messages=CX, transports={"citations": "inline_citations"}),
                      capabilities={"instruct": True}, registry=REG)
    r = p.render(question="Capital?", sources=[Source("Paris is the capital.", title="Atlas"), Source("Lyon.", url="u")])
    assert r.messages[0]["parts"][0]["text"] == "Capital?\n\n[1] Atlas: Paris is the capital.\n[2] u: Lyon."
    v = p.parse("<answer>\nParis [1], not Lyon [2] [1] [see].\n</answer>")
    assert v["citations"] == [Citation(source=1), Citation(source=2)]
    assert v["answer"] == "Paris [1], not Lyon [2] [1] [see]."      # remove: false keeps the prose


def test_native_citations_ask_for_search_and_read_citation_parts():
    p = searched.bind(lmcc.adapter(messages=CX, transports={"citations": "native_citations"}),
                      capabilities={"native_citations": True}, registry=REG)
    assert p.render(question="q").request_settings == {"tools": [{"type": "builtin", "name": "web_search"}]}
    v = p.parse({"role": "assistant", "parts": [{"type": "text", "text": "<answer>\nParis\n</answer>"},
                                                 {"type": "citation", "url": "https://x", "title": "X", "text": "t"}]})
    assert v == {"answer": "Paris", "citations": [Citation(url="https://x", title="X", text="t")]}
    quiet = lmcc.use("native_citations", search=False)
    assert searched.bind(lmcc.adapter(messages=CX, transports={"citations": quiet}),
                         capabilities={"native_citations": True}, registry=REG).render(question="q").request_settings == {}

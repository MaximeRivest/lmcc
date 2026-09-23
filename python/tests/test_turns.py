"""Turns (kernel §3a): the record, its lifecycle, and the rules the corpus
cannot express without host code (Python formats, typed values)."""

import dataclasses
import json

import pytest

import lmcc
import lmcc_std
from lmcc_std.tools import Tool, ToolCall

registry = lmcc.Registry()
lmcc_std.install(registry)


@dataclasses.dataclass
class Reply:
    reply: str
    reasoning: lmcc.Purpose["reasoning", str]
    calls: lmcc.Purpose["tools.calls", list[ToolCall]]


@lmcc.fn
def agent(message: str, tools: lmcc.Purpose["tools", list[Tool]]) -> Reply:
    """Help. A tool request is not execution."""


TOOLS = [Tool("run_python", "Run Python.", {"type": "object", "properties": {"code": {"type": "string"}}})]
THINK = lmcc.Transport(in_template=False, spelling={"position": "before"},
                      find=[{"from": "text", "between": ["<think>", "</think>"], "to": "@purpose", "remove": True}])
CALL = "<think>Use Python.</think>\nrun_python <<'PY_END'\nprint(6 * 7)\nPY_END"


def heredoc(messages=None, **kw):
    adapter = lmcc.adapter(
        messages=messages or [lmcc.system("{instruction}\n{reply}"), lmcc.turns(), lmcc.user("{message}")],
        formats={"list[Tool]": lmcc.use("function_tool"), "list[ToolCall]": lmcc.use("code_calls")},
        transports={"reasoning": THINK, "tools": lmcc.use("heredoc_tools")}, **kw)
    return agent.bind(adapter, capabilities={"instruct": True}, registry=registry)


def native():
    adapter = lmcc.adapter(
        messages=[lmcc.system("{instruction}\n{reply}"), lmcc.turns(), lmcc.user("{message}")],
        formats={"list[Tool]": lmcc.use("function_tool"), "list[ToolCall]": lmcc.use("tool_calls")},
        transports={"reasoning": lmcc.use("native_reasoning"), "tools": lmcc.use("native_tools")})
    return agent.bind(adapter, capabilities={"native_function_calling": True, "native_reasoning": True}, registry=registry)


def episode(plan):
    turn = plan.render(plan.turn(message="6*7?", tools=TOOLS)).step(CALL)
    turn = turn.tool(turn.pending_calls()[0].id, "42")
    return plan.render(turn).step("The result is 42.").finish()


# ------------------------------------------------------------ lifecycle

def test_render_inputs_is_render_of_a_new_turn():
    plan = heredoc()
    assert plan.render(message="hi", tools=TOOLS) == plan.render(plan.turn(message="hi", tools=TOOLS))


def test_step_records_values_message_request_hash_and_calls_field():
    plan = heredoc()
    rendered = plan.render(plan.turn(message="6*7?", tools=TOOLS))
    step = rendered.step(CALL).steps[0]
    assert step.outputs["calls"] == [ToolCall("call_1", "run_python", {"code": "print(6 * 7)"})]
    assert step.message == {"role": "assistant", "parts": [{"type": "text", "text": CALL}]}
    assert step.request == lmcc.turn.sha256(rendered.request()) and step.calls_field == "calls"


def test_the_live_input_is_written_once_and_the_reply_as_it_came():
    plan = heredoc()
    turn = plan.render(plan.turn(message="6*7?", tools=TOOLS)).step(CALL).tool("call_1", "42")
    texts = [(m["role"], m["parts"][0]["text"]) for m in plan.render(turn).messages]
    assert texts == [("user", "6*7?"), ("assistant", CALL), ("user", "Result of run_python (call_1):\n42")]


def test_tool_and_finish_refuse_out_of_order():
    plan = heredoc()
    turn = plan.render(plan.turn(message="x", tools=TOOLS)).step(CALL)
    for bad in (lambda: turn.tool("call_9", "42"), turn.finish, lambda: plan.render(turn),
                lambda: plan.turn(message="x").tool("call_1", "42"), plan.turn(message="x").finish):
        with pytest.raises(lmcc.Refusal) as err:
            bad()
        assert err.value.code == "turn-invalid" and err.value.fix is None


def test_turns_are_immutable():
    plan = heredoc()
    start = plan.turn(message="x", tools=TOOLS)
    plan.render(start).step(CALL)
    assert start.steps == ()


# ------------------------------------------------------------ JSON

def test_json_round_trip_lifts_values_and_renders_identically():
    plan = heredoc()
    done = episode(plan)
    blob = json.loads(json.dumps(done.to_dict()))
    back = plan.load_turn(blob)
    assert back.outputs == done.outputs and isinstance(back.steps[0].outputs["calls"][0], ToolCall)
    nxt = plan.turn(message="again", tools=TOOLS)
    assert plan.render(nxt, turns=[back]) == plan.render(nxt, turns=[done])
    assert blob["signature"] == lmcc.signature_fingerprint(agent.signature)


def test_fingerprint_ignores_prose_and_changes_with_fields():
    a = lmcc.signature("Say it.", inputs={"q": str}, outputs={"a": str})
    b = lmcc.signature("Say it differently.", inputs={"q": str}, outputs={"a": str})
    c = lmcc.signature("Say it.", inputs={"q": str}, outputs={"a": int})
    assert lmcc.signature_fingerprint(a) == lmcc.signature_fingerprint(b) != lmcc.signature_fingerprint(c)


def test_host_values_without_json_refuse():
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.Turn("sha256:x", {"message": object()}).to_dict()
    assert err.value.code == "turn-invalid"


# ------------------------------------------------------------ swapping adapters

def test_text_recorded_turn_under_native_drops_unforgeable_thinking():
    past = episode(heredoc())
    plan = native()
    r = plan.render(message="again", tools=TOOLS, turns=[past])
    kinds = [(m["role"], [p["type"] for p in m["parts"]]) for m in r.messages]
    assert kinds[1] == ("assistant", ["tool_call"]) and kinds[2] == ("tool", ["tool_result"])
    assert r.messages[1]["parts"][0]["id"] == "s0_call_1" == r.messages[2]["parts"][0]["id"]
    assert plan.describe()["turns"]["replayed"] == ["reasoning"]


def test_native_recorded_thinking_goes_back_verbatim():
    plan = native()
    signed = {"type": "thinking", "text": "Arithmetic.", "continuation": {"signature": "opaque"}}
    reply = {"role": "assistant", "parts": [signed, {"type": "tool_call", "id": "tc_1", "name": "run_python",
                                                     "input": {"code": "print(1)"}}]}
    turn = plan.render(plan.turn(message="x", tools=TOOLS)).step(reply).tool("tc_1", "1")
    assert plan.render(turn).messages[1] == reply


def test_tool_images_follow_the_result_text():
    plan = heredoc()
    image = {"type": "image", "media_type": "image/png", "url": "https://example.com/chart.png"}
    turn = plan.render(plan.turn(message="x", tools=TOOLS)).step(CALL)
    turn = turn.tool("call_1", [{"type": "text", "text": "chart"}, image])
    assert plan.render(turn).messages[-1]["parts"] == [
        {"type": "text", "text": "Result of run_python (call_1):\nchart"}, image]


def test_children_are_kept_and_never_written():
    plan = heredoc()
    child = episode(plan)
    turn = plan.render(plan.turn(message="x", tools=TOOLS)).step(CALL).tool("call_1", "42", children=[child])
    assert turn.steps[1].children == (child,)
    assert "The result is 42." not in json.dumps(plan.render(turn).messages)
    assert turn.to_dict()["steps"][1]["children"][0]["outputs"]["reply"] == "The result is 42."


# ------------------------------------------------------------ slots

def test_text_form_refuses_parts_it_cannot_hold():
    plan = agent.bind(lmcc.adapter(
        messages=[lmcc.system("{instruction}\n{% for m in examples %}{m.text}\n{% endfor %}\n{reply}"),
                  lmcc.user("{message}")],
        formats={"list[Tool]": lmcc.use("function_tool"), "list[ToolCall]": lmcc.use("tool_calls")},
        transports={"reasoning": THINK, "tools": lmcc.use("native_tools")}),
        capabilities={"native_function_calling": True}, registry=registry)
    reply = {"role": "assistant", "parts": [{"type": "tool_call", "id": "t", "name": "run_python", "input": {}}]}
    past = plan.render(plan.turn(message="x", tools=TOOLS)).step(reply).tool("t", "1")
    past = plan.render(past).step("done").finish()
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(message="y", tools=TOOLS, turns={"examples": [past]})
    assert err.value.code == "turn-not-renderable" and "tool_call" in err.value.hint


def test_steps_need_a_slot_and_slots_need_names():
    plan = agent.bind(lmcc.adapter(
        messages=[lmcc.system("{instruction}\n{reply}"), lmcc.user("{message}")],
        formats={"list[Tool]": lmcc.use("function_tool"), "list[ToolCall]": lmcc.use("code_calls")},
        transports={"reasoning": THINK, "tools": lmcc.use("heredoc_tools")}), capabilities={"instruct": True}, registry=registry)
    turn = plan.render(plan.turn(message="x", tools=TOOLS)).step(CALL).tool("call_1", "42")
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(turn)
    assert err.value.code == "turns-unplaced"
    for bad, code in ((lmcc.turns("inputs"), "template-syntax"), (lmcc.turns("message"), "turns-layout")):
        with pytest.raises(lmcc.Refusal) as err:
            heredoc([lmcc.system("{instruction}\n{reply}"), bad, lmcc.user("{message}")])
        assert err.value.code == code
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=[lmcc.system("{% if examples %}x{% endif %}{instruction}\n{reply}"),
                               lmcc.user("{message}")])
    assert err.value.code == "template-syntax"


def test_the_output_pattern_cannot_hide_behind_a_guard():
    with pytest.raises(lmcc.Refusal) as err:
        heredoc([lmcc.system("{instruction}\n{% if turns %}ANSWER: {reply}{% endif %}"),
                 lmcc.turns(), lmcc.user("{message}")])
    assert err.value.code == "not-readable"


# ------------------------------------------------------------ writers at bind

class ReadOnly(lmcc.Format):
    accepts = ("string",)
    direction = "out"

    def __init__(self, options):
        pass

    def read(self, capture, field):
        return capture.text


class FromCallComments(lmcc.Format):
    accepts = ("string",)
    direction = "out"
    reads = ("tool_call",)

    def __init__(self, options):
        pass

    def read(self, capture, field):
        return "\n".join(line[1:].strip() for p in capture.parts
                         for line in p["input"].get("code", "").splitlines() if line.startswith("#"))


def _with_reasoning_format(fmt, transport, tools="heredoc_tools", caps=None):
    reg = lmcc.Registry()
    lmcc_std.install(reg)
    reg.register_format("test/reasoning", fmt)
    sig = lmcc.signature_to_dict(agent.signature)
    for f in sig["fields"]:
        if f["name"] == "reasoning":
            f["type"] = "Analysis"
    adapter = lmcc.adapter(
        messages=[lmcc.system("{instruction}\n{reply}"), lmcc.turns(), lmcc.user("{message}")],
        formats={"list[Tool]": lmcc.use("function_tool"),
                 "list[ToolCall]": lmcc.use("code_calls" if tools == "heredoc_tools" else "tool_calls"),
                 "Analysis": lmcc.use("test/reasoning")},
        transports={"reasoning": transport, "tools": lmcc.use(tools)})
    return adapter.bind(lmcc.signature_from_dict(sig), caps or {"instruct": True}, registry=reg)


def test_a_read_only_reasoning_format_refuses_at_bind_not_render():
    with pytest.raises(lmcc.Refusal) as err:
        _with_reasoning_format(ReadOnly, THINK)
    assert err.value.code == "spelling-drift"
    assert err.value.fix == {"action": "edit-entry", "path": "transports['reasoning'].spelling"}
    dropped = lmcc.Transport(in_template=False, spelling={"value": None},
                            find=[{"from": "text", "between": ["<think>", "</think>"], "to": "@purpose",
                                       "remove": True}])
    assert _with_reasoning_format(ReadOnly, dropped).describe()["turns"]["writers"]["reasoning"] == {"by": "dropped"}


def test_reasoning_read_from_native_calls_is_a_projection_not_a_second_call():
    comments = lmcc.Transport(in_template=False, find=[{"from": "part:tool_call", "to": "@purpose"}])
    plan = _with_reasoning_format(FromCallComments, comments, tools="native_tools",
                                  caps={"native_function_calling": True})
    assert plan.describe()["turns"]["projections"] == {"reasoning": "calls"}
    reply = {"role": "assistant", "parts": [{"type": "tool_call", "id": "tc_1", "name": "run_python",
                                             "input": {"code": "# why\nprint(1)"}}]}
    turn = plan.render(plan.turn(message="x", tools=TOOLS)).step(reply).tool("tc_1", "1")
    assert turn.steps[0].outputs["reasoning"] == "why"
    for replay in ("recorded", "values"):
        plan.adapter.replay = replay
        assert [p["type"] for p in plan.render(turn).messages[1]["parts"]] == ["tool_call"]

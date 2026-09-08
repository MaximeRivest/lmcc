"""lmcc_lm15: the typed face over a shared wire — offline, against real lm15 types.

No network, no keys: lm15 objects are built by hand. What is proven:
the plan's request *is* an lm15 Request through lm15's own serde; a
plan's patch reaches Config; a caller cannot silently contradict it; an
lm15 Response parses; lm15 stream events drive lmcc's stream to the
same values as batch (kernel §8).
"""

import dataclasses

import pytest

import lmcc
import lmcc_std

lm15 = pytest.importorskip("lm15")
import lmcc_lm15  # noqa: E402
from lm15 import (Config, Message, Reasoning, Request, Response, StreamDeltaEvent, StreamEndEvent,
                  StreamStartEvent, TextDelta, ThinkingDelta, ThinkingPart, TextPart, Usage)
from lm15.serde import request_to_dict


@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Role["reasoning", str]
    answer: int


@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve it."""


XML = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{problem}")])
REG = lmcc.Registry()
lmcc_std.install(REG)


def plan_for(strategy, caps):
    adapter = lmcc.adapter(messages=XML.template, strategies={"reasoning": strategy})
    return solve.bind(adapter, capabilities=caps, registry=REG)


def test_request_is_an_lm15_request_through_lm15_serde():
    plan = plan_for("reasoning_tags", {"instruct": True})
    rendered = plan.render(problem="2+2")
    req = lmcc_lm15.request(rendered, model="m", config=Config(max_tokens=64))
    assert isinstance(req, Request) and req.model == "m"
    assert isinstance(req.system, str) and "<think>" in req.system
    assert [m.role for m in req.messages] == ["user"] and isinstance(req.messages[0].parts[0], TextPart)
    assert req.config.max_tokens == 64
    # the canonical JSON of the lm15 Request equals lmcc's rendered request plus the Config
    assert request_to_dict(req) == {**rendered.request("m"), "config": {"max_tokens": 64}}


def test_a_strategy_patch_reaches_config_and_the_caller_cannot_contradict_it():
    plan = plan_for("native_reasoning", {"instruct": True, "native_reasoning": True})
    rendered = plan.render(problem="2+2")
    assert rendered.patch == {"config": {"reasoning": {"effort": "medium"}}}
    req = lmcc_lm15.request(rendered, model="m", config=Config(max_tokens=64))
    assert req.config.reasoning == Reasoning(effort="medium") and req.config.max_tokens == 64
    with pytest.raises(lmcc_lm15.ConfigConflict) as err:
        lmcc_lm15.request(rendered, model="m", config=Config(reasoning=Reasoning(effort="high")))
    assert "config.reasoning.effort" in str(err.value)
    forced = lmcc_lm15.request(rendered, model="m", config=Config(reasoning=Reasoning(effort="high")), override=True)
    assert forced.config.reasoning.effort == "high"
    # agreeing is not a conflict
    same = lmcc_lm15.request(rendered, model="m", config=Config(reasoning=Reasoning(effort="medium")))
    assert same.config.reasoning.effort == "medium"


def test_native_reasoning_options_spell_lm15_reasoning():
    adapter = lmcc.adapter(messages=XML.template, strategies={"reasoning": lmcc.use(
        "native_reasoning", effort="low", thinking_budget=1024)})
    plan = solve.bind(adapter, capabilities={"native_reasoning": True}, registry=REG)
    req = lmcc_lm15.request(plan.render(problem="x"), model="m")
    assert req.config.reasoning == Reasoning(effort="low", thinking_budget=1024)


def _response(*parts):
    return Response(id="r", model="m", message=Message.assistant(parts), finish_reason="stop",
                    usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2))


def test_parse_reads_an_lm15_response_and_a_message():
    plan = plan_for("native_reasoning", {"instruct": True, "native_reasoning": True})
    resp = _response(ThinkingPart("two and two"), TextPart("<answer>\n4\n</answer>"))
    assert lmcc_lm15.parse(plan, resp) == {"reasoning": "two and two", "answer": 4}
    assert lmcc_lm15.parse(plan, resp.message) == {"reasoning": "two and two", "answer": 4}


def test_stream_events_drive_the_plan_to_the_batch_values():
    plan = plan_for("native_reasoning", {"instruct": True, "native_reasoning": True})
    events = [StreamStartEvent(id="r", model="m"),
              StreamDeltaEvent(delta=ThinkingDelta(text="two ", part_index=0)),
              StreamDeltaEvent(delta=ThinkingDelta(text="and two", part_index=0)),
              StreamDeltaEvent(delta=TextDelta(text="<answer>\n", part_index=1)),
              StreamDeltaEvent(delta=TextDelta(text="4\n</answer>", part_index=1)),
              StreamEndEvent(finish_reason="stop")]
    emitted, result = lmcc_lm15.stream(plan, events)
    assert result.values == {"reasoning": "two and two", "answer": 4}
    deltas = "".join(e["text"] for e in emitted if e["kind"] == "field_delta" and e["field"] == "reasoning")
    assert deltas == "two and two"
    batch = lmcc_lm15.parse(plan, _response(ThinkingPart("two and two"), TextPart("<answer>\n4\n</answer>")))
    assert batch == result.values


def test_json_lens_patch_is_a_valid_lm15_response_format():
    sig = lmcc.signature("x", inputs={"q": str}, outputs={"answer": str, "n": int})
    plan = lmcc.adapter(messages=[lmcc.user("{q}")], parse={"kind": "json_object"}).bind(
        sig, {"native_structured_output": True}, registry=REG)
    req = lmcc_lm15.request(plan.render(q="?"), model="m")
    assert req.config.response_format["type"] == "json_schema"
    assert req.config.response_format["schema"]["required"] == ["answer", "n"]

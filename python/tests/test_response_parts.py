"""Response part normalization and shape checks (kernel §6, §8)."""
import copy

import pytest

import lmcc
from lmcc import core


def test_logical_parts_metadata_boundaries_and_input_ownership():
    parts = [
        {"type": "thinking", "text": "fo", "id": 1, "keep": True},
        {"type": "thinking", "text": "", "id": 2},
        {"type": "thinking", "text": "ur"},
        {"type": "thinking", "id": 3},
        {"type": "thinking", "text": "b"},
        {"type": "text", "text": "<answer>ok</answer>"},
    ]
    before = copy.deepcopy(parts)
    expected = [
        {"type": "thinking", "text": "four", "id": 2, "keep": True},
        {"type": "thinking", "id": 3},
        {"type": "thinking", "text": "b"},
        {"type": "text", "text": "<answer>ok</answer>"},
    ]
    assert core.response_text_and_parts({"role": "assistant", "parts": parts}) == ("<answer>ok</answer>", expected)
    plan = lmcc.adapter(messages=[lmcc.system("<answer>{answer}</answer>")]).bind(
        lmcc.signature("", outputs={"answer": str}))
    stream = plan.stream()
    for part in parts:
        stream.feed(part)
    assert stream._materialized_parts() == expected
    assert stream.finish().values == {"answer": "ok"}
    assert parts == before


@pytest.mark.parametrize("part", [None, 7, [], "bare", {}, {"type": None},
    {"type": 7}, {"type": "text", "text": None}, {"type": "thinking", "text": 7}])
def test_malformed_parts_refuse_without_fix_or_host_errors(part):
    plan = lmcc.adapter(messages=[lmcc.system("<answer>{answer}</answer>")]).bind(
        lmcc.signature("", outputs={"answer": str}))
    with pytest.raises(lmcc.Refusal) as batch:
        plan.parse({"role": "assistant", "parts": [part]})
    assert batch.value.code == "response-malformed"
    assert batch.value.fix is None
    if not isinstance(part, str):  # Strings are legal text deltas, not legal list parts.
        with pytest.raises(lmcc.Refusal) as feed:
            plan.stream().feed(part)
        assert feed.value.describe() == batch.value.describe()

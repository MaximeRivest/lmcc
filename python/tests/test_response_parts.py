"""Response part normalization and shape checks (kernel §6, §8)."""
import copy

import lmcc
from lmcc import core


def test_logical_parts_metadata_boundaries_and_input_ownership():
    parts = [
        {"kind": "thinking", "text": "fo", "id": 1, "keep": True},
        {"kind": "thinking", "text": "", "id": 2},
        {"kind": "thinking", "text": "ur"},
        {"kind": "thinking", "id": 3},
        {"kind": "thinking", "text": "b"},
        {"kind": "text", "text": "<answer>ok</answer>"},
    ]
    before = copy.deepcopy(parts)
    expected = [
        {"kind": "thinking", "text": "four", "id": 2, "keep": True},
        {"kind": "thinking", "id": 3},
        {"kind": "thinking", "text": "b"},
        {"kind": "text", "text": "<answer>ok</answer>"},
    ]
    assert core.response_text_and_parts({"content": parts}) == ("<answer>ok</answer>", expected)
    plan = lmcc.adapter(messages=[lmcc.system("<answer>{answer}</answer>")]).bind(
        lmcc.signature("", outputs={"answer": str}))
    stream = plan.stream()
    for part in parts:
        stream.feed(part)
    assert stream._materialized_parts() == expected
    assert stream.finish().values == {"answer": "ok"}
    assert parts == before

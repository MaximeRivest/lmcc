"""Keep the research notebook's claims executable, not merely its imports.

The notebook is the single implementation of the experimental formats and
transports. These tests load its cells and check the complete factor matrix,
raw code, reasoning projections, turns, artifacts and streaming.
"""

import ast
import copy
import itertools
import re
import runpy
import sys
from pathlib import Path

import pytest
import lmcc

NOTEBOOK = Path(__file__).resolve().parents[2] / "docs/howto/13-research-tool-reasoning-cross-design.md"


def cells():
    return re.findall(r"```python\n(.*?)```", NOTEBOOK.read_text(), re.DOTALL)


@pytest.fixture(scope="module")
def research(tmp_path_factory):
    path = tmp_path_factory.mktemp("research_notebook") / "research_cross_design.py"
    path.write_text("\n".join(cells()))
    return runpy.run_path(str(path), run_name="research_notebook")


def test_notebook_imports_only_kernel_and_stdlib():
    tree = ast.parse("\n".join(cells()))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"eval", "exec", "__import__"}
    assert imports <= sys.stdlib_module_names | {"lmcc"}
    assert "lmcc_std" not in imports and "lmcc_lm15" not in imports


def test_full_matrix_is_simulated_and_declares_controls(research):
    r = research
    keys = set(itertools.product(r["CALL_STYLES"], r["REASONING_STYLES"]))
    assert set(r["plans"]) == keys and len(keys) == len(r["rows"]) == 9
    for (call_style, style), (turn, requests) in r["episodes"].items():
        records = [s.outputs for s in turn.steps if s.kind == "model"]
        assert [s.kind for s in turn.steps] == ["model", "tool", "model"]
        assert len(records) == len(requests) == 2 and turn.outputs == records[-1]
        first, final = records
        assert first["reply"] == ""
        assert len(first["calls"]) == 1
        assert first["calls"][0].name == "run_python"
        code = r["COMMENT_CODE"] if style == "code_comments" else r["PLAIN_CODE"]
        assert first["calls"][0].input == {"code": code}
        want_reasoning = ("Multiply the two numbers.\nReport the result."
                          if style == "code_comments" else r["RATIONALE"])
        assert first["reasoning"] == want_reasoning
        assert final == {"reply": "The result is 42.", "calls": [], "reasoning": ""}
        for request in requests:
            assert request["config"]["reasoning"]["effort"] == ("low" if style == "native" else "off")
            if call_style == "native":
                assert request["tools"][0]["type"] == "function"
            else:
                assert "tools" not in request
        second = requests[1]["messages"]
        assert second[0]["parts"][0]["text"] == r["TASK"]
        assert second[-1]["role"] == ("tool" if call_style == "native" else "user")
        # the recorded reply goes back exactly as it came
        assert second[1]["parts"] == r["simulated_call_reply"](call_style, style)["parts"]


def response_with_code(research, call_style, code):
    if call_style == "native":
        return {"role": "assistant", "parts": [{"type": "tool_call", "id": "fixture_call",
                "name": "run_python", "input": {"code": code}}]}
    if call_style == "json_fence":
        payload = research["json"].dumps({"name": "run_python", "input": {"code": code}})
    else:
        payload = code
    opening, closing = research["ENVELOPES"][call_style]
    return {"role": "assistant", "parts": [{"type": "text", "text": opening + payload + closing}]}


@pytest.mark.parametrize("call_style", ["native", "json_fence", "heredoc"])
def test_comments_are_tokens_not_string_contents_and_code_is_unchanged(research, call_style):
    code = ('# reason: Explain the actual statement.\r\n'
            'text = "# reason: not analysis <think>not a tag</think>"\r\n'
            'print(text)  # reason: trailing comment excluded\r\n')
    plan = research["plans"][(call_style, "code_comments")]
    value = plan.parse(response_with_code(research, call_style, code))
    assert value["reasoning"] == "Explain the actual statement."
    assert value["calls"][0].input["code"] == code
    assert value["reply"] == ""
    assert plan.parse("Hello!") == {"reply": "Hello!", "calls": [], "reasoning": ""}


def stream_chunkings(message):
    parts = message["parts"]
    yield copy.deepcopy(parts)
    # One-scalar replay plus every split inside each text-bearing part.
    yield [delta for part in parts for delta in (
        [{**part, "text": c} for c in part["text"]] if part.get("text") else [part])]
    for index, part in enumerate(parts):
        if isinstance(part.get("text"), str):
            for offset in range(len(part["text"]) + 1):
                yield (parts[:index] + [{**part, "text": part["text"][:offset]},
                       {**part, "text": part["text"][offset:]}] + parts[index + 1:])


@pytest.mark.parametrize("call_style,style", list(itertools.product(
    ["native", "json_fence", "heredoc"], ["native", "think_tags", "code_comments"])))
def test_every_cell_streams_and_reloads(research, call_style, style):
    r = research
    plan = r["plans"][(call_style, style)]
    response = r["simulated_call_reply"](call_style, style)
    want = plan.parse(response)
    for chunks in stream_chunkings(response):
        stream = plan.stream()
        for chunk in chunks:
            stream.feed(copy.deepcopy(chunk))
        assert stream.finish().values == want
    entry = r["artifacts"][f"{call_style}/{style}"]
    loaded = lmcc.load(entry, registry=r["registry"])
    assert loaded.dump(registry=r["registry"]) == entry
    assert loaded.bind(r["signature"], r["CAPABILITIES"], registry=r["registry"]).parse(response) == want


@pytest.mark.parametrize("call_style", ["native", "json_fence", "heredoc"])
def test_native_thinking_requires_declared_support(research, call_style):
    with pytest.raises(lmcc.Refusal) as caught:
        research["adapters"][(call_style, "native")].bind(
            research["signature"], {"instruct": True, "native_function_calling": True},
            registry=research["registry"])
    assert caught.value.code == "capability-missing"
    assert caught.value.fix == {"action": "declare-capability", "fact": "native_reasoning"}


def test_writer_drift_and_delimiter_collision_fail_visibly(research):
    r = research
    with pytest.raises(lmcc.Refusal) as caught:
        r["broken_adapter"].bind(r["signature"], r["CAPABILITIES"], registry=r["registry"])
    assert caught.value.code == "spelling-drift"
    with pytest.raises(ValueError):
        r["raw_code"].write({"code": 'print("CODE_END")'}, None)
    malformed = {"role": "assistant", "parts": [{"type": "text", "text": r["FENCE"] + 'tool\n{"wrong": 1}\n' + r["FENCE"]}]}
    with pytest.raises(lmcc.Refusal) as caught:
        r["plans"][("json_fence", "think_tags")].parse(malformed)
    assert caught.value.code == "format-read-error"


def test_runner_bounds_reasoning_only_continuations(research):
    r = research
    requests = []
    def reasoning_only(request):
        requests.append(request)
        return {"role": "assistant", "parts": [{"type": "text", "text": "<think>Still thinking.</think>"}]}
    def never_execute(call):
        pytest.fail("reasoning-only response must not execute a tool")
    with pytest.raises(RuntimeError, match="model-call budget exhausted"):
        r["run_episode"](r["plans"][("heredoc", "think_tags")], reasoning_only, never_execute,
                         max_model_calls=2)
    assert len(requests) == 2

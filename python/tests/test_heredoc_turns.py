"""Formatted arguments: history writer and bind probe share the exact path."""
import copy
import json
from pathlib import Path

import pytest
import lmcc
import lmcc_std
from lmcc_std.code import CodeArguments, CodeCalls, heredoc_tools

CASES = Path(__file__).resolve().parents[2] / "contract/corpus/cases"


def case():
    return json.loads((CASES / "116-render-heredoc-history.json").read_text())


def registry():
    reg = lmcc.Registry()
    lmcc_std.install(reg)
    return reg


def plan(entry=None, reg=None):
    c = case()
    reg = reg or registry()
    a = lmcc.load(entry or c["entry"], registry=reg)
    return a.bind(lmcc.signature_from_dict(c["signature"]), {"instruct": True}, registry=reg)


def history(code, name="run_python"):
    return [{"role": "assistant", "parts": [{"type": "tool_call", "id": "original",
             "name": name, "input": {"code": code}}]}]


@pytest.mark.parametrize("code", ["", " \t", "    print(1)", "print(1)\n", "\n\nprint(1)\n\n",
                                 '    print("café ☃ {input} {{}}")\r\n'])
def test_exact_history_parse_and_every_split(code):
    p = plan()
    rendered = p.render(inputs=case()["inputs"], history=history(code))
    body = rendered.messages[0]["parts"][0]["text"]
    assert body == "run_python <<'PY_END'\n" + code + "\nPY_END"
    want = {"calls": [{"id": "call_1", "name": "run_python", "input": {"code": code}}]}
    assert p.parse(body) == want
    for i in range(len(body) + 1):
        s = p.stream()
        s.feed(body[:i]); s.feed(body[i:])
        assert s.finish().values == want


def test_explicit_sample_and_same_bound_writer_used_in_history():
    class Writer(CodeArguments):
        def __init__(self, options):
            super().__init__(options)
            self.values = []
        def write(self, value, field):
            assert (field.name, field.direction, field.shape) == ("input", "input", {"type": "object"})
            self.values.append(copy.deepcopy(value))
            return super().write(value, field)
    reg = registry()
    reg.register_format("tracked", Writer)
    e = case()["entry"]
    s = heredoc_tools({}).to_dict()
    s["turns"]["input_format"] = {"use": "tracked"}
    s["turns"]["probe"] = {"name": "run_python", "input": {"code": "  custom sample\n"}}
    e["strategies"]["tools"] = s
    p = plan(e, reg)
    writer = p.turn_input_formats["tools"]
    assert writer.values == [{"code": "  custom sample\n"}]
    p.render(inputs=case()["inputs"], history=history("history code\n"))
    assert writer.values[-1] == {"code": "history code\n"}
    assert p.describe()["turns"]["tools"] == {"input_format": {"use": "tracked"}, "version": "0.1.0"}


@pytest.mark.parametrize("value", [None, [], "bad", {"name": "run_python"},
    {"name": "", "input": {}}, {"name": "run_python", "input": "x"},
    {"name": "run_python", "input": {}, "extra": True}, {"name": "run_python", "input": {}, "id": ""}])
def test_malformed_probe_refuses_at_load(value):
    e = case()["entry"]
    e["strategies"]["tools"] = heredoc_tools({}).to_dict()
    e["strategies"]["tools"]["turns"]["probe"] = value
    with pytest.raises(lmcc.Refusal) as caught:
        lmcc.load(e, registry=registry())
    assert caught.value.code == "entry-malformed"
    assert caught.value.fix == {"action": "edit-entry", "path": "strategies['tools'].turns"}


@pytest.mark.parametrize("ref", [None, [], "json", {}, {"use": ""}, {"use": "json", "options": []},
                                {"use": "json", "surprise": True}])
def test_malformed_writer_ref(ref):
    s = heredoc_tools({})
    s.turns["input_format"] = ref
    with pytest.raises(lmcc.Refusal) as caught:
        s.validate(where="strategy")
    assert caught.value.code == "entry-malformed"


@pytest.mark.parametrize("change", [
    lambda t: t.update(call="WRONG {input}"),
    lambda t: t.update(probe={"name": "other_tool", "input": {"code": "x"}}),
    lambda t: t.update(probe={"name": "run_python", "input": {"code": "PY_END"}}),
    lambda t: t.update(probe={"name": "run_python", "input": {"wrong": "x"}}),
])
def test_probe_refusals_stay_at_bind_with_fix(change):
    e = case()["entry"]
    s = heredoc_tools({}).to_dict()
    change(s["turns"])
    e["strategies"]["tools"] = s
    a = lmcc.load(e, registry=registry())  # source data loads, no sample is executed here
    with pytest.raises(lmcc.Refusal) as caught:
        a.bind(lmcc.signature_from_dict(case()["signature"]), {"instruct": True}, registry=registry())
    assert caught.value.code == "turns-drift"
    assert caught.value.fix == {"action": "edit-entry", "path": "strategies['tools'].turns"}


def test_history_collision_refuses_without_mutating_input():
    p = plan()
    h = history("print('PY_END')")
    before = copy.deepcopy(h)
    with pytest.raises(lmcc.Refusal) as caught:
        p.render(inputs=case()["inputs"], history=h)
    assert caught.value.code == "value-collides" and caught.value.fix is None
    assert h == before


def test_inactive_branch_writer_resolved_and_version_checked():
    e = case()["entry"]
    s = heredoc_tools({}).to_dict()
    e["strategies"]["tools"] = {"choose": [{"when": {"capability": "instruct"}, "use": s}, {"else": s}]}
    e["versions"]["vocab"] = {"format/code_arguments": "0.2.0"}
    with pytest.raises(lmcc.Refusal) as caught:
        lmcc.load(e, registry=registry())
    assert caught.value.code == "version-incompatible"
    del e["versions"]["vocab"]["format/code_arguments"]
    e["strategies"]["tools"]["choose"][1] = {"else": copy.deepcopy(s)}
    e["strategies"]["tools"]["choose"][1]["else"]["turns"]["input_format"] = {"use": "missing"}
    with pytest.raises(lmcc.Refusal) as caught:
        lmcc.load(e, registry=registry())
    assert caught.value.code == "unknown-format"


def test_roundtrip_inline_choice_preserves_writer_sample_and_version():
    reg = registry()
    a = lmcc.adapter(messages=case()["entry"]["template"], strategies={"tools": lmcc.Strategy(choose=[
        {"when": {"capability": "instruct"}, "use": heredoc_tools({})}, {"else": heredoc_tools({})}])},
        formats=case()["entry"]["formats"])
    entry = a.dump(registry=reg)
    assert entry["versions"]["vocab"]["format/code_arguments"] == "0.1.0"
    assert lmcc.load(entry, registry=reg).dump(registry=reg) == entry


def test_wrong_writer_shape_and_missing_call_target():
    reg = registry()
    reg.register_format("parts_writer", lambda opts: lmcc.make_format(write=lambda value: [], emits="parts"))
    e = case()["entry"]
    s = heredoc_tools({}).to_dict()
    s["turns"]["input_format"] = {"use": "parts_writer"}
    e["strategies"]["tools"] = s
    with pytest.raises(lmcc.Refusal) as caught:
        plan(e, reg)
    assert caught.value.code == "entry-malformed"
    assert caught.value.fix["path"].endswith(".turns.input_format")
    s["turns"]["input_format"] = {"use": "code_arguments"}
    s["routings"] = []
    e["formats"]["list[ToolCall]"] = {"use": "json"}  # no route, but ordinary visible field has a valid format
    with pytest.raises(lmcc.Refusal) as caught:
        plan(e, reg)
    assert caught.value.code == "turns-drift"


@pytest.mark.parametrize("options", [{"marker": "END\n"}, {"marker": ""}, {"marker": "é"},
                                     {"tool": "sh -c"}, {"typo": "x"}])
def test_bad_options_fail_early(options):
    with pytest.raises(ValueError):
        heredoc_tools(options)


def test_configurable_name_marker_and_native_ids():
    options = {"tool": "evaluate", "marker": "CODE_END"}
    e = case()["entry"]
    e["strategies"]["tools"]["options"] = options
    e["formats"]["list[ToolCall]"]["options"] = options
    p = plan(e)
    text = p.render(inputs=case()["inputs"], history=history("x\n", "evaluate")).messages[0]["parts"][0]["text"]
    assert text == "evaluate <<'CODE_END'\nx\n\nCODE_END"
    assert p.parse(text)["calls"][0]["input"]["code"] == "x\n"
    fmt = CodeCalls(options)
    field = lmcc.core.Field("calls", "output", {"type": "array"})
    call = {"id": "native_17", "name": "evaluate", "input": {"code": "x\n"}}
    assert fmt.read(lmcc.Span(fmt.write([call], field)), field) == [call]

"""Kernel §10: declared execution extensions — declare, bind, refuse, inspect."""

import pytest

import lmcc
from lmcc.extensions import LegacyRE2, PatternBinding

LEGACY = {"pattern/legacy-re2": "0.1.0"}
XML = [lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
       lmcc.user("{q}")]
SIG = lmcc.signature("Answer.", inputs={"q": str},
                     outputs={"reasoning": lmcc.field(str, role="reasoning"), "answer": str})
PATTERN = lmcc.Strategy(visible=False, routings=[
    {"from": "text", "pattern": r"Thought: ([^\n]+)", "to": "@role", "consume": True}])


def test_default_registry_binds_natives_and_core_only_binds_none():
    assert lmcc.Registry().describe()["extensions"] == {
        "pattern/legacy-re2": {"version": "0.1.0", "binding": "python:re"}}
    assert lmcc.Registry(extensions=()).describe()["extensions"] == {}
    assert [b.extension for b in lmcc.native_extensions()] == ["pattern/legacy-re2"]
    with pytest.raises(ValueError):
        lmcc.Registry(extensions=["pattern/nope"])


def test_discovery_is_separate_from_capabilities():
    described = lmcc.Registry().describe()
    assert "extensions" in described and "native_reasoning" not in str(described["extensions"])


def test_core_only_host_refuses_before_any_plan():
    adapter = lmcc.adapter(messages=XML, strategies={"reasoning": PATTERN}, extensions=LEGACY)
    with pytest.raises(lmcc.Refusal) as err:
        adapter.bind(SIG, registry=lmcc.Registry(extensions=()))
    assert err.value.code == "extension-unsupported"
    assert err.value.fix == {"action": "bind-extension", "name": "pattern/legacy-re2", "needs": "0.1.0"}


def test_undeclared_pattern_refuses_at_bind_for_code_built_adapters():
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, strategies={"reasoning": PATTERN}).bind(SIG)
    assert err.value.code == "extension-undeclared"
    assert err.value.fix == {"action": "declare-extension", "family": "pattern",
                             "path": "strategies['reasoning'].routings[0]"}


def test_undeclared_pattern_inside_choose_names_the_branch():
    choose = lmcc.Strategy(choose=[
        {"when": {"capability": "native_reasoning"},
         "use": lmcc.Strategy(visible=False, routings=[{"from": "channel:thinking", "to": "@role"}])},
        {"else": PATTERN}])
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, strategies={"reasoning": choose}).bind(SIG, {"native_reasoning": True})
    assert err.value.code == "extension-undeclared"
    assert err.value.fix["path"] == "strategies['reasoning'].choose[1].routings[0]"


def test_pattern_from_a_named_strategy_counts_at_the_same_path():
    registry = lmcc.Registry()
    registry.register_strategy("thought", lambda options: PATTERN)
    adapter = lmcc.adapter(messages=XML, strategies={"reasoning": "thought"})
    with pytest.raises(lmcc.Refusal) as err:
        adapter.bind(SIG, registry=registry)
    assert err.value.code == "extension-undeclared"
    assert err.value.fix["path"] == "strategies['reasoning'].routings[0]"


def test_admission_refuses_at_the_routing_path_after_declaration():
    bad = lmcc.Strategy(visible=False, routings=[{"from": "text", "pattern": "(?=x)", "to": "@role"}])
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, strategies={"reasoning": bad}, extensions=LEGACY).bind(SIG)
    assert err.value.code == "entry-malformed"
    assert err.value.fix == {"action": "edit-entry", "path": "strategies['reasoning'].routings[0]"}


@pytest.mark.parametrize("extensions, hint", [
    ({"Pattern/x": "0.1.0"}, "not an extension name"),
    ({"pattern/x": "1.0"}, "MAJOR.MINOR.PATCH"),
    ({"pattern/a": "0.1.0", "pattern/b": "0.1.0"}, "one contract per family"),
    ("pattern/a", "must be an object"),
])
def test_declaration_shape_refuses_at_extensions(extensions, hint):
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=XML, extensions=extensions)
    assert err.value.code == "entry-malformed" and err.value.fix == {"action": "edit-entry", "path": "extensions"}
    assert hint in err.value.hint


def test_unused_declaration_is_allowed_and_dumped_verbatim():
    adapter = lmcc.adapter(messages=XML, extensions=LEGACY)
    entry = adapter.dump()
    assert entry["extensions"] == LEGACY
    assert list(entry)[:3] == ["name", "versions", "extensions"]
    assert lmcc.load(entry).extensions == LEGACY
    assert "extensions" not in lmcc.adapter(messages=XML).dump()


def test_plan_describes_what_resolved():
    plan = lmcc.adapter(messages=XML, strategies={"reasoning": PATTERN}, extensions=LEGACY).bind(SIG)
    assert plan.describe()["extensions"] == {
        "pattern/legacy-re2": {"needs": "0.1.0", "provides": "0.1.0", "binding": "python:re"}}
    assert plan.parse("Thought: t\n<answer>\nA\n</answer>\n") == {"reasoning": "t", "answer": "A"}
    plain = lmcc.adapter(messages=XML).bind(lmcc.signature("x", inputs={"q": str}, outputs={"answer": str}))
    assert plain.describe()["extensions"] == {}


def test_a_host_can_bind_its_own_implementation():
    class Upper(PatternBinding):
        extension, version, binding = "pattern/legacy-re2", "0.1.0", "test:upper"

        def admit(self, regex, *, where):
            pass

        def spans(self, regex, text):
            return [(m.start(), m.end(), m.group(1).upper())
                    for m in __import__("re").finditer(regex, text)]

    registry = lmcc.Registry(extensions=())
    registry.register_extension(Upper())
    with pytest.raises(lmcc.Refusal) as err:
        registry.register_extension(Upper())
    assert err.value.code == "already-registered"
    plan = lmcc.adapter(messages=XML, strategies={"reasoning": PATTERN}, extensions=LEGACY).bind(
        SIG, registry=registry)
    assert plan.describe()["extensions"]["pattern/legacy-re2"]["binding"] == "test:upper"
    assert plan.parse("Thought: t\n<answer>\nA\n</answer>\n")["reasoning"] == "T"


def test_version_mismatch_reuses_match_version():
    adapter = lmcc.adapter(messages=XML, extensions={"pattern/legacy-re2": "0.2.0"})
    with pytest.raises(lmcc.Refusal) as err:
        adapter.bind(SIG)
    assert err.value.code == "version-incompatible"
    assert err.value.fix == {"action": "match-version", "entry": "pattern/legacy-re2",
                             "needs": "0.2.0", "provides": "0.1.0"}


def test_legacy_re2_is_dotall_group_one_and_drops_empty_matches():
    b = LegacyRE2()
    assert b.spans("a(.)c", "a\nc") == [(0, 3, "\n")]
    assert b.spans("x*", "xx yx") == [(0, 2, "xx"), (4, 5, "x")]
    assert b.spans("(a)|b", "b") == [(0, 1, "")]

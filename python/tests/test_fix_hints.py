"""Fix hints (spec/errors.md, Fix actions): every refusal that fires
before render carries a machine-actionable ``fix``; render and parse
refusals carry none. The corpus pins the fixes both kernels emit; this
file drives the Python surface (``@lmcc.fn``, ``Registry``, ``ship``)
that the corpus cannot reach and validates every fix against
``fix.schema.json`` with a validator small enough to need no library.
"""

import dataclasses
import json
import pathlib

import pytest

import lmcc
from lmcc import formats as F

ROOT = pathlib.Path(lmcc.__file__).resolve().parent.parent.parent
FIX_SCHEMA = json.loads((ROOT / "contract" / "schema" / "fix.schema.json").read_text())

PATTERN = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.demos(), lmcc.user("{text}")])


def check_fix(fix: dict) -> None:
    """``fix`` matches exactly one branch of fix.schema.json: its action's
    required parameters are present, no unknown ones, string-typed
    (``predicate`` an object)."""
    assert isinstance(fix, dict) and "action" in fix, fix
    branch = next((b for b in FIX_SCHEMA["oneOf"]
                   if b["properties"]["action"]["const"] == fix["action"]), None)
    assert branch is not None, f"unknown action {fix['action']!r}"
    assert set(branch["required"]) <= set(fix) <= set(branch["properties"]), (
        f"{fix}: wants {branch['required']}, allows {sorted(branch['properties'])}")
    for key, value in fix.items():
        expected = branch["properties"][key]
        if "const" in expected:
            assert value == expected["const"]
        elif "enum" in expected:
            assert value in expected["enum"], (key, value)
        elif expected["type"] == "object":
            assert isinstance(value, dict), (key, value)
        else:
            assert isinstance(value, str), (key, value)


def refusal(fn, *a, **kw) -> lmcc.Refusal:
    with pytest.raises(lmcc.Refusal) as err:
        fn(*a, **kw)
    return err.value


# ------------------------------------------------------------ signature


def test_unmapped_type_names_the_parameter():
    def bad(text, other: str) -> str:   # noqa: ANN001 — the missing annotation is the point
        """x"""
    err = refusal(lmcc.fn, bad)
    assert err.code == "unmapped-type"
    assert err.fix == {"action": "edit-signature", "field": "text"}
    check_fix(err.fix)


def test_unmapped_type_names_the_return():
    def bad(text: str):
        """x"""
    err = refusal(lmcc.fn, bad)
    assert err.code == "unmapped-type" and err.fix == {"action": "edit-signature", "field": "bad"}


def test_unmapped_annotation_names_the_nested_path():
    @dataclasses.dataclass
    class Odd:
        inner: object

    def bad(text: str) -> lmcc.One[Odd]:
        """x"""
    err = refusal(lmcc.fn, bad)
    assert err.code == "unmapped-type" and err.fix == {"action": "edit-signature", "field": "bad.inner"}


def test_signature_malformed_names_the_field():
    err = refusal(lmcc.signature_from_dict, {"fields": [{"name": "1x", "direction": "input", "shape": {}}]})
    assert err.code == "signature-malformed" and err.fix == {"action": "edit-signature", "field": "1x"}
    err = refusal(lmcc.signature_from_dict, {"fields": ["nope"]})
    assert err.code == "signature-malformed" and err.fix == {"action": "edit-signature"}
    check_fix(err.fix)


# ---------------------------------------------------------------- bind


def test_format_direction_says_which_key_to_rebind():
    reg = lmcc.Registry()
    reg.register_format("in_only", lambda o: F.make(write=lambda v: v, accepts=("string",)))
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"a": str})
    err = refusal(lmcc.adapter(messages=PATTERN.template, formats={"string": "in_only"}).bind,
                  sig, registry=reg)
    assert err.code == "format-direction"
    assert err.fix == {"action": "bind-format", "field": "a", "key": "string"}
    check_fix(err.fix)


def test_no_format_key_is_the_type_name_when_the_frontend_spelled_one():
    @dataclasses.dataclass
    class Person:
        name: str

    @lmcc.fn
    def extract(text: str) -> lmcc.One[Person]:
        """x"""
    err = refusal(extract.bind, PATTERN, registry=lmcc.Registry())
    assert err.code == "no-format"
    assert err.fix == {"action": "bind-format", "field": "extract", "key": "Person"}


def test_no_format_at_write_time_names_the_path_and_key():
    """The one code that can fire either side of render carries its fix on
    both sides (errors.md)."""
    err = refusal(lmcc.core.spell_value, {"type": "array"}, [1], where="rows[]", field="rows[]")
    assert err.code == "no-format"
    assert err.fix == {"action": "bind-format", "field": "rows[]", "key": "list[*]"}


def test_unknown_slot_names_the_slot():
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"a": str})
    adapter = lmcc.adapter(messages=[lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n{% endfor %}"),
                                     lmcc.user("{text} {typo}")])
    err = refusal(adapter.bind, sig)
    assert err.code == "unknown-slot"
    assert err.fix == {"action": "edit-template", "path": "template[1]", "slot": "typo"}
    check_fix(err.fix)


def test_template_syntax_names_the_message():
    err = refusal(lmcc.adapter, messages=[lmcc.system("ok"), lmcc.user("{% for f in nothing %}{% endfor %}")])
    assert err.code == "template-syntax" and err.fix == {"action": "edit-template", "path": "template[1]"}


def test_not_lensable_variants_name_the_message_and_the_offender():
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"a": str, "b": str})
    none = lmcc.adapter(messages=[lmcc.user("{text}")])
    assert refusal(none.bind, sig).fix == {"action": "edit-template", "path": "template"}
    same_anchor = lmcc.adapter(messages=[
        lmcc.system("{% for f in outputs %}==\n{f.value}\n{% endfor %}"), lmcc.user("{text}")])
    assert refusal(same_anchor.bind, sig).fix == {"action": "edit-template", "path": "template[0]", "field": "b"}
    two_holes = lmcc.adapter(messages=[
        lmcc.system("{% for f in outputs %}<{f.name}>{f.value}{f.value}{% endfor %}"), lmcc.user("{text}")])
    assert refusal(two_holes.bind, sig).fix == {"action": "edit-template", "path": "template[0]"}


def test_capability_missing_for_when_carries_the_predicate():
    s = lmcc.Strategy(when={"not": {"capability": "instruct"}}, visible=False,
                      routings=[{"from": "channel:thinking", "to": "@role"}])
    sig = lmcc.signature("x", inputs={"text": str},
                         outputs={"r": lmcc.field(str, role="reasoning"), "a": str})
    adapter = lmcc.adapter(messages=PATTERN.template, strategies={"reasoning": s})
    err = refusal(adapter.bind, sig, {"instruct": True})
    assert err.code == "capability-missing"
    assert err.fix == {"action": "satisfy-predicate", "role": "reasoning",
                       "predicate": {"not": {"capability": "instruct"}}}
    check_fix(err.fix)


# ---------------------------------------------------------------- load


def test_udf_unplaceable_names_the_language():
    entry = {"name": "x", "versions": {"kernel": lmcc.KERNEL_VERSION, "vocab": {}},
             "template": PATTERN.template, "parse": {"kind": "derived"},
             "formats": {"Person": {"language": "javascript", "write": "x => x", "sha256": "0"}}}
    err = refusal(lmcc.load, entry, registry=lmcc.Registry(allow_udf=True))
    assert err.code == "udf-unplaceable"
    assert err.fix == {"action": "place-udf", "language": "javascript", "path": "formats['Person']"}
    check_fix(err.fix)


def test_ship_refusals_point_at_the_face():
    helper = 1
    def write(v):
        return str(v + helper)
    err = refusal(F.ship, F.make(write=write))
    assert err.code == "format-not-self-contained" and err.fix == {"action": "reship-udf", "path": "write"}
    err = refusal(F.ship, F.make(write=lambda v: v))
    assert err.code == "format-not-self-contained" and err.fix == {"action": "reship-udf", "path": "write"}


def test_entry_malformed_paths_are_locators():
    base = {"name": "x", "versions": {"kernel": lmcc.KERNEL_VERSION, "vocab": {}},
            "template": PATTERN.template, "parse": {"kind": "derived"}}
    err = refusal(lmcc.load, {**base, "strategies": {"reasoning": {"routings": [{"from": "text", "to": "@role"}]}}})
    assert err.code == "entry-malformed"
    assert err.fix == {"action": "edit-entry", "path": "strategies['reasoning'].routings[0]"}
    err = refusal(lmcc.load, {**base, "versions": {"kernel": 2}})
    assert err.fix == {"action": "edit-entry", "path": "versions"}
    err = refusal(lmcc.load, {k: v for k, v in base.items() if k != "parse"})
    assert err.fix == {"action": "edit-entry", "path": "parse"}


# --------------------------------------------------- after render: none


def test_render_and_parse_refusals_carry_no_fix():
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"n": int})
    plan = PATTERN.bind(sig)
    assert refusal(plan.render).code == "missing-input"
    assert refusal(plan.render).fix is None
    err = refusal(plan.parse, "<n>\nnine\n</n>")
    assert err.code == "parse-value" and err.fix is None
    err = refusal(plan.parse, "nothing")
    assert err.code == "parse-missing-fields" and err.fix is None and err.partial == {}


def test_refusal_describe_is_plain_data():
    err = refusal(PATTERN.bind, lmcc.signature("x", inputs={"text": str, "more": str}, outputs={"a": str}))
    assert err.describe() == {
        "code": "field-uncovered",
        "hint": err.hint,
        "fix": {"action": "edit-template", "path": "template", "field": "more"},
        "partial": None}
    json.dumps(err.describe())   # serializable

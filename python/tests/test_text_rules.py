"""Kernel §7a text rules and §4 invertibility — pinned at the helper level.

The corpus pins these through whole cases; here each rule is checked in
isolation so a regression names the exact rule, not a whole render.
"""

import pytest

import lmcc
from lmcc import core
from lmcc.parse import DerivedLens, SectionsLens, run_text_extract, validate_extract
from lmcc_std import jsontext


# ---------------------------------------------------------- number spelling

@pytest.mark.parametrize("value, text", [
    (0.0, "0"), (-0.0, "0"), (3.0, "3"), (0.5, "0.5"), (-0.5, "-0.5"),
    (100.0, "100"), (1e21, "1e+21"), (1e20, "100000000000000000000"),
    (123456789012345680000.0, "123456789012345680000"),
    (0.000001, "0.000001"), (1e-7, "1e-7"), (1.5e300, "1.5e+300"),
    (2.5e-8, "2.5e-8"), (0.1 + 0.2, "0.30000000000000004"),
    (1.7976931348623157e308, "1.7976931348623157e+308"),
    (5e-324, "5e-324"), (12345.678, "12345.678"),
])
def test_number_spelling_is_ecmascript(value, text):
    assert core.format_number(value) == text


def test_non_finite_numbers_refuse():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(lmcc.LMCCError) as err:
            core.format_number(bad)
        assert err.value.code == "value-invalid"


# ---------------------------------------------------------- reading grammars

@pytest.mark.parametrize("text, value", [
    ("7", 7), (" -7 ", -7), ("007", 7), ("\t12\n", 12)])
def test_integer_grammar_accepts(text, value):
    assert core.read_integer(text, where="t") == value


@pytest.mark.parametrize("text", ["+5", "1,000", "1_000", "٣", "1.0", "", "0x1f"])
def test_integer_grammar_rejects(text):
    with pytest.raises(lmcc.LMCCError) as err:
        core.read_integer(text, where="t")
    assert err.value.code == "value-invalid"


@pytest.mark.parametrize("text, value", [
    ("1e3", 1000.0), ("-2.5", -2.5), ("007.5", 7.5), ("1E-2", 0.01)])
def test_number_grammar_accepts(text, value):
    assert core.read_number(text, where="t") == value


@pytest.mark.parametrize("text", [".5", "5.", "NaN", "Infinity", "+1", "1e", "1_0"])
def test_number_grammar_rejects(text):
    with pytest.raises(lmcc.LMCCError) as err:
        core.read_number(text, where="t")
    assert err.value.code == "value-invalid"


def test_boolean_words_ascii_casefold_only():
    assert core.read_boolean("TRUE", where="t") is True
    assert core.read_boolean("No", where="t") is False
    with pytest.raises(lmcc.LMCCError):
        core.read_boolean("oui", where="t")


def test_strip_is_ascii_whitespace_only():
    assert core.strip(" \t\r\n\f\vx\v\f\n\r\t ") == "x"
    assert core.strip("\u00a0x\u3000") == "\u00a0x\u3000"


# ------------------------------------------------------------- signatures

@pytest.mark.parametrize("fields", [
    [{"name": "a", "direction": "output", "shape": {"type": "string"}},
     {"name": "a", "direction": "input", "shape": {"type": "string"}}],
    [{"name": "bad name", "direction": "output", "shape": {"type": "string"}}],
    [{"name": "é", "direction": "output", "shape": {"type": "string"}}],
    [{"name": "a", "direction": "sideways", "shape": {"type": "string"}}],
    [{"name": "a", "direction": "output", "shape": "string"}],
])
def test_signature_validation(fields):
    with pytest.raises(lmcc.LMCCError) as err:
        lmcc.signature_from_dict({"instructions": "", "fields": fields})
    assert err.value.code == "signature-malformed"


def test_python_frontend_validates_too():
    with pytest.raises(lmcc.LMCCError) as err:
        lmcc.signature("x", inputs={"my field": str})
    assert err.value.code == "signature-malformed"


# ------------------------------------------------------------- extractors

def test_between_is_a_plain_scan():
    text, found = run_text_extract("a<t>1</t>b<t>2</t><t>open", {
        "kind": "between", "open": "<t>", "close": "</t>"}, strip=True)
    assert found == ["1", "2"]
    assert text == "ab<t>open"


def test_line_prefixed_keeps_newlines_and_cr():
    text, found = run_text_extract("> a\r\nx\n> b", {
        "kind": "line_prefixed", "prefix": "> "}, strip=True)
    assert found == ["a\r", "b"]
    assert text == "\nx\n"


def test_pattern_discards_empty_matches_and_strips_whole_match():
    text, found = run_text_extract("k: 1, k: 22.", {
        "kind": "pattern", "regex": "k: ([0-9]*)"}, strip=True)
    assert found == ["1", "22"]
    assert text == ", ."


@pytest.mark.parametrize("regex", [
    "(?=a)b", "(?!a)b", "(?<=a)b", "(?<!a)b", "(a)\\1", "(?>a)", "a++", "a{2}+",
    "(?P<x>a)", "(?<x>a)"])
def test_regex_outside_re2_refuses(regex):
    with pytest.raises(lmcc.LMCCError) as err:
        validate_extract({"kind": "pattern", "regex": regex}, where="t")
    assert err.value.code == "entry-malformed"


@pytest.mark.parametrize("regex", ["\\(?=a\\)", "(?:a)", "(?i)a", "a\\+\\+", "[+]+"])
def test_re2_lint_has_no_false_positives(regex):
    validate_extract({"kind": "pattern", "regex": regex}, where="t")


# ---------------------------------------------------------- invertibility

def test_sections_join_refuses_marker_collisions():
    lens = SectionsLens({"kind": "sections", "open": "<{name}>", "tail": "</done>"})
    for bad in ("x <b> y", "x </done> y", "<a>"):
        with pytest.raises(lmcc.LMCCError) as err:
            lens.join([("a", bad), ("b", "ok")])
        assert err.value.code == "value-collides"
    assert lens.join([("a", "fine"), ("b", "ok")]) == "<a>\nfine\n<b>\nok\n</done>"


def test_derived_join_refuses_anchor_and_close_collisions():
    lens = DerivedLens([("a", "<a>\n", "\n</a>\n"), ("b", "<b>\n", "\n</b>\n")])
    for bad in ("has </a> inside", "has <b> inside"):
        with pytest.raises(lmcc.LMCCError) as err:
            lens.join([("a", bad), ("b", "ok")])
        assert err.value.code == "value-collides"


def test_lens_law_holds_on_marker_free_trimmed_values():
    lens = SectionsLens({"kind": "sections", "open": "<{name}>", "close": "</{name}>"})
    x = [("a", "line one\nline two"), ("b", "<not-a-marker>")]
    assert lens.split(lens.join(x), ["a", "b"]) == dict(x)


def test_repeated_close_and_tail_refuse():
    lens = SectionsLens({"kind": "sections", "open": "<{name}>", "close": "</{name}>"})
    with pytest.raises(lmcc.LMCCError) as err:
        lens.split("<a>\nx </a> y\n</a>", ["a"])
    assert err.value.code == "parse-ambiguous"
    tailed = SectionsLens({"kind": "sections", "open": "<{name}>", "tail": "</done>"})
    with pytest.raises(lmcc.LMCCError) as err:
        tailed.split("<a>\nx </done> y\n</done>", ["a"])
    assert err.value.code == "parse-ambiguous"


# ------------------------------------------------------------- std JSON text

def test_jsontext_layouts():
    v = {"x": 1.0, "s": "é\n\"q\"", "e": {}, "l": [], "n": None, "t": [1, 2]}
    assert jsontext.dumps(v, indent=None) == (
        '{"x": 1, "s": "é\\n\\"q\\"", "e": {}, "l": [], "n": null, "t": [1, 2]}')
    assert jsontext.dumps(v) == (
        '{\n  "x": 1,\n  "s": "é\\n\\"q\\"",\n  "e": {},\n  "l": [],\n  "n": null,'
        '\n  "t": [\n    1,\n    2\n  ]\n}')
    assert jsontext.dumps("\u0001\u007f\u2028") == '"\\u0001\u007f\u2028"'


def test_jsontext_reads_strictly():
    for bad in ("NaN", "[1,]", '{"a":1,"a":2}', "{'a': 1}", "Infinity"):
        with pytest.raises(ValueError):
            jsontext.loads(bad)
    assert jsontext.loads("[1, 2.5, \"x\"]") == [1, 2.5, "x"]


def test_jsontext_members_keep_source_text_and_duplicates():
    members = jsontext.members('{"a": [1,   2], "b": "s", "a": 3 }')
    assert members == [("a", [1, 2], "[1,   2]"), ("b", "s", '"s"'), ("a", 3, "3")]
    with pytest.raises(ValueError):
        jsontext.members('{"a": 1} trailing')

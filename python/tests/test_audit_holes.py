"""Plan 09, Bin 2: behaviors the clean-room audit found unwritten, pinned
against kernel 0.8 (rechecked 2026-09-23). One test per audit row that
still applies; rows made obsolete by turns (0.7) are listed in plan 09.
The normative sentence for each is in kernel.md or the vocab spec named."""

import copy
import dataclasses
import enum
import json
from pathlib import Path

import pytest

import lmcc
import lmcc_std

CASES = Path(__file__).resolve().parents[2] / "contract" / "corpus" / "cases"
TAGS = "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"


def reg():
    r = lmcc.Registry()
    lmcc_std.install(r)
    return r


def bind(template, sig, caps=None, **kw):
    return lmcc.adapter(messages=template, **kw).bind(sig, caps or {}, registry=reg())


def code(thunk):
    try:
        thunk()
    except lmcc.Refusal as r:
        return r.code
    return None


def sig(inputs=None, outputs=None):
    return lmcc.signature("Do.", inputs=inputs or {"q": str}, outputs=outputs or {"a": str})


# C2, G22 — dump writes the current kernel and the referenced vocabulary versions
def test_c2_g22_dump_records_current_versions():
    entry = json.loads((CASES / "19-std-scaled-number.json").read_text())["entry"]
    e = copy.deepcopy(entry)
    e["versions"] = {"kernel": "0.8.9", "vocab": {"format/scaled_number": "0.2.3"}}
    dumped = lmcc.load(e, registry=reg()).dump(registry=reg())
    assert dumped["versions"] == {"kernel": lmcc.KERNEL_VERSION, "vocab": {"format/scaled_number": "0.2.0"}}


# E4 — an integer is written from an integer, never from an integral float
def test_e4_integer_write_needs_an_integer():
    p = bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{n}")], sig({"n": int}))
    assert p.render(n=3).messages[0]["parts"][0]["text"] == "3"
    assert code(lambda: p.render(n=3.0)) == "value-invalid"
    assert code(lambda: p.render(n=3.5)) == "value-invalid"


# F7 — the tail is the literal after the outputs loop up to its line end
def test_f7_tail_after_a_newline():
    p = bind([lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n{% endfor %}\n</done>"),
              lmcc.user("{q}")], sig())
    assert p.skeleton()["stops"] == ["</done>"]
    assert p.parse("<a>\nx\n</done>") == {"a": "x"}
    assert code(lambda: p.parse("</done>\n<a>\nx\n</done>")) == "parse-ambiguous"


# F13 — a hidden output in a bare slot shows its placeholder and is not read there
def test_f13_hidden_output_in_a_bare_slot():
    @dataclasses.dataclass
    class O:
        reasoning: lmcc.Purpose["reasoning", str]
        a: str

    @lmcc.fn
    def f(q: str) -> O:
        """Do."""
    p = f.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\nThink: {reasoning}\nA: {a}"), lmcc.user("{q}")],
                            transports={"reasoning": "reasoning_tags"}), capabilities={"instruct": True},
               registry=reg())
    assert "Think: ..." in p.render(q="x").system
    assert p.parse("<think>t</think>A: 1") == {"a": "1", "reasoning": "t"}


# F26 — unknown loop attributes refuse by where they are
def test_f26_unknown_loop_attributes():
    assert code(lambda: bind([lmcc.system("{instruction}\nA: {a}"),
                              lmcc.user("{% for f in inputs %}{f.nope}{% endfor %}")], sig())) == "unknown-slot"


# G1 — a structural binding covers the nullable form of its shape
def test_g1_nullable_uses_the_base_structural_key():
    p = bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{x}")], sig({"x": float | None}),
             formats={"number": lmcc.use("scaled_number", scale=100, suffix="%")})
    assert p.render(x=0.5).messages[0]["parts"][0]["text"] == "50%"


# G17, G18, G26 — an unmatched between rule captures nothing and removes nothing
def test_g26_unclosed_between_consumes_nothing():
    t = lmcc.Transport(in_template=False, find=[{"from": "text", "between": ["<n>", "</n>"],
                                                 "to": "@purpose", "remove": True}])

    @dataclasses.dataclass
    class O:
        note: lmcc.Purpose["note", str]
        a: str

    @lmcc.fn
    def f(q: str) -> O:
        """Do."""
    p = f.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")],
                            transports={"note": t}))
    assert p.parse("A: x <n> y") == {"a": "x <n> y", "note": ""}


# G19 — removed prefixed lines leave their line feed
def test_g19_removed_lines_keep_their_line_feed():
    t = lmcc.Transport(in_template=False, find=[{"from": "text", "line_prefixed": "NOTE: ",
                                                 "to": "@purpose", "remove": True}])

    @dataclasses.dataclass
    class O:
        note: lmcc.Purpose["note", str]
        a: str

    @lmcc.fn
    def f(q: str) -> O:
        """Do."""
    p = f.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")],
                            transports={"note": t}))
    assert p.parse("A: one\nNOTE: n\ntwo") == {"a": "one\n\ntwo", "note": "n"}


# G23 — an unused vocabulary pin is ignored; a referenced incompatible one refuses
def test_g23_only_referenced_pins_are_checked():
    entry = json.loads((CASES / "19-std-scaled-number.json").read_text())["entry"]
    e = copy.deepcopy(entry)
    e["versions"]["vocab"]["format/never_used"] = "9.0.0"
    lmcc.load(e, registry=reg())
    e["versions"]["vocab"]["format/scaled_number"] = "9.0.0"
    assert code(lambda: lmcc.load(e, registry=reg())) == "version-incompatible"


# I1 — load order: kernel version before references
def test_i1_load_refusal_precedence():
    entry = json.loads((CASES / "09-refuse-load-unknown-format.json").read_text())["entry"]
    e = copy.deepcopy(entry)
    e["versions"]["kernel"] = "9.0.0"
    assert code(lambda: lmcc.load(e, registry=reg())) == "version-incompatible"


# I3 — structure before values: a duplicate anchor beats a bad value
def test_i3_structure_before_typed_reads():
    p = bind([lmcc.system(TAGS), lmcc.user("{q}")], sig(outputs={"a": int, "b": str}))
    assert code(lambda: p.parse("<a>\nnine\n</a>\n<b>\n1\n</b>\n<b>\n2\n</b>")) == "parse-ambiguous"


# A5, DOC-2 — the stop is the stripped tail, else the stripped last close
def test_a5_stop_precedence():
    p = bind([lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}</done>"),
              lmcc.user("{q}")], sig())
    assert p.skeleton()["stops"] == ["</done>"]
    p = bind([lmcc.system("{instruction}\nA: {a}\n"), lmcc.user("{q}")], sig())
    assert p.skeleton()["stops"] == []


# F8 — the tail twice is ambiguous
def test_f8_duplicated_tail():
    p = bind([lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n{% endfor %}</done>"),
              lmcc.user("{q}")], sig())
    assert code(lambda: p.parse("</done> first\n<a>\nx\n</done>")) == "parse-ambiguous"


# F11, DOC-3 — a missing-fields partial carries raw text, before typed reads
def test_f11_partial_is_raw_text():
    p = bind([lmcc.system(TAGS), lmcc.user("{q}")], sig(outputs={"stars": int, "summary": str, "c": str}))
    with pytest.raises(lmcc.Refusal) as err:
        p.parse("<stars>\n5\n</stars>\n<summary>\nGreat\n</summary>")
    assert err.value.code == "parse-missing-fields"
    assert err.value.partial == {"stars": "5", "summary": "Great"}


# F17, F18 — kernel placeholders are mechanical hints
def test_f17_f18_mechanical_hints():
    class C(enum.Enum):
        x = "x"
        y = "y"
    p = bind([lmcc.system("{instruction}\n{% for f in outputs %}{f.name}: {f.value}\n{% endfor %}"),
              lmcc.user("{q}")],
             sig(outputs={"n": int, "b": bool, "c": C | None, "s": str,
                          "pic": lmcc.field({"media": "image"})}))
    assert p.render(q="?").system == \
        "Do.\nn: (integer)\nb: (boolean)\nc: one of: x, y\ns: ...\npic: (image)\n"


# G2 — an enum resolves through the enum key, never the string key
def test_g2_enum_is_not_a_string_for_resolution():
    class C(enum.Enum):
        x = "x"
    shout = lmcc.make_format(write=lambda v: str(v).upper(), read=lambda c: c.text.lower())
    p = bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{e}")], sig({"e": C}),
             formats={"string": shout})
    assert p.render(e=C.x).messages[0]["parts"][0]["text"] == "x"


# G12 — a message put accepts parts (an image joins the user message)
def test_g12_message_put_accepts_parts():
    s = lmcc.signature("Do.", inputs={"q": str, "pic": lmcc.field({"media": "image"}, purpose="photo")},
                       outputs={"a": str})
    p = bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")], s,
             transports={"photo": {"put": {"@purpose": "message:user"}}})
    parts = p.render(q="look", pic={"url": "u"}).messages[0]["parts"]
    assert [x["type"] for x in parts] == ["text", "image"]


# G14 — equal settings from two transports merge once
def test_g14_equal_settings_do_not_conflict():
    s = lmcc.signature("Do.", inputs={"q": lmcc.field(str, purpose="x")},
                       outputs={"a": lmcc.field(str, purpose="y")})
    same = {"request_settings": {"config": {"temperature": 0.2}}}
    p = bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")], s, transports={"x": same, "y": same})
    assert p.render(q="?").request_settings == {"config": {"temperature": 0.2}}


# G20, I4 — `when` is checked before `requires`
def test_g20_when_before_requires():
    s = lmcc.signature("Do.", inputs={"q": str}, outputs={"a": lmcc.field(str, purpose="x")})
    t = {"when": {"capability": "native_reasoning"}, "requires": ["instruct"]}
    with pytest.raises(lmcc.Refusal) as err:
        bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")], s, transports={"x": t})
    assert err.value.fix["action"] == "satisfy-predicate"


# G21 — several missing facts: the first listed is named
def test_g21_first_missing_fact_is_named():
    s = lmcc.signature("Do.", inputs={"q": str}, outputs={"a": lmcc.field(str, purpose="x")})
    t = {"requires": ["image_input", "instruct"]}
    with pytest.raises(lmcc.Refusal) as err:
        bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")], s, transports={"x": t})
    assert err.value.fix == {"action": "declare-capability", "fact": "image_input"}


# H4 — text parts join across other parts, in response order
def test_h4_text_parts_join_across_other_parts():
    p = bind([lmcc.system(TAGS), lmcc.user("{q}")], sig())
    reply = {"role": "assistant", "parts": [{"type": "text", "text": "<a>\nx"},
                                            {"type": "thinking", "text": "hm"},
                                            {"type": "text", "text": "y\n</a>"}]}
    assert p.parse(reply) == {"a": "xy"}


# G5, G6 — table rows may omit the final delimiter; a missing value is the null cell.
# Found in the recheck: prose with no table row refused (table 0.2.0), never [].
def test_g5_g6_table_rows():
    @dataclasses.dataclass
    class Row:
        name: str
        score: int | None

    @lmcc.fn
    def t(q: str) -> lmcc.One[list[Row]]:
        """Rows."""
    p = t.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\nTable: {t}"), lmcc.turns(), lmcc.user("{q}")],
                            formats={"list[object]": lmcc.use("table", columns=["name", "score"])}),
               registry=reg())
    assert p.parse("Table: | ann | 3") == {"t": [Row("ann", 3)]}
    assert p.parse("Table: | ann |  |") == {"t": [Row("ann", None)]}
    assert p.parse("Table:") == {"t": []}
    assert code(lambda: p.parse("Table: no rows here")) == "format-read-error"
    written = p.render(q="x", turns=[p.example({"q": "d"}, {"t": [Row("bo", None)]})])
    assert written.messages[1]["parts"][0]["text"] == "Table: | bo |  |"


# F15 — a transport for a purpose no field bears contributes nothing
def test_f15_unused_transport_is_inert():
    p = bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")], sig(),
             transports={"ghost": {"tell": {"system": "BOO"}, "request_settings": {"config": {"temperature": 1}}}})
    assert p.render(q="x").request() == {"system": "Do.\nA: ...",
                                         "messages": [{"role": "user", "parts": [{"type": "text", "text": "x"}]}]}


# B4 — a purpose key may contain dots
def test_b4_dotted_purpose():
    s = lmcc.signature("Do.", inputs={"q": str}, outputs={"a": str, "n": lmcc.field(str, purpose="work.notes")})
    p = bind([lmcc.system("{instruction}\nA: {a}"), lmcc.user("{q}")], s,
             transports={"work.notes": {"in_template": False, "find": [
                 {"from": "text", "between": ["[", "]"], "to": "@purpose", "remove": True}]}})
    assert p.parse("A: x [n1]") == {"a": "x", "n": "n1"}


# F24 — no output pattern at all: the fix names the whole template
def test_f24_missing_pattern_fix():
    with pytest.raises(lmcc.Refusal) as err:
        bind([lmcc.system("{instruction}"), lmcc.user("{q}")], sig())
    assert err.value.code == "not-readable"
    assert err.value.fix == {"action": "edit-template", "path": "template"}


# G9 — the json_object reader recovers a document whose closing fence is missing
def test_g9_json_reader_unclosed_fence():
    p = bind([lmcc.system("{instruction}\n{format}"), lmcc.user("{q}")], sig(),
             {"native_structured_output": True}, reader={"kind": "json_object"})
    assert p.parse('```json\n{"a": "x"}') == {"a": "x"}

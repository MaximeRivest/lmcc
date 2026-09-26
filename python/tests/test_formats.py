"""Formats (kernel §5): resolution order, kernel defaults, type bindings,
composing formats refusing at a path, shipping and admitting UDFs."""

import dataclasses
import json

import pytest

import lmcc
from lmcc import formats as F

PATTERN = lmcc.adapter(messages=[
    lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.turns(), lmcc.user("{text}")])


@dataclasses.dataclass
class Person:
    name: str
    age: int


@lmcc.fn
def extract(text: str) -> lmcc.One[Person]:
    """Extract the person mentioned."""


def test_structured_with_no_format_refuses_no_format():
    with pytest.raises(lmcc.Refusal) as err:
        extract.bind(PATTERN, registry=lmcc.Registry())
    assert err.value.code == "no-format" and "'extract'" in err.value.hint


def test_type_binding_at_runtime_is_the_lmcc_format_surface():
    reg = lmcc.Registry()
    reg.format(Person,
               write=lambda p: json.dumps(p.__dict__),
               read=lambda capture: Person(**json.loads(capture.text)),
               describe=lambda: "name and age, as JSON")
    plan = extract.bind(PATTERN, registry=reg)
    assert plan.describe()["outputs"][0]["resolved_by"] == "runtime:Person"
    req = plan.render(text="t", turns=[plan.example({"text": "d"}, {"extract": Person("Ann", 41)})])
    assert req.system == "<extract>\nname and age, as JSON\n</extract>\n"
    assert req.messages[1]["parts"][0]["text"] == '<extract>\n{"name": "Ann", "age": 41}\n</extract>'
    assert plan.parse('<extract>\n{"name": "Bo", "age": 7}\n</extract>') == {"extract": Person("Bo", 7)}


def test_resolution_order_artifact_type_then_structural_then_runtime_then_kernel():
    reg = lmcc.Registry()
    reg.register_format("upper", lambda o: F.make(write=lambda v: str(v).upper(), read=lambda s: s.text.lower()))
    reg.register_format("tag", lambda o: F.make(write=lambda v: f"<{v}>", read=lambda s: s.text.strip("<>")))
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"a": str, "b": int})
    sig.field_named("a").type = "Name"
    adp = lmcc.adapter(messages=PATTERN.template, formats={"Name": "upper", "string": "tag", "integer": "tag"})
    plan = adp.bind(sig, registry=reg)
    d = {o["name"]: o["resolved_by"] for o in plan.describe()["outputs"]}
    assert d == {"a": "artifact:Name", "b": "artifact:integer"}
    assert plan.render(text="t", turns=[plan.example({"text": "d"}, {"a": "ann", "b": 3})]).messages[1]["parts"][0]["text"] == \
        "<a>\nANN\n</a>\n<b>\n<3>\n</b>"
    plain = lmcc.adapter(messages=PATTERN.template).bind(sig, registry=reg)
    assert {o["resolved_by"] for o in plain.describe()["outputs"]} == {"kernel"}


def test_star_is_consulted_after_kernel_defaults():
    reg = lmcc.Registry()
    reg.register_format("q", lambda o: F.make(write=lambda v: json.dumps(v), read=lambda s: json.loads(s.text)))
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"s": str, "rows": list[int]})
    plan = lmcc.adapter(messages=PATTERN.template, formats={"*": "q"}).bind(sig, registry=reg)
    d = {o["name"]: o["resolved_by"] for o in plan.describe()["outputs"]}
    assert d == {"s": "kernel", "rows": "artifact:*"}


def test_format_shape_and_direction_contracts():
    reg = lmcc.Registry()
    reg.register_format("in_only", lambda o: F.make(write=lambda v: v, accepts=("string",)))
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"a": str})
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=PATTERN.template, formats={"string": "in_only"}).bind(sig, registry=reg)
    assert err.value.code == "format-direction"
    reg.register_format("ints", lambda o: F.make(write=lambda v: v, read=lambda s: s.text, accepts=("integer",)))
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=PATTERN.template, formats={"string": "ints"}).bind(sig, registry=reg)
    assert err.value.code == "format-shape-mismatch"


def test_composing_format_refuses_at_its_path():
    """A list layout that asks the plan for the element's format and
    refuses no-format at the path when there is none (kernel §5)."""
    reg = lmcc.Registry()

    class Lines(F.Format):
        accepts = ("list[*]",)

        def write(self, value, field):
            return "\n".join("- " + str(v) for v in value)

        def read(self, capture, field):
            items = field.shape.get("items", {})
            if F.kernel_default(items) is None:
                lmcc.refuse("no-format", f"{field.name}[]: elements of shape {items} have no format")
            return [lmcc.core.read_value(items, line[2:], where=field.name) for line in capture.text.split("\n")]

    reg.register_format("lines", lambda o: Lines())
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"rows": list[int]})
    plan = lmcc.adapter(messages=PATTERN.template, formats={"list[*]": "lines"}).bind(sig, registry=reg)
    assert plan.parse("<rows>\n- 1\n- 2\n</rows>") == {"rows": [1, 2]}
    nested = lmcc.signature("x", inputs={"text": str}, outputs={"rows": list[dict]})
    plan = lmcc.adapter(messages=PATTERN.template, formats={"list[*]": "lines"}).bind(nested, registry=reg)
    with pytest.raises(lmcc.Refusal) as err:
        plan.parse("<rows>\n- x\n</rows>")
    assert err.value.code == "no-format" and "rows[]" in err.value.hint


def test_media_default_writes_parts_and_reads_them():
    sig = lmcc.signature("x", inputs={"photo": {"media": "image"}, "text": str}, outputs={"a": str})
    adp = lmcc.adapter(messages=[lmcc.system("{% for f in outputs %}<{f.name}>{f.value}{% endfor %}"),
                                 lmcc.user("{text}{photo}")])
    plan = adp.bind(sig)
    req = plan.render(text="see", photo={"data": "b64", "mime": "image/png"})
    assert req.messages[0]["parts"] == [{"type": "text", "text": "see"},
                                          {"type": "image", "data": "b64", "mime": "image/png"}]
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(text="see", photo="not a part")
    assert err.value.code == "value-invalid"


def test_ship_and_load_udf():
    def write(p, f):
        return p["name"] + " (" + str(p["age"]) + ")"

    def read(capture, f):
        name, _, rest = capture.text.rpartition(" (")
        return {"name": name, "age": int(rest[:-1])}

    fmt = F.make(write=write, read=read, accepts=("Person",))
    entry = F.ship(fmt, authored_by="tests")
    assert set(entry) >= {"language", "write", "read", "sha256", "accepts", "writes", "round_trip", "reads"}
    assert entry["sha256"] == F.digest({"write": entry["write"], "read": entry["read"]})
    loaded = F.load_udf(entry, where="formats['Person']")
    assert loaded.write({"name": "Ann", "age": 41}, None) == "Ann (41)"
    assert loaded.read(lmcc.Capture.of_text("Bo (7)"), None) == {"name": "Bo", "age": 7}

    tampered = {**entry, "sha256": "0" * 64}
    with pytest.raises(lmcc.Refusal) as err:
        F.load_udf(tampered, where="x")
    assert err.value.code == "udf-tampered"
    with pytest.raises(lmcc.Refusal) as err:
        F.load_udf({**entry, "language": "go"}, where="x")
    assert err.value.code == "udf-unplaceable"


def test_ship_refuses_non_self_contained():
    helper = str

    def write(v, f):
        return helper(v)

    with pytest.raises(lmcc.Refusal) as err:
        F.ship(F.make(write=write))
    assert err.value.code == "format-not-self-contained"
    with pytest.raises(lmcc.Refusal) as err:
        F.ship(F.make(write=lambda v: v))
    assert err.value.code == "format-not-self-contained"

    def clean(v, f):
        import json
        return json.dumps(v)

    assert "import json" in F.ship(F.make(write=clean))["write"]


def test_artifact_with_udf_loads_only_when_allowed():
    def write(p, f):
        return str(p)

    def read(capture, f):
        return capture.text

    adp = lmcc.adapter(messages=PATTERN.template, formats={"Person": F.make(write=write, read=read)})
    entry = adp.dump(registry=lmcc.Registry())
    assert entry["formats"]["Person"]["language"] == "python"
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.load(entry, registry=lmcc.Registry())
    assert err.value.code == "format-untrusted"
    again = lmcc.load(entry, registry=lmcc.Registry(allow_udf=True))
    assert again.dump(registry=lmcc.Registry(allow_udf=True)) == entry


def test_turn_not_renderable_for_lossy_formats():
    reg = lmcc.Registry()
    reg.register_format("lossy", lambda o: F.make(write=lambda v: "x", read=lambda s: s.text, round_trip=False))
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"a": str})
    plan = lmcc.adapter(messages=PATTERN.template, formats={"string": "lossy"}).bind(sig, registry=reg)
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(text="t", turns=[plan.example({"text": "d"}, {"a": "v"})])
    assert err.value.code == "turn-not-renderable"


def test_description_is_data_names_its_entry_and_keeps_the_kernel_read():
    """Kernel §5 descriptions (D-51): the banking77 'short' adapter — a student
    that learned the intents is told `<intent>`, not the list — as pure data.
    It dumps (no code to ship), plan.describe() names the entry, and the read
    stays the kernel's: forgiving, reported, and off under strict."""
    from typing import Literal

    import lmcc

    intent = Literal["card_arrival", "card_delivery_estimate"]
    sig = lmcc.signature("Classify.", inputs={"text": str}, outputs={"answer": intent})
    short = lmcc.adapter(messages=[lmcc.system("{instruction}\nIntent: {answer}"), lmcc.user("{text}")],
                         formats={"enum": {"describe": "<intent>"}})
    entry = short.dump()
    assert entry["formats"] == {"enum": {"describe": "<intent>"}}
    plan = lmcc.load(entry, registry=lmcc.Registry()).bind(sig)
    assert plan.render(text="hi").system == "Classify.\nIntent: <intent>"
    (out,) = plan.describe()["outputs"]
    assert (out["format"], out["resolved_by"], out["described_by"]) == \
        ("kernel-scalar", "kernel", "artifact:enum")
    reading = plan.read("Intent: Card_Arrival")
    assert reading.values == {"answer": "card_arrival"}
    assert reading.repairs == [{"repair": "value", "field": "answer", "saw": "Card_Arrival",
                                "as": "card_arrival"}]
    strict = lmcc.adapter(messages=short.template, formats=short.formats, strict=True).bind(sig)
    with pytest.raises(lmcc.Refusal) as err:
        strict.read("Intent: Card_Arrival")
    assert err.value.code == "parse-value"


def test_reference_rejects_unknown_keys():
    import lmcc

    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=[lmcc.system("{a}")], formats={"object": {"use": "json", "optoins": {}}})
    assert err.value.code == "entry-malformed"
    assert err.value.fix == {"action": "edit-entry", "path": "formats['object']"}


def test_a_bound_host_type_lowers_through_the_registry():
    """Kernel §1/§5 step 3: a type only the runtime knows (a DataFrame) lowers
    to the shape its binding declares — default {}, structured — and the
    bound format writes it. Before, the signature refused unmapped-type
    before any binding was consulted, though the docstrings promised it."""
    import lmcc

    class Frame:
        def __init__(self, rows):
            self.rows = rows

    reg = lmcc.Registry()
    reg.format(Frame, write=lambda v: "\n".join(",".join(map(str, r)) for r in v.rows),
               describe=lambda: "CSV rows")

    @lmcc.fn(registry=reg)
    def total(data: Frame) -> int:
        """Add the numbers."""

    (data, _) = total.signature.fields
    assert (data.shape, data.type) == ({}, "Frame")
    # inside a list it lowers too; the list itself still needs its own format (§5: no nesting)
    many = lmcc.signature("x", inputs={"rows": list[Frame]}, outputs={"a": str}, registry=reg)
    assert many.fields[0].shape == {"type": "array", "items": {}}
    plan = total.bind(lmcc.adapter(messages=[lmcc.user("{data}\nTotal: {total}")]), registry=reg)
    assert plan.render(data=Frame([[1, 2], [3, 4]])).messages[0]["parts"][0]["text"] == \
        "1,2\n3,4\nTotal: (integer)"
    assert plan.describe()["inputs"][0]["resolved_by"] == "runtime:Frame"

    reg.format(dict, write=lambda v: "", shape={"type": "object"})   # a declared shape is kept
    assert reg.shape_of(dict) == {"type": "object"}
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.signature("x", inputs={"f": Frame}, outputs={"a": str}, registry=lmcc.Registry())
    assert err.value.code == "unmapped-type" and "lmcc.format(Frame" in err.value.hint

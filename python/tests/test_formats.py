"""Formats (kernel §5): resolution order, kernel defaults, type bindings,
composing formats refusing at a path, shipping and admitting UDFs."""

import dataclasses
import json

import pytest

import lmcc
from lmcc import formats as F

PATTERN = lmcc.adapter(messages=[
    lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.demos(), lmcc.user("{text}")])


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
               read=lambda span: Person(**json.loads(span.text)),
               describe=lambda: "name and age, as JSON")
    plan = extract.bind(PATTERN, registry=reg)
    assert plan.describe()["outputs"][0]["resolved_by"] == "runtime:Person"
    req = plan.render(text="t", demos=[{"text": "d", "extract": Person("Ann", 41)}])
    assert req.messages[0]["content"][0]["text"] == "<extract>\nname and age, as JSON\n</extract>\n"
    assert req.messages[2]["content"][0]["text"] == '<extract>\n{"name": "Ann", "age": 41}\n</extract>'
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
    assert plan.render(text="t", demos=[{"text": "d", "a": "ann", "b": 3}]).messages[2]["content"][0]["text"] == \
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

        def read(self, span, field):
            items = field.shape.get("items", {})
            if F.kernel_default(items) is None:
                lmcc.refuse("no-format", f"{field.name}[]: elements of shape {items} have no format")
            return [lmcc.core.read_value(items, line[2:], where=field.name) for line in span.text.split("\n")]

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
    assert req.messages[1]["content"] == [{"kind": "text", "text": "see"},
                                          {"kind": "image", "data": "b64", "mime": "image/png"}]
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(text="see", photo="not a part")
    assert err.value.code == "value-invalid"


def test_ship_and_load_udf():
    def write(p, f):
        return p["name"] + " (" + str(p["age"]) + ")"

    def read(span, f):
        name, _, rest = span.text.rpartition(" (")
        return {"name": name, "age": int(rest[:-1])}

    fmt = F.make(write=write, read=read, accepts=("Person",))
    entry = F.ship(fmt, authored_by="tests")
    assert set(entry) >= {"language", "write", "read", "sha256", "accepts", "emits", "round_trip", "reads"}
    assert entry["sha256"] == F.digest({"write": entry["write"], "read": entry["read"]})
    loaded = F.load_udf(entry, where="formats['Person']")
    assert loaded.write({"name": "Ann", "age": 41}, None) == "Ann (41)"
    assert loaded.read(lmcc.Span.of_text("Bo (7)"), None) == {"name": "Bo", "age": 7}

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

    def read(span, f):
        return span.text

    adp = lmcc.adapter(messages=PATTERN.template, formats={"Person": F.make(write=write, read=read)})
    entry = adp.dump(registry=lmcc.Registry())
    assert entry["formats"]["Person"]["language"] == "python"
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.load(entry, registry=lmcc.Registry())
    assert err.value.code == "format-untrusted"
    again = lmcc.load(entry, registry=lmcc.Registry(allow_udf=True))
    assert again.dump(registry=lmcc.Registry(allow_udf=True)) == entry


def test_demo_not_renderable_for_lossy_formats():
    reg = lmcc.Registry()
    reg.register_format("lossy", lambda o: F.make(write=lambda v: "x", read=lambda s: s.text, round_trip=False))
    sig = lmcc.signature("x", inputs={"text": str}, outputs={"a": str})
    plan = lmcc.adapter(messages=PATTERN.template, formats={"string": "lossy"}).bind(sig, registry=reg)
    with pytest.raises(lmcc.Refusal) as err:
        plan.render(text="t", demos=[{"text": "d", "a": "v"}])
    assert err.value.code == "demo-not-renderable"

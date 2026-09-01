"""The host socket: native type hints in, LLM-ready context out.

The two-layer rule, executable: the host type is a per-runtime binding
(code, never serialized); it lowers to a neutral shape + plain data, and
its registered default codec is the renderer that spells it. Artifacts
carry only shapes and codec names, so they stay cross-language.
"""

import dataclasses

import pytest

import a15
import a15_std


@dataclasses.dataclass
class Person:
    name: str
    age: int


class FakeImage:
    """Stands in for PIL.Image: a native object with no JSON form."""

    def __init__(self, data: str):
        self.data = data


def _registry():
    registry = a15.Registry()
    a15_std.install(registry)
    registry.register_host(
        Person,
        shape={"type": "object",
               "properties": {"name": {"type": "string"},
                              "age": {"type": "integer"}},
               "required": ["name", "age"]},
        lower=dataclasses.asdict,
        lift=lambda d: Person(**d),
        codec="json",                       # the registered renderer
    )
    registry.register_host(
        FakeImage,
        shape={"media": "image"},
        lower=lambda img: {"data": img.data, "mime": "image/png"},
    )
    return registry


def _adapter():
    return a15.adapter(
        template=a15.template([
            a15.message("system", "{instruction}\n\nAnswer in exactly this "
                        "form:\n{% for f in outputs %}<{f.name}>\n{f.value}\n"
                        "</{f.name}>\n{% endfor %}"),
            a15.message("user", "{photo}\n{text}"),
        ]),
        parse={"kind": "derived"})


def test_native_type_hints_end_to_end():
    registry = _registry()
    sig = a15.signature(
        "Extract every person you can see or read.",
        inputs={"photo": FakeImage, "text": str},
        outputs={"people": list[Person]},
        registry=registry)
    baked = _adapter().bake(sig, {}, registry=registry)

    # forward: the native image became a message part, not text
    r = baked.render(inputs={"photo": FakeImage("b64bytes"),
                             "text": "Ana is 31."})
    parts = r.messages[1]["content"]
    assert {"kind": "image", "data": "b64bytes", "mime": "image/png"} in parts

    # backward: raw JSON text became a list of real Person objects
    values = baked.parse('<people>\n[{"name": "Ana", "age": 31}]\n</people>')
    assert values == {"people": [Person("Ana", 31)]}


def test_registered_renderer_spells_the_type():
    """No codec bound in the entry: the type's registered default renders."""
    registry = _registry()
    sig = a15.signature("List people.", inputs={"text": str},
                        outputs={"people": list[Person]}, registry=registry)
    adp = a15.adapter(
        template=a15.template([
            a15.message("system", "{% for f in outputs %}<{f.name}>\n{f.value}"
                        "\n</{f.name}>\n{% endfor %}"),
            a15.directive("demos"),
            a15.message("user", "{text}"),
        ]),
        parse={"kind": "derived"})
    baked = adp.bake(sig, {}, registry=registry)
    demo = {"text": "Ana is 31.", "people": [Person("Ana", 31)]}
    turn = baked.render(inputs={"text": "x"}, demos=[demo]).messages[2]
    assert '"name": "Ana"' in turn["content"][0]["text"]  # spelled by json
    assert baked.parse(turn["content"][0]["text"]) == {
        "people": [Person("Ana", 31)]}  # and lifted back to Person


def test_entry_binding_beats_host_default():
    registry = _registry()
    sig = a15.signature("List people.", inputs={"text": str},
                        outputs={"people": list[Person]}, registry=registry)
    adp = a15.adapter(
        template=a15.template([
            a15.message("system", "{% for f in outputs %}<{f.name}>\n{f.value}"
                        "\n</{f.name}>\n{% endfor %}"),
            a15.message("user", "{text}"),
        ]),
        parse={"kind": "derived"},
        codecs={"people": a15.codec("table", columns=["name", "age"])})
    baked = adp.bake(sig, {}, registry=registry)
    assert baked.codecs["people"].kind == "table"


def test_unregistered_native_type_refuses_by_name():
    class Mystery:
        pass
    with pytest.raises(a15.A15Error) as err:
        a15.signature("x", inputs={"thing": Mystery}, outputs={"answer": str},
                      registry=_registry())
    assert err.value.code == "unmapped-type"
    assert "thing" in err.value.detail

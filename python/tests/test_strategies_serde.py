"""Strategies (visibility, routing, capabilities), serde, and sockets."""

import pytest

import a15
import a15_std
from a15 import A15Error


@pytest.fixture
def registry():
    r = a15.Registry()
    a15_std.install(r)
    return r


@pytest.fixture
def sig():
    return a15.signature(
        "Answer.",
        inputs={"question": str},
        outputs={"reasoning": a15.field(str, role="reasoning"),
                 "answer": str},
    )


def make_adapter(strategy, registry=None):
    return a15.adapter(
        template=a15.template([
            a15.message("system", "{instruction}\n"
                        "{% for f in outputs %}<{f.name}>\n{% endfor %}"),
            a15.message("user", "{question}"),
        ]),
        parse={"kind": "sections", "open": "<{name}>"},
        strategies={"reasoning": strategy},
    )


def test_reasoning_tags_hides_routes_and_strips(registry, sig):
    baked = make_adapter("reasoning_tags").bake(
        sig, {"instruct": True}, registry=registry)
    # hidden: the reasoning section is not announced, the fragment is
    system = baked.render(inputs={"question": "q"}).messages[0]["content"][0]["text"]
    assert "<reasoning>" not in system
    assert "<think>" in system
    values = baked.parse(
        "<answer>\nParis<think>capital of France</think> is correct.")
    assert values["reasoning"] == "capital of France"
    assert values["answer"] == "Paris is correct."


def test_native_reasoning_reads_parts(registry, sig):
    baked = make_adapter("native_reasoning").bake(
        sig, {"native_reasoning": True}, registry=registry)
    values = baked.parse({"content": [
        {"kind": "thinking", "text": "let me think"},
        {"kind": "text", "text": "<answer>\nParis"}]})
    assert values == {"reasoning": "let me think", "answer": "Paris"}


def test_capability_refusal_names_everything(registry, sig):
    with pytest.raises(A15Error) as err:
        make_adapter("native_reasoning").bake(sig, {"instruct": True},
                                              registry=registry)
    assert err.value.code == "capability-missing"
    for needle in ("reasoning", "native_reasoning"):
        assert needle in str(err.value)


def test_prefix_cot_stays_visible(registry, sig):
    baked = make_adapter("prefix_cot").bake(
        sig, {"instruct": True}, registry=registry)
    system = baked.render(inputs={"question": "q"}).messages[0]["content"][0]["text"]
    assert "<reasoning>" in system
    assert "'reasoning' section" in system  # {field} resolved in fragment
    values = baked.parse("<reasoning>\nsteps\n<answer>\nParis")
    assert values == {"reasoning": "steps", "answer": "Paris"}


def test_dump_load_roundtrip(registry, sig):
    adp = make_adapter("reasoning_tags")
    entry = adp.dump(registry=registry)
    assert entry["versions"]["kernel"] == a15.KERNEL_VERSION
    assert entry["versions"]["vocab"] == {"strategy/reasoning_tags": "0.1.0"}
    again = a15.load(entry, registry=registry)
    assert a15.dump(again, registry) == entry
    # and the reloaded adapter behaves identically
    baked = again.bake(sig, {"instruct": True}, registry=registry)
    values = baked.parse("<answer>\nx<think>t</think>")
    assert values == {"reasoning": "t", "answer": "x"}


def test_load_refuses_unknown_names(registry):
    entry = {"name": "x", "versions": {"kernel": a15.KERNEL_VERSION},
             "template": {"messages": [{"role": "user", "text": "{q}"}]},
             "parse": {"kind": "sections", "open": "<{name}>"},
             "codecs": {"out": {"kind": "nope"}}}
    with pytest.raises(A15Error) as err:
        a15.load(entry, registry=registry)
    assert err.value.code == "unknown-codec"
    assert "nope" in str(err.value)


def test_load_refuses_version_mismatch(registry):
    entry = {"name": "x", "versions": {"kernel": "9.0.0"},
             "template": {"messages": []},
             "parse": {"kind": "sections", "open": "<{name}>"}}
    with pytest.raises(A15Error) as err:
        a15.load(entry, registry=registry)
    assert err.value.code == "version-incompatible"


def test_data_only_entry_loads_with_empty_registry():
    entry = {"name": "bare", "versions": {"kernel": a15.KERNEL_VERSION},
             "template": {"messages": [{"role": "user", "text": "{q}"}]},
             "parse": {"kind": "sections", "open": "<{name}>"},
             "strategies": {"reasoning": {
                 "requires": [], "visible": False,
                 "routings": [{"extract": {"kind": "between", "open": "<t>",
                                           "close": "</t>"},
                               "field": "@role", "join": " ", "strip": True}]}}}
    adp = a15.load(entry, registry=a15.Registry())  # zero registrations
    sig = a15.signature("x", inputs={"q": str},
                        outputs={"reasoning": a15.field(str, role="reasoning"),
                                 "a": str})
    baked = adp.bake(sig, {}, registry=a15.Registry())
    assert baked.parse("<a>\nyes<t>hm</t>") == {"reasoning": "hm", "a": "yes"}


def test_double_covered_refuses(registry, sig):
    visible_but_routed = a15.Strategy(
        routings=[{"extract": {"kind": "between", "open": "<t>", "close": "</t>"},
                   "field": "@role"}],
        visible=True)
    with pytest.raises(A15Error) as err:
        make_adapter(visible_but_routed).bake(sig, {}, registry=registry)
    assert err.value.code == "field-double-covered"


def test_host_socket_lowers_and_lifts(registry):
    class Temperature:  # a stand-in for any foreign type
        def __init__(self, celsius):
            self.celsius = celsius

    registry.register_host(Temperature, shape={"type": "number"},
                           lower=lambda t: t.celsius,
                           lift=lambda v: Temperature(v))
    sig = a15.signature("Convert.", inputs={"t": Temperature},
                        outputs={"f": Temperature}, registry=registry)
    adp = a15.adapter(template=a15.template([a15.message("user", "{t}")]),
                      parse={"kind": "sections", "open": "<{name}>"})
    baked = adp.bake(sig, {}, registry=registry)
    txt = baked.render(inputs={"t": Temperature(21.5)})
    assert txt.messages[0]["content"][0]["text"] == "21.5"
    out = baked.parse("<f>\n70.7")
    assert isinstance(out["f"], Temperature) and out["f"].celsius == 70.7


def test_unmapped_type_refuses():
    class Mystery:
        pass

    with pytest.raises(A15Error) as err:
        a15.signature("x", inputs={"m": Mystery}, outputs={})
    assert err.value.code == "unmapped-type"
    assert "Mystery" in str(err.value)

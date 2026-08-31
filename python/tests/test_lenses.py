"""Lens socket + marker profiles + the json_object lens."""

import pytest

import a15
import a15_std
from a15_std.lenses import JsonObjectLens


def _sig():
    return a15.signature(
        "Answer.",
        inputs={"question": str},
        outputs={"answer": str, "score": int, "payload": a15.field(
            {"type": "array"}, desc="items")})


def _adapter(parse):
    return a15.adapter(
        template=a15.template([
            a15.message("system", "{instruction}"),
            a15.directive("demos"),
            a15.message("user", "{question}"),
        ]),
        parse=parse,
        codecs={"payload": "json"})


def _registry():
    registry = a15.Registry()
    a15_std.install(registry)
    return registry


# ------------------------------------------------------- marker profiles


def test_xml_profile_is_pure_data():
    """XML markers are a spelling of the kernel sections lens: data only."""
    baked = _adapter({"kind": "sections", "open": "<{name}>",
                      "close": "</{name}>"}).bake(_sig(), {},
                                                  registry=_registry())
    reply = ("<answer>Paris</answer>\n<score>9</score>\n"
             "<payload>[1, 2]</payload>")
    assert baked.parse(reply) == {"answer": "Paris", "score": 9,
                                  "payload": [1, 2]}


def test_dspy_profile_is_pure_data():
    """DSPy chat-adapter markers: also just data for the sections lens."""
    baked = _adapter({"kind": "sections", "open": "[[ ## {name} ## ]]",
                      "tail": "[[ ## completed ## ]]"}).bake(
        _sig(), {}, registry=_registry())
    reply = ("[[ ## answer ## ]]\nParis\n[[ ## score ## ]]\n9\n"
             "[[ ## payload ## ]]\n[1, 2]\n[[ ## completed ## ]]")
    assert baked.parse(reply) == {"answer": "Paris", "score": 9,
                                  "payload": [1, 2]}
    # the lens writes demos in the same layout it reads
    demo = {"question": "q", "answer": "Paris", "score": 9,
            "payload": [1, 2]}
    result = baked.render(inputs={"question": "x"}, demos=[demo])
    assistant = result.messages[2]
    assert assistant["role"] == "assistant"
    assert baked.parse(assistant["content"][0]["text"]) == {
        "answer": "Paris", "score": 9, "payload": [1, 2]}


# ------------------------------------------------------- json_object lens


def test_json_lens_demo_roundtrips():
    baked = _adapter({"kind": "json_object"}).bake(_sig(), {},
                                                   registry=_registry())
    demo = {"question": "q", "answer": "Paris", "score": 9,
            "payload": [{"a": 1}]}
    result = baked.render(inputs={"question": "x"}, demos=[demo])
    assistant = result.messages[2]["content"][0]["text"]
    assert baked.parse(assistant) == {"answer": "Paris", "score": 9,
                                      "payload": [{"a": 1}]}


def test_json_lens_reads_fence_and_native_values():
    baked = _adapter({"kind": "json_object"}).bake(_sig(), {},
                                                   registry=_registry())
    reply = ('```json\n{"answer": "Paris", "score": 9, '
             '"payload": [1, 2], "chatter": "ignored"}\n```')
    assert baked.parse(reply) == {"answer": "Paris", "score": 9,
                                  "payload": [1, 2]}


def test_json_lens_missing_key_refuses_with_partial():
    baked = _adapter({"kind": "json_object"}).bake(_sig(), {},
                                                   registry=_registry())
    with pytest.raises(a15.A15Error) as err:
        baked.parse('{"answer": "Paris"}')
    assert err.value.code == "parse-missing-fields"
    assert err.value.partial == {"answer": "Paris"}


def test_json_lens_malformed_refuses():
    baked = _adapter({"kind": "json_object"}).bake(_sig(), {},
                                                   registry=_registry())
    with pytest.raises(a15.A15Error) as err:
        baked.parse("no json here")
    assert err.value.code == "lens-parse-error"


def test_join_embed_rule_is_raw_text_identity():
    lens = JsonObjectLens({"kind": "json_object"})
    spelled = [("s", "plain"), ("n", "9"), ("b", "true"),
               ("quoted", '"hi"'), ("arr", "[1, 2]")]
    raw = lens.split(lens.join(spelled), [n for n, _ in spelled])
    assert raw == {"s": "plain", "n": "9", "b": "true",
                   "quoted": '"hi"', "arr": "[1,2]"}


# --------------------------------------------------------------- refusals


def test_bake_unknown_lens_refuses():
    adp = _adapter({"kind": "json_object"})
    with pytest.raises(a15.A15Error) as err:
        adp.bake(_sig(), {}, registry=a15.Registry())  # std not installed
    assert err.value.code == "unknown-parse-kind"


def test_load_unknown_lens_refuses():
    entry = {"versions": {"kernel": a15.KERNEL_VERSION},
             "template": {"messages": [{"role": "user", "text": "hi"}]},
             "parse": {"kind": "json_object"}}
    with pytest.raises(a15.A15Error) as err:
        a15.load(entry, registry=a15.Registry())
    assert err.value.code == "unknown-parse-kind"


def test_dump_records_lens_version():
    registry = _registry()
    adp = _adapter({"kind": "json_object"})
    entry = a15.dump(adp, registry)
    assert entry["versions"]["vocab"]["lens/json_object"] == "0.1.0"
    assert a15.load(entry, registry=registry).parse == {"kind": "json_object"}


def test_sections_lens_cannot_be_replaced():
    registry = a15.Registry()
    with pytest.raises(a15.A15Error) as err:
        registry.register_lens("sections", JsonObjectLens)
    assert err.value.code == "already-registered"

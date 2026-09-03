"""The DSPy feature catalog (plans/07-dspy-parity.md).

One DSPy signature per feature. Each row must (1) lower to a
SignatureCore losing nothing but DSPy's declared no-ops, and (2) bake,
render and round-trip through the DSPy-shaped LMCC entry: the assistant
turn the lens writes for a full example parses back to the example's
outputs. A feature not in this file is not claimed.

Runs against a real DSPy (``python/lmcc_dspy/check``); the kernel suite
never imports dspy.
"""

from __future__ import annotations

import datetime
import enum
import typing
import warnings

import pytest

pydantic = pytest.importorskip("pydantic")
dspy = pytest.importorskip("dspy")

import lmcc  # noqa: E402
import lmcc_dspy  # noqa: E402


def _fixture():
    registry = lmcc.Registry()
    adapter = lmcc_dspy.adapter(registry)
    return registry, adapter


def roundtrip(signature, example: dict, *, capabilities=None, expect_values=None):
    """Lower, bake, render a full example as a demo, parse the demo's
    assistant turn back, and compare to the example's outputs."""
    registry, adapter = _fixture()
    lowered = lmcc_dspy.lower(signature, registry=registry)
    baked = adapter.bake(lowered.signature, capabilities or {}, registry=registry)
    inputs, history = lowered.split_inputs(example)
    outputs = {f.name: example[f.name] for f in lowered.signature.outputs if f.name in example}
    request = baked.render(inputs=inputs, demos=[{**inputs, **outputs}], history=history)
    assistant = [m for m in request.messages if m["role"] == "assistant"]
    values = baked.parse(assistant[0]["content"][0]["text"])
    assert values == (expect_values if expect_values is not None else outputs)
    return lowered, baked, request


def shapes(lowered) -> dict:
    return {f.name: f.shape for f in lowered.signature.fields}


# ------------------------------------------------------------ string syntax

def test_string_signature_untyped():
    lowered, _, req = roundtrip("question -> answer", {"question": "q?", "answer": "a"})
    assert shapes(lowered) == {"question": {"type": "string"}, "answer": {"type": "string"}}
    assert lowered.signature.instructions.startswith("Given the fields")


def test_string_signature_typed():
    lowered, _, _ = roundtrip(
        "question: str, context: list[str] -> answer: str, score: int, ok: bool, p: float",
        {"question": "q", "context": ["c1", "c2"], "answer": "a", "score": 3,
         "ok": True, "p": 0.5})
    assert shapes(lowered)["context"] == {"type": "array", "items": {"type": "string"}}
    assert shapes(lowered)["p"] == {"type": "number"}


# ----------------------------------------------------- class-based features

class Rich(dspy.Signature):
    """Answer with care."""
    question: str = dspy.InputField(desc="the user's question")
    style: typing.Literal["short", "long"] = dspy.InputField()
    answer: str = dspy.OutputField(description="pydantic-style description")
    confidence: float = dspy.OutputField(ge=0, le=1, desc="0..1")
    note: typing.Optional[str] = dspy.OutputField()
    tags: list[str] = dspy.OutputField(min_length=1)


def test_desc_description_literal_optional_constraints():
    lowered, _, _ = roundtrip(Rich, {
        "question": "why?", "style": "short", "answer": "because",
        "confidence": 0.75, "note": None, "tags": ["x"]})
    s = shapes(lowered)
    by = {f.name: f for f in lowered.signature.fields}
    assert lowered.signature.instructions == "Answer with care."
    assert by["question"].desc == "the user's question"
    assert by["answer"].desc == "pydantic-style description"
    assert by["style"].desc is None                     # DSPy's ${name} default → none
    assert s["style"] == {"enum": ["short", "long"], "type": "string"}
    assert s["confidence"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert s["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert s["tags"] == {"type": "array", "items": {"type": "string"}, "minItems": 1}


def test_optional_output_present_and_null_both_round_trip():
    roundtrip(Rich, {"question": "q", "style": "long", "answer": "a",
                     "confidence": 1, "note": "n", "tags": ["t"]},
              expect_values={"answer": "a", "confidence": 1, "note": "n", "tags": ["t"]})


# ------------------------------------------------------------ pydantic types

class Author(pydantic.BaseModel):
    name: str
    born: int


class Book(pydantic.BaseModel):
    title: str
    author: Author
    tags: list[str] = []


class Extract(dspy.Signature):
    text: str = dspy.InputField()
    book: Book = dspy.OutputField()
    others: list[Author] = dspy.OutputField()
    maybe: typing.Optional[Author] = dspy.OutputField()


def test_pydantic_models_lower_to_schema_and_lift_back():
    book = Book(title="Dune", author=Author(name="Herbert", born=1920), tags=["sf"])
    lowered, baked, _ = roundtrip(Extract, {
        "text": "t", "book": book, "others": [Author(name="A", born=1)], "maybe": None})
    s = shapes(lowered)
    assert s["book"]["properties"]["author"]["$ref"] == "#/$defs/Author"
    assert "$defs" in s["book"]
    assert s["others"]["items"]["$ref"] == "#/$defs/Author"
    # a parsed reply lifts back to native models through the host socket
    values = baked.parse("[[ ## book ## ]]\n"
                         '{"title": "X", "author": {"name": "Y", "born": 2}}\n'
                         "[[ ## others ## ]]\n[]\n[[ ## maybe ## ]]\n"
                         '{"name": "Z", "born": 3}\n[[ ## completed ## ]]')
    assert isinstance(values["book"], Book) and values["book"].author.born == 2
    assert values["others"] == []
    assert values["maybe"] == {"name": "Z", "born": 3}   # Optional[Model]: json, not lifted (stated)


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Pick(dspy.Signature):
    q: str = dspy.InputField()
    color: Color = dspy.OutputField()


def test_enum_class_lowers_to_enum_and_lifts():
    lowered, baked, _ = roundtrip(Pick, {"q": "q", "color": Color.RED})
    assert shapes(lowered)["color"] == {"enum": ["red", "blue"], "type": "string"}
    assert baked.parse("[[ ## color ## ]]\nblue\n[[ ## completed ## ]]") == {"color": Color.BLUE}


# ------------------------------------------------- unions, any, dict, dates

class Loose(dspy.Signature):
    q: str = dspy.InputField()
    pick: typing.Union[str, int] = dspy.OutputField()
    blob: typing.Any = dspy.OutputField()
    table: dict[str, int] = dspy.OutputField()
    nested: list[dict[str, list[int]]] = dspy.OutputField()
    when: datetime.date = dspy.OutputField()


def test_unions_any_dict_nested_generics_and_dates():
    lowered, _, _ = roundtrip(Loose, {
        "q": "q", "pick": "seven", "blob": {"k": [1, "x", None]}, "table": {"a": 1},
        "nested": [{"a": [1, 2]}], "when": "2026-09-03"})
    s = shapes(lowered)
    assert s["pick"] == {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    assert s["blob"] == {}
    assert s["table"] == {"type": "object", "additionalProperties": {"type": "integer"}}
    assert s["when"] == {"type": "string", "format": "date"}


# ------------------------------------------------------------- dspy types

class Vision(dspy.Signature):
    image: dspy.Image = dspy.InputField()
    q: str = dspy.InputField()
    caption: str = dspy.OutputField()


def test_image_input_is_a_media_shape():
    registry, adapter = _fixture()
    lowered = lmcc_dspy.lower(Vision, registry=registry)
    assert shapes(lowered)["image"] == {"media": "image"}
    baked = adapter.bake(lowered.signature, {"image_input": True}, registry=registry)
    registry.register_host(dspy.Image, shape={"media": "image"},
                           lower=lambda im: {"url": im.url})
    req = baked.render(inputs={"image": dspy.Image(url="https://x/y.png"), "q": "?"})
    user = req.messages[-1]["content"]
    assert {"kind": "image", "url": "https://x/y.png"} in user


class Chat(dspy.Signature):
    history: dspy.History = dspy.InputField()
    question: str = dspy.InputField()
    answer: str = dspy.OutputField()


def test_history_input_becomes_field_turns():
    lowered, baked, req = roundtrip(Chat, {
        "history": dspy.History(messages=[{"question": "first", "answer": "one"},
                                          {"question": "second", "answer": "two"}]),
        "question": "third", "answer": "three"})
    assert lowered.history_field == "history"
    assert [f.name for f in lowered.signature.fields] == ["question", "answer"]
    texts = [m["content"][0]["text"] for m in req.messages]
    assert any("first" in t for t in texts) and any("[[ ## answer ## ]]\ntwo" in t for t in texts)
    # history turns come after the demo turns and before the live question
    assert texts.index(next(t for t in texts if "second" in t)) < len(texts) - 1


class CoT(dspy.Signature):
    question: str = dspy.InputField()
    reasoning: dspy.Reasoning = dspy.OutputField()
    answer: str = dspy.OutputField()


def test_reasoning_type_lowers_to_the_reasoning_role():
    lowered, _, _ = roundtrip(CoT, {"question": "q", "reasoning": "hm", "answer": "a"})
    assert {f.name: f.role for f in lowered.signature.outputs} == {
        "reasoning": "reasoning", "answer": "plain"}


class WithTools(dspy.Signature):
    question: str = dspy.InputField()
    tools: list[dspy.Tool] = dspy.InputField()
    calls: dspy.ToolCalls = dspy.OutputField()


def test_tools_lower_to_the_tools_role_and_still_render():
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    registry, adapter = _fixture()
    lowered = lmcc_dspy.lower(WithTools, registry=registry)
    roles = {f.name: f.role for f in lowered.signature.fields}
    assert roles == {"question": "plain", "tools": "tools", "calls": "tools"}
    assert shapes(lowered)["tools"]["items"]["required"] == ["name", "description", "parameters"]
    with pytest.raises(lmcc.LMCCError) as err:
        adapter.bake(lowered.signature, {}, registry=registry)
    assert err.value.code == "role-ambiguous"   # two fields on one role: the kernel rule

    # with the output side renamed to plain, the tool declarations render as json
    only_in = dspy.Signature({"question": (str, dspy.InputField()),
                              "tools": (list[dspy.Tool], dspy.InputField()),
                              "calls": (dspy.ToolCalls, dspy.OutputField())})
    lowered = lmcc_dspy.lower(only_in, registry=registry)
    lowered.signature.field_named("calls").role = "plain"
    baked = adapter.bake(lowered.signature, {}, registry=registry)
    req = baked.render(inputs={"question": "2+2?", "tools": [dspy.Tool(add)]})
    user = req.messages[-1]["content"][0]["text"]
    assert '"name": "add"' in user and '"description": "Add two numbers."' in user


class Coded(dspy.Signature):
    task: str = dspy.InputField()
    program: dspy.Code = dspy.OutputField()


JavaCode = dspy.Code["java"]          # each subscription makes a new class


class Java(dspy.Signature):
    task: str = dspy.InputField()
    program: JavaCode = dspy.OutputField()


def test_code_type_lowers_as_a_string_with_language_and_lifts():
    lowered, _, _ = roundtrip(Coded, {"task": "t", "program": dspy.Code(code="print(1)")})
    assert shapes(lowered)["program"] == {"type": "string", "format": "code", "language": "python"}

    lowered, _, _ = roundtrip(Java, {"task": "t", "program": JavaCode(code="int x;")})
    assert shapes(lowered)["program"]["language"] == "java"


# ------------------------------------------------ deprecated / no-op extras

def test_deprecated_prefix_format_parser_are_dropped_not_refused():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        class Old(dspy.Signature):
            q: str = dspy.InputField(prefix="Question:", format=lambda x: x)
            a: str = dspy.OutputField(prefix="Answer:", parser=str)

    lowered, _, _ = roundtrip(Old, {"q": "q", "a": "a"})
    assert [f.name for f in lowered.signature.fields] == ["q", "a"]


# ------------------------------------------------------- signature algebra

def test_signature_operations_relower():
    base = dspy.Signature("question -> answer")
    sig = base.with_instructions("Be brief.").append("score", dspy.OutputField(), int)
    sig = sig.prepend("context", dspy.InputField(desc="ctx"), list[str]).delete("score")
    lowered = lmcc_dspy.lower(sig)
    assert lowered.signature.instructions == "Be brief."
    assert [f.name for f in lowered.signature.fields] == ["context", "question", "answer"]
    assert lowered.signature.fields[0].desc == "ctx"


# ---------------------------------------------------------------- refusals

def test_non_identifier_field_name_refuses_by_name():
    sig = dspy.Signature({"réponse": (str, dspy.OutputField()), "q": (str, dspy.InputField())})
    with pytest.raises(lmcc.LMCCError) as err:
        lmcc_dspy.lower(sig)
    assert err.value.code == "signature-malformed" and "réponse" in err.value.detail


def test_unloweable_annotation_refuses_unmapped_type():
    # pydantic accepts a Callable annotation but cannot give it a JSON schema:
    # the one kind of type DSPy lets through that has no data form
    sig = dspy.Signature({"q": (str, dspy.InputField()),
                          "o": (typing.Callable[[int], int], dspy.OutputField())})
    with pytest.raises(lmcc.LMCCError) as err:
        lmcc_dspy.lower(sig)
    assert err.value.code == "unmapped-type" and "'o'" in err.value.detail

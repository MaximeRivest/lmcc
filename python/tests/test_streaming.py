"""Streaming is a refinement of batch parse (kernel §8)."""

import pytest

import lmcc
from lmcc.parse import Lens


def tagged(*, outputs=None, strategies=None, formats=None):
    sig = lmcc.signature("Answer.", inputs={"q": str}, outputs=outputs or {"answer": str})
    adapter = lmcc.adapter(messages=[
        lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        lmcc.user("{q}")], strategies=strategies, formats=formats)
    return sig, adapter


def run(plan, chunks):
    stream = plan.stream()
    events = []
    for chunk in chunks:
        events.extend(stream.feed(chunk))
    result = stream.finish()
    events.extend(result.events)
    return events, result.values


def deltas(events):
    out = {}
    for event in events:
        if event["kind"] == "field_delta":
            out[event["field"]] = out.get(event["field"], "") + event["text"]
    return out


def test_every_split_refines_batch_and_preserves_raw_text():
    sig, adapter = tagged(outputs={"answer": str, "score": int})
    plan = adapter.bind(sig)
    text = "noise <answer>\n  blue \n sky  \n</answer>\n<score>\n 09 \n</score>"
    batch = plan.parse(text)
    for cut in range(len(text) + 1):
        events, values = run(plan, [text[:cut], text[cut:]])
        assert values == batch == {"answer": "blue \n sky", "score": 9}
        assert deltas(events) == {"answer": "blue \n sky", "score": "09"}
        assert [e["field"] for e in events if e["kind"] == "field_done"] == ["answer", "score"]


def test_feed_emits_started_and_safe_delta_but_finish_owns_done():
    sig, adapter = tagged()
    stream = adapter.bind(sig).stream()
    assert stream.feed("<answer>\n hello") == [
        {"kind": "field_started", "field": "answer"},
        {"kind": "field_delta", "field": "answer", "text": "hello"}]
    # Trailing whitespace and a partial close are held.
    assert stream.feed("  \n</ans") == []
    assert stream.feed("wer>") == []
    result = stream.finish()
    assert result.values == {"answer": "hello"}
    assert result.events == [{"kind": "field_done", "field": "answer", "value": "hello"}]


def test_eof_releases_unclosed_field_and_trailing_internal_whitespace():
    sig, adapter = tagged()
    stream = adapter.bind(sig).stream()
    events = stream.feed("<answer>\na  ")
    assert deltas(events) == {"answer": "a"}
    # More content makes held spaces internal.
    assert stream.feed("b") == [{"kind": "field_delta", "field": "answer", "text": "  b"}]
    result = stream.finish()
    assert result.values == {"answer": "a  b"}
    assert result.events[-1] == {"kind": "field_done", "field": "answer", "value": "a  b"}


def routed_plan(routing):
    strategy = lmcc.Strategy(visible=False, routings=[{**routing, "to": "@role"}])
    sig = lmcc.signature("Answer.", inputs={"q": str},
                         outputs={"reasoning": lmcc.field(str, role="reasoning"), "answer": str})
    adapter = lmcc.adapter(messages=[
        lmcc.system("{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        lmcc.user("{q}")], strategies={"reasoning": strategy})
    return adapter.bind(sig)


def test_between_routing_streams_after_close_and_consumes_before_lens():
    plan = routed_plan({"from": "text", "between": ["<think>", "</think>"], "consume": True})
    stream = plan.stream()
    assert stream.feed("<thi") == []
    assert stream.feed("nk>  why ") == []       # unclosed capture is not yet real to batch
    routed = stream.feed(" now </think><answer>\nyes\n</answer>")
    assert deltas(routed) == {"reasoning": "why  now", "answer": "yes"}
    result = stream.finish()
    assert result.values == {"answer": "yes", "reasoning": "why  now"}


def test_line_routing_waits_for_newline_and_preserves_lens_newline():
    plan = routed_plan({"from": "text", "line_prefixed": "THINK: ", "consume": True})
    stream = plan.stream()
    assert stream.feed("THINK: first") == []
    events = stream.feed(" line\n<answer>\nok\n</answer>")
    assert deltas(events) == {"reasoning": "first line", "answer": "ok"}
    assert stream.finish().values == {"answer": "ok", "reasoning": "first line"}


def test_channel_part_deltas_coalesce_and_stream():
    plan = routed_plan({"from": "channel:thinking"})
    stream = plan.stream()
    assert stream.feed({"kind": "thinking", "text": "  rea"}) == [
        {"kind": "field_started", "field": "reasoning"},
        {"kind": "field_delta", "field": "reasoning", "text": "rea"}]
    assert stream.feed({"kind": "thinking", "text": "son  "}) == [
        {"kind": "field_delta", "field": "reasoning", "text": "son"}]
    stream.feed({"kind": "text", "text": "<answer>\nok\n</answer>"})
    result = stream.finish()
    assert result.values == {"answer": "ok", "reasoning": "reason"}


def test_pattern_routing_buffers_only_its_field_when_non_consuming():
    plan = routed_plan({"from": "text", "pattern": r"THINK\((.*?)\)"})
    assert plan.describe()["streaming"]["mode"] == "hybrid"
    stream = plan.stream()
    events = stream.feed("THINK(why)<answer>\nyes\n</answer>")
    assert deltas(events) == {"answer": "yes"}
    result = stream.finish()
    assert result.values == {"answer": "yes", "reasoning": "why"}
    assert deltas(result.events) == {"reasoning": "why"}


def test_consuming_pattern_buffers_lens_too_and_says_why():
    plan = routed_plan({"from": "text", "pattern": r"THINK\((.*?)\)", "consume": True})
    description = plan.describe()["streaming"]
    assert description["mode"] == "buffered"
    assert "consuming pattern" in description["lens"]["reason"]
    stream = plan.stream()
    assert stream.feed("THINK(why)<answer>\nyes\n</answer>") == []
    result = stream.finish()
    assert result.values == {"answer": "yes", "reasoning": "why"}


def test_multiple_routings_to_one_field_buffer_to_preserve_declaration_order():
    strategy = lmcc.Strategy(visible=False, routings=[
        {"from": "text", "between": ["<late>", "</late>"], "to": "@role"},
        {"from": "text", "between": ["<early>", "</early>"], "to": "@role"}])
    sig = lmcc.signature("x", inputs={"q": str},
                         outputs={"notes": lmcc.field(str, role="notes"), "answer": str})
    adapter = lmcc.adapter(messages=[
        lmcc.system("{% for f in outputs %}<{f.name}>{f.value}</{f.name}>{% endfor %}"),
        lmcc.user("{q}")], strategies={"notes": strategy})
    plan = adapter.bind(sig)
    stream = plan.stream()
    events = stream.feed("<early>E</early><late>L</late><answer>A</answer>")
    assert "notes" not in deltas(events)
    result = stream.finish()
    assert result.values["notes"] == "L\nE"
    assert deltas(result.events)["notes"] == "L\nE"


def test_vocabulary_lens_without_streaming_face_buffers_visibly():
    import lmcc_std
    registry = lmcc.Registry()
    lmcc_std.install(registry)
    sig = lmcc.signature("x", inputs={"q": str}, outputs={"answer": str})
    adapter = lmcc.adapter(messages=[lmcc.user("{q}")], parse={"kind": "json_object"})
    plan = adapter.bind(sig, {"native_structured_output": True}, registry=registry)
    assert plan.describe()["streaming"]["mode"] == "buffered"
    stream = plan.stream()
    assert stream.feed('{"answer": "yes"}') == []
    result = stream.finish()
    assert result.values == {"answer": "yes"}
    assert deltas(result.events) == {"answer": "yes"}


class PipeReducer:
    def __init__(self, names):
        self.names = names
        self.text = ""

    def feed(self, delta):
        self.text += delta
        bits = self.text.split("|")
        return {name: bits[i] for i, name in enumerate(self.names) if i < len(bits) - 1}

    def finish(self):
        bits = self.text.split("|")
        return {name: bits[i] for i, name in enumerate(self.names)}


class PipeLens(Lens):
    def split(self, text, field_names):
        return dict(zip(field_names, text.split("|")))

    def join(self, spelled):
        return "|".join(text for _, text in spelled)

    def stream(self, field_names):
        return PipeReducer(field_names)


def test_vocabulary_lens_optional_streaming_face_is_checked_against_batch():
    registry = lmcc.Registry()
    registry.register_lens("pipe", lambda spec: PipeLens())
    sig = lmcc.signature("x", inputs={"q": str}, outputs={"a": str, "b": str})
    plan = lmcc.adapter(messages=[lmcc.user("{q}")], parse={"kind": "pipe"}).bind(sig, registry=registry)
    assert plan.describe()["streaming"]["mode"] == "incremental"
    stream = plan.stream()
    assert deltas(stream.feed("first|sec")) == {"a": "first"}
    result = stream.finish()
    assert result.values == {"a": "first", "b": "sec"}
    assert deltas(result.events) == {"b": "sec"}


class MissingPipeLens(PipeLens):
    def stream(self, field_names):
        return PipeReducer(field_names[:1])


def test_vocabulary_lens_stream_must_report_every_batch_field():
    registry = lmcc.Registry()
    registry.register_lens("bad_pipe", lambda spec: MissingPipeLens())
    sig = lmcc.signature("x", inputs={"q": str}, outputs={"a": str, "b": str})
    plan = lmcc.adapter(messages=[lmcc.user("{q}")], parse={"kind": "bad_pipe"}).bind(
        sig, registry=registry)
    stream = plan.stream()
    stream.feed("first|second")
    with pytest.raises(RuntimeError, match="lens stream fields"):
        stream.finish()


def test_parse_refusals_are_deferred_to_finish_and_identical():
    sig, adapter = tagged(outputs={"a": str, "b": str})
    plan = adapter.bind(sig)
    bad = "<a>x</a><a>y</a>"
    batch = None
    try:
        plan.parse(bad)
    except lmcc.Refusal as err:
        batch = err
    stream = plan.stream()
    stream.feed(bad)
    with pytest.raises(lmcc.Refusal) as streamed:
        stream.finish()
    assert streamed.value.describe() == batch.describe()


def test_stream_state_misuse_is_not_a_contract_refusal():
    sig, adapter = tagged()
    stream = adapter.bind(sig).stream()
    with pytest.raises(lmcc.Refusal) as malformed:
        stream.feed({"text": "no kind"})
    assert malformed.value.code == "response-malformed"
    stream.feed("<answer>x</answer>")
    stream.finish()
    with pytest.raises(RuntimeError, match="already finished"):
        stream.feed("more")
    with pytest.raises(RuntimeError, match="already finished"):
        stream.finish()


# ------------------------------------------------------------------ fuzz
#
# The harness replays every corpus response at every single split. These
# tests add random multi-chunk splits over random replies, including
# marker fragments and Unicode, against the same plan set the Go kernel
# fuzzes (go/lmcc/stream_test.go): names, templates and routings match.

import random
import time


def fuzz_plan(template, routings=None, outputs=None):
    outputs = dict(outputs or {"answer": str})
    strategies = None
    if routings is not None:
        outputs = {"reasoning": lmcc.field(str, role="reasoning"), **outputs}
        strategies = {"reasoning": lmcc.Strategy(
            visible=False, routings=[{**r, "to": "@role"} for r in routings])}
    sig = lmcc.signature("x", inputs={"q": str}, outputs=outputs)
    adapter = lmcc.adapter(messages=[lmcc.system(template), lmcc.user("{q}")],
                           strategies=strategies)
    return adapter.bind(sig)


TAGGED = "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"
DSPY = "{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}[[ ## completed ## ]]"
MARKDOWN = "**Reasoning:**{reasoning}**Answer:**{answer}"


def fuzz_plans():
    return {
        "tagged": fuzz_plan(TAGGED, outputs={"answer": str, "score": int}),
        "tagged_one": fuzz_plan(TAGGED),
        "dspy": fuzz_plan(DSPY, outputs={"reasoning": str, "answer": str}),
        "markdown": fuzz_plan(MARKDOWN, outputs={"reasoning": str, "answer": str}),
        "between": fuzz_plan(TAGGED, [{"from": "text", "between": ["<think>", "</think>"], "consume": True}]),
        "between_keep": fuzz_plan(TAGGED, [{"from": "text", "between": ["<think>", "</think>"]}]),
        "between_same": fuzz_plan(TAGGED, [{"from": "text", "between": ["```", "```"], "consume": True}]),
        "line": fuzz_plan(TAGGED, [{"from": "text", "line_prefixed": "THINK: ", "consume": True}]),
        "line_keep": fuzz_plan(TAGGED, [{"from": "text", "line_prefixed": "THINK: "}]),
        "pattern": fuzz_plan(TAGGED, [{"from": "text", "pattern": r"T\((.*?)\)"}]),
        "pattern_consume": fuzz_plan(TAGGED, [{"from": "text", "pattern": r"T\((.*?)\)", "consume": True}]),
        "channel": fuzz_plan(TAGGED, [{"from": "channel:thinking"}]),
        "double": fuzz_plan(TAGGED, [{"from": "text", "between": ["<late>", "</late>"]},
                                    {"from": "text", "line_prefixed": "N: ", "consume": True}]),
    }


ATOMS = ["<answer>", "</answer>", "<score>", "</score>", "<think>", "</think>", "[[ ## ", " ## ]]",
         "reasoning", "answer", "completed", "```", "THINK: ", "T(", ")", "N: ", "<late>", "</late>",
         "**Reasoning:**", "**Answer:**", "**", "Answer:", "\n", "\n\n", " ", "  ", "\t", "a", "b",
         "7", "42", "<", ">", "/", "[", "]", "#", "é", "日本"]
SMALL = ["a", "b", " ", "\n", "é", "7", "<", ">", "]", "#", "[[ ", "```", "T(", "THINK: ", "N: ", "**", "Answer:"]


class FuzzGenerator:
    def __init__(self, seed):
        self.rng = random.Random(seed)

    def text(self):
        return "".join(self.rng.choice(ATOMS) for _ in range(self.rng.randint(0, 14)))

    def valid(self, name):
        rng = self.rng
        v = lambda: "".join(rng.choice(SMALL) for _ in range(rng.randint(0, 6)))  # noqa: E731
        ws = lambda: rng.choice(["", " ", "\n", "\n\n", "  \n"])  # noqa: E731
        if name == "tagged":
            return f"{ws()}<answer>{ws()}{v()}{ws()}</answer>{ws()}<score>{ws()}42{ws()}</score>{ws()}"
        if name == "dspy":
            return f"[[ ## reasoning ## ]]{ws()}{v()}{ws()}[[ ## answer ## ]]{ws()}{v()}{ws()}[[ ## completed ## ]]{ws()}"
        if name == "markdown":
            return f"**Reasoning:**{ws()}{v()}{ws()}**Answer:**{ws()}{v()}{ws()}"
        if name == "double":
            return f"N: {v()}\n<late>{v()}</late><answer>{v()}</answer>"
        pre = ""
        if name == "between_same":
            pre = f"```{ws()}{v()}{ws()}```"
        elif name.startswith("between"):
            pre = f"{v()}<think>{ws()}{v()}{ws()}</think>{v()}"
        elif name.startswith("line"):
            pre = f"{v()}\nTHINK: {v()}\n{v()}\n"
        elif name.startswith("pattern"):
            pre = f"{v()}T({v()}){v()}"
        return f"{pre}{ws()}<answer>{ws()}{v()}{ws()}</answer>{ws()}"

    def chunks(self, text):
        if len(text) < 2:
            return [text]
        cuts = sorted(self.rng.sample(range(1, len(text)), min(len(text) - 1, self.rng.randint(0, 6))))
        out, prev = [], 0
        for c in cuts:
            out.append(text[prev:c])
            prev = c
        return out + [text[prev:]]

    def parts(self):
        parts = []
        for _ in range(self.rng.randint(1, 5)):
            kind = self.rng.choice(["text", "thinking", "image"])
            parts.append({"kind": "image", "url": "x"} if kind == "image" else {"kind": kind, "text": self.text()})
        chunks = []
        for p in parts:
            if isinstance(p.get("text"), str):
                chunks.extend({**p, "text": piece} for piece in self.chunks(p["text"]))
            else:
                chunks.append(dict(p))
        coalesced: list = []
        for p in parts:
            if (coalesced and isinstance(p.get("text"), str) and coalesced[-1].get("kind") == p["kind"]
                    and isinstance(coalesced[-1].get("text"), str)):
                coalesced[-1] = {**coalesced[-1], "text": coalesced[-1]["text"] + p["text"]}
            else:
                coalesced.append(dict(p))
        return {"content": coalesced}, chunks


def test_fuzz_random_chunking_refines_batch():
    plans = fuzz_plans()
    names = sorted(plans)
    gen = FuzzGenerator(7)
    successes = 0
    for run in range(3000):
        name = gen.rng.choice(names)
        plan = plans[name]
        if name == "channel" or gen.rng.random() < 0.2:
            response, chunks = gen.parts()
        else:
            response = gen.valid(name) if gen.rng.random() < 0.6 else gen.text()
            chunks = gen.chunks(response)
        where = f"run {run} {name}: {response!r} as {chunks!r}"
        try:
            batch = ("ok", plan._parse_with_spans(response))
        except lmcc.Refusal as err:
            batch = ("refuse", err.describe())
        stream = plan.stream()
        events = []
        try:
            for chunk in chunks:
                events.extend(stream.feed(chunk))
            result = stream.finish()
            events.extend(result.events)
            streamed = ("ok", result.values)
        except lmcc.Refusal as err:
            streamed = ("refuse", err.describe())
        assert batch[0] == streamed[0], where
        if batch[0] == "refuse":
            assert batch[1] == streamed[1], where
            continue
        successes += 1
        values, spans = batch[1]
        assert streamed[1] == values, where
        joined, started, done = {}, {}, {}
        for e in events:
            if e["kind"] == "field_delta":
                assert e["text"], where
                joined[e["field"]] = joined.get(e["field"], "") + e["text"]
            elif e["kind"] == "field_started":
                started[e["field"]] = started.get(e["field"], 0) + 1
            else:
                done[e["field"]] = done.get(e["field"], 0) + 1
                assert e["value"] == values[e["field"]], where
        for field, span in spans.items():
            assert joined.get(field, "") == span.text, where
            assert started.get(field) == 1 and done.get(field) == 1, where
        assert set(started) <= set(spans) and set(done) <= set(spans), where
    assert successes > 500, "the generator lost its coverage"


def test_marker_overlap_never_revises_emitted_text():
    # "**Answer:**" can start inside "**Reasoning:**": batch gives reasoning
    # an empty section (kernel §4). The reducer holds "A" until it knows.
    plan = fuzz_plans()["markdown"]
    text = "**Reasoning:**Answer:** hi"
    batch = plan.parse(text)
    assert batch == {"reasoning": "", "answer": "hi"}
    for cut in range(len(text) + 1):
        events, values = run(plan, [text[:cut], text[cut:]])
        assert values == batch
        assert deltas(events) == {"answer": "hi"}
    # With no overlap in sight the same plan streams eagerly.
    assert deltas(plan.stream().feed("**Reasoning:** hello")) == {"reasoning": "hello"}


def test_stream_cost_is_linear_in_reply_length():
    plan = fuzz_plans()["dspy"]
    body = "lorem ipsum dolor sit amet " * 8000

    def cost(n):
        text = f"[[ ## reasoning ## ]]\n{body[:n]}\n\n[[ ## answer ## ]]\nok\n\n[[ ## completed ## ]]"
        stream = plan.stream()
        start = time.perf_counter()
        for i in range(0, len(text), 4):
            stream.feed(text[i:i + 4])
        assert stream.finish().values["answer"] == "ok"
        return time.perf_counter() - start

    cost(10_000)  # warm up
    small, large = cost(40_000), cost(160_000)
    assert large < 12 * small + 0.05, f"4x the reply cost {large:.2f}s vs {small:.2f}s"

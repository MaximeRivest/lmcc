"""Kernel §4a: marker repairs, the report, truncation — and streaming
agreeing with batch on all of it (§8)."""

import dataclasses
import random

import pytest

import lmcc


@dataclasses.dataclass
class Out:
    reasoning: str
    answer: int


@lmcc.fn
def solve(question: str) -> Out:
    """Answer the question."""


TAGS = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{question}")])
LABELS = lmcc.adapter(messages=[
    lmcc.system("{instruction}\nReasoning: {reasoning}\nAnswer: {answer}"), lmcc.user("{question}")])
DSPY = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}"
                "[[ ## completed ## ]]"), lmcc.user("{question}")])


def plan(adapter=TAGS):
    return solve.bind(adapter, capabilities={"instruct": True})


def outcome(p, reply, chunks=None, finish_reason=None):
    """('ok', values, repairs) or ('refuse', code), batch or streamed."""
    try:
        if chunks is None:
            r = p.read(reply if finish_reason is None else {
                "message": {"role": "assistant", "parts": [{"type": "text", "text": reply}]},
                "finish_reason": finish_reason})
            return ("ok", r.values, r.repairs)
        s = p.stream()
        for c in chunks:
            s.feed(c)
        r = s.finish(finish_reason)
        return ("ok", r.values, r.repairs)
    except lmcc.Refusal as err:
        return ("refuse", err.code)


# ------------------------------------------------------------------ batch


def test_misspelled_tags_are_repaired_and_reported():
    r = plan().read("<Reasoning>\nx\n</REASONING>\n<answer>\n4\n</answer>")
    assert r.values == {"reasoning": "x", "answer": 4}
    assert r.repairs == [{"repair": "marker", "marker": "<reasoning>", "saw": "<Reasoning>"},
                         {"repair": "marker", "marker": "</reasoning>", "saw": "</REASONING>"}]
    assert not r.clean


def test_a_well_spelled_reply_is_clean():
    r = plan().read("<reasoning>\nx\n</reasoning>\n<answer>\n4\n</answer>")
    assert r.clean and r.repairs == []


@pytest.mark.parametrize("reply", [
    "**Reasoning:** x\n**Answer:** 4",
    "**Reasoning**: x\n**Answer**: 4",
    "__Reasoning:__ x\n__Answer:__ 4",
    "### Reasoning:\nx\n### Answer:\n4",
    "REASONING : x\nanswer: 4",
])
def test_markdown_labels_are_repaired(reply):
    assert plan(LABELS).read(reply).values == {"reasoning": "x", "answer": 4}


def test_bold_around_an_exact_label_is_decoration_not_value():
    # 0.7 read '** 4' here; §4a states this one change
    assert plan(LABELS).parse("Reasoning: x\n**Answer:** 4") == {"reasoning": "x", "answer": 4}


def test_emphasis_inside_a_value_is_kept():
    r = plan(LABELS).read("Reasoning: it is *very* clear\nAnswer: 4")
    assert r.values["reasoning"] == "it is *very* clear" and r.clean


def test_dspy_markers_with_other_spacing():
    r = plan(DSPY).read("[[## Reasoning ##]]\nx\n\n[[##answer##]]\n4\n\n[[ ## completed ## ]]")
    assert r.values == {"reasoning": "x", "answer": 4}
    assert [x["saw"] for x in r.repairs] == ["[[## Reasoning ##]]", "[[##answer##]]"]


def test_the_exact_spelling_wins_over_a_mention():
    r = plan().read("<reasoning>\nthe <ANSWER> tag comes next\n</reasoning>\n<answer>\n4\n</answer>")
    assert r.values == {"reasoning": "the <ANSWER> tag comes next", "answer": 4} and r.clean


def test_a_repair_never_joins_lines():
    assert outcome(plan(LABELS), "Reasoning: x\nAns\nwer: 4")[0] == "refuse"


def test_the_colon_is_part_of_a_label():
    # 'answer' in prose is not the label 'Answer:'; guessing it would invent a value
    assert outcome(plan(LABELS), "Reasoning: the answer is 4") == ("refuse", "parse-missing-fields")


def test_two_misspelled_anchors_refuse():
    assert outcome(plan(), "<Answer>\n1\n</Answer>\n<ANSWER>\n2\n</ANSWER>\n<reasoning>\nx\n</reasoning>") \
        == ("refuse", "parse-ambiguous")


def test_strict_turns_every_repair_off():
    strict = lmcc.adapter(messages=TAGS.template, strict=True)
    p = plan(strict)
    assert outcome(p, "<Reasoning>\nx\n</Reasoning>\n<answer>\n4\n</answer>") == ("refuse", "parse-missing-fields")
    assert outcome(p, "<reasoning>\nx\n</reasoning>\n<answer>\n4.\n</answer>") == ("refuse", "parse-value")
    assert p.describe()["strict"] is True
    assert p.describe()["streaming"]["repairs"] == {"mode": "strict"}
    assert lmcc.load(strict.dump()).strict is True


@pytest.mark.parametrize("kw,path", [
    ({"strict": "yes"}, "strict"),
    ({"reader": {"kind": "derived", "markers": "exact"}}, "reader"),
])
def test_bad_options_refuse_with_a_fix(kw, path):
    with pytest.raises(lmcc.Refusal) as err:
        lmcc.adapter(messages=TAGS.template, **kw)
    assert err.value.code == "entry-malformed" and err.value.fix == {"action": "edit-entry", "path": path}


def test_markers_sharing_a_key_are_not_repaired():
    @dataclasses.dataclass
    class Two:
        answer: str
        Answer: str

    @lmcc.fn
    def twin(question: str) -> Two:
        """Both."""
    p = twin.bind(TAGS, capabilities={"instruct": True})
    assert set(p.describe()["reader"]["unrepaired"]) == {"<answer>", "</answer>", "<Answer>", "</Answer>"}


def test_report_order_and_kinds():
    r = plan().read("Sure!\n<reasoning>\nhmm\n<Answer>\n4\n</answer>\nBye")
    assert r.repairs == [{"repair": "marker", "marker": "<answer>", "saw": "<Answer>"},
                         {"repair": "ignored", "saw": "Sure!"},
                         {"repair": "unclosed", "field": "reasoning", "close": "</reasoning>"},
                         {"repair": "ignored", "saw": "Bye"}]


def test_a_missing_last_close_is_what_a_stop_sequence_leaves():
    assert plan().read("<reasoning>\nx\n</reasoning>\n<answer>\n4").clean


# ------------------------------------------------------------- truncation


def test_a_cut_reply_refuses_and_keeps_what_ended():
    with pytest.raises(lmcc.Refusal) as err:
        plan().read({"message": {"role": "assistant", "parts": [
            {"type": "text", "text": "<reasoning>\nx\n</reasoning>\n<answer>\n4"}]}, "finish_reason": "length"})
    assert err.value.code == "parse-truncated" and err.value.partial == {"reasoning": "x"}
    assert "'answer'" in err.value.hint


def test_a_cut_reply_missing_a_field_refuses_truncated_not_missing():
    assert outcome(plan(), "<reasoning>\nand then", finish_reason="length") == ("refuse", "parse-truncated")


def test_a_reply_cut_after_its_answer_reads():
    assert outcome(plan(), "<reasoning>\nx\n</reasoning>\n<answer>\n4\n</answer>\nAlso",
                   finish_reason="length")[:2] == ("ok", {"reasoning": "x", "answer": 4})


def test_a_normal_stop_reads_to_the_end():
    assert outcome(plan(LABELS), "Reasoning: x\nAnswer: 4", finish_reason="stop")[0] == "ok"
    assert outcome(plan(LABELS), "Reasoning: x\nAnswer: 4", finish_reason="length") == ("refuse", "parse-truncated")


def test_rendered_step_refuses_a_cut_reply():
    p = plan()
    rendered = p.render(question="q")
    with pytest.raises(lmcc.Refusal) as err:
        rendered.step({"message": {"role": "assistant", "parts": [{"type": "text", "text": "<reasoning>\nx"}]},
                       "finish_reason": "length"})
    assert err.value.code == "parse-truncated"


# ------------------------------------------------------------- streaming


def test_a_well_spelled_reply_streams_as_before():
    p = plan()
    s = p.stream()
    events = []
    for c in "<reasoning>\nthinking hard\n</reasoning>\n<answer>\n4\n</answer>":
        events += s.feed(c)
    deltas = "".join(e["text"] for e in events if e["kind"] == "field_delta" and e["field"] == "reasoning")
    assert deltas == "thinking hard"   # all of it before finish


def test_a_misspelled_reply_streams_up_to_its_first_slip():
    p = plan()
    s = p.stream()
    events = []
    for c in "<reasoning>\nthinking hard\n</reasoning>\n<Answer>\n4\n</Answer>":
        events += s.feed(c)
    assert "".join(e["text"] for e in events if e["kind"] == "field_delta") == "thinking hard"
    result = s.finish()
    assert result.values == {"reasoning": "thinking hard", "answer": 4}
    assert [r["saw"] for r in result.repairs] == ["<Answer>", "</Answer>"]


# Random replies from correct, misspelled and decorated pieces: any
# chunking must equal batch — values, repairs, refusal code.
PIECES = {
    "tags": ["<reasoning>", "<Reasoning>", "< reasoning >", "</reasoning>", "</REASONING>", "<answer>",
           "<ANSWER>", "**<answer>**", "</answer>", "</Answer>"],
    "labels": ["Reasoning:", "**Reasoning:**", "### Reasoning:", "reasoning :", "Answer:", "**Answer**:",
             "__Answer:__", "\nAnswer:", "\n**Answer:**", "ANSWER:"],
    "dspy": ["[[ ## reasoning ## ]]", "[[## Reasoning ##]]", "[[ ## answer ## ]]", "[[##answer##]]",
           "[[ ## completed ## ]]", "[[## completed##]]", "## answer", "# "],
}
FILLER = ["4", " 4 ", "4.", "`4`", "\"4\"", "x", "\n", " ", "*", "**", "_", "#", "an", "ans", "<", "**bold**", "Sure!", "12"]


@pytest.mark.parametrize("name", ["tags", "labels", "dspy"])
def test_fuzz_streaming_repairs_refine_batch(name):
    rng = random.Random(7)
    p = plan({"tags": TAGS, "labels": LABELS, "dspy": DSPY}[name])
    for run in range(600):
        reply = "".join(rng.choice(PIECES[name] + FILLER) for _ in range(rng.randint(1, 9)))
        cuts = sorted(rng.sample(range(1, len(reply)), min(len(reply) - 1, rng.randint(0, 6)))) \
            if len(reply) > 1 else []
        chunks = [reply[a:b] for a, b in zip([0] + cuts, cuts + [len(reply)])]
        reason = rng.choice([None, None, "stop", "length"])
        batch = outcome(p, reply, finish_reason=reason)
        assert outcome(p, reply, chunks, finish_reason=reason) == batch, (run, reply, chunks)
        assert outcome(p, reply, list(reply), finish_reason=reason) == batch, (run, reply)


# ---------------------------------------------------------- values, tags


@pytest.mark.parametrize("text,value", [("42.", 42), ("`42`", 42), ("\"42\"", 42), ("'42.'", 42)])
def test_integer_slips_read(text, value):
    r = plan().read(f"<reasoning>\nx\n</reasoning>\n<answer>\n{text}\n</answer>")
    assert r.values["answer"] == value and r.repairs[-1]["repair"] == "value"


@pytest.mark.parametrize("text", ["42.0", "4 2", "42..", "forty-two", "N/A", "none"])
def test_not_a_slip_still_refuses(text):
    assert outcome(plan(), f"<reasoning>\nx\n</reasoning>\n<answer>\n{text}\n</answer>") \
        == ("refuse", "parse-value")


def test_a_string_is_never_repaired():
    @lmcc.fn
    def say(question: str) -> str:
        """Say it."""
    p = say.bind(TAGS, capabilities={"instruct": True})
    r = p.read("<say>\n\"None.\"\n</say>")
    assert r.values == {"say": "\"None.\""} and r.clean


def test_reasoning_tags_are_repaired_but_code_delimiters_are_not():
    import lmcc_std
    reg = lmcc.Registry()
    lmcc_std.install(reg)

    @dataclasses.dataclass
    class Thought:
        reasoning: lmcc.Purpose["reasoning", str]
        answer: int

    @lmcc.fn
    def think(question: str) -> Thought:
        """Think."""
    p = think.bind(lmcc.adapter(messages=TAGS.template, transports={"reasoning": "reasoning_tags"}),
                   capabilities={"instruct": True}, registry=reg)
    r = p.read("<THINK>hm</Think><answer>\n4\n</answer>")
    assert r.values == {"answer": 4, "reasoning": "hm"}
    heredoc = reg.transport("heredoc_tools", {})
    assert not any(rule.get("repair") for rule in heredoc.find)

"""End-to-end: lmcc's three reasoning strategies through lm15, against live models.

One program (``solve``), one adapter, three strategies, chosen by declared
capabilities — the claim the reasoning vocabulary makes. This script spends
real money to check it holds:

- ``prefix_cot``       visible section, any instruct model
- ``reasoning_tags``   ``<think>`` spans routed out of the text, any instruct model
- ``native_reasoning`` the provider's thinking channel, read from response parts

Each runs batch (``plan.parse``) and streaming (``plan.stream`` fed by
lm15's stream events), and the streamed values must equal the batch ones
(kernel §8). Finally the ``auto`` (choose) strategy is bound twice with
different facts to show the program never changes.

lmcc never touches the network; the bridge below is the whole seam:
lmcc messages/patch → lm15 ``Request``; lm15 parts/deltas → lmcc parts.

Run:
    source ~/Projects/lm15-dev/.env
    PYTHONPATH=~/Projects/lmcc/python:~/Projects/lm15-dev/lm15-python \\
        python ~/Projects/lmcc/python/integration/lm15_reasoning.py [--only prefix_cot,tags,native,auto]

Or under pytest (skips without keys):
    PYTHONPATH=...  python -m pytest integration/lm15_reasoning.py -v -s
"""

from __future__ import annotations

import dataclasses
import os
import sys
import time

import lmcc
import lmcc_std

import lm15
from lm15 import (AnthropicLM, Config, Message, OpenAILM, Reasoning, Request, TextPart,
                  StreamDeltaEvent, TextDelta, ThinkingDelta)

# ------------------------------------------------------------------ the bridge


def to_lm15_request(rendered, *, model: str, config: Config | None = None) -> Request:
    """lmcc's rendered messages are lm15-shaped dicts; lift them to lm15 types.
    The system message becomes ``Request.system``; the patch is the caller's
    to merge into Config (lmcc only says *what* it asked for)."""
    system, messages = None, []
    for m in rendered.messages:
        parts = [TextPart(p["text"]) for p in m["content"] if p["kind"] == "text"]
        if m["role"] == "system":
            system = "".join(p.text for p in parts)
        else:
            messages.append(Message(role=m["role"], parts=tuple(parts)))
    return Request(model=model, system=system, messages=tuple(messages), config=config or Config())


def to_lmcc_response(response) -> dict:
    """lm15 parts → lmcc parts: ``type`` is lmcc's ``kind``."""
    content = []
    for p in response.message.parts:
        if p.type in ("text", "thinking"):
            content.append({"kind": p.type, "text": p.text})
        else:
            content.append({"kind": p.type})
    return {"content": content}


def feed_stream(plan, lm, request):
    """Drive an lmcc stream from lm15 stream events; return (events, values)."""
    stream = plan.stream()
    events = []
    for event in lm.stream(request):
        if not isinstance(event, StreamDeltaEvent):
            continue
        d = event.delta
        if isinstance(d, TextDelta):
            events.extend(stream.feed(d.text))
        elif isinstance(d, ThinkingDelta):
            events.extend(stream.feed({"kind": "thinking", "text": d.text}))
    result = stream.finish()
    events.extend(result.events)
    return events, result.values


# ------------------------------------------------------------------ the program


@dataclasses.dataclass
class Solution:
    reasoning: lmcc.Role["reasoning", str]
    answer: int


@lmcc.fn
def solve(problem: str) -> Solution:
    """Solve the arithmetic problem. The answer is a single integer."""


XML = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nReply with exactly this pattern and nothing else:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{problem}")])

PROBLEM = "A shop sells pens at 3 each. Ana buys 7 pens and pays with a 50 note. How much change does she get?"
EXPECTED = 29

REGISTRY = lmcc.Registry()
lmcc_std.install(REGISTRY)


def bound(strategy, capabilities):
    adapter = lmcc.adapter(messages=XML.template, strategies={"reasoning": strategy})
    return solve.bind(adapter, capabilities=capabilities, registry=REGISTRY)


# ------------------------------------------------------------------ the checks


def check(name, plan, lm, model, config=None):
    t0 = time.time()
    rendered = plan.render(problem=PROBLEM)
    request = to_lm15_request(rendered, model=model, config=config)
    d = plan.describe()
    print(f"\n== {name}  [{model}]  strategy={d['strategies']['reasoning']}  "
          f"hidden={d['hidden']}  routings={[r['from'] for r in d['routings']]}")
    print("   system:", repr(rendered.messages[0]["content"][0]["text"][-140:]))

    response = lm.complete(request)
    batch = plan.parse(to_lmcc_response(response))
    print(f"   batch : answer={batch['answer']!r}  reasoning={batch['reasoning'][:90]!r}…")
    assert batch["answer"] == EXPECTED, batch
    assert isinstance(batch["reasoning"], str) and batch["reasoning"].strip(), "reasoning came back empty"

    events, streamed = feed_stream(plan, lm, request)
    kinds = [e["kind"] for e in events]
    print(f"   stream: answer={streamed['answer']!r}  events={len(events)} "
          f"(started={kinds.count('field_started')}, deltas={kinds.count('field_delta')}, "
          f"done={kinds.count('field_done')})  {time.time() - t0:.1f}s")
    assert streamed["answer"] == EXPECTED, streamed
    assert set(streamed) == {"reasoning", "answer"} and kinds.count("field_done") == 2
    deltas = "".join(e["text"] for e in events if e["kind"] == "field_delta" and e["field"] == "reasoning")
    assert deltas.strip() == streamed["reasoning"].strip(), "streamed reasoning deltas != final value"
    return batch, streamed


def run(only=None):
    openai = OpenAILM(api_key=os.environ["OPENAI_API_KEY"])
    anthropic = AnthropicLM(api_key=os.environ["ANTHROPIC_API_KEY"])
    instruct, native = {"instruct": True}, {"instruct": True, "native_reasoning": True}
    want = lambda k: only is None or k in only

    if want("prefix_cot"):
        check("prefix_cot", bound("prefix_cot", instruct), openai, "gpt-4.1-mini")

    if want("tags"):
        check("reasoning_tags", bound("reasoning_tags", instruct), openai, "gpt-4.1-mini")

    if want("native"):
        # The std strategy only *routes* channel:thinking; asking for thinking is
        # the request's business, so it rides in lm15's Config — the same seam
        # a controls patch would cross.
        cfg = Config(max_tokens=4000, reasoning=Reasoning(effort="low", thinking_budget=1024))
        check("native_reasoning", bound("native_reasoning", native), anthropic, "claude-sonnet-4-5", cfg)

    if want("auto"):
        auto = lmcc.Strategy(choose=[
            {"when": {"capability": "native_reasoning"}, "use": lmcc_std.strategies.native_reasoning({})},
            {"else": lmcc_std.strategies.reasoning_tags({})}])
        cfg = Config(max_tokens=4000, reasoning=Reasoning(effort="low", thinking_budget=1024))
        a = check("auto → tags   (instruct only)", bound(auto, instruct), openai, "gpt-4.1-mini")
        b = check("auto → native (native_reasoning)", bound(auto, native), anthropic, "claude-sonnet-4-5", cfg)
        assert a[0]["answer"] == b[0]["answer"] == EXPECTED

    print("\nALL STRATEGIES HOLD END TO END")


# ------------------------------------------------------------------ pytest face

def _have_keys():
    return all(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"))


def test_reasoning_strategies_end_to_end():
    import pytest
    if not _have_keys():
        pytest.skip("OPENAI_API_KEY and ANTHROPIC_API_KEY needed (source lm15-dev/.env)")
    run()


if __name__ == "__main__":
    if not _have_keys():
        sys.exit("set OPENAI_API_KEY and ANTHROPIC_API_KEY (source ~/Projects/lm15-dev/.env)")
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    run(only)

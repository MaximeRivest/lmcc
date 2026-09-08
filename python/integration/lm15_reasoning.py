"""End-to-end: lmcc's three reasoning strategies through lm15, against live models.

One program (``solve``), one adapter, three strategies, chosen by declared
capabilities — the claim the reasoning vocabulary makes. This script spends
real money to check it holds, through the typed bridge (``lmcc_lm15``):

- ``prefix_cot``       visible section, any instruct model
- ``reasoning_tags``   ``<think>`` spans routed out of the text, any instruct model
- ``native_reasoning`` asks for thinking (``config.reasoning`` in the request
                       patch — the strategy does everything) and reads it back
                       from the provider's thinking channel

Each runs batch (``lmcc_lm15.parse``) and streaming (``lmcc_lm15.stream`` fed
by ``lm.stream``), and the streamed values must equal the batch ones (kernel
§8). Finally the ``auto`` (choose) strategy is bound twice with different
facts to show the program never changes.

Run:
    set -a; source ~/Projects/lm15-dev/.env; set +a
    PYTHONPATH=~/Projects/lmcc/python:~/Projects/lm15-dev/lm15-python \\
        python ~/Projects/lmcc/python/integration/lm15_reasoning.py [--only prefix_cot,tags,native,auto]

Not part of ./check: it costs money and needs keys (under pytest it skips without them).
"""

from __future__ import annotations

import dataclasses
import os
import sys
import time

import lmcc
import lmcc_lm15
import lmcc_std
from lm15 import AnthropicLM, Config, OpenAILM


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


def check(name, plan, lm, model, config=None):
    t0 = time.time()
    rendered = plan.render(problem=PROBLEM)
    request = lmcc_lm15.request(rendered, model=model, config=config or Config(max_tokens=4000))
    d = plan.describe()
    print(f"\n== {name}  [{model}]  strategy={d['strategies']['reasoning']}  hidden={d['hidden']}  "
          f"routings={[r['from'] for r in d['routings']]}  patch={rendered.patch}")
    print("   system:", repr(rendered.system[-120:]))

    batch = lmcc_lm15.parse(plan, lm.complete(request))
    print(f"   batch : answer={batch['answer']!r}  reasoning={batch['reasoning'][:90]!r}…")
    assert batch["answer"] == EXPECTED, batch
    assert batch["reasoning"].strip(), "reasoning came back empty"

    events, result = lmcc_lm15.stream(plan, lm.stream(request))
    kinds = [e["kind"] for e in events]
    print(f"   stream: answer={result.values['answer']!r}  events={len(events)} "
          f"(started={kinds.count('field_started')}, deltas={kinds.count('field_delta')}, "
          f"done={kinds.count('field_done')})  {time.time() - t0:.1f}s")
    assert result.values["answer"] == EXPECTED and kinds.count("field_done") == 2
    deltas = "".join(e["text"] for e in events if e["kind"] == "field_delta" and e["field"] == "reasoning")
    assert deltas.strip() == result.values["reasoning"].strip(), "streamed deltas != final value"
    return batch


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
        # The strategy asks for thinking itself (config.reasoning in the patch);
        # the caller only sets a budget on top, which does not contradict it.
        strategy = lmcc.use("native_reasoning", effort="low", thinking_budget=1024)
        check("native_reasoning", bound(strategy, native), anthropic, "claude-sonnet-4-5")
    if want("auto"):
        auto = lmcc.Strategy(choose=[
            {"when": {"capability": "native_reasoning"},
             "use": lmcc_std.strategies.native_reasoning({"effort": "low", "thinking_budget": 1024})},
            {"else": lmcc_std.strategies.reasoning_tags({})}])
        a = check("auto → tags   (instruct only)", bound(auto, instruct), openai, "gpt-4.1-mini")
        b = check("auto → native (native_reasoning)", bound(auto, native), anthropic, "claude-sonnet-4-5")
        assert a["answer"] == b["answer"] == EXPECTED

    print("\nALL STRATEGIES HOLD END TO END")


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

"""One program, three reasoning strategies, two providers — live, through lm15.

    set -a; source ~/Projects/lm15-dev/.env; set +a
    PYTHONPATH=~/Projects/lmcc/python:~/Projects/lm15-dev/lm15-python python integration/lm15_reasoning.py

Not in ./check: it costs money. Under pytest it skips without keys.
"""

import dataclasses
import os

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


XML = [lmcc.system("{instruction}\n\nReply with exactly this pattern and nothing else:\n"
                   "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
       lmcc.user("{problem}")]
PROBLEM = "Pens cost 3 each. Ana buys 7 and pays with a 50 note. How much change does she get?"

registry = lmcc.Registry()
lmcc_std.install(registry)


def run(name, strategy, capabilities, lm, model):
    plan = solve.bind(lmcc.adapter(messages=XML, strategies={"reasoning": strategy}),
                      capabilities=capabilities, registry=registry)
    request = lmcc_lm15.request(plan.render(problem=PROBLEM), model=model, config=Config(max_tokens=4000))

    batch = lmcc_lm15.parse(plan, lm.complete(request))
    events, streamed = lmcc_lm15.stream(plan, lm.stream(request))

    assert batch["answer"] == streamed.values["answer"] == 29, (batch, streamed.values)
    assert batch["reasoning"].strip() and streamed.values["reasoning"].strip()
    print(f"{name:<18} {model:<18} answer={batch['answer']}  stop={request.config.stop}  "
          f"reasoning_cfg={request.config.reasoning.effort if request.config.reasoning else '-'}  "
          f"events={len(events)}  reasoning={batch['reasoning'][:40]!r}…")


def main():
    openai = OpenAILM(api_key=os.environ["OPENAI_API_KEY"])
    claude = AnthropicLM(api_key=os.environ["ANTHROPIC_API_KEY"])
    # Capability facts are per model, declared, never sniffed: OpenAI's Responses
    # API has no stop field (lm15 refuses rather than omit), Claude honors one.
    instruct = {"instruct": True}
    native = {"instruct": True, "native_reasoning": True, "stop_sequences": True}
    auto = lmcc.Strategy(choose=[
        {"when": {"capability": "native_reasoning"}, "use": lmcc_std.strategies.native_reasoning({"effort": "low"})},
        {"else": lmcc_std.strategies.reasoning_tags({})}])

    run("prefix_cot", "prefix_cot", instruct, openai, "gpt-4.1-mini")
    run("reasoning_tags", "reasoning_tags", instruct, openai, "gpt-4.1-mini")
    run("native_reasoning", lmcc.use("native_reasoning", effort="low"), native, claude, "claude-sonnet-4-5")
    run("auto → tags", auto, instruct, openai, "gpt-4.1-mini")
    run("auto → native", auto, native, claude, "claude-sonnet-4-5")
    print("all strategies hold: same program, batch == stream, answer == 29")


def test_reasoning_strategies_end_to_end():
    import pytest
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("needs OPENAI_API_KEY and ANTHROPIC_API_KEY")
    main()


if __name__ == "__main__":
    main()

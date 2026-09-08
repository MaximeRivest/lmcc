"""Tools and citations, live: one program per role, native and text tiers, two providers.

    set -a; source ~/Projects/lm15-dev/.env; set +a
    PYTHONPATH=~/Projects/lmcc/python:~/Projects/lm15-dev/lm15-python python integration/lm15_tools_citations.py

The tool loop is the caller's (kernel §6): lmcc lays out one call and reads
one reply; we run the function and append two lm15 messages to history.
Not in ./check: it costs money. Under pytest it skips without keys.
"""

import dataclasses
import os

import lmcc
import lmcc_lm15
import lmcc_std
from lm15 import AnthropicLM, Config, Message, OpenAILM
from lmcc_std.tools import Citation, Source, Tool, ToolCall

registry = lmcc.Registry()
lmcc_std.install(registry)
TAGS = ("Reply with exactly this pattern and nothing else, also after a tool result:\n"
        "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}")


# ------------------------------------------------------------------ tools

@dataclasses.dataclass
class Out:
    calls: lmcc.Role["tools.calls", list[ToolCall]]
    answer: str


@lmcc.fn
def ask(question: str, tools: lmcc.Role["tools", list[Tool]]) -> Out:
    """Answer the question. Use a tool when you need facts you do not have."""


WEATHER = Tool("get_weather", "Current weather for a city.",
               {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})


def get_weather(city: str) -> str:
    return f"Sunny and 22°C in {city}."


def tool_loop(name, strategy, caps, lm, model):
    plan = ask.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\n\n" + TAGS), lmcc.user("{question}"), lmcc.history()],
                                 strategies={"tools": strategy}), capabilities=caps, registry=registry)
    history, turns = [], 0
    while True:
        request = lmcc_lm15.request(plan.render(question="What is the weather in Montreal right now?",
                                                tools=[WEATHER], history=history),
                                    model=model, config=Config(max_tokens=400))
        response = lm.complete(request)
        values = lmcc_lm15.parse(plan, response)
        turns += 1
        if not values.get("calls"):
            break
        call = values["calls"][0]
        result = get_weather(**call.input)
        # native: the provider's own messages; fenced: the same lm15 shapes, spelled by `turns`
        history += [lmcc_lm15.message_to_history(response.message),
                    lmcc_lm15.message_to_history(Message.tool(call.id, result))]
        assert turns < 4, "loop did not converge"
    assert "22" in values["answer"] and "Montreal" in values["answer"], values
    print(f"{name:<14} {model:<18} turns={turns}  call={call.name}({call.input})  answer={values['answer'][:60]!r}")


# -------------------------------------------------------------- citations

@dataclasses.dataclass
class Grounded:
    answer: str
    citations: lmcc.Role["citations", list[Citation]]


@lmcc.fn
def grounded(question: str, sources: lmcc.Role["citations.sources", list[Source]]) -> Grounded:
    """Answer the question from the sources only."""


@lmcc.fn
def searched(question: str) -> Grounded:
    """Answer the question in one sentence, citing a web source."""


def inline(lm, model):
    plan = grounded.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\n\n" + TAGS), lmcc.user("{question}")],
                                      strategies={"citations": "inline_citations"}),
                         capabilities={"instruct": True}, registry=registry)
    sources = [Source("The Eiffel Tower was completed in 1889.", title="Encyclopedia"),
               Source("The Eiffel Tower is 330 metres tall.", title="Almanac")]
    request = lmcc_lm15.request(plan.render(question="When was the Eiffel Tower completed, and how tall is it?", sources=sources),
                                model=model, config=Config(max_tokens=200))
    values = lmcc_lm15.parse(plan, lm.complete(request))
    cited = {c.source for c in values["citations"]}
    assert cited == {1, 2}, values
    print(f"{'inline':<14} {model:<18} cites={sorted(cited)}  answer={values['answer'][:70]!r}")


def native(lm, model):
    # search mode answers in prose and ignores reply patterns; the adapter says
    # so: the whole reply is the answer (kernel §4), citations ride as parts
    plan = searched.bind(lmcc.adapter(messages=[lmcc.system("{instruction}\n{answer}"), lmcc.user("{question}")],
                                      strategies={"citations": "native_citations"}),
                         capabilities={"native_citations": True}, registry=registry)
    request = lmcc_lm15.request(plan.render(question="Where will the 2028 Summer Olympics be held?"),
                                model=model, config=Config(max_tokens=400))
    assert request.tools and request.tools[0].name == "web_search"
    values = lmcc_lm15.parse(plan, lm.complete(request))
    assert values["citations"] and values["citations"][0].url, values
    print(f"{'native':<14} {model:<18} citations={len(values['citations'])}  first={values['citations'][0].url[:50]}  "
          f"answer={values['answer'][:50]!r}")


def main():
    openai = OpenAILM(api_key=os.environ["OPENAI_API_KEY"])
    claude = AnthropicLM(api_key=os.environ["ANTHROPIC_API_KEY"])
    tool_loop("native_tools", "native_tools", {"native_function_calling": True}, openai, "gpt-4.1-mini")
    tool_loop("native_tools", "native_tools", {"native_function_calling": True}, claude, "claude-sonnet-4-5")
    tool_loop("fenced_tools", "fenced_tools", {"instruct": True}, openai, "gpt-4.1-mini")
    inline(openai, "gpt-4.1-mini")
    native(openai, "gpt-4.1-mini")
    print("tools and citations hold: same programs, native and text tiers")


def test_tools_and_citations_end_to_end():
    import pytest
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("needs OPENAI_API_KEY and ANTHROPIC_API_KEY")
    main()


if __name__ == "__main__":
    main()

"""Repairs and truncation, live (kernel §4a): what real models actually write.

    set -a; source ~/Projects/lm15-dev/.env; set +a
    PYTHONPATH=. python integration/lm15_repairs.py

Three adapter styles × models from several providers, small ones on
purpose (they slip most). For each reply: the values or the refusal, and
every repair the reader made. Then a reply cut at its length limit, a
streamed reply checked against batch, and a conversation whose repaired
turn is replayed clean. Not in ./check: it costs money (cents).
"""

import collections
import dataclasses
import enum
import json
import os
import sys

import lmcc
import lmcc_lm15
from lm15 import AnthropicLM, Config, GeminiLM, OpenAIChatLM, OpenAILM


class Sentiment(enum.Enum):
    positive = "positive"
    negative = "negative"
    mixed = "mixed"


@dataclasses.dataclass
class Review:
    reasoning: str
    sentiment: Sentiment
    stars: int
    would_return: bool


@lmcc.fn
def review(text: str) -> Review:
    """Read the restaurant review. Give brief reasoning, the overall sentiment, the star
    rating (1 to 5) the reviewer would give, and whether they would return."""


ADAPTERS = {
    "tags": lmcc.adapter(messages=[
        lmcc.system("{instruction}\n\nReply in exactly this form:\n"
                    "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
        lmcc.turns(), lmcc.user("{text}")]),
    "labels": lmcc.adapter(messages=[
        lmcc.system("{instruction}\n\nReply in exactly this form:\n"
                    "Reasoning: {reasoning}\nSentiment: {sentiment}\nStars: {stars}\n"
                    "Would return: {would_return}"),
        lmcc.turns(), lmcc.user("{text}")]),
    "dspy": lmcc.adapter(messages=[
        lmcc.system("{instruction}\n\nReply in exactly this form:\n"
                    "{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}"
                    "[[ ## completed ## ]]"),
        lmcc.turns(), lmcc.user("{text}")]),
}

REVIEWS = [
    "Waited 50 minutes for cold pasta and the waiter shrugged. Never again.",
    "The tacos were incredible and cheap, though the music was far too loud. I'll be back for sure.",
    "Beautiful room, fine wine list, but the steak was overcooked and the bill was huge. Hard to say.",
]


def models():
    env = os.environ
    out = []
    if env.get("OPENAI_API_KEY"):
        lm = OpenAILM(api_key=env["OPENAI_API_KEY"])
        out += [("openai", lm, "gpt-4.1-nano"), ("openai", lm, "gpt-4.1-mini")]
    if env.get("ANTHROPIC_API_KEY"):
        out.append(("anthropic", AnthropicLM(api_key=env["ANTHROPIC_API_KEY"]), "claude-haiku-4-5"))
    if env.get("GEMINI_API_KEY"):
        out.append(("gemini", GeminiLM(api_key=env["GEMINI_API_KEY"]), "gemini-2.5-flash-lite"))
    if env.get("GROQ_API_KEY"):
        out.append(("groq", OpenAIChatLM(api_key=env["GROQ_API_KEY"],
                                         base_url="https://api.groq.com/openai/v1"), "openai/gpt-oss-20b"))
    if env.get("OPENROUTER_API_KEY"):
        lm = OpenAIChatLM(api_key=env["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1")
        out += [("openrouter", lm, "meta-llama/llama-3.2-3b-instruct"),
                ("openrouter", lm, "qwen/qwen-2.5-7b-instruct"),
                ("openrouter", lm, "mistralai/mistral-nemo")]
    if env.get("DEEPSEEK_API_KEY"):
        out.append(("deepseek", OpenAIChatLM(api_key=env["DEEPSEEK_API_KEY"],
                                             base_url="https://api.deepseek.com/v1"), "deepseek-chat"))
    return out


def sweep(log):
    kinds = collections.Counter()
    outcomes = collections.Counter()
    for provider, lm, model in models():
        for style, adapter in ADAPTERS.items():
            plan = review.bind(adapter, capabilities={"instruct": True})
            for i, text in enumerate(REVIEWS):
                request = lmcc_lm15.request(plan.render(text=text), model=model,
                                            config=Config(max_tokens=400))
                try:
                    response = lm.complete(request)
                except Exception as exc:  # noqa: BLE001 — a provider problem, not lmcc's
                    outcomes["provider-error"] += 1
                    log.append({"model": model, "style": style, "review": i,
                                "provider_error": str(exc)[:200]})
                    print(f"  {model:34} {style:6} #{i}  PROVIDER ERROR {str(exc)[:80]}")
                    break
                reply = "".join(getattr(p, "text", "") or "" for p in response.message.parts)
                entry = {"model": model, "style": style, "review": i, "reply": reply,
                         "finish_reason": response.finish_reason}
                try:
                    reading = lmcc_lm15.read(plan, response)
                    entry["values"] = {k: (v.value if isinstance(v, enum.Enum) else v)
                                       for k, v in reading.values.items()}
                    entry["repairs"] = reading.repairs
                    outcomes["read, clean" if reading.clean else "read, repaired"] += 1
                    for r in reading.repairs:
                        kinds[r["repair"]] += 1
                    note = ", ".join(f"{r['repair']}:{r.get('saw', r.get('field'))!r}"[:40]
                                     for r in reading.repairs if r["repair"] != "ignored") or "clean"
                    print(f"  {model:34} {style:6} #{i}  ok  {note}")
                except lmcc.Refusal as err:
                    entry["refusal"] = err.describe()
                    outcomes[f"refused {err.code}"] += 1
                    print(f"  {model:34} {style:6} #{i}  REFUSED {err.code}: {err.hint[:110]}")
                log.append(entry)
    return outcomes, kinds


def truncation():
    lm = OpenAILM(api_key=os.environ["OPENAI_API_KEY"])
    plan = review.bind(ADAPTERS["tags"], capabilities={"instruct": True})
    response = lm.complete(lmcc_lm15.request(plan.render(text=REVIEWS[2]), model="gpt-4.1-mini",
                                             config=Config(max_tokens=25)))
    assert response.finish_reason == "length", response.finish_reason
    try:
        lmcc_lm15.parse(plan, response)
        raise AssertionError("a cut reply was read as finished")
    except lmcc.Refusal as err:
        assert err.code == "parse-truncated", err.code
        print(f"  cut at 25 tokens: parse-truncated, partial={err.partial}  ({err.hint[:60]}…)")


def streaming():
    lm = AnthropicLM(api_key=os.environ["ANTHROPIC_API_KEY"])
    plan = review.bind(ADAPTERS["labels"], capabilities={"instruct": True})
    request = lmcc_lm15.request(plan.render(text=REVIEWS[1]), model="claude-haiku-4-5",
                                config=Config(max_tokens=400))
    events = list(lm.stream(request))
    emitted, result = lmcc_lm15.stream(plan, events)
    text = "".join(getattr(e.delta, "text", "") or "" for e in events if hasattr(e, "delta"))
    batch = plan.read(text)
    assert result.values == batch.values and result.repairs == batch.repairs
    print(f"  streamed {len(events)} events, {len(emitted)} lmcc events; batch == stream; "
          f"repairs={[r['repair'] for r in result.repairs] or 'none'}")


def conversation():
    lm = OpenAILM(api_key=os.environ["OPENAI_API_KEY"])
    plan = review.bind(ADAPTERS["tags"], capabilities={"instruct": True})
    # a past turn whose recorded reply needed repairs: replayed clean
    past = plan.render(text=REVIEWS[0]).step(
        "<Reasoning>\nCold food, rude staff.\n</Reasoning>\n<sentiment>\nNegative\n</sentiment>\n"
        "<stars>\n1.\n</stars>\n<would_return>\nno\n</would_return>").finish()
    rendered = plan.render(text=REVIEWS[1], turns=[past])
    replayed = rendered.messages[1]["parts"][0]["text"]
    assert "<reasoning>" in replayed and "negative" in replayed and "1." not in replayed, replayed
    values = lmcc_lm15.parse(plan, lm.complete(lmcc_lm15.request(rendered, model="gpt-4.1-mini",
                                                                   config=Config(max_tokens=400))))
    print(f"  past turn replayed clean; next answer: {values['sentiment'].value}, {values['stars']} stars")


def main():
    log = []
    print("sweep:")
    outcomes, kinds = sweep(log)
    print("\noutcomes:", dict(outcomes))
    print("repairs by kind:", dict(kinds))
    print("\ntruncation:")
    truncation()
    print("streaming:")
    streaming()
    print("conversation:")
    conversation()
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/lmcc-repairs-live.jsonl"
    with open(out, "w") as f:
        for e in log:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"\nlog: {out}")


if __name__ == "__main__":
    main()

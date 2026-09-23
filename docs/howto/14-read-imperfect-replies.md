# Read replies that are almost right

**Goal.** Get typed values from the reply a model actually wrote, which is
often not quite the layout it was shown: `<Answer>` for `<answer>`,
`**Answer:**` for `Answer:`, a fence around everything, a cheerful
sentence before it. Know exactly what lmcc repaired, turn repairs off
when you want the strict behavior, and never mistake a reply the
provider cut short for a finished answer.

This guide is a notebook: run the cells in order and read what they
print. No network is touched; the replies are written by hand. The rule
itself is kernel §4a (`contract/spec/kernel.md`).

## 0. Setup

```python
import dataclasses

import lmcc

@dataclasses.dataclass
class Answer:
    reasoning: str
    answer: int

@lmcc.fn
def solve(question: str) -> Answer:
    """Solve the problem."""

tags = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{question}")])
plan = solve.bind(tags, capabilities={"instruct": True})

def refuses(thunk):
    """Run something that should refuse; print the refusal like a REPL would."""
    try:
        thunk()
        print("(did not refuse)")
    except lmcc.Refusal as r:
        print(f"Refusal[{r.code}]  partial={r.partial}\n  {r.hint[:110]}")
```

## 1. `read`: the values and what was repaired

`parse` gives the values. `read` gives the values *and* a list of every
repair the reader made to get them.

```python
reading = plan.read("<Reasoning>\nsix times seven\n</REASONING>\n<answer>\n42\n</Answer>")
print(reading.values)
for r in reading.repairs:
    print(r)
assert reading.values == {"reasoning": "six times seven", "answer": 42}
assert not reading.clean
```

```output
{'reasoning': 'six times seven', 'answer': 42}
{'repair': 'marker', 'marker': '<reasoning>', 'saw': '<Reasoning>'}
{'repair': 'marker', 'marker': '</reasoning>', 'saw': '</REASONING>'}
{'repair': 'marker', 'marker': '</answer>', 'saw': '</Answer>'}
```

`<answer>` was written correctly, so it is not in the list. A reply
written exactly as the template says has no repairs: `reading.clean` is
`True`.

## 2. The rule, in one sentence

A marker matches **ignoring letter case, spaces, and markdown's `*`, `_`
and `#`, but never across a line**, and bold or heading marks around it
belong to the marker, not to the value next to it.

Because the rule is about markers, never about field names, it works for
any signature. Here it is on a template with plain labels:

```python
labels = lmcc.adapter(messages=[
    lmcc.system("{instruction}\nReasoning: {reasoning}\nAnswer: {answer}"), lmcc.user("{question}")])
lp = solve.bind(labels, capabilities={"instruct": True})

for reply in ["**Reasoning:** half of ten\n**Answer:** 5",
              "### Reasoning:\nhalf of ten\n### Answer:\n5",
              "REASONING : half of ten\nanswer: 5"]:
    r = lp.read(reply)
    assert r.values == {"reasoning": "half of ten", "answer": 5}
    print([x["saw"] for x in r.repairs])
```

```output
['**Reasoning:**', '\n**Answer:**']
['### Reasoning:', '\n### Answer:']
['REASONING :', '\nanswer:']
```

(`\nAnswer:` is the marker as the template has it: the label starts a
line.)

## 3. It never guesses

Three things keep a repair from inventing a value.

**The exact spelling wins.** If the marker appears exactly anywhere in
the reply, every other spelling of it is ordinary text, so a model that
mentions a tag in its reasoning does not break a correct reply:

```python
r = plan.read("<reasoning>\nI will put it in <ANSWER> next.\n</reasoning>\n<answer>\n7\n</answer>")
print(r.values, r.clean)
```

```output
{'reasoning': 'I will put it in <ANSWER> next.', 'answer': 7} True
```

**Two readings refuse.** Two misspelled anchors for one field are as
ambiguous as two exact ones:

```python
refuses(lambda: plan.parse("<Answer>\n1\n</Answer>\n<ANSWER>\n2\n</ANSWER>\n<reasoning>\nx\n</reasoning>"))
```

```output
Refusal[parse-ambiguous]  partial=None
  anchor '<answer>' for field 'answer' appears 2 times in the reply — refusing to guess
```

**Punctuation and line breaks count.** `the answer is 5` is prose, not
the label `Answer:`. Reading it as one would make up a value:

```python
refuses(lambda: lp.parse("Reasoning: the answer is 5"))
```

```output
Refusal[parse-missing-fields]  partial={'reasoning': 'the answer is 5'}
  reply is missing pattern section(s): 'answer'
```

## 4. Everything lmcc tolerated is in the report

Some tolerances are older than repairs: chatter around the answer, a
code fence around everything, a section the model forgot to close
before starting the next. They are reported too, so you can count them:

```python
fence = "`" * 3
r = plan.read(f"Sure! Here you go:\n{fence}xml\n<reasoning>\nhmm\n<answer>\n4\n</answer>\n{fence}")
print(r.values)
for x in r.repairs:
    print(x)
```

```output
{'reasoning': 'hmm', 'answer': 4}
{'repair': 'ignored', 'saw': 'Sure! Here you go:\n```xml'}
{'repair': 'unclosed', 'field': 'reasoning', 'close': '</reasoning>'}
{'repair': 'ignored', 'saw': '```'}
```

A close missing at the very end is *not* reported: that is what a
provider's stop sequence leaves behind (lmcc asks for one when the model
supports it), so it is normal.

What to do with the report is your program's choice: log it, count slips
per model, or refuse a reply that needed repairs.

```python
def strict_parse(p, reply):
    reading = p.read(reply)
    if any(r["repair"] == "marker" for r in reading.repairs):
        raise ValueError(f"misspelled layout: {[r['saw'] for r in reading.repairs]}")
    return reading.values
```

## 5. Turning repairs off

Marker repairs are on by default. An adapter that wants the exact layout
or nothing says so, and it travels with the adapter when you save it:

```python
exact = lmcc.adapter(messages=tags.template, reader={"kind": "derived", "markers": "exact"})
ep = solve.bind(exact, capabilities={"instruct": True})
refuses(lambda: ep.parse("<Reasoning>\nx\n</Reasoning>\n<answer>\n4\n</answer>"))
assert exact.dump()["reader"] == {"kind": "derived", "markers": "exact"}
```

```output
Refusal[parse-missing-fields]  partial={'answer': '4'}
  reply is missing pattern section(s): 'reasoning'
```

## 6. A reply cut short is never a finished answer

When a model runs out of tokens, the provider stops it mid-sentence and
says so: lm15's `finish_reason` is `"length"`. Pass the whole lm15
response, not just its text, and lmcc checks every output ended before
the cut:

```python
def response(text, finish_reason):
    return {"message": {"role": "assistant", "parts": [{"type": "text", "text": text}]},
            "finish_reason": finish_reason}

refuses(lambda: plan.parse(response("<reasoning>\nshort\n</reasoning>\n<answer>\n12", "length")))
```

```output
Refusal[parse-truncated]  partial={'reasoning': 'short'}
  the provider cut the reply at its length limit inside field 'answer'; raise max_tokens or ask for less
```

The `12` might have been `125`, so it is not a value. What ended before
the cut is in `partial`. If the model finished its answer and was cut
while chatting afterwards, the values are safe and it reads normally:

```python
print(plan.parse(response("<reasoning>\nshort\n</reasoning>\n<answer>\n12\n</answer>\nAlso,", "length")))
```

```output
{'reasoning': 'short', 'answer': 12}
```

With `lmcc_lm15`, `lmcc_lm15.parse`, `lmcc_lm15.read`, `lmcc_lm15.step`
and `lmcc_lm15.stream` all pass the finish reason for you.

## 7. Streaming

A reply spelled as the template says streams exactly as before. From the
first misspelled marker on, the rest of the reply waits for `finish`,
because a correct marker arriving later could still make the slip mere
text. The repairs are known at `finish`:

```python
stream = plan.stream()
seen = []
for chunk in ["<reasoning>\nthinking ", "hard\n</reasoning>\n<Ans", "wer>\n4\n</Answer>"]:
    seen += [e["text"] for e in stream.feed(chunk) if e["kind"] == "field_delta"]
end = stream.finish()
print("streamed early:", seen)
print(end.values, [r["saw"] for r in end.repairs])
```

```output
streamed early: ['thinking', ' hard']
{'reasoning': 'thinking hard', 'answer': 4} ['<Answer>', '</Answer>']
```

`stream.finish(finish_reason)` takes the provider's finish reason, so a
cut stream refuses like a cut reply. `plan.describe()["streaming"]["markers"]`
states the holding rule.

## 8. Conversations stay clean

A past reply is normally replayed exactly as the model wrote it. A reply
that needed a marker repair is written back in the template's spelling
instead, so the conversation does not teach the model its own slip:

```python
chat = lmcc.adapter(messages=[tags.template[0], lmcc.turns(), tags.template[1]])
cp = solve.bind(chat, capabilities={"instruct": True})
past = cp.render(question="6*7?").step("<Reasoning>\nsix sevens\n</Reasoning>\n<answer>\n42\n</answer>").finish()
request = cp.render(question="and 6*8?", turns=[past])
print(request.messages[1]["parts"][0]["text"])
```

```output
<reasoning>
six sevens
</reasoning>
<answer>
42
</answer>
```

## What is not repaired (yet)

Values: `42.` for an integer or `Positive` for the enum member
`positive` are the format's business; write a forgiving format for your
type (GUIDE §9). Reasoning tags found by a transport (`<Think>` for
`<think>`) and provider parts are read exactly. These are stated in the
kernel's list of gaps.

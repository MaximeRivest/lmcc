# lmcc — the calling convention for calling a model

When a program calls a function in another language, a calling
convention says where each argument goes, how the result comes back, and
how each type crosses. A model is another language; lmcc is its calling
convention. It lays out each call as an [lm15](https://pypi.org/project/lm15/)
request and reads each reply back into typed values. It never touches
the network.

```python
import lmcc

@lmcc.fn
def answer(question: str) -> str:
    """Answer the question in one sentence."""

xml = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.user("{question}"),
])
plan = answer.bind(xml)
request = plan.render(question="Why is the sky blue?").request("gpt-4.1-mini")   # an lm15 request
plan.read("<Answer>\nRayleigh scattering.\n</Answer>").values   # {'answer': ...}, misspelling repaired and reported
```

`pip install "lmcc[lm15]"` adds the typed bridge to lm15 (`lmcc_lm15`).
The tutorial, how-to guides, the normative specification and the
conformance corpus are in the repository:
https://github.com/MaximeRivest/lmcc

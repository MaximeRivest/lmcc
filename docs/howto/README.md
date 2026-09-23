# How-to guides

One task per guide. Each guide states a goal, gives the complete
Python, asserts the exact output, and names what can refuse. Every
python block runs in `python/tests/test_docs_howto.py`.

New to lmcc? Read [GUIDE.md](../../GUIDE.md) first; it is the tutorial.
Need a definition? See [docs/reference](../reference/README.md).

| guide | task |
|---|---|
| [01-extract-structured-value.md](01-extract-structured-value.md) | return one dataclass with `One[T]` and a format |
| [02-return-several-outputs.md](02-return-several-outputs.md) | return several typed values from a dataclass |
| [03-adaptive-reasoning.md](03-adaptive-reasoning.md) | serve a reasoning purpose through `choose`, by declared capabilities |
| [04-stream-a-reply.md](04-stream-a-reply.md) | remove `plan.stream()` events; refusal at `finish()` |
| [05-preview-cost-and-cache.md](05-preview-cost-and-cache.md) | `prefix()`, `skeleton()`, and pure `render()` |
| [06-repair-from-a-fix.md](06-repair-from-a-fix.md) | act on a refusal's `fix` in code |
| [07-ship-an-adapter-as-json.md](07-ship-an-adapter-as-json.md) | dump, load with no registrations, ship a UDF with `allow_udf` |
| [08-use-a-dspy-signature.md](08-use-a-dspy-signature.md) | lower a `dspy.Signature` through `lmcc_dspy` |
| [09-inspect-a-plan.md](09-inspect-a-plan.md) | debug with `describe()` and `explain()` |
| [10-write-a-vocabulary-pack.md](10-write-a-vocabulary-pack.md) | register a format and a transport through the sockets |
| [11-call-tools-and-cite-sources.md](11-call-tools-and-cite-sources.md) | tools and citations, native or text: call turns, `written_as`, `turns` + probe, the whole-reply pattern |
| [12-conversational-heredoc-tools.md](12-conversational-heredoc-tools.md) | raw-code tool calls, one turn per exchange, writers of past calls and representative probes |
| [13-research-tool-reasoning-cross-design.md](13-research-tool-reasoning-cross-design.md) | build a 3 × 3 tool-transport/reasoning experiment from scratch, using only the kernel and Python's standard library |

Run a guide as a notebook (mrmd / rat): `./dev-venv` once builds the
project venv (lmcc editable, the pinned lm15, IPython) and registers the
`py@lmcc` kernel on it; then open the guide and *run all*.

The raw-code continuation is [12-conversational-heredoc-tools.md](12-conversational-heredoc-tools.md):
ordinary replies, reasoning, raw-code tool calls recorded as a turn, and the
same argument writer used for past calls and the bind-time probe. It is offline and never executes code.

Go users: [go/README.md](../../go/README.md).

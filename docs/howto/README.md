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
| [03-adaptive-reasoning.md](03-adaptive-reasoning.md) | serve a reasoning role through `choose`, by declared capabilities |
| [04-stream-a-reply.md](04-stream-a-reply.md) | consume `plan.stream()` events; refusal at `finish()` |
| [05-preview-cost-and-cache.md](05-preview-cost-and-cache.md) | `prefix()`, `skeleton()`, and pure `render()` |
| [06-repair-from-a-fix.md](06-repair-from-a-fix.md) | act on a refusal's `fix` in code |
| [07-ship-an-adapter-as-json.md](07-ship-an-adapter-as-json.md) | dump, load with no registrations, ship a UDF with `allow_udf` |
| [08-use-a-dspy-signature.md](08-use-a-dspy-signature.md) | lower a `dspy.Signature` through `lmcc_dspy` |
| [09-inspect-a-plan.md](09-inspect-a-plan.md) | debug with `describe()` and `explain()` |
| [10-write-a-vocabulary-pack.md](10-write-a-vocabulary-pack.md) | register a format and a strategy through the sockets |

Go users: [go/README.md](../../go/README.md).

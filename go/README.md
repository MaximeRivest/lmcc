# lmcc in Go

`go/lmcc` is an independent implementation of the LMCC kernel
([contract/spec/kernel.md](../contract/spec/kernel.md)). It was written
from the contract, not ported from Python. It passes the same corpus,
byte for byte. `go/lmccstd` is the standard vocabulary pack.

The kernel imports only the standard library. Values are plain data:
`nil`, `bool`, `int64`, `float64`, `string`, `[]any`, and `*Object`, an
insertion-ordered JSON object. Public functions return `error`; they
never panic.

## Build and test

```
cd go
./check            # gofmt, go vet, go test ./..., build bin/lmcc-conform
go test ./...      # unit tests, the corpus in-process, and the example below
go doc -all ./lmcc # the full API
```

Go 1.22 or newer. No dependencies.

## One complete example

The file [lmcc/example_test.go](lmcc/example_test.go) is the example
below. `go test` runs it and compares its `// Output:` block line by
line. Read that file for the exact bytes; this page explains the steps.

**1. A signature from struct tags.** Inputs are one struct, outputs
another. The tag's first item is the field name. `role=` and `desc=`
are optional.

```go
type exampleIn struct {
	Question string `lmcc:"question"`
}

type exampleOut struct {
	Reasoning string `lmcc:"reasoning,role=reasoning"`
	Answer    string `lmcc:"answer,desc=one sentence"`
	Score     int    `lmcc:"score"`
}

sig, err := lmcc.StructSignature("Answer the question.", exampleIn{}, exampleOut{}, reg)
```

`string`, every integer kind, `float32/64`, `bool`, and slices lower
mechanically. Any other type resolves through `reg.BindFormat` or
refuses `unmapped-type`, naming the field (kernel §1).

**2. An adapter is data.** A template is `[]*Object` of `{role, text}`
messages and `{directive}` entries. Strategies are keyed by role. A
`*Strategy` holds `When`, `Requires`, `Visible`, `Fragments`,
`Controls`, `Placement`, `Routings`, or `Choose`.

```go
tags := lmcc.NewStrategy()
tags.Visible = false
tags.Fragments = lmcc.Obj("system", "Think inside <think>...</think> first.")
tags.Routings = []*lmcc.Object{lmcc.Obj(
	"from", "text", "between", []any{"<think>", "</think>"}, "to", "@role", "consume", true)}

adapter, err := lmcc.NewAdapter("qa",
	[]*lmcc.Object{
		lmcc.Obj("role", "system", "text",
			"{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
		lmcc.Obj("role", "user", "text", "{question}"),
	},
	lmcc.Obj("kind", "derived"),   // parse rule: the template is the parser
	lmcc.Obj("reasoning", tags),   // strategies by role
	nil)                           // formats by type
```

`NewAdapter` validates template syntax. `lmcc.Load(entry, reg)` builds
the same adapter from a JSON artifact; `adapter.Dump(reg)` writes one.

**3. Bind.** Every refusal fires here, before any call.

```go
plan, err := lmcc.Bind(adapter, sig, lmcc.Obj("instruct", true), reg)
plan.Describe().List("hidden")   // ["reasoning"]
plan.Skeleton()                  // {"prefill": "<answer>\n", "stops": ["</score>"]}
```

`plan.Describe()` is the whole plan as an `*Object`. `plan.Explain()`
is its short text form. `plan.Prefix(demos, history)` is the
cache-stable messages.

**4. Render.** Pure. Messages are `[]any` of `*Object` with `role` and
`content` parts. `res.Patch` is the request patch.

```go
res, err := plan.Render(lmcc.Obj("question", "Why is the sky blue?"), nil, nil)
```

**5. Parse.** A reply is a `string` or an `*Object` with `content`
parts. Values come back as an `*Object` in signature order: visible
outputs first, then routed fields.

```go
values, err := plan.Parse("<think>scattering</think><answer>\nRayleigh scattering.\n</answer>\n<score>\n9\n</score>")
// {"answer": "Rayleigh scattering.", "score": 9, "reasoning": "scattering"}
```

**6. Stream.** `plan.Stream()` is a pure reducer. `Feed` takes a text
delta or one part delta and returns events. `Finish` returns EOF events
and the same values, or the same refusal, as `Parse`.

```go
stream := plan.Stream()
events, err := stream.Feed("<think>scatter")        // [] — a between routing waits for its close
events, err = stream.Feed("ing</think><answer>\nRayleigh ")
result, err := stream.Finish()
lmcc.Equal(result.Values, values)                   // true
```

The example's `// Output:` pins every event list. The Python kernel
emits the same events at the same feeds; the harness compares the two
traces on every parse case.

**7. A refusal is data.** `AsError` extracts the `*Error`. `Code` is
stable ([errors.md](../contract/spec/errors.md)). `Fix` is present on
every refusal before render.

```go
_, err = lmcc.Bind(strict, sig, lmcc.Obj("instruct", true), reg)
if e, ok := lmcc.AsError(err); ok {
	e.Code   // "capability-missing"
	e.Fix    // {"action": "declare-capability", "fact": "native_reasoning"}
}
```

## Formats: how a Go type crosses

The kernel spells scalars, enums, and nullables. A structured shape
needs a format or `Bind` refuses `no-format`. Three ways:

- Name one in the artifact: `Obj("[]string", Obj("use", "csv", "options", NewObject()))`
  as the `formats` argument, with `reg.RegisterFormat("csv", factory, "0.1.0", false)`.
- Bind a Go type at runtime: `reg.BindFormat(reflect.TypeOf(T{}), &lmcc.FormatSpec{...}, shape)`.
  This is per runtime and never serialized.
- Install the std pack: `lmccstd.Install(reg)` gives `json`, `table`,
  `scaled_number`, the reasoning strategies, and `lens/json_object`.

`FormatSpec` builds a format from functions. Zero values mean: accepts
`*`, direction `both` (or `in` when `ReadFn` is nil), emits text,
round-trips, reads text. See `lmcc/frontend_test.go` for a media
format that writes an image part.

## Run the corpus driver

`cmd/lmcc-conform` speaks the harness's JSON Lines protocol (kernel
§9): one case per line in, one `{"ok", "detail"}` per line out.

```
cd go && go build -o bin/lmcc-conform ./cmd/lmcc-conform
cd ../python && PYTHONPATH=. python ../contract/harness/runner.py --driver ../go/bin/lmcc-conform
```

At kernel 0.2 (82 cases) this prints `76 passed, 0 failed, 6 unclaimed
(udf:python), 26 stream traces match the reference kernel`. The root
`./check` runs this as step 5.

## What "unclaimed" means

Six corpus cases ship a Python UDF and declare `"requires": ["udf:python"]`.
The Go kernel has no placer for Python code. For such a case the driver
answers `{"ok": true, "unclaimed": "udf:python"}`: it did not run the
case, and it says so. The harness counts these apart from passes. A
false pass is never reported.

The same rule holds at load time. With `Registry.AllowUDF` false, an
artifact that ships a UDF refuses `format-untrusted`. With it true, the
Go kernel verifies the hash and then refuses `udf-unplaceable`: the
code is admitted as data, but this host cannot run it. Bind a Go
format for that type instead.

## Where to read next

- [contract/spec/kernel.md](../contract/spec/kernel.md): the rules.
- [contract/spec/errors.md](../contract/spec/errors.md): every code and fix.
- [docs/reference/README.md](../docs/reference/README.md): the API index.
- [docs/howto/README.md](../docs/howto/README.md): task guides (Python).

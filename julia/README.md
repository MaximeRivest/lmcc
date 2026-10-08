# LMCC.jl — lmcc for Julia

The Julia kernel of **lmcc**, the calling convention for calling a model:
where each argument goes, how the result comes back, how each type crosses.
It passes the same contract corpus as the Python, TypeScript and R kernels,
byte for byte, and serializes the same data (artifacts, turns, plans,
readings): a record written by one is read identically by the others.

- **Standard library plus OrderedCollections**, the package LM15.jl already
  uses. lmcc never touches the network.
- **lm15 is optional.** With `using LM15`, the bridge extension adds
  `lm15_request`, `lm15_stream`, and methods of `LMCC.read`, `LMCC.parse`
  and `LMCC.step` that take lm15's `Response` and `Message`.

Every block below runs in the test suite (`julia --project -e 'using Pkg; Pkg.test()'`).

## A signature, an adapter, a plan

```julia
using LMCC

answer = signature("Answer the question in one sentence."; inputs=(question=String,), outputs=(answer=String,))

xml = adapter(; messages=[
    LMCC.system("{instruction}\n\nReply with exactly this pattern:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    turns(),
    LMCC.user("{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
])

plan = LMCC.bind(xml, answer; capabilities=Dict("instruct" => true))
r = render(plan, (question="Why is the sky blue?",))
@assert r.messages[1]["parts"][1]["text"] == "<question>\nWhy is the sky blue?\n</question>\n"

@assert LMCC.parse(plan, "<answer>\nRayleigh scattering.\n</answer>")["answer"] == "Rayleigh scattering."
```

Types lower mechanically: `String`, integers, floats, `Bool`, `@enum`s,
`Vector{T}`, `Union{T,Nothing}`, `NamedTuple`s, `Dict`s and plain structs.
`field(T; purpose="reasoning", desc="…")` adds a purpose or a description.
`signature_from_dict` loads the plain-data form every kernel shares.

## Streaming, repairs, refusals

```julia
s = stream(plan)
events = feed!(s, "<answer>\nRayleigh")
@assert events[2]["text"] == "Rayleigh"
feed!(s, " scattering.\n</answer>")
@assert finish!(s).values["answer"] == "Rayleigh scattering."

reading = LMCC.read(plan, "<Answer>\nRayleigh scattering.\n</Answer>")
@assert [x["saw"] for x in reading.repairs] == ["<Answer>", "</Answer>"]

err = try
    LMCC.parse(plan, "<answer>\none\n</answer>\n<answer>\ntwo\n</answer>")
catch e
    e
end
@assert err isa Refusal && err.code == "parse-ambiguous"
```

## Turns and artifacts

```julia
ex = example(plan, (question="Is water wet?",), (answer="Yes, to the touch.",))
@assert render(plan, (question="Why is grass green?",); turns=[ex]).messages[2]["parts"][1]["text"] == "<answer>\nYes, to the touch.\n</answer>"

turn = LMCC.step(r, "<answer>\nRayleigh scattering.\n</answer>")
@assert turn_to_dict(turn)["steps"][1]["outputs"]["answer"] == "Rayleigh scattering."
noted = with_meta(turn, Dict("source" => "rating"))

artifact = LMCC.dump(xml)
@assert LMCC.dump(load(parse_json(json_text(artifact)))) == artifact
```

## Tools, with the standard pack

```julia
reg = LMCC.Std.install!(Registry())
ask = signature("Answer, using tools when needed.";
    inputs=(question=String, tools=field(Dict("type" => "array", "items" => Dict("type" => "object")); purpose="tools", type="list[Tool]")),
    outputs=(calls=field(Dict("type" => "array", "items" => Dict("type" => "object")); purpose="tools.calls", type="list[ToolCall]"), answer=String))
tooled = adapter(; messages=[LMCC.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"), turns(), LMCC.user("{question}")],
    transports=Dict("tools" => "fenced_tools"), formats=Dict("list[Tool]" => Dict("use" => "function_tool"), "list[ToolCall]" => Dict("use" => "tool_calls")))
agent = LMCC.bind(tooled, ask; capabilities=Dict("instruct" => true), registry=reg)

t = new_turn(agent, (question="Weather in Paris?", tools=[Dict("name" => "get_weather")]))
t = LMCC.step(render(agent, t), "```tool\n{\"name\": \"get_weather\", \"input\": {\"city\": \"Paris\"}}\n```")
t = tool(t, "call_1", "Sunny, 22C")
@assert render(agent, t).messages[3]["parts"][1]["text"] == "Result of get_weather (call_1):\nSunny, 22C"
```

## Sending it with lm15

```julia
# using LM15
# req = lm15_request(r; model="claude-haiku-4-5", config=Config(; max_tokens=300))
# response = complete(LMRouter(), req); LMCC.read(plan, response); LMCC.step(r, response)
# events, result = lm15_stream(plan, LM15.stream(LMRouter(), req))
```

With LM15 loaded, its media parts are field types: `inputs=(picture=LM15.ImagePart,)`
is a `{"media": "image"}` field whose value is an lm15 part, written as
lm15's canonical part data (a path stays a path; lm15 reads the file), saved
by `dump_turn` and rebuilt by `load_turn`. Loading the extension binds the
five part types in the default registry; `lm15_install!(registry)` binds
them in your own.

## Where Julia differs, stated

The differential check (`python contract/harness/differential.py --probe
'julia --project=julia julia/tools/probe.jl'`) compares everything else on
every corpus case, 3,000 fuzzed replies and 88 variants with hostile member
names against Python, member order included.

- **Shipped code (UDF formats)**: this runtime places no UDF language; the six
  corpus cases that need `udf:python` are unclaimed. A format built from Julia
  functions binds at runtime (`bind_type!`); `LMCC.dump` refuses to ship it.
- **Type names**: the frontend writes Julia's (`String`, `Int64`,
  `Vector{String}`), so a signature built from Julia types and one built from
  Python annotations have different fingerprints. `signature_from_dict` never
  differs.
- **Values** are JSON: ordered `Dict`s, `Vector{Any}`, `nothing`; integers
  `Int64`, or `BigInt` beyond it. Nothing is lifted into structs, except a
  type bound with its JSON form: `bind_type!(reg, T; to_json, from_json)`
  (D-62), which `to_json`, `turn_to_dict` and `dump_turn(plan, turn)` write
  (found by `isa`, as Python finds it by class) and `load_turn` rebuilds.
  `bind_type!`'s `name` sets the type name a signature records, which
  `string(T)` otherwise spells by what the caller imported
  (`LM15.ImagePart` or `ImagePart`); the lm15 extension gives Python's.
- **A `Dict` has no order**: Julia's `Dict` iterates in hash order, and lmcc
  writes an object's members in the order the value holds them (kernel §1),
  so a `Dict` given as a value or a shape is written in hash order (a
  shape's `required` too). Where order shows, give an `OrderedDict` (`jobj`),
  a `NamedTuple`, or JSON read with `parse_json`; every object lmcc builds
  is ordered (the kernel builds no `Dict`; a unit test holds it). Python's `dict` keeps the order written.
- **Names** Julia's `Base` uses for something else (`bind`, `parse`, `read`,
  `step`, `dump`) are `LMCC.`-qualified.
- **Regex (`pattern/legacy-re2`)**: bound to Julia's PCRE2 with DOTALL (label
  `julia:PCRE2`); what the contract leaves unspecified may differ.
- **Hints** name Julia APIs; codes, fixes and partials are identical.

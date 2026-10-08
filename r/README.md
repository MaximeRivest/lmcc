# lmcc for R

The R kernel of **lmcc**, the calling convention for calling a model: where
each argument goes, how the result comes back, how each type crosses. It
passes the same contract corpus as the Python, TypeScript and Julia kernels,
byte for byte, and serializes the same data (artifacts, turns, plans,
readings): a record written by one is read identically by the others.

- **Base R and a little C.** No package dependencies. The C is what base R
  cannot do exactly: read a decimal as the nearest double (R's `as.numeric`
  is not correctly rounded), spell a double in its shortest form, SHA-256.
- **lmcc never touches the network.** With the `lm15` package installed,
  `lm15_request()`, `lm15_read()`, `lm15_step()` and `lm15_stream()` send
  and read through lm15 for R.

Every block below runs in the test suite (`testthat`).

## A signature, an adapter, a plan

```r
library(lmcc)

answer <- lmcc_signature("Answer the question in one sentence.",
                         inputs = list(question = shape_string()), outputs = list(answer = shape_string()))

xml <- adapter(list(
  system_msg("{instruction}\n\nReply with exactly this pattern:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
  turns_slot(),
  user_msg("{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}")))

plan <- lmcc_bind(xml, answer, list(instruct = TRUE))
r <- render(plan, list(question = "Why is the sky blue?"))
stopifnot(r$messages[[1]]$parts[[1]]$text == "<question>\nWhy is the sky blue?\n</question>\n")
stopifnot(parse_reply(plan, "<answer>\nRayleigh scattering.\n</answer>")$answer == "Rayleigh scattering.")
```

Shapes come from `shape_string()`, `shape_integer()`, `shape_number()`,
`shape_boolean()`, `shape_enum()`, `shape_nullable()`, `shape_list()`,
`shape_object()`, `shape_media()`; `field_spec()` adds a purpose, a
description or a type name. `signature_from_list()` loads the plain-data
form every kernel shares.

## Streaming, repairs, refusals

```r
s <- reply_stream(plan)
events <- feed(s, "<answer>\nRayleigh")
stopifnot(events[[2]]$text == "Rayleigh")
feed(s, " scattering.\n</answer>")
stopifnot(finish(s)$values$answer == "Rayleigh scattering.")

reading <- read_reply(plan, "<Answer>\nRayleigh scattering.\n</Answer>")
stopifnot(identical(vapply(reading$repairs, function(x) x$saw, ""), c("<Answer>", "</Answer>")))

code <- tryCatch(parse_reply(plan, "<answer>\none\n</answer>\n<answer>\ntwo\n</answer>"), lmcc_refusal = function(e) e$code)
stopifnot(code == "parse-ambiguous")
```

## Turns and artifacts

```r
ex <- example_turn(plan, list(question = "Is water wet?"), list(answer = "Yes, to the touch."))
stopifnot(render(plan, list(question = "Why is grass green?"), list(ex))$messages[[2]]$parts[[1]]$text == "<answer>\nYes, to the touch.\n</answer>")

turn <- record_step(r, "<answer>\nRayleigh scattering.\n</answer>")
stopifnot(turn_to_list(turn)$steps[[1]]$outputs$answer == "Rayleigh scattering.")
noted <- with_meta(turn, list(source = "rating"))

artifact <- dump_adapter(xml)
stopifnot(identical(json_text(dump_adapter(load_adapter(parse_json(json_text(artifact))))), json_text(artifact)))
```

## Tools, with the standard pack

```r
reg <- lmcc_registry(); install_std(reg)
ask <- lmcc_signature("Answer, using tools when needed.",
  inputs = list(question = shape_string(), tools = field_spec(shape_list(shape_object()), purpose = "tools", type = "list[Tool]")),
  outputs = list(calls = field_spec(shape_list(shape_object()), purpose = "tools.calls", type = "list[ToolCall]"), answer = shape_string()))
tooled <- adapter(list(system_msg("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"), turns_slot(), user_msg("{question}")),
  transports = list(tools = "fenced_tools"), formats = list(`list[Tool]` = use_vocab("function_tool"), `list[ToolCall]` = use_vocab("tool_calls")))
agent <- lmcc_bind(tooled, ask, list(instruct = TRUE), reg)

t <- new_turn(agent, list(question = "Weather in Paris?", tools = list(list(name = "get_weather"))))
t <- record_step(render(agent, t), "```tool\n{\"name\": \"get_weather\", \"input\": {\"city\": \"Paris\"}}\n```")
t <- tool_result(t, "call_1", "Sunny, 22C")
stopifnot(render(agent, t)$messages[[3]]$parts[[1]]$text == "Result of get_weather (call_1):\nSunny, 22C")
```

## Transports with helpers

`find_between()`, `find_lines()`, `find_pattern()`, `find_part()`, `put_*()`,
`when_*()` and `choose_transport()` return the plain data you could write
by hand, the same as Python's `lmcc.find`/`put`/`when`/`choose`:

```r
think_aloud <- new_transport(when = when_lacks("native_reasoning"), in_template = FALSE,
  tell = jobj(system = "Wrap every thought in <think>...</think>."),
  find = list(find_between("<think>", "</think>", remove = TRUE, repair = TRUE)))
reasoning <- choose_transport(list(when = when_has("native_reasoning"), use = "native_reasoning"),
                              otherwise = think_aloud, registry = reg)
stopifnot(length(reasoning$choose) == 2L)
```

## Sending it with lm15

```r
# library(lm15)
# router <- new_router(env = unclass(Sys.getenv()))   # see below
# response <- complete(router, lm15_request(r, "claude-haiku-4-5", lm15::config(max_tokens = 300)))
# lm15_read(plan, response); lm15_step(r, response)
# lm15_stream(plan, router, lm15_request(r, "claude-haiku-4-5"), on_event = print)
```

lm15's media parts are field types: `inputs = list(picture = lm15_media("image"))`
is a `{"media": "image"}` field typed `ImagePart`, whose value is an lm15
part (`lm15::image_part(path = "cat.png")`), written as lm15's canonical
part data (a path stays a path; lm15 reads the file), saved by
`dump_turn(plan, turn)` and rebuilt by `load_turn()`. The default registry
has the five part types; `lm15_install(registry)` binds them in your own.

lm15 for R 1.0.0's `new_router()` rejects every API key from its default
environment lookup (the values keep the `Dlist` class its key check
refuses); pass `env = unclass(Sys.getenv())` until lm15 fixes it.

## Where R differs, stated

The differential check (`python contract/harness/differential.py --probe
'Rscript r/tools/probe.R'`) compares everything else on every corpus case,
3,000 fuzzed replies and 88 variants with hostile member names against
Python, member order included.

- **Shipped code (UDF formats)**: this runtime places no UDF language; the six
  corpus cases that need `udf:python` are unclaimed. A format built from R
  functions binds at runtime (`bind_type()`); `dump_adapter()` refuses to ship it.
- **A type's JSON form** (`bind_type(reg, "Pages", to_json =, from_json =)`,
  D-62) is found by the field's type name, as a format binding is. So a turn
  is saved with `dump_turn(plan, turn)`, which knows each value's field;
  `turn_to_list(turn)` writes values as they are. Python finds the binding
  by the value's class, so there `turn.to_dict()` applies it too.
- **Numbers**: R has no 64-bit integer. Integers are `integer` within 32 bits,
  whole doubles up to 2^53, and beyond that exact `lmcc_int` decimal text. An
  integer field accepts a whole double (`3`, R's usual literal); Python
  refuses a float there.
- **JSON in R**: an object is a named list (use `jobj()` for an empty one), an
  array an unnamed list (`jarr()`), null is `NULL`. A vector of length other
  than one is not a JSON value: use a list. R strings cannot hold U+0000, so a
  reply containing it cannot be represented.
- **A member named `""`**: any string is a member name (kernel section 1),
  and lmcc finds and writes one by position. Your own code reading what lmcc
  returns cannot use `x[[""]]` (always `NULL`) or `x[[""]] <- v` (appends a
  second member); use `x[names(x) == ""]` or `match("", names(x))`. And `$`
  completes a partial name on a list: `reading$values$na` returns a member
  `"name"` when there is no `"na"`; use `[["na"]]`, which matches exactly
  (lmcc's own driver and probe run with R's partial-match warnings as
  errors).
- **`choose_transport()`** is Python's `lmcc.choose`: R's own `choose()` is
  the binomial coefficient, which lmcc does not mask.
- **Type names**: the builders name no type unless given `type =`; a
  signature from `signature_from_list()` is identical in every kernel.
- **Names** that R's base packages use (`parse`, `load`, `system`, `step`) are
  `parse_reply()`, `load_adapter()`, `system_msg()`, `record_step()`.
- **Regex (`pattern/legacy-re2`)**: bound to R's PCRE2 with DOTALL (label
  `r:PCRE2`); what the contract leaves unspecified may differ.
- **Hints** name R APIs, and their quoting of rare non-ASCII characters is an
  approximation of Python's `repr`; codes, fixes and partials are identical.

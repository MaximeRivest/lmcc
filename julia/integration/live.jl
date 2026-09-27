# The Julia kernel against real models, through LM15.jl. Costs money: not
# part of ./check. Run by hand from the repository root:
#
#     set -a; source ~/Projects/lm15-dev/.env; set +a
#     julia julia/integration/live.jl       # writes julia/integration/live-record.json
#     python contract/harness/replay_live.py julia/integration/live-record.json
#
# Every exchange is recorded (the artifact, signature, capabilities, the turn
# rendered, the request sent, lm15's response, the turn recorded) so the
# Python kernel can re-render and re-read each one.

import Pkg
Pkg.activate(; temp=true, io=devnull)
Pkg.develop([Pkg.PackageSpec(path=joinpath(@__DIR__, "..")), Pkg.PackageSpec(path=expanduser("~/Projects/lm15-dev/lm15-jl"))]; io=devnull)

using LMCC, LM15
using LMCC: JObj, jobj, Std, json_text

const reg = Std.install!(Registry())
const router = LMRouter()
const record = Any[]
const results = Any[]

const TAGS = "Reply with exactly this pattern and nothing else:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"
const sections = adapter(; name="sections", messages=[LMCC.system("{instruction}\n\n" * TAGS), turns(), LMCC.user("{question}")])
const quiz = LMCC.signature("Answer the question. The score is how sure you are, from 1 to 10."; inputs=(question=String,), outputs=(answer=String, score=Int))

exchange(r, model, response, turn) = jobj("current" => turn_to_dict(r.turn), "request" => LMCC.request(r, model),
    "response" => LM15.to_dict(response), "turn" => turn === nothing ? nothing : turn_to_dict(turn))
save(name, a, sig, caps, exchanges) = push!(record, jobj("name" => name, "entry" => LMCC.dump(a; registry=reg),
    "signature" => signature_to_dict(sig), "capabilities" => caps, "vocab" => Any["std"], "exchanges" => exchanges))

function attempt(f, name, model)
    line = try
        "ok  " * f()
    catch err
        "FAIL " * first(sprint(showerror, err), 200)
    end
    push!(results, (name, model, line))
    println(rpad(name, 14), rpad(model, 30), line)
end

cfg(n) = Config(; max_tokens=n)

# 1. The same program on several providers; batch and stream must agree.
for (model, caps) in [("gpt-4.1-mini", jobj("instruct" => true, "stop_sequences" => true)),
                      ("claude-haiku-4-5", jobj("instruct" => true, "stop_sequences" => true)),
                      ("gemini:gemini-2.5-flash", jobj("instruct" => true)),
                      ("groq:openai/gpt-oss-20b", jobj("instruct" => true)),
                      ("deepseek:deepseek-chat", jobj("instruct" => true))]
    attempt("sections", model) do
        plan = LMCC.bind(sections, quiz; capabilities=caps, registry=reg)
        r = render(plan, (question="What is the capital of Australia?",))
        response = complete(router, lm15_request(r; model=model, config=cfg(300)))
        reading = LMCC.read(plan, response)
        turn = LMCC.step(r, response)
        events, streamed = lm15_stream(plan, LM15.stream(router, lm15_request(r; model=model, config=cfg(300))))
        reading.values["score"] isa Integer || error("score is $(typeof(reading.values["score"]))")
        save("sections/$model", sections, quiz, caps, Any[exchange(r, model, response, turn)])
        "answer=$(repr(reading.values["answer"])) score=$(reading.values["score"]) repairs=$(length(reading.repairs)) | stream answer=$(repr(streamed.values["answer"])) ($(count(e -> e["kind"] == "field_delta", events)) deltas)"
    end
end

# 2. One tool program, native and text tiers; the caller runs the loop (§6).
const ask = LMCC.signature("Answer the question. Use a tool when you need facts you do not have.";
    inputs=(question=String, tools=field(Dict("type" => "array", "items" => Dict("type" => "object")); purpose="tools", type="list[Tool]")),
    outputs=(calls=field(Dict("type" => "array", "items" => Dict("type" => "object")); purpose="tools.calls", type="list[ToolCall]"), answer=String))
const WEATHER = jobj("name" => "get_weather", "description" => "Current weather for a city.",
    "parameters" => jobj("type" => "object", "properties" => jobj("city" => jobj("type" => "string")), "required" => Any["city"]))

function tool_loop(transport, model, caps)
    a = adapter(; name="tools_$transport",
        messages=[LMCC.system("{instruction}\n\nReply with exactly this pattern and nothing else, also after a tool result:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"), turns(), LMCC.user("{question}")],
        transports=Dict("tools" => transport), formats=Dict("list[Tool]" => Dict("use" => "function_tool"), "list[ToolCall]" => Dict("use" => "tool_calls")))
    plan = LMCC.bind(a, ask; capabilities=caps, registry=reg)
    turn = new_turn(plan, (question="What is the weather in Montreal right now?", tools=Any[WEATHER]))
    exchanges = Any[]
    for round in 1:4
        r = render(plan, turn)
        response = complete(router, lm15_request(r; model=model, config=cfg(400)))
        turn = LMCC.step(r, response)
        push!(exchanges, exchange(r, model, response, turn))
        calls = something(get(turn.steps[end].outputs, "calls", nothing), Any[])
        if isempty(calls)
            turn = finish(turn)
            save("tools/$transport/$model", a, ask, caps, exchanges)
            return "$round model calls, answer=$(repr(first(string(turn.outputs["answer"]), 60)))"
        end
        for c in calls
            turn = tool(turn, c["id"], "Sunny and 22°C in $(c["input"]["city"]).")
        end
    end
    error("no answer after 4 rounds")
end

attempt(() -> tool_loop("native_tools", "gpt-4.1-mini", jobj("instruct" => true, "native_function_calling" => true)), "tools/native", "gpt-4.1-mini")
attempt(() -> tool_loop("native_tools", "claude-haiku-4-5", jobj("instruct" => true, "native_function_calling" => true)), "tools/native", "claude-haiku-4-5")
attempt(() -> tool_loop("fenced_tools", "deepseek:deepseek-chat", jobj("instruct" => true)), "tools/fenced", "deepseek:deepseek-chat")
attempt(() -> tool_loop("fenced_tools", "claude-haiku-4-5", jobj("instruct" => true)), "tools/fenced", "claude-haiku-4-5")

# 3. Reasoning: the transport chosen by the model's declared facts.
const solve = LMCC.signature("Solve the problem."; inputs=(problem=String,), outputs=(reasoning=field(String; purpose="reasoning"), answer=Int))
const thinking = adapter(; name="thinking", messages=[LMCC.system("{instruction}\n\n" * TAGS), LMCC.user("{problem}")],
    transports=Dict("reasoning" => choose(when_has("native_reasoning") => Std.native_reasoning(Dict("effort" => "low")); otherwise=Std.reasoning_tags(Dict()), registry=reg)))
for (model, caps) in [("claude-haiku-4-5", jobj("instruct" => true, "native_reasoning" => true)),
                      ("gemini:gemini-2.5-flash", jobj("instruct" => true, "native_reasoning" => true)),
                      ("gpt-4.1-mini", jobj("instruct" => true))]
    attempt("reasoning", model) do
        plan = LMCC.bind(thinking, solve; capabilities=caps, registry=reg)
        r = render(plan, (problem="A train leaves at 9:40 and arrives at 13:05. How many minutes is the trip?",))
        response = complete(router, lm15_request(r; model=model, config=cfg(4000)))
        values = LMCC.parse(plan, response)
        save("reasoning/$model", thinking, solve, caps, Any[exchange(r, model, response, LMCC.step(r, response))])
        values["answer"] == 205 || error("answer $(values["answer"])")
        "answer=205 via $(join([rr["from"] for (_, rr) in plan.find_rules], ",")), reasoning $(length(string(values["reasoning"]))) chars"
    end
end

# 4. The JSON reader, on a provider that enforces the schema.
const sentiment = LMCC.signature("Classify the review."; inputs=(review=String,),
    outputs=(label=field(Dict("enum" => ["positive", "negative", "mixed"], "type" => "string"); desc="the review's overall sentiment"), stars=Int))
const json_adapter = adapter(; name="json", messages=[LMCC.system("{instruction}"), LMCC.user("{review}")], reader=Dict("kind" => "json_object"))
attempt("json_object", "gpt-4.1-mini") do
    caps = jobj("instruct" => true, "native_structured_output" => true)
    plan = LMCC.bind(json_adapter, sentiment; capabilities=caps, registry=reg)
    r = render(plan, (review="Great battery, awful screen. Three stars.",))
    response = complete(router, lm15_request(r; model="gpt-4.1-mini", config=cfg(200)))
    v = LMCC.parse(plan, response)
    save("json_object/gpt-4.1-mini", json_adapter, sentiment, caps, Any[exchange(r, "gpt-4.1-mini", response, LMCC.step(r, response))])
    "label=$(v["label"]) stars=$(v["stars"])"
end

# 5. The prefill (§3), sent only to a model that continues one.
const prefilled = adapter(; name="prefilled", messages=[LMCC.system("{instruction}\n\n" * TAGS), LMCC.user("{question}"), LMCC.assistant("<answer>\n")])
attempt("prefill", "claude-haiku-4-5") do
    caps = jobj("instruct" => true, "assistant_prefill" => true, "stop_sequences" => true)
    plan = LMCC.bind(prefilled, quiz; capabilities=caps, registry=reg)
    r = render(plan, (question="What is 17 times 3?",))
    response = complete(router, lm15_request(r; model="claude-haiku-4-5", config=cfg(200)))
    v = LMCC.parse(plan, response)
    save("prefill/claude-haiku-4-5", prefilled, quiz, caps, Any[exchange(r, "claude-haiku-4-5", response, LMCC.step(r, response))])
    "answer=$(repr(v["answer"])) score=$(v["score"])"
end

# 6. Truncation (§4a): a reply cut at its length limit never reads as finished.
attempt("truncated", "gpt-4.1-mini") do
    caps = jobj("instruct" => true)
    plan = LMCC.bind(sections, quiz; capabilities=caps, registry=reg)
    r = render(plan, (question="Explain photosynthesis in detail.",))
    response = complete(router, lm15_request(r; model="gpt-4.1-mini", config=cfg(16)))
    save("truncated/gpt-4.1-mini", sections, quiz, caps, Any[exchange(r, "gpt-4.1-mini", response, nothing)])
    try
        LMCC.parse(plan, response)
    catch err
        err isa Refusal && err.code == "parse-truncated" && return "refused parse-truncated (finish_reason=$(response.finish_reason))"
        rethrow()
    end
    error("a cut reply was read as finished")
end

write(joinpath(@__DIR__, "live-record.json"), json_text(record; spaced=true) * "\n")
failed = count(r -> startswith(r[3], "FAIL"), results)
println("\n$(length(results) - failed) of $(length(results)) live scenarios ok; $(length(record)) recorded for the Python replay")

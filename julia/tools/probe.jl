# Observations of the Julia kernel on each case, for the differential check
# against the Python reference (contract/harness/differential.py): describe,
# dump, fingerprints, request hashes, readings, turns, stream results, refusals.
#
#     julia --project=julia julia/tools/probe.jl < cases.jsonl

using LMCC
using LMCC: JObj, jobj, isobj, parse_json, json_text, Std

refusal(err) = err isa Refusal ? jobj("code" => err.code, "fix" => err.fix, "partial" => err.partial, "hint" => err.hint) : rethrow(err)
function attempt(f)
    try
        jobj("ok" => f())
    catch err
        err isa Refusal || rethrow()
        jobj("refused" => refusal(err))
    end
end

function observe(c)
    req = String[r for r in get(c, "requires", Any[])]
    any(r -> startswith(r, "udf:"), req) && return jobj("skipped" => "udf")
    reg = Registry(; extensions=req)
    "std" in get(c, "vocab", Any[]) && Std.install!(reg)
    out = JObj()
    a = try
        load(c["entry"]; registry=reg)
    catch err
        err isa Refusal || rethrow()
        return jobj("load" => jobj("refused" => refusal(err)))
    end
    out["dump"] = attempt(() -> LMCC.dump(a; registry=reg))
    LMCC.pytruthy(get(c, "signature", nothing)) || return out
    sig = try
        signature_from_dict(c["signature"])
    catch err
        err isa Refusal || rethrow()
        out["signature"] = jobj("refused" => refusal(err))
        return out
    end
    out["fingerprint"] = signature_fingerprint(sig)
    out["signature_dict"] = signature_to_dict(sig)
    plan = try
        LMCC.bind(a, sig; capabilities=get(c, "capabilities", JObj()), registry=reg)
    catch err
        err isa Refusal || rethrow()
        out["bind"] = jobj("refused" => refusal(err))
        return out
    end
    out["describe"] = describe(plan)
    fp = signature_fingerprint(sig)
    slots = JObj(n => Any[merge(jobj("signature" => fp), t) for t in ts] for (n, ts) in get(c, "turns", JObj()))
    out["prefix"] = attempt(() -> prefix(plan; turns=slots))
    out["skeleton"] = skeleton(plan)
    if haskey(c, "inputs")
        current = jobj("signature" => fp, "inputs" => c["inputs"], "steps" => get(c, "steps", Any[]))
        out["turn_json"] = attempt(() -> turn_to_dict(turn_from_dict(current)))
        out["slot_json"] = attempt(() -> JObj(k => Any[turn_to_dict(turn_from_dict(t)) for t in ts] for (k, ts) in slots))
        out["render"] = attempt(() -> begin
            r = render(plan, turn_from_dict(current); turns=slots)
            jobj("request" => request(r, "m"), "hash" => sha256_of(request(r)))
        end)
    end
    if haskey(c, "response")
        resp = c["response"]
        out["read"] = attempt(() -> LMCC.reading_to_dict(LMCC.read(plan, resp)))
        out["step"] = attempt(() -> LMCC.step_to_dict(ModelStep(LMCC.parse(plan, resp), LMCC.as_message(resp), sha256_of(jobj("messages" => Any[])), plan.calls_field)))
        out["stream"] = attempt(() -> begin
            s = stream(plan)
            events = JObj[]
            parts = resp isa AbstractString ? Any[resp] : (isobj(get(resp, "message", nothing)) ? resp["message"] : resp)["parts"]
            for p in parts
                append!(events, feed!(s, p))
            end
            reason = isobj(resp) && haskey(resp, "message") ? get(resp, "finish_reason", nothing) : nothing
            e = finish!(s, reason)
            jobj("events" => vcat(events, e.events), "result" => jobj("events" => e.events, "values" => e.values, "repairs" => e.repairs,
                "probabilities" => e.probabilities, "measured_by" => e.measured_by))
        end)
    end
    out
end

for line in eachline(stdin)
    isempty(strip(line)) && continue
    answer = try
        observe(parse_json(line))
    catch err
        jobj("crash" => sprint(showerror, err) * "\n" * sprint(Base.show_backtrace, catch_backtrace()))
    end
    println(stdout, json_text(answer))
end

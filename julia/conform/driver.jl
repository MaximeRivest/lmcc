# The Julia kernel behind the harness's driver protocol (kernel §9):
#
#     cd python && python ../contract/harness/runner.py --driver 'julia --project=../julia ../julia/conform/driver.jl'
#
# One case per line on stdin, one {ok, detail?, unclaimed?, stream_trace?} per
# line on stdout. The same stages and stream replays as the reference driver:
# whole, one scalar at a time, every split of text and of each text-bearing
# part, and the one-scalar event trace the harness compares with Python's.

using LMCC
using LMCC: JObj, jobj, isobj, isarr, json_equal, json_text, parse_json, Std

function case_turns(c)
    fp = signature_fingerprint(signature_from_dict(c["signature"]))
    current = jobj("signature" => fp, "inputs" => get(c, "inputs", JObj()), "steps" => get(c, "steps", Any[]))
    slots = JObj(name => Any[merge(jobj("signature" => fp), t) for t in ts] for (name, ts) in get(c, "turns", JObj()))
    (current, slots)
end

function registry_for(c)
    req = String[r for r in get(c, "requires", Any[])]
    reg = Registry(; allow_udf="udf:python" in req, extensions=[r for r in req if !startswith(r, "udf:")])
    "std" in get(c, "vocab", Any[]) && Std.install!(reg)
    reg
end

function unclaimed_of(c)
    native = Set(LMCC.ext_name(b) for b in native_extensions())
    for r in get(c, "requires", Any[])
        startswith(r, "udf:") && return r          # this runtime places no UDF language
        r in native || return r
    end
    nothing
end

ok() = jobj("ok" => true, "detail" => "")
# Whether every object lists its members in the same order (kernel §1), recursively.
function same_order(a, b)
    if isobj(a) && isobj(b)
        collect(keys(a)) == collect(keys(b)) || return false
        return all(same_order(a[k], b[k]) for k in keys(a))
    end
    isarr(a) && isarr(b) && length(a) == length(b) && return all(same_order(x, y) for (x, y) in zip(a, b))
    true
end
function compare(expected, got, what, ordered=false)
    json_equal(expected, got) || return jobj("ok" => false, "detail" => "$what mismatch\n--- expected\n$(json_text(expected; spaced=true))\n--- got\n$(json_text(got; spaced=true))")
    ordered && !same_order(expected, got) && return jobj("ok" => false,
        "detail" => "$what: member order differs (the case is ordered, kernel §9)\n--- expected\n$(json_text(expected; spaced=true))\n--- got\n$(json_text(got; spaced=true))")
    ok()
end

message_parts(r) = (m = (isobj(r) && isobj(get(r, "message", nothing))) ? r["message"] : r; isobj(m) && isarr(get(m, "parts", nothing)) ? m["parts"] : Any[])
finish_reason_of(r) = (isobj(r) && isobj(get(r, "message", nothing))) ? get(r, "finish_reason", nothing) : nothing

function chunkings(response)
    if response isa AbstractString
        chars = collect(response)
        out = Any[Any[response], Any[string(ch) for ch in chars]]
        offs = [0; cumsum([ncodeunits(string(ch)) for ch in chars])]
        for o in offs
            push!(out, Any[LMCC.bsl(response, 0, o), LMCC.bsl(response, o)])
        end
        return out
    end
    parts = message_parts(response)
    out = Any[Any[parts...]]
    for (pi, part) in enumerate(parts)
        t = isobj(part) ? get(part, "text", nothing) : nothing
        t isa AbstractString || continue
        chars = collect(t)
        each = Any[merge(copy(part), jobj("text" => string(ch))) for ch in chars]
        isempty(each) && (each = Any[copy(part)])
        push!(out, vcat(parts[1:pi-1], each, parts[pi+1:end]))
        for o in [0; cumsum([ncodeunits(string(ch)) for ch in chars])]
            push!(out, vcat(parts[1:pi-1], Any[merge(copy(part), jobj("text" => LMCC.bsl(t, 0, o))), merge(copy(part), jobj("text" => LMCC.bsl(t, o)))], parts[pi+1:end]))
        end
    end
    out
end

function feed_chunk(plan, s, response, chunk)
    # a string inside a part list is not a text delta: check its list boundary first
    !(response isa AbstractString) && chunk isa AbstractString && LMCC.parse(plan, jobj("role" => "assistant", "parts" => Any[chunk]))
    feed!(s, chunk)
end

function delta_text(events)
    out = JObj()
    for e in events
        e["kind"] == "field_delta" && (out[e["field"]] = get(out, e["field"], "") * e["text"])
    end
    out
end

function check_stream_success(plan, response, reading, raw)
    baseline = nothing
    for (n, chunks) in enumerate(chunkings(response))
        s = stream(plan)
        events = JObj[]
        result = try
            for ch in chunks
                append!(events, feed_chunk(plan, s, response, ch))
            end
            r = finish!(s, finish_reason_of(response))
            append!(events, r.events)
            r
        catch err
            return jobj("ok" => false, "detail" => "stream split $(n-1) refused/failed: $(sprint(showerror, err))")
        end
        for (a, b, what) in ((reading.values, result.values, "values"), (reading.repairs, result.repairs, "repairs"),
                             (reading.probabilities, result.probabilities, "probabilities"), (reading.measured_by, result.measured_by, "measured_by"))
            json_equal(a, b) || return compare(a, b, "stream split $(n-1) $what")
        end
        d = delta_text(events)
        json_equal(d, raw) || return compare(raw, d, "stream split $(n-1) deltas against batch raw text")
        baseline === nothing ? (baseline = d) : (json_equal(d, baseline) || return compare(baseline, d, "stream split $(n-1) field deltas"))
    end
    ok()
end

function check_stream_refusal(plan, response, batch::Refusal)
    expected = LMCC.describe(batch)
    for (n, chunks) in enumerate(chunkings(response))
        s = stream(plan)
        try
            for ch in chunks
                feed_chunk(plan, s, response, ch)
            end
            finish!(s, finish_reason_of(response))
        catch err
            if err isa Refusal
                json_equal(LMCC.describe(err), expected) && continue
                return compare(expected, LMCC.describe(err), "stream split $(n-1) refusal")
            end
            return jobj("ok" => false, "detail" => "stream split $(n-1) failed outside Refusal: $(sprint(showerror, err))")
        end
        return jobj("ok" => false, "detail" => "stream split $(n-1): expected refusal [$(batch.code)]")
    end
    ok()
end

function trace_chunking(response)
    response isa AbstractString && return Any[string(c) for c in response]
    out = Any[]
    for part in message_parts(response)
        t = isobj(part) ? get(part, "text", nothing) : nothing
        if t isa AbstractString && !isempty(t)
            append!(out, [merge(copy(part), jobj("text" => string(c))) for c in t])
        else
            push!(out, part)
        end
    end
    out
end

digest(e) = e["kind"] == "field_delta" ? Any[e["kind"], e["field"], e["text"]] : Any[e["kind"], e["field"]]

function stream_trace(plan, response)
    s = stream(plan)
    trace = Any[]
    try
        for ch in trace_chunking(response)
            push!(trace, Any[digest(e) for e in feed_chunk(plan, s, response, ch)])
        end
        push!(trace, Any[digest(e) for e in finish!(s, finish_reason_of(response)).events])
    catch err
        err isa Refusal || rethrow()
        push!(trace, jobj("refusal" => err.code))
    end
    trace
end

function run_case(c)
    expect = c["expect"]
    kind = c["kind"]
    ordered = get(c, "ordered", false) === true
    u = unclaimed_of(c)
    u === nothing || return jobj("ok" => true, "detail" => "", "unclaimed" => u)
    reg = registry_for(c)
    stage = "load"
    plan = nothing
    try
        a = load(c["entry"]; registry=reg)
        kind == "roundtrip" && return compare(expect["entry"], LMCC.dump(a; registry=reg), "entry", ordered)
        stage = "signature"
        sig = signature_from_dict(c["signature"])
        stage = "bind"
        plan = LMCC.bind(a, sig; capabilities=get(c, "capabilities", JObj()), registry=reg)
        if kind == "plan"
            _, slots = case_turns(c)
            return compare(jobj("skeleton" => expect["skeleton"], "prefix" => expect["prefix"]), jobj("skeleton" => skeleton(plan), "prefix" => prefix(plan; turns=slots)), "plan", ordered)
        end
        if kind == "render"
            current, slots = case_turns(c)
            return compare(expect["request"], request(render(plan, turn_from_dict(current); turns=slots)), "request", ordered)
        end
        if kind == "parse"
            reading = LMCC.read(plan, c["response"])
            r = compare(expect["values"], reading.values, "values", ordered)
            r["ok"] || return r
            for (key, got) in (("repairs", reading.repairs), ("probabilities", reading.probabilities), ("measured_by", reading.measured_by))
                haskey(expect, key) || continue
                r = compare(expect[key], got, key, ordered)
                r["ok"] || return r
            end
            _, captures, _ = LMCC.parse_with_captures(plan, c["response"])
            raw = JObj(n => text(cap) for (n, cap) in captures if !isempty(text(cap)))
            result = check_stream_success(plan, c["response"], reading, raw)
            result["ok"] && (result["stream_trace"] = stream_trace(plan, c["response"]))
            return result
        end
        if kind == "refuse"
            if haskey(c, "inputs")
                stage = "render"
                current, slots = case_turns(c)
                render(plan, turn_from_dict(current); turns=slots)
            end
            if haskey(c, "response")
                stage = "parse"
                LMCC.parse(plan, c["response"])
            end
            return jobj("ok" => false, "detail" => "expected refusal '$(expect["code"])', but nothing refused")
        end
        return jobj("ok" => false, "detail" => "unknown case kind '$kind'")
    catch err
        err isa Refusal || return jobj("ok" => false, "detail" => "host error at $stage: $(sprint(showerror, err))\n$(sprint(Base.show_backtrace, catch_backtrace()))")
        if kind == "refuse" && err.code == expect["code"] && haskey(expect, "at") && stage != expect["at"]
            return jobj("ok" => false, "detail" => "refusal [$(err.code)] fired at $stage, the case says $(expect["at"])")
        end
        if kind == "refuse" && err.code == expect["code"]
            if haskey(expect, "fix")
                r = compare(expect["fix"], err.fix, "fix of [$(err.code)]", ordered)
                r["ok"] || return r
            end
            if get(expect, "at", nothing) == "parse" && haskey(c, "response") && plan !== nothing
                r = check_stream_refusal(plan, c["response"], err)
                r["ok"] && (r["stream_trace"] = stream_trace(plan, c["response"]))
                return r
            end
            return ok()
        end
        return jobj("ok" => false, "detail" => "unexpected refusal [$(err.code)]: $(err.hint)")
    end
end

function main()
    for line in eachline(stdin)
        isempty(strip(line)) && continue
        answer = try
            run_case(parse_json(line))
        catch err
            jobj("ok" => false, "detail" => "driver error: $(sprint(showerror, err))\n$(sprint(Base.show_backtrace, catch_backtrace()))")
        end
        println(stdout, json_text(answer))
        flush(stdout)
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end

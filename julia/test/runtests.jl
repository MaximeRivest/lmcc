# Unit tests for what the corpus and the differential check do not reach:
# the README runs, the Julia frontend lowers types, streaming refines batch
# under random multi-chunk splits of corpus and mutated replies, per-feed
# cost stays linear, text rules and hashes hold, host differences are the
# stated ones.

using Test, LMCC, Random
using LMCC: JObj, jobj, json_text, parse_json, Std, format_number, sha256_hex, pyrepr

const ROOT = dirname(dirname(@__DIR__))

@testset "README runs" begin
    text = read(joinpath(@__DIR__, "..", "README.md"), String)
    code = join((m.captures[1] for m in eachmatch(r"^```julia\n(.*?)^```$"ms, text)), "\n")
    mod = Module()
    Core.eval(mod, :(using LMCC))
    include_string(mod, code, "README.md")
    @test true
end

@testset "text rules" begin
    @test [format_number(x) for x in (3.0, 1e21, 1e-7, 0.000001, -0.0, 123456789012345680000.0)] == ["3", "1e+21", "1e-7", "0.000001", "0", "123456789012345680000"]
    @test parse_json("9007199254740993") == big"9007199254740993"
    @test parse_json("1.00000000000000011102230246251565404236316680908203125") == 1.0
    @test isinf(parse_json("1e400")) && parse_json("1e-400") == 0.0
    @test_throws Exception parse_json("{\"a\": 1, \"a\": 2}"; duplicates=:reject)
    @test json_text(Dict("\uffff" => 1, "\U1f600" => 2, "b" => 1.0, "a" => Any[1e-7, "é\n"]); sort_keys=true) == "{\"a\":[1e-7,\"é\\n\"],\"b\":1,\"\uffff\":1,\"\U1f600\":2}"
    @test pyrepr("it's") == "\"it's\"" && pyrepr(Any["a", nothing, true, 1.5, 1e-7]) == "['a', None, True, 1.5, 1e-07]"
    @test sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
end

@enum Mood happy sad
struct Person
    name::String
    age::Int
end

@testset "the Julia frontend" begin
    sig = signature("Describe."; inputs=(who=Person, mood=Union{Mood,Nothing}), outputs=(tags=Vector{String}, ok=Bool))
    d = signature_to_dict(sig)
    @test d["fields"][1]["shape"] == Dict("type" => "object", "properties" => Dict("name" => Dict("type" => "string"), "age" => Dict("type" => "integer")), "required" => ["name", "age"])
    @test d["fields"][2]["shape"]["anyOf"][1] == Dict("enum" => ["happy", "sad"], "type" => "string")
    @test d["fields"][1]["type"] == "Person"
    @test signature_fingerprint(signature_from_dict(d)) == signature_fingerprint(sig)
    err = try signature("x"; inputs=(f=Function,)) catch e e end
    @test err isa Refusal && err.code == "unmapped-type"
    err = try LMCC.Signature(5, Any[]) catch e e end
    @test err isa Refusal && err.code == "signature-malformed"
end

@testset "host differences are the stated ones" begin
    sig = signature("Count."; inputs=(n=Int,), outputs=(big=Int,))
    plan = LMCC.bind(adapter(; messages=[LMCC.system("<big>{big}</big>"), LMCC.user("{n}")]), sig)
    err = try render(plan, (n=3.0,)) catch e e end
    @test err isa Refusal && err.code == "value-invalid"          # as Python: a float is not an integer
    @test LMCC.parse(plan, "<big>9223372036854775807</big>")["big"] == typemax(Int64)
    @test LMCC.parse(plan, "<big>9223372036854775808</big>")["big"] == big"9223372036854775808"
    a = adapter(; messages=[LMCC.user("{n}")], formats=Dict("X" => make_format(; write=(v, f) -> string(v))))
    err = try LMCC.dump(a) catch e e end
    @test err isa Refusal && err.code == "format-not-self-contained"
end

function mutate(text, rng)
    n = ncodeunits(text)
    i = LMCC.boundary(text, rand(rng, 0:n))
    j = LMCC.boundary(text, min(n, i + rand(rng, 1:11)))
    j < i && (j = i)
    op = rand(rng, 1:6)
    op == 1 && return LMCC.bsl(text, 0, i) * uppercase(LMCC.bsl(text, i, j)) * LMCC.bsl(text, j)
    op == 2 && return LMCC.bsl(text, 0, i) * rand(rng, ["**", "#", "### ", "_", "\n", " "]) * LMCC.bsl(text, i)
    op == 3 && return LMCC.bsl(text, 0, i) * LMCC.bsl(text, j)
    op == 4 && return LMCC.bsl(text, 0, j) * LMCC.bsl(text, i, j) * LMCC.bsl(text, j)
    op == 5 && return LMCC.bsl(text, 0, i)
    LMCC.bsl(text, 0, i) * rand(rng, ["\"", ".", "`", "None"]) * LMCC.bsl(text, i)
end

function chunks(text, rng)
    chars = collect(text)
    length(chars) < 2 && return [text]
    cuts = sort(unique(rand(rng, 1:length(chars)-1, rand(rng, 0:6))))
    out, prev = String[], 0
    for c in cuts
        push!(out, String(chars[prev+1:c])); prev = c
    end
    push!(out, String(chars[prev+1:end]))
    out
end

@testset "streaming refines batch under random splits" begin
    rng = MersenneTwister(7)
    runs = successes = 0
    for name in sort(readdir(joinpath(ROOT, "contract", "corpus", "cases")))
        c = parse_json(read(joinpath(ROOT, "contract", "corpus", "cases", name), String))
        (get(c, "response", nothing) isa String && !any(startswith("udf:"), get(c, "requires", Any[]))) || continue
        reg = Registry(; extensions=String[r for r in get(c, "requires", Any[])])
        "std" in get(c, "vocab", Any[]) && Std.install!(reg)
        plan = try
            LMCC.bind(load(c["entry"]; registry=reg), signature_from_dict(c["signature"]); capabilities=get(c, "capabilities", JObj()), registry=reg)
        catch
            continue
        end
        for k in 1:40
            t = k == 1 ? c["response"] : mutate(c["response"], rng)
            runs += 1
            batch = try
                (:ok, LMCC.parse_with_captures(plan, t))
            catch e
                e isa Refusal || rethrow()
                (:refuse, LMCC.describe(e))
            end
            s = stream(plan)
            events = JObj[]
            try
                for piece in chunks(t, rng)
                    append!(events, feed!(s, piece))
                end
                res = finish!(s)
                append!(events, res.events)
                @test batch[1] == :ok
                values, captures, repairs = batch[2]
                @test LMCC.json_equal(res.values, values) && LMCC.json_equal(res.repairs, repairs)
                joined = Dict{String,String}()
                for e in events
                    e["kind"] == "field_delta" && (joined[e["field"]] = get(joined, e["field"], "") * e["text"])
                end
                @test all(get(joined, f, "") == text(cap) for (f, cap) in captures)
                successes += 1
            catch e
                e isa Refusal || rethrow()
                @test batch[1] == :refuse && LMCC.json_equal(LMCC.describe(e), batch[2])
            end
        end
    end
    @test runs > 1500 && successes > 500
end

@testset "streaming cost is linear in the reply length" begin
    sig = signature("Think."; inputs=(q=String,), outputs=(reasoning=String, answer=String))
    plan = LMCC.bind(adapter(; messages=[LMCC.system("{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}[[ ## completed ## ]]"), LMCC.user("{q}")]), sig)
    body = repeat("lorem ipsum dolor sit amet ", 8000)
    function cost(n)
        t = "[[ ## reasoning ## ]]\n$(body[1:n])\n\n[[ ## answer ## ]]\nok\n\n[[ ## completed ## ]]"
        s = stream(plan)
        start = time()
        for i in 1:4:ncodeunits(t)
            feed!(s, LMCC.bsl(t, i - 1, min(i + 3, ncodeunits(t))))
        end
        @assert finish!(s).values["answer"] == "ok"
        time() - start
    end
    cost(10_000)
    small, large = cost(40_000), cost(160_000)
    @test large < 12 * small + 0.05
end

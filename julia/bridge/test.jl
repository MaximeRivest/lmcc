# The lm15 bridge (ext/LMCCLM15Ext.jl) against a real LM15.jl, offline: no
# network once installed, no keys. Run by julia/check. The pin is an exact
# LM15.jl commit (LM15.jl is not in the General registry yet); the
# environment is built in julia/.lm15-env, again whenever the pin changes.
# Fails loudly if LM15 cannot be loaded, never skips.

import Pkg
const PIN = (url="https://github.com/lm15-dev/LM15.jl", rev="34c1167035c456e63209ec63c42e58fb289d5f1c")   # LM15.jl 1.0.0
const ENV_DIR = joinpath(@__DIR__, "..", ".lm15-env")
const MARK = joinpath(ENV_DIR, "lm15-pin")
Pkg.activate(ENV_DIR; io=devnull)
if !isfile(MARK) || read(MARK, String) != PIN.rev
    Pkg.develop(Pkg.PackageSpec(path=joinpath(@__DIR__, "..")); io=devnull)
    Pkg.add(Pkg.PackageSpec(url=PIN.url, rev=PIN.rev); io=devnull)
    Pkg.add("Test"; io=devnull)
    write(MARK, PIN.rev)
end
Pkg.instantiate(; io=devnull)

using Test, LMCC, LM15
using LMCC: JObj, json_text, parse_json

const ASK = adapter(; messages=[LMCC.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
                                turns(), LMCC.user("{picture}")])
const PICTURE = LM15.ImagePart(; media_type="image/png", data="iVBORw0KGgo=")
colour(reg=LMCC.default_registry()) = LMCC.bind(ASK,
    LMCC.signature("The main colour."; inputs=(picture=LM15.ImagePart,), outputs=(colour=String,), registry=reg);
    capabilities=Dict("instruct" => true), registry=reg)
response(text, reason) = LM15.Response(; model="m", message=LM15.Message(; role="assistant", parts=(LM15.TextPart(text),)),
    finish_reason=reason, usage=LM15.Usage(; input_tokens=1, output_tokens=1, total_tokens=2))

@testset "lm15 media parts are field types and values (issue #3)" begin
    p = colour()
    f = p.signature.fields[1]
    @test (f.shape, f.type) == (Dict("media" => "image"), "ImagePart")   # the name the other kernels record
    for (T, kind) in (LM15.AudioPart => "audio", LM15.VideoPart => "video", LM15.DocumentPart => "document", LM15.BinaryPart => "binary")
        @test LMCC.signature("x"; inputs=(m=T,), outputs=(a=String,)).fields[1].shape == Dict("media" => kind)
    end
    r = render(p; picture=PICTURE)
    @test LMCC.request(r, "m")["messages"][1]["parts"][1] == Dict("type" => "image", "media_type" => "image/png", "data" => "iVBORw0KGgo=")
    @test LMCC.lm15_request(r; model="m").messages[1].parts[1] isa LM15.ImagePart
    path = LM15.ImagePart(; media_type="image/png", path="cat.png")    # lm15 reads the file when it sends; lmcc never does
    @test LMCC.request(render(p; picture=path), "m")["messages"][1]["parts"][1] == Dict("type" => "image", "media_type" => "image/png", "path" => "cat.png")
    err = try render(p; picture=LM15.AudioPart(; media_type="audio/wav", data="AAAA")) catch e e end
    @test err isa Refusal && err.code == "value-invalid" && occursin("'audio'", err.hint)

    turn = LMCC.finish(LMCC.step(r, "<colour>\nred\n</colour>"))
    saved = parse_json(json_text(dump_turn(p, turn)))
    @test collect(keys(saved["inputs"]["picture"])) == ["type", "media_type", "data"]
    back = load_turn(p, saved)
    @test back.inputs["picture"] == PICTURE
    @test LMCC.request(render(p, (picture=PICTURE,); turns=[turn]), "m") == LMCC.request(render(p, (picture=PICTURE,); turns=[back]), "m")
    saved["inputs"]["picture"]["type"] = "audio"
    err = try load_turn(p, saved) catch e e end
    @test err isa Refusal && err.code == "turn-invalid"

    reg = lm15_install!(Registry())
    @test [h.name for h in reg.type_bindings] == ["ImagePart", "AudioPart", "VideoPart", "DocumentPart", "BinaryPart"]
end

@testset "a stopped response refuses parse-filtered (issue #5)" begin
    sig = LMCC.signature("Answer."; inputs=(picture=String,), outputs=(colour=String,))
    p = LMCC.bind(ASK, sig; capabilities=Dict("instruct" => true))
    for resp in (response("<colour>\nred\n</colour>", "content_filter"), response("", "content_filter"))
        err = try LMCC.parse(p, resp) catch e e end
        @test err isa Refusal && err.code == "parse-filtered"
    end
    refusal = LM15.Message(; role="assistant", parts=(LM15.RefusalPart("No."),))
    err = try LMCC.parse(p, refusal) catch e e end
    @test err isa Refusal && err.code == "parse-filtered" && occursin("'No.'", err.hint)
end

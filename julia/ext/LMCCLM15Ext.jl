"""
lmcc × lm15 (loaded with `using LMCC, LM15`): typed convenience over a shared
wire. The kernel already speaks lm15's canonical JSON; this uses lm15's own
serde both ways, so nothing here can drift from what lm15 says a request or
a response is. Mirrors the Python bridge, `lmcc_lm15`.
"""
module LMCCLM15Ext

using LMCC
using LMCC: Plan, RenderResult, JObj, merge_settings, refuse, pyrepr
import LM15

const MEDIA_PARTS = (LM15.ImagePart => "image", LM15.AudioPart => "audio", LM15.VideoPart => "video",
                     LM15.DocumentPart => "document", LM15.BinaryPart => "binary")

function LMCC.lm15_install!(reg::LMCC.Registry=LMCC.default_registry())
    for (T, kind) in MEDIA_PARTS
        LMCC.bind_type!(reg, T; name=String(nameof(T)), shape=Dict("media" => kind),
            to_json=function (part)        # lm15's part data, `type` first as every kernel writes a part
                d = LM15.to_dict(part)
                out = JObj("type" => kind)
                for (k, v) in d
                    String(k) == "type" || (out[String(k)] = v)
                end
                out
            end,
            from_json=function (data)
                (data isa AbstractDict && get(data, "type", kind) == kind) ||
                    refuse("turn-invalid", "an lm15 $kind part is rebuilt from $kind part data, got $(pyrepr(data))")
                d = Dict{String,Any}(String(k) => v for (k, v) in data)
                d["type"] = kind
                LM15.from_dict(T, d)
            end)
    end
    reg
end

__init__() = LMCC.lm15_install!()

_dict(r::Union{LM15.Response,LM15.Message}) = LM15.to_dict(r)

function LMCC.lm15_request(rendered::RenderResult; model, config=nothing, override=false)
    d = LMCC.request(rendered, model)
    if config !== nothing
        d["config"] = merge_settings(get(d, "config", JObj()), LM15.to_dict(config); path="config", override=override)
    end
    LM15.from_dict(LM15.Request, d)
end

LMCC.read(p::Plan, r::Union{LM15.Response,LM15.Message}) = LMCC.read(p, _dict(r))
LMCC.parse(p::Plan, r::Union{LM15.Response,LM15.Message}) = LMCC.parse(p, _dict(r))
LMCC.step(rendered::RenderResult, r::Union{LM15.Response,LM15.Message}) = LMCC.step(rendered, _dict(r))

function LMCC.lm15_stream(p::Plan, events; on_event=nothing)
    s = LMCC.stream(p)
    out = JObj[]
    reason = nothing
    emit(batch) = for e in batch
        push!(out, e)
        on_event === nothing || on_event(e)
    end
    for ev in events
        ev isa LM15.StreamErrorEvent && error("lm15 stream error: $(ev.error.code): $(ev.error.message)")
        ev isa LM15.StreamEndEvent && (reason = ev.finish_reason)
        ev isa LM15.StreamDeltaEvent || continue
        emit(LMCC.feed!(s, LM15.to_dict(ev.delta)))
    end
    result = LMCC.finish!(s, reason)
    emit(result.events)
    (out, result)
end

end

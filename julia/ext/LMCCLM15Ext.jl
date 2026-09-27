"""
lmcc × lm15 (loaded with `using LMCC, LM15`): typed convenience over a shared
wire. The kernel already speaks lm15's canonical JSON; this uses lm15's own
serde both ways, so nothing here can drift from what lm15 says a request or
a response is. Mirrors the Python bridge, `lmcc_lm15`.
"""
module LMCCLM15Ext

using LMCC
using LMCC: Plan, RenderResult, JObj, merge_settings
import LM15

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

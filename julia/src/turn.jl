# The turn record (kernel §3a): examples, past exchanges and the exchange in
# progress. Records are immutable; every operation returns a new turn.
# `turn_to_dict` is schema/turn.schema.json, the same record in every language.

"Kernel §3a canonical JSON: keys by code point, no whitespace, numbers by §7a (D-54)."
canonical_json(value) = json_text(tojsonvalue(value); sort_keys=true)

"`\"sha256:\"` + the hex SHA-256 of `value`'s canonical JSON: fingerprints and request hashes."
sha256_of(value) = "sha256:" * sha256_hex(canonical_json(value))

"Lowercase hex SHA-256 of a text's UTF-8 bytes."
sha256_hex(text::AbstractString) = bytes2hex(SHA.sha256(String(text)))

"Which signature a turn belongs to: each field's direction, name, purpose, shape and type."
signature_fingerprint(sig::Signature) = sha256_of(Any[jobj("direction" => f.direction, "name" => f.name,
    "purpose" => isempty(f.purpose) ? "plain" : f.purpose, "shape" => f.shape, "type" => something(f.type, "")) for f in sig.fields])

"A value as the JSON its field's shape describes; anything without a JSON form refuses `turn-invalid`."
function to_json(value, where="turn")
    value === nothing && return nothing
    (value isa AbstractString || value isa Bool || value isa Integer) && return value isa AbstractString ? String(value) : value
    if value isa Real
        isfinite(value) || refuse("turn-invalid", "$where: $value has no JSON form")
        return value
    end
    value isa Symbol && return String(value)
    value isa Enum && return string(value)
    (isarr(value) || value isa Tuple) && return Any[to_json(v, "$where[$(i-1)]") for (i, v) in enumerate(value)]
    if isobj(value) || value isa NamedTuple
        out = JObj()
        for (k, v) in pairs(value)
            (k isa AbstractString || k isa Symbol) || refuse("turn-invalid", "$where: object keys must be strings, got $(repr(k))")
            out[String(k)] = to_json(v, "$where.$k")
        end
        return out
    end
    refuse("turn-invalid", "$where: a $(typeof(value)) has no JSON form; a turn holds JSON values in their fields' shapes")
end

_get(o, k) = isobj(o) ? get(o, k, nothing) : nothing
call_id(c) = _get(c, "id")
call_name(c) = _get(c, "name")

"Parse input (a text, an lm15 message or response) as an lm15 message."
function as_message(reply)
    reply isa AbstractString && return make_message("assistant", Any[textpart(reply)])
    r = (isobj(reply) && isobj(get(reply, "message", nothing))) ? reply["message"] : reply
    if isobj(r) && isarr(get(r, "parts", nothing))
        return make_message(get(r, "role", "assistant"), Any[isobj(p) ? JObj(String(k) => v for (k, v) in p) : p for p in r["parts"]])
    end
    refuse("response-malformed", "a reply is text, an lm15 message {role, parts}, or an lm15 response {message: ...}")
end

"One model reply: parsed values, the message as it came, the request's hash, the calls field."
struct ModelStep
    outputs::JObj
    message::Union{Nothing,JObj}
    request::Union{Nothing,String}
    calls_field::Union{Nothing,String}
end
ModelStep(outputs) = ModelStep(outputs, nothing, nothing, nothing)
function step_calls(s::ModelStep)
    v = s.calls_field === nothing ? nothing : get(s.outputs, s.calls_field, nothing)
    isarr(v) ? Any[v...] : Any[]
end

"One tool result answering one call: lm15 parts, and the turns made producing it (never written)."
struct ToolStep
    id::String
    name::String
    output::Vector{Any}
    children::Vector{Any}
end

const Step = Union{ModelStep,ToolStep}

function step_to_dict(s::ModelStep)
    d = jobj("kind" => "model", "outputs" => to_json(s.outputs, "step.outputs"))
    s.message === nothing || (d["message"] = s.message)
    s.request === nothing || (d["request"] = s.request)
    s.calls_field === nothing || (d["calls_field"] = s.calls_field)
    d
end
function step_to_dict(s::ToolStep)
    d = jobj("kind" => "tool", "id" => s.id, "name" => s.name, "output" => Any[s.output...])
    isempty(s.children) || (d["children"] = Any[turn_to_dict(c) for c in s.children])
    d
end

function _output_parts(output)
    output isa AbstractString && return Any[textpart(output)]
    isarr(output) || refuse("turn-invalid", "a tool output is a text or a list of lm15 parts")
    for p in output
        (isobj(p) && get(p, "type", nothing) isa AbstractString) || refuse("turn-invalid", "a tool output part must be an lm15 part with a type, got $(pyrepr(p))")
    end
    Any[JObj(String(k) => v for (k, v) in p) for p in output]
end

"""
    Turn

One call of one signature (§3a): `signature` (fingerprint), `inputs`, `steps`,
`outputs` (`nothing` until finished), `score`, `meta`. Build with `new_turn` or
`example`; advance with `step`, `tool` and `finish`.
"""
struct Turn
    signature::String
    inputs::JObj
    steps::Vector{Step}
    outputs::Union{Nothing,JObj}
    score::Union{Nothing,Real}
    meta::JObj
end
Turn(sig, inputs) = Turn(sig, inputs, Step[], nothing, nothing, JObj())

"Calls of the last model step that no tool step has answered yet."
function pending_calls(t::Turn)
    pending = Any[]
    for s in t.steps
        if s isa ModelStep
            pending = step_calls(s)
        elseif !isempty(pending) && call_id(pending[1]) == s.id
            pending = pending[2:end]
        end
    end
    pending
end

"Answer the next pending call. `output`: a text or lm15 parts."
function tool(t::Turn, id, output; children=Turn[])
    pending = pending_calls(t)
    isempty(pending) && refuse("turn-invalid", "tool result $(pyrepr(id)) answers no pending call")
    call_id(pending[1]) == id || refuse("turn-invalid", "tool result $(pyrepr(id)) is out of order: the next pending call is $(pyrepr(call_id(pending[1])))")
    for c in children
        c isa Turn || refuse("turn-invalid", "tool step children are turns")
    end
    Turn(t.signature, t.inputs, vcat(t.steps, ToolStep(string(id), string(call_name(pending[1])), _output_parts(output), Any[children...])), t.outputs, t.score, t.meta)
end

"Close the turn: its outputs are the last model step's."
function finish(t::Turn)
    pending = pending_calls(t)
    isempty(pending) || refuse("turn-invalid", "cannot finish with unanswered call $(pyrepr(call_id(pending[1])))")
    i = findlast(s -> s isa ModelStep, t.steps)
    i === nothing && refuse("turn-invalid", "cannot finish a turn with no model step")
    Turn(t.signature, t.inputs, t.steps, copy(t.steps[i].outputs), t.score, t.meta)
end

with_step(t::Turn, s::Step) = Turn(t.signature, t.inputs, vcat(t.steps, s), t.outputs, t.score, t.meta)

"This turn with `meta` replaced (carried, never read by render); checked for JSON form now."
function with_meta(t::Turn, meta)
    isobj(meta) || refuse("turn-invalid", "turn.meta: an object")
    Turn(t.signature, t.inputs, t.steps, t.outputs, t.score, to_json(meta, "turn.meta"))
end

"This turn with `score` replaced: a finite number, or `nothing`."
function with_score(t::Turn, score)
    (score === nothing || (isnum(score) && isfinite(score))) || refuse("turn-invalid", "turn.score: a finite number or None, not $(pyrepr(score))")
    Turn(t.signature, t.inputs, t.steps, t.outputs, score, t.meta)
end

isdone(t::Turn) = t.outputs !== nothing

function turn_to_dict(t::Turn)
    d = jobj("signature" => t.signature, "inputs" => to_json(t.inputs, "turn.inputs"), "steps" => Any[step_to_dict(s) for s in t.steps])
    t.outputs === nothing || (d["outputs"] = to_json(t.outputs, "turn.outputs"))
    t.score === nothing || (d["score"] = t.score)
    isempty(t.meta) || (d["meta"] = to_json(t.meta, "turn.meta"))
    d
end

"JSON → a turn (schema/turn.schema.json)."
function turn_from_dict(data, where="turn")
    isobj(data) || refuse("turn-invalid", "$where: a turn is an object")
    unknown = sort([String(k) for k in keys(data) if !(k in ("signature", "inputs", "steps", "outputs", "score", "meta"))])
    isempty(unknown) || refuse("turn-invalid", "$where: unknown key(s) $(pyrepr(Any[unknown...]))")
    sig, ins = get(data, "signature", nothing), get(data, "inputs", nothing)
    (sig isa AbstractString && isobj(ins)) || refuse("turn-invalid", "$where: a turn needs a signature fingerprint and an inputs object")
    outs = get(data, "outputs", nothing)
    (outs === nothing || isobj(outs)) || refuse("turn-invalid", "$where.outputs: an object or null")
    steps = Step[]
    for (i, s) in enumerate(something(get(data, "steps", nothing), Any[]))
        at = "$where.steps[$(i-1)]"
        (isobj(s) && get(s, "kind", nothing) in ("model", "tool")) || refuse("turn-invalid", "$at: a step is {kind: model|tool, ...}")
        if s["kind"] == "model"
            (all(k -> k in ("kind", "outputs", "message", "request", "calls_field"), keys(s)) && isobj(get(s, "outputs", nothing))) ||
                refuse("turn-invalid", "$at: a model step is {kind, outputs, message?, request?, calls_field?}")
            msg = get(s, "message", nothing)
            if msg !== nothing
                msg = as_message(msg)
                foreach(validate_response_part, msg["parts"])
            end
            push!(steps, ModelStep(JObj(String(k) => v for (k, v) in s["outputs"]), msg, get(s, "request", nothing), get(s, "calls_field", nothing)))
        else
            (all(k -> k in ("kind", "id", "name", "output", "children"), keys(s)) &&
             all(k -> get(s, k, nothing) isa AbstractString && !isempty(s[k]), ("id", "name"))) ||
                refuse("turn-invalid", "$at: a tool step is {kind, id, name, output, children?}")
            children = Any[turn_from_dict(c, "$at.children[$(j-1)]") for (j, c) in enumerate(something(get(s, "children", nothing), Any[]))]
            push!(steps, ToolStep(s["id"], s["name"], _output_parts(get(s, "output", Any[])), children))
        end
    end
    meta = something(get(data, "meta", nothing), JObj())
    isobj(meta) || refuse("turn-invalid", "$where.meta: an object")
    score = get(data, "score", nothing)
    Turn(sig, JObj(String(k) => v for (k, v) in ins), steps, outs === nothing ? nothing : JObj(String(k) => v for (k, v) in outs),
        score, JObj(String(k) => v for (k, v) in meta))
end

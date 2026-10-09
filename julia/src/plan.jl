# Bind (kernel §3–§6): where the adapter, the signature and the model's
# declared facts meet. Every refusal fires at bind; the plan does pure things
# only: render, read/parse, stream, describe, skeleton, prefix.

struct Resolved
    purpose::String
    field::Field
    transport::Transport
    name::String
end

mutable struct FormatChoice
    format::Format
    resolved_by::String
    described::Union{Nothing,String}
    described_by::Union{Nothing,String}
end

mutable struct Plan
    adapter::Adapter
    signature::Signature
    capabilities::JObj
    registry::Registry
    visible_inputs::Vector{Field}
    visible_outputs::Vector{Field}
    resolved::Vector{Resolved}
    find_rules::Vector{Tuple{String,JObj}}
    puts::Vector{Tuple{String,String}}
    written_as::OrderedDict{String,Format}
    tell::JObj
    request_settings::JObj
    formats::OrderedDict{String,FormatChoice}
    reader::Any
    prefill::String
    find_repairable::Vector{String}
    find_unrepaired::Vector{String}
    extensions::OrderedDict{String,ResolvedExtension}
    turn_input_formats::OrderedDict{String,Format}
    rule_owner::Vector{Resolved}
    slots::OrderedDict{String,Tuple{String,Int}}
    calls_field::Union{Nothing,String}
    calls_owner::Union{Nothing,Resolved}
    turn_writers::OrderedDict{String,JObj}
    replay_types::Set{String}
end

Plan(a, s, c, r) = Plan(a, s, c, r, Field[], Field[], Resolved[], Tuple{String,JObj}[], Tuple{String,String}[], OrderedDict{String,Format}(),
    JObj(), JObj(), OrderedDict{String,FormatChoice}(), nothing, "", String[], String[], OrderedDict{String,ResolvedExtension}(),
    OrderedDict{String,Format}(), Resolved[], OrderedDict{String,Tuple{String,Int}}(), nothing, nothing, OrderedDict{String,JObj}(), Set{String}())

"An lm15 request minus its model (§3): `system`, `messages`, request settings."
struct RenderResult
    messages::Vector{Any}
    request_settings::JObj
    system::Any
    plan::Plan
    turn::Turn
end

"The whole request as lm15 canonical JSON, feedable to any lm15 implementation."
function request(r::RenderResult, model=nothing)
    out = JObj()
    model === nothing || (out["model"] = model)
    r.system === nothing || (out["system"] = r.system)
    out["messages"] = r.messages
    for (k, v) in deepcopy_json(r.request_settings)
        out[k] = v
    end
    out
end

"The reply to this request, parsed and recorded as the turn's next model step (§3a). Pure."
function step(r::RenderResult, reply)
    message = as_message(reply)
    values = parse(r.plan, reply)
    if !isempty(r.plan.prefill)
        message = make_message(message["role"], merge_text_parts(vcat(Any[textpart(r.plan.prefill)], message["parts"])))
    end
    with_step(r.turn, ModelStep(values, message, sha256_of(request(r)), r.plan.calls_field))
end

"A reply, read (§4a): typed values, repairs, and what data parts measured (§3)."
struct Reading
    values::JObj
    repairs::Vector{JObj}
    probabilities::JObj
    measured_by::JObj
end
isclean(r::Reading) = isempty(r.repairs)
reading_to_dict(r::Reading) = jobj("values" => r.values, "repairs" => r.repairs, "probabilities" => r.probabilities, "measured_by" => r.measured_by)

mutable struct WriteContext
    model_steps::Int
end

const PART_SPOT = "\ufffc"

struct Env
    plan::Plan
    values::JObj
    partial::Bool
    texts::OrderedDict{String,Vector{Tuple{String,String,String}}}
    filled::Set{String}
end

env_turn_messages(e::Env, slot) = get(e.texts, slot, Tuple{String,String,String}[])
function env_guard(e::Env, name)
    f = field_named(e.plan.signature, name)
    if f !== nothing && f.direction == "input"
        v = get(e.values, name, nothing)
        return !(v === nothing || v === false || v == "" || (isarr(v) && isempty(v)))
    end
    e.partial && return nothing
    name in e.filled
end
env_instruction(e::Env) = e.plan.signature.instructions
env_reply_format(e::Env) = reply_format(e.plan)
function env_loop_fields(e::Env, source)
    source != "inputs" && return e.plan.visible_outputs
    e.partial ? [f for f in e.plan.visible_inputs if haskey(e.values, f.name)] : e.plan.visible_inputs
end
env_field_named(e::Env, name) = field_named(e.plan.signature, name)
env_schema_of(e::Env, f) = schema_hint(e.plan, f)
function env_value_of(e::Env, f::Field)
    f.direction == "output" && return (:text, placeholder(e.plan, f))
    haskey(e.values, f.name) || refuse("missing-input", "no value supplied for field $(pyrepr(f.name))")
    parts = write_value(e.plan, f, e.values[f.name])
    length(parts) == 1 && get(parts[1], "type", nothing) == "text" && return (:text, parts[1]["text"])
    (:parts, parts)
end

# ---------------------------------------------------------------- formats

format_for(p::Plan, f::Field) = p.formats[f.name].format

function schema_hint(p::Plan, f::Field)
    d = something(p.formats[f.name].described, format_describe(format_for(p, f), f), Some(nothing))
    (d === nothing || isempty(d)) ? shape_summary(f.shape) : d
end

"desc, else the description or the format's describe, else the mechanical hint (§2, §5)."
function placeholder(p::Plan, f::Field)
    f.desc !== nothing && !isempty(f.desc) && return f.desc
    c = p.formats[f.name]
    d = something(c.described, format_describe(c.format, f), Some(nothing))
    d !== nothing && !isempty(d) && return d
    c.resolved_by != "kernel" && f.type !== nothing && !isempty(f.type) && return f.type
    s = shape_summary(f.shape)
    isempty(s) ? "..." : s
end

reply_format(p::Plan) = reader_format(p.reader, [(f.name, placeholder(p, f)) for f in p.visible_outputs])

function write_value(p::Plan, f::Field, value; fmt=nothing)
    own = fmt === nothing && startswith(p.formats[f.name].resolved_by, "runtime:")
    format = fmt === nothing ? format_for(p, f) : fmt
    if !own && to_json_hook(p.registry, value) !== nothing
        # a type bound with to_json reaches the format bound to it as itself,
        # every other format (the artifact's, the kernel's) as its JSON form
        value = try
            to_json(value, "field $(pyrepr(f.name))"; registry=p.registry)
        catch err
            err isa Refusal || rethrow()
            refuse("format-write-error", err.hint)
        end
    elseif format === MEDIA_LIST_DEFAULT && (value isa AbstractVector || value isa Tuple)
        # the kernel's list of media writes each item as one media value: an item
        # of a type bound with to_json (an lm15 part) as its JSON form
        value = try
            Any[to_json_hook(p.registry, v) === nothing ? v : to_json(v, "field $(pyrepr(f.name))[$(i - 1)]"; registry=p.registry)
                for (i, v) in enumerate(value)]
        catch err
            err isa Refusal || rethrow()
            refuse("format-write-error", err.hint)
        end
    end
    written = try
        format.write(value, f)
    catch err
        err isa Refusal && rethrow()
        refuse("format-write-error", "field $(pyrepr(f.name)): format failed to write: $(sprint(showerror, err))")
    end
    as_parts(written, "field $(pyrepr(f.name))")
end

function read_field(p::Plan, f::Field, c::Capture)
    fmt = format_for(p, f)
    try
        fmt.read === nothing && error("format $(something(fmt.name, "(inline)")) does not read")
        return fmt.read(c, f)
    catch err
        err isa Refusal && rethrow()
        refuse("format-read-error", "field $(pyrepr(f.name)): format failed to read: $(sprint(showerror, err))")
    end
end

function _spelled_text(p::Plan, f::Field, value)
    fmt = format_for(p, f)
    fmt.round_trip || refuse("turn-not-renderable", "field $(pyrepr(f.name)): format $(something(fmt.name, "(inline)")) does not round-trip, so a turn written with it could not be read back")
    parts = write_value(p, f, value)
    any(x -> get(x, "type", nothing) != "text", parts) && refuse("turn-not-renderable", "field $(pyrepr(f.name)): its format writes non-text parts, which a text pattern cannot hold")
    join(x["text"] for x in parts)
end

# ----------------------------------------------------------------- turns

fingerprint(p::Plan) = signature_fingerprint(p.signature)

"A new turn of this plan's signature, with no steps (§3a)."
function new_turn(p::Plan, inputs=JObj(); kw...)
    vals = JObj(String(k) => v for (k, v) in pairs(inputs))
    for (k, v) in kw
        vals[String(k)] = v
    end
    _check_names(p, vals, "input", "inputs")
    Turn(fingerprint(p), vals)
end

"A turn that did not happen here: inputs and outputs, no steps."
function example(p::Plan, inputs, outputs)
    i = JObj(String(k) => v for (k, v) in pairs(inputs))
    o = JObj(String(k) => v for (k, v) in pairs(outputs))
    _check_names(p, i, "input", "inputs")
    _check_names(p, o, "output", "outputs")
    Turn(fingerprint(p), i, Step[], o, nothing, JObj())
end

"""
A turn from JSON, checked against this plan's signature; each value whose
field's type is bound with `from_json` is rebuilt by it (§3a).
"""
function load_turn(p::Plan, data)
    t = _check_turn(p, turn_from_dict(data), "turn", false, true)
    function lift_all(values, where)
        out = JObj()
        for (k, v) in values
            ann = field_named(p.signature, k).annotation
            out[k] = try
                lift(ann, v; registry=p.registry)
            catch err
                err isa Refusal && rethrow()
                refuse("turn-invalid", "$where.$k: cannot rebuild a $(ann) from its JSON: $(sprint(showerror, err))")
            end
        end
        out
    end
    steps = Step[s isa ModelStep ? ModelStep(lift_all(s.outputs, "turn.steps[$(i-1)].outputs"), s.message, s.request, s.calls_field) : s
                 for (i, s) in enumerate(t.steps)]
    Turn(t.signature, lift_all(t.inputs, "turn.inputs"), steps,
         t.outputs === nothing ? nothing : lift_all(t.outputs, "turn.outputs"), t.score, t.meta)
end

"A turn of this plan as JSON: values by `to_json` with the plan's registry. What `load_turn` reads back."
dump_turn(p::Plan, t::Turn) = turn_to_dict(_check_turn(p, t, "turn", false, true); registry=p.registry)

function _check_names(p::Plan, values, direction, where)
    isobj(values) || refuse("turn-invalid", "$where: an object of $direction field values")
    known = Set(f.name for f in p.signature.fields if f.direction == direction)
    for k in keys(values)
        k in known || refuse("turn-invalid", "$where.$k: not an $direction field of this signature")
    end
end

function _check_turn(p::Plan, t, where, past, pending_ok=false)
    isobj(t) && (t = turn_from_dict(t, where))
    t isa Turn || refuse("turn-invalid", "$where: expected a turn, got $(typeof(t))")
    t.signature == fingerprint(p) || refuse("turn-invalid", "$where: recorded for signature $(t.signature), but this plan's is $(fingerprint(p))")
    _check_names(p, t.inputs, "input", "$where.inputs")
    t.outputs === nothing || _check_names(p, t.outputs, "output", "$where.outputs")
    pending = Any[]
    for (i, s) in enumerate(t.steps)
        at = "$where.steps[$(i-1)]"
        if s isa ModelStep
            isempty(pending) || refuse("turn-invalid", "$at: call $(pyrepr(call_id(pending[1]))) has no tool step")
            _check_names(p, s.outputs, "output", "$at.outputs")
            pending = step_calls(s)
        else
            (!isempty(pending) && call_id(pending[1]) == s.id) || refuse("turn-invalid", "$at: tool step $(pyrepr(s.id)) answers no pending call")
            pending = pending[2:end]
        end
    end
    !isempty(pending) && !pending_ok && refuse("turn-invalid",
        "$where: call $(pyrepr(call_id(pending[1]))) has no tool step" * (past ? "" : "; answer it with tool(turn, id, output) first"))
    t
end

# ----------------------------------------------------------------- render

"""
    render(plan, inputs_or_turn; turns=nothing)

This turn in the context of those turns (§3a). `inputs_or_turn`: a Dict or
NamedTuple of inputs, or a `Turn`; `turns`: `Dict(slot => [turn…])` or a
vector for the slot `turns`.
"""
function render(p::Plan, inputs=JObj(); turns=nothing, kw...)
    current = if inputs isa Turn
        isempty(kw) || refuse("turn-invalid", "render a turn, or inputs — not both")
        _check_turn(p, inputs, "turn", false)
    else
        new_turn(p, inputs; kw...)
    end
    _render(p, current, _slot_values(p, turns))
end

function _slot_values(p::Plan, turns)
    out = OrderedDict{String,Vector{Turn}}()
    turns === nothing && return out
    by_slot = isarr(turns) ? OrderedDict("turns" => turns) : turns
    isobj(by_slot) || refuse("turn-invalid", "turns is {slot: [turn]} or a list for the slot 'turns'")
    for (name, ts) in by_slot
        name = String(name)
        (ts === nothing || isempty(ts)) && continue
        (name == "steps" || !haskey(p.slots, name)) && refuse("turns-unplaced",
            "turns given for slot $(pyrepr(name)), which " * (name == "steps" ? "is the current turn's own steps" : "the template does not place") *
            "; placed slots: " * (isempty(p.slots) ? "none" : pyrepr(Any[sort(collect(keys(p.slots)))...])))
        out[name] = Turn[_check_turn(p, t, "turns[$(pyrepr(name))][$(i-1)]", true) for (i, t) in enumerate(ts)]
    end
    out
end

function _render(p::Plan, current::Turn, slot_values; stop_at=nothing)
    !isempty(current.steps) && isempty(p.slots) &&
        refuse("turns-unplaced", "the current turn has steps, but the template places no turn slot to write them; add turns()")
    ctx = WriteContext(0)
    texts = OrderedDict{String,Vector{Tuple{String,String,String}}}()
    for (name, (form, _)) in p.slots
        form == "text" || continue
        msgs = _slot_messages(p, name, current, slot_values, WriteContext(0))
        texts[name] = [(m["role"], kind, _text_of(m, name)) for (m, kind) in msgs]
    end
    filled = Set(name for name in keys(p.slots) if (name == "steps" ? !isempty(current.steps) : !isempty(get(slot_values, name, Turn[]))))
    messages = Any[]
    own = Any[]
    sys_tell = get(p.tell, "system", nothing)
    tell_done = sys_tell === nothing
    compiled = p.adapter.compiled
    adapter_prefill(p.adapter) !== nothing && (compiled = compiled[1:end-1])
    for (i, (msg, nodes)) in enumerate(compiled)
        stop_at !== nothing && i - 1 >= stop_at && break
        if nodes === nothing
            append!(messages, [m for (m, _) in _slot_messages(p, get(msg, "slot", "turns"), current, slot_values, ctx)])
            continue
        end
        parts = _render_message(p, nodes, current.inputs; texts=texts, filled=filled)
        if msg["role"] == "system" && !tell_done
            parts = merge_text_parts(vcat(parts, Any[textpart("\n\n" * sys_tell)]))
            tell_done = true
        end
        if !isempty(parts)
            m = make_message(msg["role"], parts)
            push!(messages, m); push!(own, m)
        end
    end
    stop_at === nothing && !haskey(p.slots, "steps") && !isempty(p.slots) && append!(messages, [m for (m, _) in _write_steps(p, current, ctx)])
    if !tell_done
        m = make_message("system", Any[textpart(sys_tell)])
        pushfirst!(messages, m); push!(own, m)
    end
    for (role, text) in p.tell
        role == "system" && continue
        i = findfirst(m -> m["role"] == role, own)
        if i === nothing
            m = make_message(role, Any[textpart(text)])
            push!(messages, m); push!(own, m)
        else
            own[i]["parts"] = merge_text_parts(vcat(own[i]["parts"], Any[textpart("\n\n" * text)]))
        end
    end
    settings = deepcopy_json(p.request_settings)
    for (fname, place) in p.puts
        f = field_named(p.signature, fname)
        (f.direction == "input" && haskey(current.inputs, fname)) || continue
        parts = write_value(p, f, current.inputs[fname]; fmt=get(p.written_as, fname, nothing))
        if startswith(place, "request.")
            _set_path!(settings, place[9:end], parts)
        else
            role = split(place, ':'; limit=2)[2]
            i = findfirst(m -> m["role"] == role, own)
            if i === nothing
                m = make_message(role, parts)
                push!(messages, m); push!(own, m)
            else
                own[i]["parts"] = merge_text_parts(vcat(own[i]["parts"], Any[textpart("\n\n")], parts))
            end
        end
    end
    !isempty(p.prefill) && stop_at === nothing && push!(messages, make_message("assistant", Any[textpart(p.prefill)]))
    sys_parts = Any[x for m in messages if m["role"] == "system" for x in m["parts"]]
    system = isempty(sys_parts) ? nothing :
             (length(sys_parts) == 1 && get(sys_parts[1], "type", nothing) == "text") ? sys_parts[1]["text"] : sys_parts
    RenderResult(Any[m for m in messages if m["role"] != "system"], settings, system, p, current)
end

function _render_message(p::Plan, nodes, values; partial=false, texts=OrderedDict{String,Vector{Tuple{String,String,String}}}(), filled=Set{String}())
    out = Any[]
    buf = IOBuffer()
    render_nodes(nodes, Env(p, values, partial, texts, filled), out, buf)
    buf.size > 0 && push!(out, textpart(String(take!(buf))))
    merge_text_parts(out)
end

function _text_of(m, slot)
    for x in m["parts"]
        get(x, "type", nothing) == "text" || refuse("turn-not-renderable",
            "slot $(pyrepr(slot)) is placed as text, but a $(m["role"]) message of its turns holds a $(pyrepr(get(x, "type", nothing))) part, which text cannot hold; place the slot as messages (turns($(pyrepr(slot)))) or use a text transport")
    end
    join(x["text"] for x in m["parts"])
end

function _slot_messages(p::Plan, name, current, slot_values, ctx)
    name == "steps" && return _write_steps(p, current, ctx)
    out = Tuple{JObj,String}[]
    for t in get(slot_values, name, Turn[])
        append!(out, [(m, "input") for m in _user_side(p, t.inputs)])
        if !isempty(t.steps)
            append!(out, _write_steps(p, t, ctx))
        elseif t.outputs !== nothing && !isempty(t.outputs)
            m, _ = _model_message(p, ModelStep(t.outputs), ctx)
            m === nothing || push!(out, (m, "model"))
        end
    end
    out
end

function _user_side(p::Plan, inputs)
    out = JObj[]
    for (msg, nodes) in p.adapter.compiled
        (nodes !== nothing && msg["role"] == "user") || continue
        parts = _render_message(p, nodes, inputs; partial=true)
        isempty(parts) || push!(out, make_message("user", parts))
    end
    out
end

function _write_steps(p::Plan, t::Turn, ctx)
    out = Tuple{JObj,String}[]
    ids = OrderedDict{String,String}()
    for s in t.steps
        if s isa ModelStep
            m, ids = _model_message(p, s, ctx)
            m === nothing || push!(out, (m, "model"))
        else
            push!(out, (_tool_message(p, s, get(ids, s.id, s.id)), "tool"))
        end
    end
    out
end

"§3a: the recorded reply when this plan reads it back into the same values; else written from them."
function _model_message(p::Plan, s::ModelStep, ctx)
    if p.adapter.replay == "verbatim" && s.message !== nothing
        ctx.model_steps += 1
        return (make_message("assistant", Any[copy(x) for x in s.message["parts"]]), OrderedDict{String,String}())
    end
    if p.adapter.replay == "recorded" && s.message !== nothing
        same = try
            values, _, reps = parse_with_captures(p, s.message; continued=false)
            json_equal(to_json(values; registry=p.registry), to_json(s.outputs; registry=p.registry)) && !any(r -> r["repair"] in ("marker", "unclosed", "value"), reps)
        catch err
            err isa Refusal || rethrow()
            false
        end
        if same
            ctx.model_steps += 1
            return (make_message("assistant", Any[copy(x) for x in s.message["parts"]]), OrderedDict{String,String}())
        end
    end
    _write_model_step(p, s, ctx)
end

function _write_model_step(p::Plan, s::ModelStep, ctx)
    outs = s.outputs
    recorded = s.message === nothing ? Any[] : s.message["parts"]
    parts = Any[copy(x) for x in recorded if get(x, "type", nothing) in p.replay_types]
    before, after = String[], String[]
    for (fname, w) in p.turn_writers
        v = get(outs, fname, nothing)
        (w["by"] in ("dropped", "projection", "replayed", "spelling.call", "format:parts") || v === nothing || v == "" || (isarr(v) && isempty(v))) && continue
        f = field_named(p.signature, fname)
        t = _spelled_text(p, f, v)
        piece = if w["by"] == "derived:between"
            open_, close = w["between"]
            occursin(close, t) && refuse("value-collides", "field $(pyrepr(fname)): its written value contains $(pyrepr(close)), the marker that ends it")
            open_ * t * close
        elseif w["by"] == "derived:line_prefixed"
            join((w["prefix"] * line for line in split(t, '\n')), "\n")
        else
            spell_turn(w["template"], OrderedDict("value" => t))
        end
        push!(get(w, "position", "after") == "before" ? before : after, piece)
    end
    spelled = Tuple{String,String}[]
    placed = Vector{Any}[]
    for f in p.visible_outputs
        haskey(outs, f.name) || continue
        fmt = format_for(p, f)
        if fmt.writes == "parts" && p.reader isa DerivedReader
            fmt.round_trip || refuse("turn-not-renderable", "field $(pyrepr(f.name)): format $(something(fmt.name, "(inline)")) does not round-trip")
            push!(placed, write_value(p, f, outs[f.name]))
            push!(spelled, (f.name, PART_SPOT))
        else
            tv = _spelled_text(p, f, outs[f.name])
            occursin(PART_SPOT, tv) && refuse("value-collides", "field $(pyrepr(f.name)): its value contains U+FFFC, which marks where a part goes")
            push!(spelled, (f.name, tv))
        end
    end
    body = isempty(spelled) ? "" : reader_join(p.reader, spelled)
    text = join([x for x in vcat(before, [body], after) if !isempty(x)], "\n")
    ids = OrderedDict{String,String}()
    calls = p.calls_field === nothing ? nothing : get(outs, p.calls_field, nothing)
    call_parts = Any[]
    if pytruthy(calls)
        f = field_named(p.signature, p.calls_field)
        written = try
            write_value(p, f, calls)
        catch err
            (err isa Refusal && err.code == "format-write-error") || rethrow()
            refuse("turn-not-renderable", "field $(pyrepr(p.calls_field)): $(err.hint)")
        end
        for x in written
            (get(x, "type", nothing) == "tool_call" && get(x, "id", nothing) isa AbstractString && get(x, "name", nothing) isa AbstractString && isobj(get(x, "input", nothing))) ||
                refuse("turn-not-renderable", "field $(pyrepr(p.calls_field)): its format must write lm15 tool_call parts {type, id, name, input}; got $(pyrepr(x))")
            isempty(x["id"]) && refuse("turn-invalid", "field $(pyrepr(p.calls_field)): call $(pyrepr(x["name"])) has the id '', and a call's id is non-empty text (lm15 ToolCallPart.id; a tool step answers the call by it)")
        end
        owner = p.calls_owner
        if owner !== nothing && haskey(owner.transport.spelling, "call")
            ct = join((call_text(p, owner, x) for x in written), "\n")
            text = isempty(text) ? ct : text * "\n" * ct
        else
            assigned = !any(x -> get(x, "type", nothing) == "tool_call", recorded)
            k = ctx.model_steps
            for x in written
                if assigned
                    ids[x["id"]] = "s$(k)_$(x["id"])"
                    x = merge(JObj(String(a) => b for (a, b) in x), jobj("id" => ids[x["id"]]))
                end
                push!(call_parts, x)
            end
        end
    end
    if !isempty(placed)
        pieces = split(text, PART_SPOT)
        tails = vcat(placed, [Any[]])
        for i in 1:min(length(pieces), length(tails))
            isempty(pieces[i]) || push!(parts, textpart(pieces[i]))
            append!(parts, [copy(x) for x in tails[i]])
        end
    elseif !isempty(text)
        push!(parts, textpart(text))
    end
    append!(parts, call_parts)
    isempty(parts) && return (nothing, ids)
    ctx.model_steps += 1
    (make_message("assistant", parts), ids)
end

function _tool_message(p::Plan, s::ToolStep, written_id)
    owner = p.calls_owner
    if owner !== nothing && haskey(owner.transport.spelling, "result")
        output = join((x["text"] for x in s.output if get(x, "type", nothing) == "text" && get(x, "text", nothing) isa AbstractString), "\n")
        t = spell_turn(owner.transport.spelling["result"], OrderedDict("id" => s.id, "name" => s.name, "output" => output))
        return make_message("user", vcat(Any[textpart(t)], Any[copy(x) for x in s.output if get(x, "type", nothing) != "text"]))
    end
    make_message("tool", Any[jobj("type" => "tool_result", "id" => written_id, "name" => s.name, "content" => Any[copy(x) for x in s.output])])
end

const _INPUT_FIELD = Field("input", "input", jobj("type" => "object"))

"One call writer, used for written turns and the bind-time sample (§6)."
function call_text(p::Plan, r::Resolved, call)
    fmt = get(p.turn_input_formats, r.purpose, nothing)
    input = something(get(call, "input", nothing), JObj())
    body = if fmt === nothing
        json_text(input; spaced=true, code="format-write-error")
    else
        try
            ps = as_parts(fmt.write(input, _INPUT_FIELD), "spelling.input_format")
            any(x -> get(x, "type", nothing) != "text" || !(get(x, "text", nothing) isa AbstractString), ps) && error("argument writer must return only text parts")
            join(x["text"] for x in ps)
        catch err
            err isa Refusal && rethrow()
            refuse("format-write-error", "spelling.input_format on purpose $(pyrepr(r.purpose)): $(sprint(showerror, err))")
        end
    end
    spell_turn(r.transport.spelling["call"], OrderedDict("id" => pystr(something(get(call, "id", nothing), "")),
        "name" => pystr(something(get(call, "name", nothing), "")), "input" => body))
end

"The rendered request prefix that does not depend on inputs (§3): the cache-stable bytes."
function prefix(p::Plan; turns=nothing)
    stop = nothing
    names = Set(f.name for f in p.visible_inputs)
    compiled = p.adapter.compiled
    for (i, (_, nodes)) in enumerate(compiled)
        if nodes !== nothing && _depends_on_inputs(nodes, names)
            stop = i - 1
            break
        end
    end
    put_roles = Set(split(place, ':'; limit=2)[2] for (fname, place) in p.puts
                    if startswith(place, "message:") && field_named(p.signature, fname).direction == "input")
    for (i, (msg, nodes)) in enumerate(compiled)
        if nodes !== nothing && msg["role"] in put_roles
            stop = stop === nothing ? i - 1 : min(stop, i - 1)
            break
        end
    end
    varies = "system" in put_roles || (stop !== nothing && any(nodes !== nothing && msg["role"] == "system" for (msg, nodes) in compiled[stop+1:end]))
    varies && return jobj("messages" => Any[])
    r = _render(p, Turn(fingerprint(p), JObj()), _slot_values(p, turns); stop_at=stop)
    out = JObj()
    r.system === nothing || (out["system"] = r.system)
    out["messages"] = r.messages
    out
end

skeleton(p::Plan) = reader_skeleton(p.reader)

# ------------------------------------------------------------------ parse

"The one batch parse path, shared by `read`, `parse` and stream EOF: `(values, captures, repairs)`."
function parse_with_captures(p::Plan, response; continued=true)
    reason = finish_reason(response)
    cut = reason in ("length", "error") ? reason : nothing   # §4a: truncated, interrupted
    text, parts = response_text_and_parts(response)
    _refuse_filtered(response, parts)   # §4a: before anything is read
    lead = continued && !isempty(p.prefill) ? p.prefill : ""
    text = lead * text
    atoms = _atoms(parts, p.find_rules, blen(lead))
    edits = Vector{Edit}[]
    repairs = JObj[]
    isempty(p.find_repairable) || ((text, repairs) = repair_markers(text, p.find_repairable; edits=edits))
    text, found = apply_find_rules(text, parts, p.find_rules, pattern_binding(p); edits=edits)
    complete = any(pytruthy(get(r, "complete_reply", false)) && haskey(found, n) && !isempty(found[n].parts) for (n, r) in p.find_rules)
    names = [f.name for f in p.visible_outputs]
    derived = p.reader isa DerivedReader
    to_end = Set{String}()
    missing_err = nothing
    result = nothing
    raw = try
        if derived
            result = derived_read(p.reader, text, names; allow_missing=true, edits=edits)
            to_end = result.to_end
            append!(repairs, result.repairs)
            result.raw
        else
            JObj(String(k) => v for (k, v) in reader_split(p.reader, text, names))
        end
    catch err
        if err isa Refusal
            cut !== nothing && !derived && _refuse_cut(p, cut, "", JObj(); why=err.hint)
            (err.code == "parse-missing-fields" && err.partial isa AbstractDict) || rethrow()
            missing_err = err
            JObj(String(k) => v for (k, v) in err.partial)
        else
            cut !== nothing && !derived && _refuse_cut(p, cut, "", JObj(); why=sprint(showerror, err))
            refuse("reader-error", "reader $(pyrepr(p.adapter.reader["kind"])) failed to read the reply: $(sprint(showerror, err))")
        end
    end
    missing = [n for n in names if !haskey(raw, n)]
    if cut !== nothing
        ended = JObj(k => v for (k, v) in raw if !(k in to_end))
        isempty(missing) || _refuse_cut(p, cut, "before field $(pyrepr(missing[1]))", ended)
        isempty(to_end) || _refuse_cut(p, cut, "inside field $(pyrepr(names[findfirst(n -> n in to_end, names)]))", ended)
        derived || _refuse_cut(p, cut, "", ended)
    end
    if !isempty(missing) && !complete
        missing_err === nothing || throw(missing_err)
        refuse_missing(raw, names)
    end
    captures = OrderedDict{String,Capture}()
    for f in p.visible_outputs
        haskey(raw, f.name) && (captures[f.name] = capture_of_text(raw[f.name]))
    end
    if !isempty(atoms) && derived
        placed, ignored = _place_atoms(atoms, edits, result)
        for (name, inside) in placed
            haskey(captures, name) && (captures[name] = _interleaved(result.text, result.spans[name], inside, raw[name]))
        end
        append!(repairs, [jobj("repair" => "ignored", "part" => get(x, "type", nothing)) for x in ignored])
    end
    for (n, c) in found
        captures[n] = c
    end
    values = JObj()
    for f in p.visible_outputs
        haskey(captures, f.name) && (values[f.name] = _read_forgiving(p, f, captures[f.name], repairs))
    end
    for (n, c) in found
        values[n] = _read_forgiving(p, field_named(p.signature, n), c, repairs)
    end
    (values, captures, repairs)
end

function _read_forgiving(p::Plan, f::Field, c::Capture, repairs)
    try
        return read_field(p, f, c)
    catch err
        (err isa Refusal && !p.adapter.strict && err.code == "parse-value" && format_for(p, f) === SCALAR_DEFAULT) || rethrow()
        v = forgive_value(f.shape, text(c), "field $(pyrepr(f.name))")
        push!(repairs, jobj("repair" => "value", "field" => f.name, "saw" => wstrip(text(c)), "as" => spell_value(f.shape, v, "field $(pyrepr(f.name))")))
        return v
    end
end

"§4a: a reply the provider stopped is not an answer, whether or not its text reads."
function _refuse_filtered(response, parts)
    i = findfirst(q -> get(q, "type", nothing) == "refusal", parts)
    i === nothing && finish_reason(response) != "content_filter" && return
    hint = if i !== nothing
        t = get(parts[i], "text", "")
        said = wstrip(t isa AbstractString ? t : "")
        "the model declined to answer" * (isempty(said) ? "" : ": $(pyrepr(said))")
    else
        "the provider stopped the reply (finish_reason content_filter: its safety filter, or the model declining)"
    end
    refuse("parse-filtered", hint * "; the same request would be stopped again, so change the request or the model rather than asking again"; partial=JObj())
end

"§4a: the provider cut the reply (at its length limit, or by an error); say where, keep what ended."
function _refuse_cut(p::Plan, reason, where, partial; why="")
    error = reason == "error"
    cause = error ? "the provider ended the reply in error" : "the provider cut the reply at its length limit"
    remedy = error ? "send the request again" : "raise max_tokens or ask for less"
    hint = if !isempty(where)
        "$cause $where"
    else
        "$cause; reader $(pyrepr(p.adapter.reader["kind"])) cannot tell which outputs ended before it" * (isempty(why) ? "" : " ($why)")
    end
    error && refuse("parse-interrupted", hint * "; " * remedy; partial=partial)
    refuse("parse-truncated", hint * "; " * remedy; partial=partial)
end

"""
    read(plan, response) -> Reading

The typed values of a reply, every repair made to read them (§4a), and what
its data parts measured (§3). `response`: text, an lm15 message or response.
"""
function read(p::Plan, response)
    probs, measured = reply_probabilities(response)
    values, _, repairs = parse_with_captures(p, response)
    Reading(values, repairs, probs, measured)
end

"The typed values of a reply: `read(plan, response).values`."
parse(p::Plan, response) = read(p, response).values

pattern_binding(p::Plan) = (for r in values(p.extensions); ext_family(r.binding) == "pattern" && return r.binding; end; nothing)

# ------------------------------------------------------------------ atoms (§4b)

function _atoms(parts, find_rules, shift)
    claimed = Set(r["from"][6:end] for (_, r) in find_rules if startswith(r["from"], "part:"))
    out = Tuple{Int,JObj}[]
    pos = shift
    for x in parts
        t = get(x, "type", nothing)
        if t in ("text", "data")
            pos += blen(part_text(x))
        elseif !(t in claimed)
            push!(out, (pos, x))
        end
    end
    out
end

function _map_offset(offset, stages)
    for stage in stages
        shift = 0
        for (a, b, n) in stage
            offset <= a && break
            offset < b && return nothing
            shift += n - (b - a)
        end
        offset += shift
    end
    offset
end

function _place_atoms(atoms, edits, result)
    placed = OrderedDict{String,Vector{Tuple{Int,JObj}}}()
    ignored = JObj[]
    for (offset, part) in atoms
        o = _map_offset(offset, edits)
        owner = nothing
        if o !== nothing
            for (name, (a, b)) in result.spans
                if a <= o <= b
                    owner = name
                    break
                end
            end
        end
        owner === nothing ? push!(ignored, part) : push!(get!(placed, owner, Tuple{Int,JObj}[]), (o, part))
    end
    (placed, ignored)
end

function _interleaved(text, span, inside, raw)
    a, b = span
    seq = Any[]
    pos = a
    for (o, part) in sort(inside; by=first)
        push!(seq, textpart(bsl(text, pos, o)), part)
        pos = o
    end
    push!(seq, textpart(bsl(text, pos, b)))
    get(seq[1], "type", nothing) == "text" && (seq[1] = textpart(wlstrip(seq[1]["text"])))
    get(seq[end], "type", nothing) == "text" && (seq[end] = textpart(wrstrip(seq[end]["text"])))
    Capture(Any[x for x in seq if get(x, "type", nothing) != "text" || !isempty(x["text"])], raw)
end

function _bare_slots(nodes)
    out = Set{String}()
    for n in nodes
        if n isa SlotNode && !occursin('.', n.path)
            push!(out, n.path)
        elseif n isa GuardNode
            union!(out, _bare_slots(branches(n)))
        end
    end
    out
end

function _depends_on_inputs(nodes, names)
    for n in nodes
        n isa SlotNode && n.path in names && return true
        n isa LoopNode && !over_turns(n) && (n.source == "inputs" || _depends_on_inputs(n.body, names)) && return true
        n isa GuardNode && (n.slot in names || _depends_on_inputs(branches(n), names)) && return true
    end
    false
end

const _MISSING = Symbol("missing")
function _get_path(target, path)
    for k in split(path, '.')
        (isobj(target) && haskey(target, k)) || return _MISSING
        target = target[k]
    end
    target
end
function _set_path!(target, path, value)
    keys = split(path, '.')
    for k in keys[1:end-1]
        haskey(target, k) || (target[String(k)] = JObj())
        target = target[k]
    end
    target[String(keys[end])] = value
end

function _merge_setting!(p::Plan, path, value, owner, setting_owner, conflict_path)
    existing = _get_path(p.request_settings, path)
    existing !== _MISSING && !json_equal(existing, value) && refuse("setting-conflict",
        "$(pyrepr(owner)) and $(pyrepr(get(setting_owner, path, nothing))) disagree on request control $(pyrepr(path))";
        fix=jobj("action" => "edit-entry", "path" => conflict_path))
    _set_path!(p.request_settings, path, value)
    haskey(setting_owner, path) || (setting_owner[path] = owner)
end

# --------------------------------------------------------- derived reader

function _output_holes(nodes, sig, holes)
    for node in nodes
        if node isa GuardNode
            inner = Any[]
            _output_holes(branches(node), sig, inner)
            isempty(inner) || refuse("not-readable", "the output pattern cannot sit inside a {% if %} guard: the reply's shape must not depend on which turns were given";
                fix=jobj("action" => "edit-template", "path" => "template"))
        elseif node isa LoopNode && over_turns(node)
            continue
        elseif node isa LoopNode
            if node.source == "outputs" && any(n -> n isa SlotNode && n.path == "$(node.var).value", node.body)
                push!(holes, (:loop, node))
            else
                _output_holes(node.body, sig, holes)
            end
        elseif node isa SlotNode
            f = field_named(sig, node.path)
            f !== nothing && f.direction == "output" && push!(holes, (:slot, node))
        end
    end
end

function _derive_reader(p::Plan)
    sig = p.signature
    found = Tuple{Int,Vector{Node},Vector{Any}}[]
    for (i, (_, nodes)) in enumerate(p.adapter.compiled)
        nodes === nothing && continue
        holes = Any[]
        _output_holes(nodes, sig, holes)
        isempty(holes) || push!(found, (i - 1, nodes, holes))
    end
    isempty(found) && refuse("not-readable", "parse kind 'derived' needs an output pattern — an outputs loop containing {f.value}, or output slots — and the template has none";
        fix=jobj("action" => "edit-template", "path" => "template"))
    length(found) > 1 && refuse("not-readable", "the output pattern must live in one message; found holes in messages $(pyrepr(Any[i for (i, _, _) in found]))";
        fix=jobj("action" => "edit-template", "path" => "template[$(found[2][1])]"))
    index, nodes, holes = found[1]
    here = jobj("action" => "edit-template", "path" => "template[$index]")
    loops = [h for h in holes if h[1] == :loop]
    length(loops) > 1 && refuse("not-readable", "the template has $(length(loops)) output-pattern loops; one pattern"; fix=here)
    anchors = Tuple{String,String,String}[]
    tail = ""
    texts = OrderedDict{String,String}()
    if !isempty(loops)
        length(holes) == 1 || refuse("not-readable", "an outputs loop and bare output slots cannot both form the pattern"; fix=here)
        loop = loops[1][2]
        for f in p.visible_outputs
            pre, post = _instantiate(loop, f, p, here)
            push!(anchors, (f.name, pre, post))
        end
        tail = _tail_after(nodes, loop)
    else
        texts = _literal_segments(nodes, sig)
        for (_, slot) in holes
            f = field_named(sig, slot.path)
            any(v -> v === f, p.visible_outputs) || continue
            push!(anchors, (f.name, get(texts, "before\0$(slot.path)", ""), get(texts, "after\0$(slot.path)", "")))
        end
    end
    for (name, prefix, _) in anchors
        whole = isempty(loops) && length(anchors) == 1 && isempty(wstrip(get(texts, "rest\0$(holes[1][2].path)", "x")))
        if isempty(wrstrip(prefix)) && !whole
            hint = "field $(pyrepr(name)): no literal text before its hole — nothing anchors the parser; put the field's marker before the hole"
            isempty(loops) && (hint *= ", on the same line: a bare slot's marker is the text on its own line (write 'Answer: {$name}' or '<$name>{$name}</$name>', not a marker on the line above), or use an outputs loop")
            refuse("not-readable", hint; fix=merge(here, jobj("field" => name)))
        end
    end
    seen = OrderedDict{String,String}()
    for (name, prefix, _) in anchors
        key = wrstrip(prefix)
        haskey(seen, key) && refuse("not-readable", "fields $(pyrepr(seen[key])) and $(pyrepr(name)) share the anchor $(pyrepr(key)); anchors must tell fields apart";
            fix=merge(here, jobj("field" => name)))
        seen[key] = name
    end
    DerivedReader(anchors, tail, !p.adapter.strict)
end

function _instantiate(loop::LoopNode, f::Field, p::Plan, fix)
    pre, post = IOBuffer(), IOBuffer()
    target = pre
    for node in loop.body
        if node isa TextNode
            write(target, node.text)
        elseif node isa SlotNode
            _, dot, attr = _partition(node.path, '.')
            isempty(dot) && refuse("not-readable", "slot {$(node.path)} inside the output pattern is not invertible"; fix=merge(fix, jobj("slot" => node.path)))
            if attr == "value"
                target === post && refuse("not-readable", "the output-pattern block has two {f.value} holes per field; one value, one hole"; fix=fix)
                target = post
            elseif attr == "name"; write(target, f.name)
            elseif attr == "desc"; write(target, something(f.desc, ""))
            elseif attr == "type"; write(target, something(f.type, ""))
            elseif attr == "schema"; write(target, schema_hint(p, f))
            elseif attr == "purpose"; write(target, f.purpose)
            else
                refuse("not-readable", "slot {$(node.path)} inside the output pattern is not invertible"; fix=merge(fix, jobj("slot" => node.path)))
            end
        else
            refuse("not-readable", "nested loops inside the output-pattern block are not invertible"; fix=fix)
        end
    end
    (String(take!(pre)), String(take!(post)))
end

function _tail_after(nodes, loop)
    seen = false
    out = IOBuffer()
    for node in nodes
        node === loop && (seen = true; continue)
        seen || continue
        node isa TextNode ? write(out, node.text) : break
    end
    literal = String(take!(out))
    stripped = String(Base.lstrip(==('\n'), literal))
    occursin('\n', stripped) && return literal[1:ncodeunits(literal)-ncodeunits(stripped)] * split(stripped, '\n'; limit=2)[1] * "\n"
    literal
end

function _literal_segments(nodes, sig)
    out = OrderedDict{String,String}()
    prev = ""
    last = nothing
    firstline(s) = occursin('\n', s) ? String(split(s, '\n'; limit=2)[1]) : s
    for node in nodes
        if node isa TextNode
            prev *= node.text
            continue
        end
        last === nothing || (out["after\0$last"] = firstline(prev))
        f = node isa SlotNode ? field_named(sig, node.path) : nothing
        if node isa SlotNode && f !== nothing && f.direction == "output"
            out["before\0$(node.path)"] = last !== nothing ? prev : String(split(prev, '\n')[end])
            last = node.path
        else
            last = nothing
        end
        prev = ""
    end
    if last !== nothing
        out["after\0$last"] = firstline(prev)
        out["rest\0$last"] = prev
    end
    out
end

# -------------------------------------------------------------- resolve

function _resolve_format(p::Plan, f::Field)
    adp, reg = p.adapter, p.registry
    materialize(b, key) = b isa Format ? b : isreference(b) ? named_format(reg, b["use"], get(b, "options", nothing); where="formats[$(pyrepr(key))]") :
                          load_udf(b, "formats[$(pyrepr(key))]")
    function check(fmt, by, key)
        rebind = jobj("action" => "bind-format", "field" => f.name, "key" => key)
        format_accepts(fmt, f) || refuse("format-shape-mismatch",
            "field $(pyrepr(f.name)): format $(something(fmt.name, by)) accepts $(pyrepr(Any[fmt.accepts...])), but the field's type/shape is $(something(f.type, pyrepr(f.shape)))"; fix=rebind)
        ((fmt.direction == "in" && f.direction == "output") || (fmt.direction == "out" && f.direction == "input")) && refuse("format-direction",
            "field $(pyrepr(f.name)): format $(something(fmt.name, by)) is $(fmt.direction)-only, but the field is an $(f.direction)"; fix=rebind)
        FormatChoice(fmt, by, nothing, nothing)
    end
    has(k) = haskey(adp.formats, k) && !isdescription(adp.formats[k])
    # §5: a key written for every value never writes media as text; whether a format
    # writes text is what it declares, read without running it (a shipped one: text
    # when it says nothing)
    media = holds_media(f.shape)
    function writes_text(b, key)
        isobj(b) && !(b isa Format) && !isreference(b) && return get(b, "writes", "text") == "text"
        materialize(b, key).writes == "text"
    end
    passed_over(key) = media && !names_media(key) && writes_text(adp.formats[key], key)
    choice = if f.type !== nothing && has(f.type)
        check(materialize(adp.formats[f.type], f.type), "artifact:$(f.type)", f.type)
    else
        c = nothing
        for key in structural_keys(f.shape)
            if has(key) && !passed_over(key)
                c = check(materialize(adp.formats[key], key), "artifact:$key", key)
                break
            end
        end
        if c === nothing
            bound = type_binding(reg, f.annotation)
            if bound !== nothing
                c = check(bound, "runtime:$(something(f.type, string(f.annotation)))", format_key(f.type, f.shape))
            else
                d = kernel_default(f.shape)
                if d !== nothing
                    c = FormatChoice(d, "kernel", nothing, nothing)
                elseif haskey(adp.formats, "*") && !passed_over("*")
                    c = check(materialize(adp.formats["*"], "*"), "artifact:*", "*")
                else
                    key = format_key(f.type, f.shape)
                    media && refuse("no-format", "field $(pyrepr(f.name)) ($(something(f.type, pyrepr(f.shape)))) holds media, which text cannot carry to a model, and no format that writes parts is bound for it — bind one in the artifact under $(pyrepr(key)), register one for its type at runtime, or ship one (a format bound under $(pyrepr(key)) is taken even if it writes text)";
                        fix=jobj("action" => "bind-format", "field" => f.name, "key" => key))
                    refuse("no-format", "field $(pyrepr(f.name)) ($(something(f.type, pyrepr(f.shape)))) has a structured shape and no format — bind one in the artifact under its type name or a structural key, register one for its type at runtime, or ship one";
                        fix=jobj("action" => "bind-format", "field" => f.name, "key" => key))
                end
            end
        end
        c
    end
    keys = vcat(f.type !== nothing && !isempty(f.type) ? [f.type] : String[], structural_keys(f.shape))
    choice.resolved_by == "artifact:*" && push!(keys, "*")
    for key in keys
        e = get(adp.formats, key, nothing)
        if isobj(e) && !haskey(e, "language") && haskey(e, "describe")
            choice.described, choice.described_by = e["describe"], "artifact:$key"
            break
        end
    end
    choice
end

# ------------------------------------------------------------------ bind

"""
    bind(adapter, signature; capabilities=Dict(), registry=default_registry())

Join an adapter, a signature and the model's declared facts into a `Plan`.
Every refusal fires here, before any request is sent.
"""
function bind(adapter::Adapter, sig::Signature; capabilities=JObj(), registry::Registry=default_registry())
    caps = JObj(String(k) => v for (k, v) in pairs(capabilities))
    p = Plan(adapter, sig, caps, registry)
    p.extensions = resolve_extensions(adapter, registry)

    # 1. transports per purpose, in signature order
    by_purpose = OrderedDict{String,Field}()
    for f in sig.fields
        f.purpose == "plain" && continue
        haskey(by_purpose, f.purpose) && refuse("purpose-ambiguous",
            "purpose $(pyrepr(f.purpose)) appears on both $(pyrepr(by_purpose[f.purpose].name)) and $(pyrepr(f.name)); a purpose may bind to one field";
            fix=jobj("action" => "edit-signature", "field" => f.name, "purpose" => f.purpose))
        by_purpose[f.purpose] = f
    end
    hidden = Set{String}()
    setting_owner = OrderedDict{String,Any}()
    for f in sig.fields
        f.purpose == "plain" && continue
        b = get(adapter.transports, f.purpose, nothing)
        b === nothing && continue
        t, name = b isa Transport ? (b, "(inline)") : (named_transport(registry, b["use"], get(b, "options", nothing); where="transports[$(pyrepr(f.purpose))]"), b["use"])
        t = bound_transport(select_transport(t, caps, f.purpose, name), f.name)
        res = Resolved(f.purpose, f, t, name)
        push!(p.resolved, res)
        function target(ref, what)
            ref == "@purpose" && return f
            sub = ref[10:end]
            tf = get(by_purpose, "$(f.purpose).$sub", nothing)
            tf === nothing && refuse("unknown-slot",
                "purpose $(pyrepr(f.purpose)): transport $(pyrepr(name)) $what targets $(pyrepr(ref)), but no field bears the purpose $(pyrepr(f.purpose * "." * sub))";
                fix=jobj("action" => "assign-purpose", "purpose" => "$(f.purpose).$sub"))
            tf
        end
        (!t.in_template || !isempty(t.put)) && push!(hidden, f.name)
        for r in t.find
            tf = target(r["to"], "rule")
            push!(p.find_rules, (tf.name, JObj(k => v for (k, v) in r if k != "to")))
            push!(p.rule_owner, res)
            tf !== f && push!(hidden, tf.name)
            if r["to"] == "@purpose.calls" && tf.direction == "output"
                p.calls_field, p.calls_owner = tf.name, res
            end
        end
        for (ref, place) in t.put
            tf = target(ref, "put")
            push!(p.puts, (tf.name, place))
            push!(hidden, tf.name)
            haskey(t.written_as, ref) && (p.written_as[tf.name] = named_format(registry, t.written_as[ref], JObj(); where="transports[$(pyrepr(f.purpose))].written_as"))
        end
        for (role, text) in t.tell
            existing = get(p.tell, role, nothing)
            p.tell[role] = pytruthy(existing) ? existing * "\n" * text : text
        end
        for (path, value) in setting_leaves(t.request_settings)
            _merge_setting!(p, path, value, f.purpose, setting_owner, "transports[$(pyrepr(f.purpose))].request_settings[$(pyrepr(path))]")
        end
    end

    # 2. visibility
    p.visible_inputs = [f for f in inputs(sig) if !(f.name in hidden)]
    p.visible_outputs = [f for f in outputs(sig) if !(f.name in hidden)]

    # 3. one format per field (§5)
    for f in sig.fields
        p.formats[f.name] = _resolve_format(p, f)
    end
    routed = OrderedDict{String,Set{String}}()
    for (fname, r) in p.find_rules
        kind = startswith(r["from"], "part:") ? r["from"][6:end] : "text"
        push!(get!(routed, fname, Set{String}()), kind)
    end
    for (fname, kinds) in routed
        fmt = p.formats[fname].format
        f = field_named(sig, fname)
        !("*" in fmt.reads) && !issubset(kinds, Set(fmt.reads)) && refuse("format-capture-mismatch",
            "field $(pyrepr(fname)): its find rules deliver $(sortedrepr(kinds)) parts, but its format $(something(fmt.name, "(inline)")) reads $(pyrepr(Any[fmt.reads...]))";
            fix=jobj("action" => "bind-format", "field" => fname, "key" => format_key(f.type, f.shape)))
    end
    for (fname, place) in p.puts
        fmt = haskey(p.written_as, fname) ? p.written_as[fname] : p.formats[fname].format
        f = field_named(sig, fname)
        startswith(place, "request.") && fmt.writes != "parts" && refuse("format-put-mismatch",
            "field $(pyrepr(fname)): put $(pyrepr(place)) needs parts, but its format $(something(fmt.name, "(inline)")) writes text";
            fix=jobj("action" => "bind-format", "field" => fname, "key" => format_key(f.type, f.shape)))
    end

    # 4. the reader; its gate and request settings
    p.reader = adapter.reader["kind"] == "derived" ? _derive_reader(p) : named_reader(registry, adapter.reader)
    delims = String[d for (_, r) in p.find_rules if pytruthy(get(r, "repair", false)) for d in r["between"]]
    p.find_repairable, p.find_unrepaired = adapter.strict ? (String[], String[]) : repairable_markers(delims)
    for fact in reader_requires(p.reader)
        pytruthy(get(caps, fact, nothing)) || refuse("capability-missing",
            "reader $(pyrepr(adapter.reader["kind"])) requires capability $(pyrepr(fact)), which the model does not declare — use an invertible pattern instead";
            fix=jobj("action" => "declare-capability", "fact" => fact))
    end
    for (path, value) in setting_leaves(something(reader_request_settings(p.reader, p.visible_outputs), JObj()))
        validate_setting_path(path, "parse")
        _merge_setting!(p, path, value, "(reader)", setting_owner, "transports[$(pyrepr(get(setting_owner, path, nothing)))].request_settings[$(pyrepr(path))]")
    end
    stops = get(reader_skeleton(p.reader), "stops", Any[])
    if pytruthy(get(caps, "stop_sequences", nothing)) && !isempty(stops)
        _merge_setting!(p, "config.stop", Any[stops...], "(skeleton)", setting_owner,
            "transports[$(pyrepr(get(setting_owner, "config.stop", nothing)))].request_settings['config.stop']")
    end

    # 4b. a put into the request may not share a path with a fixed setting or another put
    overlaps(a, b) = a == b || startswith(a, b * ".") || startswith(b, a * ".")
    fixed = [path for (path, _) in setting_leaves(p.request_settings)]
    seen_puts = Tuple{String,String}[]
    for (fname, place) in p.puts
        startswith(place, "request.") || continue
        path = place[9:end]
        where = "transports[$(pyrepr(split(field_named(sig, fname).purpose, '.')[1]))].put"
        ci = findfirst(q -> overlaps(path, q), fixed)
        oi = findfirst(x -> overlaps(path, x[2]), seen_puts)
        (ci !== nothing || oi !== nothing) && refuse("setting-conflict", "field $(pyrepr(fname)) is put at request $(pyrepr(path)), which " *
            (ci !== nothing ? "the request setting $(pyrepr(fixed[ci])) also sets" : "field $(pyrepr(seen_puts[oi][1])) is also put at") *
            " — one would silently overwrite the other"; fix=jobj("action" => "edit-entry", "path" => where))
        push!(seen_puts, (fname, path))
    end

    # 5. template validation + input coverage
    known = Set(f.name for f in sig.fields)
    input_names = Set(f.name for f in p.visible_inputs)
    covered = Set{String}()
    slot_names = Set(keys(adapter_turn_slots(adapter)))
    for (i, (_, nodes)) in enumerate(adapter.compiled)
        nodes === nothing && continue
        union!(covered, validate_nodes(nodes; known_fields=known, input_fields=input_names, where="template[$(i-1)]", slots=slot_names))
    end
    uncovered = sort(collect(setdiff(input_names, covered)))
    isempty(uncovered) || refuse("field-uncovered", "input field(s) never rendered by the template: " * join(pyrepr.(uncovered), ", ");
        fix=jobj("action" => "edit-template", "path" => "template", "field" => uncovered[1]))

    # 6. written by the template and carried by a transport is ambiguous
    put_inputs = Set(fname for (fname, _) in p.puts if field_named(sig, fname).direction == "input")
    for (i, (_, nodes)) in enumerate(adapter.compiled)
        nodes === nothing && continue
        for fname in sort(collect(intersect(_bare_slots(nodes), put_inputs)))
            refuse("field-double-covered", "template[$(i-1)]: input $(pyrepr(fname)) has a slot here and is also put by its transport — it would be sent twice; drop the slot or the put";
                fix=jobj("action" => "edit-template", "path" => "template[$(i-1)]", "field" => fname))
        end
    end
    visible_out = Set(f.name for f in p.visible_outputs)
    for (fname, _) in p.find_rules
        fname in visible_out && refuse("field-double-covered", "field $(pyrepr(fname)) is both a parsed section and a rule target — hide it (in_template: false) or drop the rule";
            fix=jobj("action" => "edit-entry", "path" => "transports[$(pyrepr(field_named(sig, fname).purpose))].in_template"))
    end

    # 7. the turns probe (§6)
    if p.calls_owner !== nothing
        for r in p.resolved
            if r !== p.calls_owner && (haskey(r.transport.spelling, "call") || haskey(r.transport.spelling, "result"))
                where = "transports[$(pyrepr(r.purpose))].spelling"
                refuse("entry-malformed", "$where: spelling.call/spelling.result belong to the transport that owns the calls field ($(pyrepr(p.calls_owner.purpose))); here they would be a second spelling of one call, or a spelling nothing uses";
                    fix=jobj("action" => "edit-entry", "path" => where))
            end
        end
    end
    for r in p.resolved
        haskey(r.transport.spelling, "call") || continue
        ci = findfirst(x -> field_named(sig, x[1]).purpose == "$(r.purpose).calls", p.find_rules)
        calls_field = ci === nothing ? nothing : p.find_rules[ci][1]
        ref = get(r.transport.spelling, "input_format", nothing)
        if ref !== nothing
            where = "transports[$(pyrepr(r.purpose))].spelling.input_format"
            fmt = named_format(registry, ref["use"], get(ref, "options", nothing); where=where)
            (fmt.writes == "text" && fmt.direction in ("in", "both") && format_accepts(fmt, _INPUT_FIELD)) ||
                _malformed(where, "$where: must write an object as text")
            p.turn_input_formats[r.purpose] = fmt
        end
        if calls_field === nothing
            (ref !== nothing || haskey(r.transport.spelling, "probe")) && refuse("spelling-drift",
                "purpose $(pyrepr(r.purpose)): formatted turns need an @purpose.calls target"; fix=jobj("action" => "edit-entry", "path" => "transports[$(pyrepr(r.purpose))].spelling"))
            continue
        end
        probe = merge(jobj("id" => "probe"), something(get(r.transport.spelling, "probe", nothing), jobj("name" => "probe", "input" => jobj("probe" => true))))
        own = [(n, rt) for (n, rt) in p.find_rules if n == calls_field && rt["from"] == "text"]
        read_back = nothing
        spelled = "(writer refused)"
        try
            spelled = call_text(p, r, probe)
            _, got = apply_find_rules(spelled, Any[], own, pattern_binding(p))
            haskey(got, calls_field) && !isempty(got[calls_field].parts) && (read_back = read_field(p, field_named(sig, calls_field), got[calls_field]))
        catch err
            err isa Refusal || rethrow()
            read_back = nothing
        end
        first_call = isarr(read_back) && length(read_back) == 1 ? read_back[1] : nothing
        ok = isobj(first_call) && get(first_call, "name", nothing) == probe["name"] && json_equal(get(first_call, "input", nothing), probe["input"])
        ok || refuse("spelling-drift",
            "purpose $(pyrepr(r.purpose)): transport $(pyrepr(r.name)): spelling.call spells a call as $(pyrepr(spelled)), and its own find rule and format read back $(pyrepr(read_back)) — the spelling and the reader disagree";
            fix=jobj("action" => "edit-entry", "path" => "transports[$(pyrepr(r.purpose))].spelling"))
    end

    # 8. turn slots (§3a): layout, then a writer for every hidden output
    p.slots = adapter_turn_slots(adapter)
    p.prefill = pytruthy(get(caps, "assistant_prefill", nothing)) ? wrstrip(something(adapter_prefill(adapter), "")) : ""
    _bind_turns(p)
    p
end

function _bind_turns(p::Plan)
    sig = p.signature
    compiled = p.adapter.compiled
    for (name, (_, i)) in p.slots
        field_named(sig, name) === nothing || refuse("turns-layout", "template[$i]: turn slot $(pyrepr(name)) has the name of a signature field; rename the slot";
            fix=jobj("action" => "edit-template", "path" => "template[$i]"))
    end
    names = Set(f.name for f in p.visible_inputs)
    li = findfirst(x -> x[2] !== nothing && x[1]["role"] != "system" && _depends_on_inputs(x[2], names), compiled)
    live = li === nothing ? nothing : li - 1
    for (name, (form, i)) in p.slots
        (form == "messages" && live !== nothing) || continue
        name != "steps" && i > live && refuse("turns-layout",
            "template[$i]: turn slot $(pyrepr(name)) comes after the message that renders the live input (template[$live]); past turns go before it";
            fix=jobj("action" => "edit-template", "path" => "template[$i]"))
        name == "steps" && i < live && refuse("turns-layout",
            "template[$i]: the current turn's steps come after the message that renders its input (template[$live])";
            fix=jobj("action" => "edit-template", "path" => "template[$i]"))
    end
    isempty(p.slots) && return
    drift(field, owner, why) = refuse("spelling-drift", "field $(pyrepr(field)): $why"; fix=jobj("action" => "edit-entry", "path" => "transports[$(pyrepr(owner.purpose))].spelling"))
    groups = OrderedDict{String,Vector{Tuple{String,JObj,Resolved}}}()
    for (idx, (fname, r)) in enumerate(p.find_rules)
        field_named(sig, fname).direction == "output" || continue
        key = startswith(r["from"], "part:") ? "channel\0" * r["from"] :
              (k = first(x for x in ("between", "line_prefixed", "pattern") if haskey(r, x)); k * "\0" * json_text(r[k]))
        push!(get!(groups, key, Tuple{String,JObj,Resolved}[]), (fname, r, p.rule_owner[idx]))
    end
    replay_types = Set{String}()
    for (key, members) in groups
        startswith(key, "channel\0") || continue
        names_ = [m[1] for m in members]
        if p.calls_field !== nothing && p.calls_field in names_
            p.turn_writers[p.calls_field] = jobj("by" => "format:parts")
            for other in names_
                other == p.calls_field || (p.turn_writers[other] = jobj("by" => "projection", "of" => p.calls_field))
            end
        else
            from = key[9:end]
            push!(replay_types, split(from, ':'; limit=2)[2])
            for n in names_
                p.turn_writers[n] = jobj("by" => "replayed")
            end
        end
    end
    p.replay_types = replay_types
    for (key, members) in groups
        startswith(key, "channel\0") && continue
        names_ = [m[1] for m in members]
        if p.calls_field !== nothing && p.calls_field in names_
            owner = p.calls_owner
            haskey(owner.transport.spelling, "call") || drift(p.calls_field, owner, "calls are read from text, but the transport has no spelling.call to write past calls")
            p.turn_writers[p.calls_field] = jobj("by" => "spelling.call", "position" => "after")
            for other in names_
                other == p.calls_field || (p.turn_writers[other] = jobj("by" => "projection", "of" => p.calls_field))
            end
            continue
        end
        distinct = unique(names_)
        length(distinct) > 1 && drift(names_[2], members[2][3], "fields $(sortedrepr(distinct)) read the same capture and none of them is the calls field; which writes it is ambiguous")
        fname, r, owner = members[1]
        sp = owner.transport.spelling
        position = get(sp, "position", "after")
        if haskey(sp, "value")
            p.turn_writers[fname] = sp["value"] === nothing ? jobj("by" => "dropped") : jobj("by" => "spelling.value", "template" => sp["value"], "position" => position)
        elseif !pytruthy(get(r, "remove", false))
            p.turn_writers[fname] = jobj("by" => "projection", "of" => "the reader body")
            continue
        elseif haskey(r, "between")
            p.turn_writers[fname] = jobj("by" => "derived:between", "between" => Any[r["between"]...], "position" => position)
        elseif haskey(r, "line_prefixed")
            p.turn_writers[fname] = jobj("by" => "derived:line_prefixed", "prefix" => r["line_prefixed"], "position" => position)
        else
            drift(fname, owner, "a pattern rule has a reader but no writer; declare spelling.value (text with {value}) or spelling.value: null to drop it on purpose")
        end
        if p.turn_writers[fname]["by"] != "dropped"
            fmt = format_for(p, field_named(sig, fname))
            (!fmt.round_trip || fmt.writes != "text" || !(fmt.direction in ("both", "in"))) && drift(fname, owner,
                "its format $(something(fmt.name, "(inline)")) cannot write the value back as text (it reads only, is lossy, or writes parts), so a past value cannot be written into a turn; give it a write, or spelling.value: null")
        end
    end
    if p.calls_field !== nothing
        fmt = format_for(p, field_named(sig, p.calls_field))
        fmt.direction in ("both", "in") || drift(p.calls_field, p.calls_owner, "its format $(something(fmt.name, "(inline)")) only reads, so past calls cannot be written")
    end
end

# ---------------------------------------------------------------- describe

function describe(p::Plan)
    found = Set(n for (n, _) in p.find_rules)
    ch(f) = p.formats[f.name]
    desc(f) = ch(f).described_by === nothing ? JObj() : jobj("described_by" => ch(f).described_by)
    vi, vo = Set(f.name for f in p.visible_inputs), Set(f.name for f in p.visible_outputs)
    fieldinfo(f) = merge(jobj("name" => f.name, "type" => f.type, "shape" => f.shape, "format" => something(ch(f).format.name, "(inline)"),
        "resolved_by" => ch(f).resolved_by), desc(f))
    out = jobj("adapter" => p.adapter.name, "reader" => jobj("kind" => p.adapter.reader["kind"]), "capabilities" => copy(p.capabilities),
        "inputs" => Any[fieldinfo(f) for f in p.visible_inputs],
        "outputs" => Any[merge(fieldinfo(f), jobj("found" => f.name in found)) for f in p.visible_outputs],
        "hidden" => Any[f.name for f in p.signature.fields if !(f.name in vi) && !(f.name in vo)],
        "transports" => JObj(r.purpose => r.name for r in p.resolved),
        "extensions" => JObj(n => resolved_describe(r) for (n, r) in sort(collect(p.extensions); by=first)),
        "find" => Any[merge(jobj("field" => n), r) for (n, r) in p.find_rules],
        "puts" => Any[jobj("field" => n, "at" => place) for (n, place) in p.puts],
        "tell" => copy(p.tell), "request_settings" => deepcopy_json(p.request_settings), "strict" => p.adapter.strict)
    pf = adapter_prefill(p.adapter)
    pf === nothing || (out["prefill"] = jobj("text" => wrstrip(pf), "sent" => !isempty(p.prefill)))
    out["skeleton"] = skeleton(p)
    out["streaming"] = describe_streaming(p)
    if p.reader isa DerivedReader
        out["reader"]["anchors"] = Any[Any[a...] for a in p.reader.anchors]
        isempty(p.reader.unrepaired) || (out["reader"]["unrepaired"] = Any[p.reader.unrepaired...])
        isempty(p.reader.tail) || (out["reader"]["tail"] = p.reader.tail)
    else
        spec = reader_spec(p.reader)
        spec === nothing || for (k, v) in spec
            k == "kind" || (out["reader"][k] = v)
        end
    end
    vocab = JObj()
    for c in values(p.formats)
        c.format.name !== nothing && haskey(p.registry.formats, c.format.name) && (vocab["format/$(c.format.name)"] = p.registry.formats[c.format.name].version)
    end
    for r in p.resolved
        haskey(p.registry.transports, r.name) && (vocab["transport/$(r.name)"] = p.registry.transports[r.name].version)
    end
    k = p.adapter.reader["kind"]
    haskey(p.registry.readers, k) && (vocab["reader/$k"] = p.registry.readers[k].version)
    turn_info = JObj()
    for r in p.resolved
        haskey(p.turn_input_formats, r.purpose) || continue
        ref = r.transport.spelling["input_format"]
        v = p.registry.formats[ref["use"]].version
        vocab["format/$(ref["use"])"] = v
        turn_info[r.purpose] = jobj("input_format" => deepcopy_json(ref), "version" => v)
    end
    out["turns"] = jobj("slots" => Any[jobj("name" => n, "form" => form) for (n, (form, _)) in p.slots],
        "steps" => isempty(p.slots) ? nothing : haskey(p.slots, "steps") ? "placed" : "after the template",
        "replay" => p.adapter.replay,
        "writers" => JObj(k => deepcopy_json(v) for (k, v) in p.turn_writers if !(v["by"] in ("projection", "replayed"))),
        "projections" => JObj(k => v["of"] for (k, v) in p.turn_writers if v["by"] == "projection"),
        "replayed" => Any[sort([k for (k, v) in p.turn_writers if v["by"] == "replayed"])...],
        "input_formats" => turn_info)
    out["versions"] = jobj("kernel" => KERNEL_VERSION, "vocab" => vocab)
    out
end

function explain(p::Plan)
    d = describe(p)
    lines = ["adapter: $(d["adapter"])", "reader: $(d["reader"]["kind"])"]
    for f in d["inputs"]
        push!(lines, "input  $(rpad(f["name"], 20)) $(f["format"]) ($(f["resolved_by"]))")
    end
    for f in d["outputs"]
        push!(lines, "output $(rpad(f["name"], 20)) $(f["format"]) ($(f["resolved_by"]))$(f["found"] ? " + rule" : "")")
    end
    for h in d["hidden"]
        push!(lines, "hidden $(rpad(h, 20)) served by transport/put")
    end
    isempty(d["request_settings"]) || push!(lines, "request_settings: $(json_text(d["request_settings"]))")
    join(lines, "\n")
end

# ---------------------------------------------------------- lm15 bridge stubs

"""
The caller's `Config` contradicts what the plan's request settings require (a
transport or reader asked for them). Thrown by `lm15_request` unless `override=true`.
"""
struct ConfigConflict <: Exception
    msg::String
end
Base.showerror(io::IO, e::ConfigConflict) = print(io, e.msg)

"Deep-merge the caller's settings under the plan's; a contradiction throws `ConfigConflict`."
function merge_settings(base::AbstractDict, extra::AbstractDict; path="", override=false)
    out = JObj(String(k) => v for (k, v) in base)
    for (k, v) in extra
        here = isempty(path) ? k : "$path.$k"
        if haskey(out, k) && isobj(out[k]) && isobj(v)
            out[k] = merge_settings(out[k], v; path=here, override=override)
        elseif haskey(out, k) && !json_equal(out[k], v) && !override
            throw(ConfigConflict("$here: the plan's request settings require $(json_text(out[k])) (a transport or reader asked for it) but the caller's Config says $(json_text(v)); pass override=true to insist"))
        else
            out[k] = v
        end
    end
    out
end

"""
    lm15_request(rendered; model, config=nothing, override=false) -> LM15.Request

The lm15 request for a rendered plan (needs `using LM15`): the plan's request
settings are the base, the caller's `LM15.Config` fills the rest.
"""
function lm15_request end

"""
    lm15_stream(plan, events; on_event=nothing) -> (events, StreamResult)

Drive `stream(plan)` from lm15 stream events (needs `using LM15`).
"""
function lm15_stream end

"""
    lm15_install!(registry=default_registry()) -> registry

Bind lm15's media part types (`LM15.ImagePart`, `AudioPart`, `VideoPart`,
`DocumentPart`, `BinaryPart`; needs `using LM15`) in `registry`: each lowers
to `{"media": kind}`, crosses by the format that shape resolves (the
kernel's media default unless the artifact binds one), and has lm15's
canonical part data (`LM15.to_dict`, `type` included) as its JSON form, so
an lm15 part is a value for a media field of its kind, a turn saves it as
that data and `load_turn` rebuilds the part. A part given by `path` keeps
its path: lm15 reads the file. Loading the extension binds them in the
default registry.
"""
function lm15_install! end

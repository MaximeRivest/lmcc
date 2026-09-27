# Transports (kernel §6): how a meaning travels, as data.

const _TKEYS = ["when", "requires", "in_template", "tell", "request_settings", "put", "written_as", "find", "spelling"]
const _PRED_KEYS = ["capability", "not", "all", "any"]
const _TO = r"^@purpose(\.[A-Za-z_][A-Za-z0-9_]*)?$"
const _PUT = r"^(request\.[a-z_][a-z0-9_.]*|message:(system|developer|user|assistant))$"
const _FROM = r"^(text|part:[a-z_]+)$"

"The pinned lm15 `Config` fields (lm15 1.0.1, contract 3763eec; kernel §3)."
const LM15_CONFIG_FIELDS = Set(["max_tokens", "temperature", "top_p", "top_k", "stop", "response_format", "tool_choice",
    "reasoning", "cache", "seed", "frequency_penalty", "presence_penalty", "service_tier", "user_id", "store", "logprobs",
    "probabilities", "extensions"])

_malformed(path, hint) = refuse("entry-malformed", hint; fix=jobj("action" => "edit-entry", "path" => path))

function validate_setting_path(path, where)
    seg = split(path, '.')
    ok = seg[1] == "tools" || (seg[1] == "config" && length(seg) >= 2 && seg[2] in LM15_CONFIG_FIELDS)
    ok || _malformed(where, "$where: $(pyrepr(path)) is not a field of an lm15 request — request settings 'config.<field>' ($(join(sort(collect(LM15_CONFIG_FIELDS)), ", "))) or 'tools'; provider-native knobs go under config.extensions")
end

"Request settings as `(dotted path, value)` at the two levels the kernel validates."
function setting_leaves(settings, prefix="")
    out = Tuple{String,Any}[]
    for (k, v) in settings
        if k == "config" && isempty(prefix) && isobj(v)
            append!(out, setting_leaves(v, "config."))
        else
            push!(out, (prefix * k, v))
        end
    end
    out
end

"""
    Transport

`when`, `requires`, `in_template`, `tell`, `request_settings`, `put`,
`written_as`, `find`, `spelling`, or `choose` alternatives
(`[(when=…, use=Transport)…, (else_=Transport,)]`).
"""
mutable struct Transport
    when::Any
    requires::Vector{String}
    in_template::Bool
    tell::JObj
    request_settings::JObj
    put::JObj
    find::Vector{JObj}
    spelling::JObj
    written_as::JObj
    choose::Union{Nothing,Vector{Any}}
end
Transport(; when=nothing, requires=String[], in_template=true, tell=JObj(), request_settings=JObj(), put=JObj(),
    find=JObj[], spelling=JObj(), written_as=JObj(), choose=nothing) =
    Transport(when, requires, in_template, tell, request_settings, put, find, spelling, written_as, choose)

function transport_to_dict(t::Transport)
    if t.choose !== nothing
        return jobj("choose" => Any[haskey(a, :else_) ? jobj("else" => transport_to_dict(a.else_)) :
            jobj("when" => deepcopy_json(a.when), "use" => transport_to_dict(a.use)) for a in t.choose])
    end
    d = JObj()
    t.when === nothing || (d["when"] = deepcopy_json(t.when))
    isempty(t.requires) || (d["requires"] = Any[t.requires...])
    t.in_template || (d["in_template"] = false)
    isempty(t.tell) || (d["tell"] = copy(t.tell))
    isempty(t.request_settings) || (d["request_settings"] = deepcopy_json(t.request_settings))
    isempty(t.put) || (d["put"] = copy(t.put))
    isempty(t.written_as) || (d["written_as"] = copy(t.written_as))
    isempty(t.find) || (d["find"] = Any[copy(r) for r in t.find])
    isempty(t.spelling) || (d["spelling"] = deepcopy_json(t.spelling))
    d
end

_aslist(x) = x === nothing ? Any[] : isarr(x) ? Any[x...] : x isa AbstractString ? Any[string(c) for c in x] : isobj(x) ? Any[keys(x)...] : Any[x]
function _asdict(x, where, key)
    x === nothing && return JObj()
    isobj(x) || _malformed("$where.$key", "$where.$key: must be an object")
    JObj(String(k) => v for (k, v) in x)
end

function transport_from_dict(data, where)
    data isa Transport && (validate_transport(data, where); return data)
    isobj(data) || _malformed(where, "$where: a transport is an object")
    if haskey(data, "choose")
        ch = data["choose"]
        (length(data) == 1 && isarr(ch) && !isempty(ch)) || _malformed(where, "$where: choose is a non-empty list and stands alone")
        alts = Any[]
        for (i, alt) in enumerate(ch)
            aw = "$where.choose[$(i-1)]"
            isobj(alt) || _malformed(aw, "$aw: an alternative is an object")
            if haskey(alt, "else")
                (length(alt) == 1 && i == length(ch)) || _malformed(aw, "$aw: else stands alone and comes last")
                push!(alts, (else_=transport_from_dict(alt["else"], aw),))
            elseif sort(collect(String, keys(alt))) == ["use", "when"]
                validate_predicate(alt["when"], "$aw.when")
                push!(alts, (when=alt["when"], use=transport_from_dict(alt["use"], aw)))
            else
                _malformed(aw, "$aw: an alternative is {when, use} or {else}")
            end
        end
        return Transport(choose=alts)
    end
    unknown = [k for k in keys(data) if !(k in _TKEYS)]
    isempty(unknown) || _malformed(where, "$where: unknown transport key(s) $(sortedrepr(unknown)); known keys are $(pyrepr(Any[_TKEYS...]))")
    haskey(data, "spelling") && !isobj(data["spelling"]) && _malformed("$where.spelling", "$where.spelling: must be an object")
    find = JObj[]
    for (i, r) in enumerate(_aslist(get(data, "find", nothing)))
        isobj(r) || _malformed("$where.find[$(i-1)]", "$where.find[$(i-1)]: a rule is an object")
        push!(find, JObj(String(k) => v for (k, v) in r))
    end
    s = Transport(when=get(data, "when", nothing), requires=Any[r for r in _aslist(get(data, "requires", nothing))],
        in_template=pytruthy(get(data, "in_template", true)), tell=_asdict(get(data, "tell", nothing), where, "tell"),
        request_settings=_asdict(get(data, "request_settings", nothing), where, "request_settings"),
        put=_asdict(get(data, "put", nothing), where, "put"), find=find,
        spelling=_asdict(get(data, "spelling", nothing), where, "spelling"),
        written_as=_asdict(get(data, "written_as", nothing), where, "written_as"))
    validate_transport(s, where)
    s
end

function validate_transport(t::Transport, where)
    if t.choose !== nothing
        for (i, a) in enumerate(t.choose)
            haskey(a, :when) && validate_predicate(a.when, "$where.choose[$(i-1)].when")
            validate_transport(haskey(a, :else_) ? a.else_ : a.use, "$where.choose[$(i-1)]")
        end
        return
    end
    t.when === nothing || validate_predicate(t.when, "$where.when")
    for (i, fact) in enumerate(t.requires)
        (fact isa AbstractString && fact in CAPABILITY_FACTS) ||
            _malformed("$where.requires[$(i-1)]", "$where.requires: $(pyrepr(fact)) is not a capability fact; known: $(sortedrepr(CAPABILITY_FACTS))")
    end
    for (i, r) in enumerate(t.find)
        validate_find_rule(r, "$where.find[$(i-1)]")
    end
    for (target, place) in t.put
        (occursin(_TO, target) && place isa AbstractString && occursin(_PUT, place)) ||
            _malformed("$where.put", "$where.put: $(pyrepr(target)): $(pyrepr(place)) — a put is '@purpose' or '@purpose.<sub>' → 'request.<key>' or 'message:<role>'")
    end
    for (path, _) in setting_leaves(t.request_settings)
        validate_setting_path(path, "$where.request_settings[$(pyrepr(path))]")
    end
    for (_, place) in t.put
        startswith(place, "request.") && validate_setting_path(place[9:end], "$where.put")
    end
    for (target, name) in t.written_as
        (haskey(t.put, target) && name isa AbstractString && !isempty(name)) ||
            _malformed("$where.written_as", "$where.written_as: $(pyrepr(target)) must name a placed field and a format name")
    end
    validate_spelling(t.spelling, "$where.spelling")
    for (k, v) in t.tell
        (k in ("system", "developer", "user", "assistant") && v isa AbstractString) ||
            _malformed("$where.tell", "$where.tell: $(pyrepr(k)) must name a message role, text")
    end
    !t.in_template && isempty(t.find) && isempty(t.put) &&
        _malformed(where, "$where: in_template=false but no rule or put serves the field — the value would be unrecoverable")
end

"Resolve `choose` against the declared facts; check `when` and `requires`."
function select_transport(t::Transport, caps, purpose, name)
    s = t
    while s.choose !== nothing
        chosen = nothing
        for a in s.choose
            if haskey(a, :else_) || eval_predicate(a.when, caps)
                chosen = haskey(a, :else_) ? a.else_ : a.use
                break
            end
        end
        chosen === nothing && refuse("capability-missing",
            "purpose $(pyrepr(purpose)): transport $(pyrepr(name)): no alternative of 'choose' holds for the declared capabilities and there is no else";
            fix=jobj("action" => "satisfy-predicate", "purpose" => purpose, "predicate" => jobj("any" => Any[deepcopy_json(a.when) for a in s.choose])))
        s = chosen
    end
    s.when !== nothing && !eval_predicate(s.when, caps) && refuse("capability-missing",
        "purpose $(pyrepr(purpose)): transport $(pyrepr(name)): 'when' $(pyrepr(s.when)) is false for the declared capabilities";
        fix=jobj("action" => "satisfy-predicate", "purpose" => purpose, "predicate" => deepcopy_json(s.when)))
    for fact in s.requires
        pytruthy(get(caps, fact, nothing)) || refuse("capability-missing",
            "purpose $(pyrepr(purpose)): transport $(pyrepr(name)) requires capability $(pyrepr(fact)), which the model does not declare";
            fix=jobj("action" => "declare-capability", "fact" => fact))
    end
    s
end

"A copy with `{field}` in tell bound to the purpose's field."
bound_transport(t::Transport, field_name) = Transport(when=t.when, requires=copy(t.requires), in_template=t.in_template,
    tell=JObj(k => replace(v, "{field}" => field_name) for (k, v) in t.tell), request_settings=copy(t.request_settings),
    put=copy(t.put), find=[copy(r) for r in t.find], spelling=copy(t.spelling), written_as=copy(t.written_as))

function _write_slots(template::AbstractString)
    names = String[]
    i = 0
    n = blen(template)
    while i < n
        if bstartswith(template, "{{", i) || bstartswith(template, "}}", i)
            i += 2
            continue
        end
        c = bchar(template, i)
        if c == '{'
            j = bfind(template, "}", i)
            j < 0 && return ["?"]
            push!(names, bsl(template, i + 1, j))
            i = j + 1
            continue
        end
        c == '}' && return ["?"]
        i += 1
    end
    names
end

function validate_spelling(sp, where)
    valid = isobj(sp)
    if valid
        valid = all(k -> k in ("call", "result", "input_format", "probe", "value", "position"), keys(sp))
        valid &= all(k -> !haskey(sp, k) || sp[k] isa AbstractString, ("call", "result"))
        if haskey(sp, "value")
            w = sp["value"]
            valid &= w === nothing || (w isa AbstractString && _write_slots(w) == ["value"])
        end
        haskey(sp, "position") && (valid &= sp["position"] in ("before", "after"))
        if haskey(sp, "input_format")
            ref = sp["input_format"]
            valid &= haskey(sp, "call") && isobj(ref) && all(k -> k in ("use", "options"), keys(ref)) &&
                     get(ref, "use", nothing) isa AbstractString && !isempty(ref["use"]) && isobj(get(ref, "options", JObj()))
        end
        if haskey(sp, "probe")
            pr = sp["probe"]
            valid &= haskey(sp, "call") && isobj(pr) && all(k -> k in ("id", "name", "input"), keys(pr)) &&
                     get(pr, "name", nothing) isa AbstractString && !isempty(pr["name"]) && isobj(get(pr, "input", nothing)) &&
                     get(pr, "id", "probe") isa AbstractString && !isempty(get(pr, "id", "probe"))
        end
    end
    valid || _malformed(where, "$where: expected call/result text, input_format {use, options?}, probe {name, input: object, id?} (formatter and probe require call), value (text with one {value} slot, or null) and position (before|after)")
end

"Kernel §6 spelling: the closed slot set, `{{`/`}}` escapes."
function spell_turn(template::AbstractString, slots)
    io = IOBuffer()
    i = 0
    n = blen(template)
    while i < n
        c = bchar(template, i)
        if c == '{' && bstartswith(template, "{{", i)
            write(io, '{'); i += 2; continue
        end
        if c == '}' && bstartswith(template, "}}", i)
            write(io, '}'); i += 2; continue
        end
        if c == '{'
            j = bfind(template, "}", i)
            name = j > i ? bsl(template, i + 1, j) : ""
            if haskey(slots, name)
                write(io, slots[name]); i = j + 1; continue
            end
        end
        write(io, codeunit(template, i + 1))
        i += 1
    end
    String(take!(io))
end

function validate_find_rule(r, where)
    isobj(r) || _malformed(where, "$where: a rule is an object")
    src, to = get(r, "from", nothing), get(r, "to", nothing)
    (src isa AbstractString && occursin(_FROM, src)) || _malformed(where, "$where: 'from' is 'text' or 'part:<part kind>'")
    (to isa AbstractString && occursin(_TO, to)) || _malformed(where, "$where: 'to' is '@purpose' or '@purpose.<sub>'")
    known = ("from", "to", "remove", "between", "pattern", "line_prefixed", "complete_reply", "repair")
    unknown = [k for k in keys(r) if !(k in known)]
    isempty(unknown) || _malformed(where, "$where: unknown rule key(s) $(sortedrepr(unknown))")
    kinds = [k for k in ("between", "pattern", "line_prefixed") if haskey(r, k)]
    if src == "text"
        length(kinds) == 1 || _malformed(where, "$where: a text rule needs exactly one of between/pattern/line_prefixed")
        k = kinds[1]; v = r[k]
        if k == "between"
            (isarr(v) && length(v) == 2 && all(x -> x isa AbstractString && !isempty(x), v)) ||
                _malformed(where, "$where: between is [open, close], non-empty strings")
        else
            (v isa AbstractString && !isempty(v)) || _malformed(where, "$where: $k is a non-empty string")
        end
    end
    haskey(r, "repair") && (!(r["repair"] isa Bool) || src != "text" || !haskey(r, "between")) &&
        _malformed(where, "$where: 'repair' is true or false, on a between rule only (its delimiters are repaired like markers, kernel §4a)")
    src != "text" && (!isempty(kinds) || pytruthy(get(r, "remove", false))) &&
        _malformed(where, "$where: a channel rule takes no text extractor and no remove")
end

function validate_predicate(p, where)
    (isobj(p) && length(p) == 1) || _malformed(where, "$where: a predicate is one of $(pyrepr(Any[_PRED_KEYS...])), one key")
    key, value = first(p)
    if key == "capability"
        value isa AbstractString && !(value in CAPABILITY_FACTS) &&
            _malformed(where, "$where: $(pyrepr(value)) is not a capability fact; known: $(sortedrepr(CAPABILITY_FACTS))")
        value isa AbstractString || _malformed(where, "$where: 'capability' names a fact")
    elseif key == "not"
        validate_predicate(value, "$where.not")
    elseif key in ("all", "any")
        isarr(value) || _malformed(where, "$where: $(pyrepr(key)) takes a list")
        for (j, q) in enumerate(value)
            validate_predicate(q, "$where.$key[$(j-1)]")
        end
    else
        _malformed(where, "$where: unknown predicate key $(pyrepr(key)); known: $(pyrepr(Any[_PRED_KEYS...]))")
    end
end

function eval_predicate(p, caps)
    key, value = first(p)
    key == "capability" && return pytruthy(get(caps, value, nothing))
    key == "not" && return !eval_predicate(value, caps)
    key == "all" && return all(q -> eval_predicate(q, caps), value)
    any(q -> eval_predicate(q, caps), value)
end

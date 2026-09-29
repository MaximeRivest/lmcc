# The adapter (kernel §2) and the artifact (serde, §5, §6, §9, §10).

const KERNEL_VERSION = "0.8.4"
const _SLOT_NAME = r"\A[A-Za-z_][A-Za-z0-9_]*\z"
const REPLAY = ("recorded", "values", "verbatim")

system(text) = jobj("role" => "system", "text" => text)
developer(text) = jobj("role" => "developer", "text" => text)
user(text) = jobj("role" => "user", "text" => text)
assistant(text) = jobj("role" => "assistant", "text" => text)
"A turn slot in messages form (§3a); `turns()` is the slot `turns`."
turns(slot="turns") = slot == "turns" ? jobj("directive" => "turns") : jobj("directive" => "turns", "slot" => slot)
"A reference to a named format or transport: `use(\"table\"; columns=[…])`."
use(name; options...) = jobj("use" => name, "options" => JObj(String(k) => v for (k, v) in options))

"""
    Adapter

A template, a reader, transports by purpose, formats by type — never a field
name. Build with `adapter(...)` or `load(entry)`; it meets a signature at `bind`.
"""
mutable struct Adapter
    template::Vector{JObj}
    reader::JObj
    transports::OrderedDict{String,Any}     # purpose => Transport | reference (use, options)
    formats::OrderedDict{String,Any}        # key => reference | description | Format
    name::String
    extensions::JObj
    replay::String
    strict::Bool
    compiled::Vector{Tuple{JObj,Union{Nothing,Vector{Node}}}}
    guards::Vector{Tuple{String,Int}}
end

"""
A transport's key, checked as it is loaded (§2): a purpose a field can bear,
a name or dotted names (`tools`, `tools.calls`); `""` or `a-b` would key a
transport no field reaches. Returns its path.
"""
function check_purpose(purpose)
    where = "transports[$(pyrepr(purpose))]"
    (purpose isa AbstractString && occursin(_PURPOSE, purpose)) ||
        _malformed(where, "$where: a purpose is a name or dotted names (tools, tools.calls), as a field declares it")
    where
end

"The template's last message when it is an assistant message: the reply's prefill (§3)."
function adapter_prefill(a::Adapter)
    isempty(a.template) && return nothing
    last = a.template[end]
    get(last, "role", nothing) == "assistant" ? last["text"] : nothing
end

"Every placed turn slot: name => (form, 0-based template index) (§3a)."
function adapter_turn_slots(a::Adapter)
    slots = OrderedDict{String,Tuple{String,Int}}()
    guards = Tuple{String,Int}[]
    for (i, (msg, nodes)) in enumerate(a.compiled)
        idx = i - 1
        if nodes === nothing
            placed, guarded, form = [get(msg, "slot", "turns")], String[], "messages"
        else
            placed, guarded = node_turn_slots(nodes)
            form = "text"
        end
        for name in placed
            haskey(slots, name) && refuse("template-syntax", "template[$idx]: turn slot $(pyrepr(name)) is already placed at template[$(slots[name][2])]; a slot is placed once";
                fix=jobj("action" => "edit-template", "path" => "template[$idx]"))
            slots[name] = (form, idx)
        end
        append!(guards, [(g, idx) for g in guarded])
    end
    a.guards = guards
    slots
end

isdescription(b) = isobj(b) && length(b) == 1 && haskey(b, "describe")
isreference(b) = isobj(b) && haskey(b, "use")

function _description(value, where)
    haskey(value, "describe") || return JObj()
    t = value["describe"]
    (t isa AbstractString && !isempty(t)) || _malformed("$where.describe", "$where.describe: a description is non-empty text")
    jobj("describe" => t)
end

"One `formats` entry, normalized (§5)."
function format_entry(key, value)
    where = "formats[$(pyrepr(key))]"
    value isa AbstractString && return jobj("use" => value, "options" => JObj())
    value isa Format && return value
    if isobj(value) && haskey(value, "use")
        extra = sort([String(k) for k in keys(value) if !(k in ("use", "options", "describe"))])
        (isempty(extra) && isobj(get(value, "options", JObj()))) ||
            _malformed(where, "$where: a reference is {use, options?, describe?}" * (isempty(extra) ? "" : ", not $(pyrepr(Any[extra...]))"))
        return merge(jobj("use" => value["use"], "options" => JObj(String(k) => v for (k, v) in get(value, "options", JObj()))), _description(value, where))
    end
    isobj(value) && haskey(value, "language") && return JObj(String(k) => v for (k, v) in value)
    if isobj(value) && haskey(value, "describe")
        length(value) == 1 || _malformed(where, "$where: a description is {describe} alone, not $(pyrepr(sort([String(k) for k in keys(value) if k != "describe"])))")
        d = _description(value, where)
        key == "*" && _malformed(where, "$where: a description alone under '*' describes nothing — '*' reaches only fields no other step spells, and a description chooses no format; put it on the reference ({\"use\": ..., \"describe\": ...}) or under a type or key")
        return d
    end
    _malformed(where, "$where: expected a name, use(...), a shipped format, a description {describe}, or a Format")
end

"""
    adapter(; messages, reader=Dict("kind"=>"derived"), transports, formats, name="adapter",
            extensions=nothing, replay="recorded", strict=false, declare_defaults=true)

Build an adapter. `transports` values: a name, a `Transport`, a Dict, or
`use(...)`. `formats` keys are type names or structural keys; values a name,
`use(...)`, a description `Dict("describe"=>…)`, or a `Format`.
"""
function adapter(; messages=nothing, template=nothing, reader=nothing, transports=nothing, formats=nothing, name="adapter",
                 extensions=nothing, replay="recorded", strict=false, declare_defaults=true)
    msgs = messages === nothing ? template : messages
    isarr(msgs) || _malformed("template", "template must be a list of messages and directives")
    msgs = Any[msgs...]
    for (i, m) in enumerate(msgs)
        at = "template[$(i-1)]"
        (isobj(m) && ((haskey(m, "role") && haskey(m, "text")) || haskey(m, "directive"))) || _malformed(at, "$at: a message is {role, text} or {directive}")
        if haskey(m, "directive")
            slot = get(m, "slot", "turns")
            (m["directive"] == "turns" && all(k -> k in ("directive", "slot"), keys(m)) && slot isa AbstractString && occursin(_SLOT_NAME, slot)) ||
                _malformed(at, "$at: a directive is {\"directive\": \"turns\", \"slot\"?: name} (demos and history are turn slots since kernel 0.7)")
            slot in RESERVED_SLOTS && refuse("template-syntax", "$at: $(pyrepr(slot)) is reserved, not a turn slot"; fix=jobj("action" => "edit-template", "path" => at))
        end
        haskey(m, "role") && !(m["role"] in ("system", "developer", "user", "assistant")) && _malformed(at, "$at: role must be system/developer/user/assistant")
        get(m, "role", nothing) == "system" && any(x -> (haskey(x, "role") && x["role"] != "system") || haskey(x, "directive"), msgs[1:i-1]) &&
            _malformed(at, "$at: system messages lead the template (they become the lm15 request's system field); put later instructions in a developer message")
    end
    replay in REPLAY || _malformed("replay", "replay must be one of $(pyrepr(Any[REPLAY...])), not $(pyrepr(replay))")
    rd = reader === nothing ? jobj("kind" => "derived") : reader
    isobj(rd) || _malformed("reader", "entry.reader must be an object")
    kind = get(rd, "kind", nothing)
    (kind isa AbstractString && !isempty(kind)) || refuse("unknown-reader", "reader.kind must name a reader"; fix=jobj("action" => "edit-entry", "path" => "reader"))
    kind == "derived" && length(rd) != 1 && _malformed("reader", "reader: the derived reader takes only 'kind', not $(pyrepr(sort([String(k) for k in keys(rd) if k != "kind"])))")
    strict isa Bool || _malformed("strict", "strict must be true or false, not $(pyrepr(strict))")
    sb = OrderedDict{String,Any}()
    for (purpose, value) in something(transports, JObj())
        purpose = String(purpose)
        where = check_purpose(purpose)
        if value isa AbstractString
            sb[purpose] = jobj("use" => value, "options" => JObj())
        elseif value isa Transport
            validate_transport(value, where)
            sb[purpose] = value
        elseif isobj(value) && haskey(value, "use")
            sb[purpose] = jobj("use" => value["use"], "options" => JObj(String(k) => v for (k, v) in something(get(value, "options", nothing), JObj())))
        elseif isobj(value)
            sb[purpose] = transport_from_dict(value, where)
        else
            _malformed(where, "$where: expected a name, Transport, use(...), or Dict")
        end
    end
    fb = OrderedDict{String,Any}()
    for (key, value) in something(formats, JObj())
        fb[String(key)] = format_entry(String(key), value)
    end
    declared = validate_declaration(extensions)
    declare_defaults && (declared = default_declaration(sb, declared))
    a = Adapter(JObj[JObj(String(k) => v for (k, v) in m) for m in msgs], JObj(String(k) => v for (k, v) in rd), sb, fb, String(name),
        declared, String(replay), strict, Tuple{JObj,Union{Nothing,Vector{Node}}}[], Tuple{String,Int}[])
    a.compiled = [haskey(m, "directive") ? (m, nothing) : (m, compile_template(m["text"], "template[$(i-1)]")) for (i, m) in enumerate(a.template)]
    if !isempty(a.compiled)
        last, nodes = a.compiled[end]
        n = length(a.compiled) - 1
        get(last, "role", nothing) == "assistant" && nodes !== nothing && any(x -> !(x isa TextNode), nodes) &&
            refuse("template-syntax", "template[$n]: a last assistant message is the reply's prefill (kernel §3) and holds literal text only, no slots, loops or guards";
                fix=jobj("action" => "edit-template", "path" => "template[$n]"))
    end
    adapter_turn_slots(a)
    a
end

# --------------------------------------------------------------------- serde

function _parse_version(v, what)
    v isa AbstractString || _malformed("versions", "$what: version must be a string")
    parts = split(v, '.')
    (length(parts) == 3 && all(p -> !isempty(p) && all(isdigit, p), parts)) || _malformed("versions", "$what: version $(pyrepr(v)) is not MAJOR.MINOR.PATCH")
    Base.parse.(Int, parts)
end

"Semver while major = 0: minor is breaking; patches are compatible (§9)."
function check_compatible(kind, theirs, ours)
    t = _parse_version(theirs, kind)
    o = _parse_version(ours, kind)
    ok = t[1] == o[1] && (t[1] > 0 ? t[2] <= o[2] : t[2] == o[2])
    ok || refuse("version-incompatible", "$kind: artifact needs $theirs, this implementation provides $ours";
        fix=jobj("action" => "match-version", "entry" => kind, "needs" => theirs, "provides" => ours))
end

_check_vocab(ref, declared, provided) = haskey(declared, ref) && check_compatible(ref, declared[ref], provided)

_transport_of(reg, binding, where) = binding isa Transport ? binding : named_transport(reg, binding["use"], get(binding, "options", nothing); where=where)

"Every referenced argument writer, including inactive choose branches (§6)."
function spelling_format_refs(a::Adapter, reg::Registry)
    out = Tuple{String,JObj}[]
    function walk(t, where)
        if t.choose !== nothing
            for (i, alt) in enumerate(t.choose)
                walk(haskey(alt, :else_) ? alt.else_ : alt.use, "$where.choose[$(i-1)]")
            end
            return
        end
        validate_spelling(t.spelling, "$where.spelling")
        haskey(t.spelling, "input_format") && push!(out, ("$where.spelling.input_format", t.spelling["input_format"]))
    end
    for (purpose, binding) in a.transports
        where = "transports[$(pyrepr(purpose))]"
        walk(_transport_of(reg, binding, where), where)
    end
    out
end

"Kernel §10 rules 1–6, before any plan exists."
function resolve_extensions(a::Adapter, reg::Registry)
    declared = validate_declaration(a.extensions)
    resolved = OrderedDict{String,ResolvedExtension}()
    for (name, needs) in declared
        b = get(reg.extensions, name, nothing)
        b === nothing && refuse("extension-unsupported",
            "the artifact declares extension $(pyrepr(name)) $needs, and this runtime binds no implementation of it (describe(registry)[\"extensions\"] lists what it binds)";
            fix=jobj("action" => "bind-extension", "name" => name, "needs" => needs))
        check_compatible(name, needs, ext_version(b))
        resolved[name] = ResolvedExtension(name, needs, b)
    end
    by_family = OrderedDict(family_of(n) => r for (n, r) in resolved)
    for (purpose, binding) in a.transports
        where = "transports[$(pyrepr(purpose))]"
        _walk_rules(_transport_of(reg, binding, where), (r, path) -> begin
            haskey(r, "pattern") || return
            p = get(by_family, "pattern", nothing)
            p === nothing && refuse("extension-undeclared",
                "$path: 'pattern' needs a pattern/* extension and the artifact declares none (kernel §10; pattern/legacy-re2 is what 0.2 did)";
                fix=jobj("action" => "declare-extension", "family" => "pattern", "path" => path))
            pattern_admit(p.binding, r["pattern"], path)
        end, where)
    end
    resolved
end

"""
    load(entry; registry=default_registry())

An adapter from its artifact. Names resolve only through `registry`; unknown
names, malformed structure, incompatible versions and shipped code this
runtime will not place refuse, naming the path. Loading never runs a UDF.
"""
function load(entry; registry::Registry=default_registry())
    reg = registry
    isobj(entry) || _malformed("", "entry must be a JSON object")
    for key in ("template", "reader", "versions")
        haskey(entry, key) || _malformed(key, "entry is missing required key $(pyrepr(key))")
    end
    versions = entry["versions"]
    isobj(versions) || _malformed("versions", "versions must be an object")
    check_compatible("kernel", haskey(versions, "kernel") ? versions["kernel"] : "0.0.0", KERNEL_VERSION)
    vocab = something(get(versions, "vocab", nothing), JObj())
    vocab = pytruthy(vocab) ? vocab : JObj()
    template = entry["template"]
    isobj(template) && haskey(template, "messages") && _malformed("template", "template is a list in kernel 0.2 (the 0.1 {\"messages\": [...]} form is gone)")
    isarr(template) || _malformed("template", "template must be a list")
    rs = entry["reader"]
    isobj(rs) || _malformed("reader", "entry.reader must be an object")
    kind = get(rs, "kind", nothing)
    if kind != "derived"
        named = kind isa AbstractString ? get(reg.readers, kind, nothing) : nothing
        named === nothing && refuse("unknown-reader", "reader.kind $(pyrepr(kind)) is neither the kernel reader 'derived' nor a registered reader";
            fix=jobj("action" => "install-vocabulary", "kind" => "reader", "name" => pystr(kind)))
        _check_vocab("reader/$kind", vocab, named.version)
        named_reader(reg, rs)
    end
    transports = OrderedDict{String,Any}()
    ets = get(entry, "transports", nothing)
    for (purpose, s) in (pytruthy(ets) ? ets : JObj())
        where = check_purpose(purpose)
        isobj(s) || _malformed(where, "$where: must be an object")
        if haskey(s, "use")
            name = s["use"]
            named = name isa AbstractString ? get(reg.transports, name, nothing) : nothing
            named === nothing && refuse("unknown-transport", "$where: transport $(pyrepr(name)) is not registered";
                fix=jobj("action" => "install-vocabulary", "kind" => "transport", "name" => pystr(name)))
            _check_vocab("transport/$name", vocab, named.version)
            options = JObj(String(k) => v for (k, v) in something(get(s, "options", nothing), JObj()))
            named_transport(reg, name, options; where=where)
            transports[purpose] = jobj("use" => name, "options" => options)
        else
            transports[purpose] = transport_from_dict(s, where)
        end
    end
    formats = OrderedDict{String,Any}()
    efs = get(entry, "formats", nothing)
    for (key, f) in (pytruthy(efs) ? efs : JObj())
        where = "formats[$(pyrepr(key))]"
        isobj(f) || _malformed(where, "$where: must be an object")
        if haskey(f, "use")
            name = f["use"]
            named = name isa AbstractString ? get(reg.formats, name, nothing) : nothing
            named === nothing && refuse("unknown-format", "$where: format $(pyrepr(name)) is not registered";
                fix=jobj("action" => "install-vocabulary", "kind" => "format", "name" => pystr(name)))
            _check_vocab("format/$name", vocab, named.version)
            options = JObj(String(k) => v for (k, v) in something(get(f, "options", nothing), JObj()))
            named_format(reg, name, options; where=where)
            g = JObj(String(k) => v for (k, v) in f)
            g["options"] = options
            formats[key] = g
        elseif haskey(f, "language")
            for req in ("write", "sha256")
                haskey(f, req) || _malformed("$where.$req", "$where: a shipped format needs $(pyrepr(req))")
            end
            reg.allow_udf || refuse("format-untrusted", "$where: the artifact ships a $(pystr(f["language"])) UDF and this runtime will not place code (a Julia runtime places no UDF language; bind a runtime format for the type with bind_type!)";
                fix=jobj("action" => "place-udf", "language" => pystr(f["language"]), "path" => where))
            load_udf(f, where)
        elseif haskey(f, "describe")
            formats[key] = JObj(String(k) => v for (k, v) in f)
        else
            _malformed(where, "$where: a format entry is {use}, a shipped UDF, or a description {describe}")
        end
    end
    a = adapter(; messages=template, reader=rs, transports=transports, formats=formats, name=get(entry, "name", "adapter"),
        extensions=get(entry, "extensions", nothing), replay=get(entry, "replay", "recorded"), strict=get(entry, "strict", false),
        declare_defaults=false)
    resolve_extensions(a, reg)
    for (where, ref) in spelling_format_refs(a, reg)
        named_format(reg, ref["use"], get(ref, "options", nothing); where=where)
        _check_vocab("format/$(ref["use"])", vocab, reg.formats[ref["use"]].version)
    end
    a
end

function _ref(b)
    out = jobj("use" => b["use"])
    pytruthy(get(b, "options", nothing)) && (out["options"] = deepcopy_json(b["options"]))
    haskey(b, "describe") && (out["describe"] = b["describe"])
    out
end

"""
    dump(adapter; registry=default_registry())

The adapter as its artifact, pinning the kernel and each referenced
vocabulary entry's version. A code-built format refuses: a Julia closure is
not portable source.
"""
function dump(a::Adapter; registry::Registry=default_registry())
    reg = registry
    vocab = JObj()
    transports = JObj()
    for (purpose, b) in a.transports
        if b isa Transport
            transports[purpose] = transport_to_dict(b)
        else
            named = get(reg.transports, b["use"], nothing)
            named === nothing && refuse("unknown-transport", "cannot dump: transport $(pyrepr(b["use"])) is not registered (its version is part of the artifact)";
                fix=jobj("action" => "install-vocabulary", "kind" => "transport", "name" => b["use"]))
            vocab["transport/$(b["use"])"] = named.version
            transports[purpose] = _ref(b)
        end
    end
    for (where, ref) in spelling_format_refs(a, reg)
        named_format(reg, ref["use"], get(ref, "options", nothing); where=where)
        vocab["format/$(ref["use"])"] = reg.formats[ref["use"]].version
    end
    formats = JObj()
    for (key, b) in a.formats
        if b isa Format
            b.shipped !== nothing && (formats[key] = copy(b.shipped); continue)
            refuse("format-not-self-contained", "cannot dump formats[$(pyrepr(key))]: a Julia format is a closure, not shippable source; bind it at runtime with bind_type! (never serialized) or reference a registered format by name";
                fix=jobj("action" => "reship-udf", "path" => "formats[$(pyrepr(key))]"))
        elseif isreference(b)
            named = get(reg.formats, b["use"], nothing)
            named === nothing && refuse("unknown-format", "cannot dump: format $(pyrepr(b["use"])) is not registered";
                fix=jobj("action" => "install-vocabulary", "kind" => "format", "name" => b["use"]))
            vocab["format/$(b["use"])"] = named.version
            formats[key] = _ref(b)
        else
            formats[key] = copy(b)
        end
    end
    kind = a.reader["kind"]
    if kind != "derived"
        named = get(reg.readers, kind, nothing)
        named === nothing && refuse("unknown-reader", "cannot dump: reader $(pyrepr(kind)) is not registered (its version is part of the artifact)";
            fix=jobj("action" => "install-vocabulary", "kind" => "reader", "name" => pystr(kind)))
        vocab["reader/$kind"] = named.version
    end
    entry = jobj("name" => a.name, "versions" => jobj("kernel" => KERNEL_VERSION, "vocab" => vocab))
    isempty(a.extensions) || (entry["extensions"] = copy(a.extensions))
    entry["template"] = Any[copy(m) for m in a.template]
    entry["reader"] = copy(a.reader)
    a.replay == "recorded" || (entry["replay"] = a.replay)
    a.strict && (entry["strict"] = true)
    isempty(transports) || (entry["transports"] = transports)
    isempty(formats) || (entry["formats"] = formats)
    entry
end

# Extensions (kernel §10) and the registry: the sockets vocabulary plugs into.

const _EXT_NAME = r"\A[a-z][a-z0-9_]*/[a-z][a-z0-9_-]*\z"
const _SEMVER = r"\A[0-9]+\.[0-9]+\.[0-9]+\z"
family_of(name) = split(name, '/')[1]

"What a host binds under an extension name: the contract, its version, a label saying how."
abstract type ExtensionBinding end
ext_family(::ExtensionBinding) = ""

const _NON_RE2 = r"\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+"

"""
`pattern/legacy-re2` 0.1.0 through Julia's `Regex` (PCRE2) with DOTALL (`s`).
The contract's lexical exclusion check refuses what it names; the rest is
the engine's. Inputs the contract leaves unspecified (Unicode classes, POSIX
classes, `\\Q…\\E`) may differ from the reference's `python:re`.
"""
struct LegacyRE2 <: ExtensionBinding
    compiled::OrderedDict{String,Tuple{Regex,Bool}}
end
LegacyRE2() = LegacyRE2(OrderedDict{String,Tuple{Regex,Bool}}())
ext_name(::LegacyRE2) = "pattern/legacy-re2"
ext_version(::LegacyRE2) = "0.1.0"
ext_label(::LegacyRE2) = "julia:PCRE2"
ext_family(::LegacyRE2) = "pattern"

function _compile(b::LegacyRE2, regex::AbstractString)
    get!(b.compiled, regex) do
        re = Regex(regex, "s")
        groups = length(match(Regex("(?:" * regex * ")|", "s"), "").captures) > 0
        (re, groups)
    end
end

function pattern_admit(b::LegacyRE2, regex, where)
    unescaped = replace(regex, r"\\[^1-9k]" => "")
    m = match(_NON_RE2, unescaped)
    m === nothing || refuse("entry-malformed",
        "$where: regex $(pyrepr(regex)) uses $(pyrepr(m.match)), which is outside the pattern/legacy-re2 dialect (no lookaround, backreferences, named groups, atomic or possessive constructs)";
        fix=jobj("action" => "edit-entry", "path" => where))
    try
        _compile(b, regex)
    catch err
        refuse("entry-malformed", "$where: regex $(pyrepr(regex)) does not compile: $(sprint(showerror, err))";
            fix=jobj("action" => "edit-entry", "path" => where))
    end
    nothing
end

function pattern_captures(b::LegacyRE2, regex, text)
    re, groups = _compile(b, regex)
    out = Tuple{Int,Int,String}[]
    for m in eachmatch(re, text)
        isempty(m.match) && continue
        start = m.offset - 1
        cap = groups ? (m.captures[1] === nothing ? "" : String(m.captures[1])) : String(m.match)
        push!(out, (start, start + ncodeunits(m.match), cap))
    end
    out
end

ext_describe(b::ExtensionBinding) = jobj("version" => ext_version(b), "binding" => ext_label(b))

"The bindings this runtime can honestly claim with Julia alone."
native_extensions() = ExtensionBinding[LegacyRE2()]

struct ResolvedExtension
    name::String
    needs::String
    binding::ExtensionBinding
end
resolved_describe(r::ResolvedExtension) = jobj("needs" => r.needs, "provides" => ext_version(r.binding), "binding" => ext_label(r.binding))

function _walk_rules(t::Transport, visit, where)
    if t.choose !== nothing
        for (i, a) in enumerate(t.choose)
            _walk_rules(haskey(a, :else_) ? a.else_ : a.use, visit, "$where.choose[$(i-1)]")
        end
        return
    end
    for (i, r) in enumerate(t.find)
        visit(r, "$where.find[$(i-1)]")
    end
end

function uses_family(transports, family)
    found = false
    for (_, s) in transports
        s isa Transport || continue
        _walk_rules(s, (r, _) -> (family == "pattern" && haskey(r, "pattern") && (found = true)), "")
    end
    found
end

"The constructor's convenience (§10): an inline `pattern` rule declares the default tier."
function default_declaration(transports, declared)
    if uses_family(transports, "pattern") && !any(family_of(n) == "pattern" for n in keys(declared))
        d = copy(declared)
        d["pattern/legacy-re2"] = "0.1.0"
        return d
    end
    declared
end

"Rules 1–2 of kernel §10: shape, names, versions, one per family."
function validate_declaration(ext)
    ext === nothing && return JObj()
    isobj(ext) || _malformed("extensions", "extensions must be an object of '<family>/<name>': version")
    seen = OrderedDict{String,String}()
    for (name, version) in ext
        (name isa AbstractString && occursin(_EXT_NAME, name)) ||
            _malformed("extensions", "extensions: $(pyrepr(name)) is not an extension name ('<family>/<name>', lowercase)")
        (version isa AbstractString && occursin(_SEMVER, version)) ||
            _malformed("extensions", "extensions: $(pyrepr(name)): version $(pyrepr(version)) is not MAJOR.MINOR.PATCH")
        fam = family_of(name)
        haskey(seen, fam) && _malformed("extensions", "extensions: $(pyrepr(seen[fam])) and $(pyrepr(name)) both govern family $(pyrepr(fam)); declare one contract per family")
        seen[fam] = name
    end
    JObj(String(k) => v for (k, v) in ext)
end

# ------------------------------------------------------------------ registry

struct Named
    factory::Function
    version::String
end

"""
    HostType

How one Julia type crosses in this runtime (never serialized): its format
(`nothing`: the format its shape resolves), the shape it lowers to
(`nothing`: none declared), and its JSON form both ways (`to_json`,
`from_json`; kernel §3a: a turn holds JSON, a host lifts it back), and
the type name a signature records for it (`nothing`: `string(T)`, which
depends on what the caller's module imports).
"""
struct HostType
    type::Any
    name::Union{Nothing,String}
    binding::Any            # a Format, (use, options), or nothing
    shape::Union{Nothing,JObj}
    to_json::Any
    from_json::Any
end

"""
    Registry(; allow_udf=false, extensions=nothing)

Named formats, transports and readers (with versions), runtime type bindings,
and the extensions this runtime binds (`extensions=String[]` for a core-only
host; default every native binding). Explicit objects: `load` reads only the
one it is given.
"""
mutable struct Registry
    formats::OrderedDict{String,Named}
    type_bindings::Vector{HostType}
    transports::OrderedDict{String,Named}
    readers::OrderedDict{String,Named}
    extensions::OrderedDict{String,ExtensionBinding}
    allow_udf::Bool
end

function Registry(; allow_udf::Bool=false, extensions=nothing)
    natives = OrderedDict(ext_name(b) => b for b in native_extensions())
    reg = Registry(OrderedDict{String,Named}(), HostType[], OrderedDict{String,Named}(), OrderedDict{String,Named}(),
        OrderedDict{String,ExtensionBinding}(), allow_udf)
    for name in (extensions === nothing ? collect(keys(natives)) : extensions)
        haskey(natives, name) || throw(ArgumentError("no native binding for extension $(repr(name)); use register_extension! with your own"))
        reg.extensions[name] = natives[name]
    end
    reg
end

function register_extension!(reg::Registry, b::ExtensionBinding; exist_ok=false)
    haskey(reg.extensions, ext_name(b)) && !exist_ok && refuse("already-registered", "extension $(pyrepr(ext_name(b))) is already bound")
    reg.extensions[ext_name(b)] = b
end

function register_format!(reg::Registry, name, factory; version="0.1.0", exist_ok=false)
    haskey(reg.formats, name) && !exist_ok && refuse("already-registered", "format $(pyrepr(name)) is already registered")
    reg.formats[name] = Named(factory, version)
end

"Resolve `{\"use\": name, \"options\"}`; a failing factory is `entry-malformed` at `where` (§5)."
function named_format(reg::Registry, name, options; where=nothing)
    e = get(reg.formats, name, nothing)
    e === nothing && refuse("unknown-format", "format $(pyrepr(name)) is not registered — install the package that provides it, or ship the format with the artifact";
        fix=jobj("action" => "install-vocabulary", "kind" => "format", "name" => name))
    at = something(where, "format $(pyrepr(name))")
    fmt = try
        e.factory(options === nothing ? JObj() : options)
    catch err
        err isa Refusal && rethrow()
        _malformed(at, "$at: format $(pyrepr(name)) rejects its options: $(sprint(showerror, err))")
    end
    fmt isa Format || _malformed(at, "$at: format $(pyrepr(name)) returned $(typeof(fmt)), not a Format")
    fmt.name = name
    fmt
end

"""
    bind_type!(reg, T; write, read, describe, use, options, shape, to_json, from_json, name, kwargs...)

Bind a Julia type, per runtime, never serialized: a format built from
functions, or a named one (`use="table", options=Dict(...)`). A type the
kernel cannot lower lowers to `shape` (default `{}`: structured, contents
unknown).

`to_json(value)` and `from_json(data)`: the type's JSON form, both ways. A
turn writes it (`to_json`, `dump_turn`), `load_turn` rebuilds the value from
it, and every format but the one bound here receives it, so the format bound
here always receives the value itself, live or replayed.

With neither `write` nor `use`, no format is bound: the type crosses by the
format its shape resolves (and, without `shape`, lowers as usual). `name`
is the type name a signature records and formats resolve by (default
`string(T)`, which reads `LM15.ImagePart` or `ImagePart` depending on what
the caller imported); give it to match the other kernels. Binding
the same type again replaces its binding. Returns the bound format, or
`nothing`.
"""
function bind_type!(reg::Registry, T; write=nothing, read=nothing, describe=nothing, use=nothing, options=nothing, shape=nothing,
                    to_json=nothing, from_json=nothing, name=nothing, kwargs...)
    shape === nothing || shape isa AbstractDict ||
        refuse("unmapped-type", "$(T): shape must be a JSON-Schema Dict"; fix=jobj("action" => "edit-signature"))
    for (name, hook) in (("to_json", to_json), ("from_json", from_json))
        hook === nothing || hook isa Base.Callable || hook isa Function ||
            _malformed(name, "$(T): $name must be a function")
    end
    shp = shape === nothing ? nothing : JObj(String(k) => v for (k, v) in shape)
    binding = if use !== nothing
        (use, options === nothing ? JObj() : options)
    elseif write !== nothing
        make_format(; write=write, read=read, describe=describe, kwargs...)
    elseif read !== nothing || describe !== nothing || !isempty(kwargs) || options !== nothing ||
           (shp === nothing && to_json === nothing && from_json === nothing)
        _malformed("write", "a format needs at least write")
    else
        nothing
    end
    name === nothing || name isa AbstractString || _malformed("name", "$(T): name must be a string")
    record = HostType(T, name === nothing ? nothing : String(name), binding, shp, to_json, from_json)
    i = findfirst(h -> h.type === T, reg.type_bindings)
    i === nothing ? push!(reg.type_bindings, record) : (reg.type_bindings[i] = record)   # bound again: replaced
    binding === nothing && return nothing
    binding isa Format ? binding : named_format(reg, use, options)
end

_matches(ann, T) = ann === T || ann == T || (ann isa Type && T isa Type && ann <: T)

"The binding of a type (or of a type it subtypes), or `nothing`."
host_of(reg::Registry, ann) = ann === nothing ? nothing : (i = findfirst(h -> _matches(ann, h.type), reg.type_bindings); i === nothing ? nothing : reg.type_bindings[i])

"The shape a bound type lowers to (`{}` when bound with a format and no shape), or `nothing`."
function shape_of(reg::Registry, ann)
    h = host_of(reg, ann)
    h === nothing && return nothing
    h.shape !== nothing && return deepcopy_json(h.shape)
    h.binding === nothing ? nothing : JObj()
end

function type_binding(reg::Registry, ann)
    ann === nothing && return nothing
    for h in reg.type_bindings
        (h.binding !== nothing && _matches(ann, h.type)) || continue
        return h.binding isa Format ? h.binding : named_format(reg, h.binding[1], h.binding[2])
    end
    nothing
end

const _PLAIN_JSON = Union{Nothing,AbstractString,Bool,Number,Symbol,AbstractDict,AbstractVector,Tuple,NamedTuple}

"The `to_json` bound to a value's type (by `isa`), or `nothing`."
function to_json_hook(reg::Registry, value)
    value isa _PLAIN_JSON && return nothing
    i = findfirst(h -> h.to_json !== nothing && h.type isa Type && value isa h.type, reg.type_bindings)
    i === nothing ? nothing : reg.type_bindings[i].to_json
end

"The `from_json` bound to a type (or a type it subtypes), or `nothing`."
function from_json_hook(reg::Registry, ann)
    ann === nothing && return nothing
    i = findfirst(h -> h.from_json !== nothing && _matches(ann, h.type), reg.type_bindings)
    i === nothing ? nothing : reg.type_bindings[i].from_json
end

function register_transport!(reg::Registry, name, factory; version="0.1.0", exist_ok=false)
    haskey(reg.transports, name) && !exist_ok && refuse("already-registered", "transport $(pyrepr(name)) is already registered")
    reg.transports[name] = Named(factory, version)
end

"Resolve `{\"use\": name}`; what the factory returns is checked as inline data (§6)."
function named_transport(reg::Registry, name, options; where=nothing)
    e = get(reg.transports, name, nothing)
    e === nothing && refuse("unknown-transport", "transport $(pyrepr(name)) is not registered — install the package that provides it, or inline the transport as data";
        fix=jobj("action" => "install-vocabulary", "kind" => "transport", "name" => name))
    at = something(where, "transport $(pyrepr(name))")
    built = try
        e.factory(options === nothing ? JObj() : options)
    catch err
        err isa Refusal && rethrow()
        _malformed(at, "$at: transport $(pyrepr(name)) rejects its options: $(sprint(showerror, err))")
    end
    try
        return built isa Transport ? (validate_transport(built, at); built) : transport_from_dict(built, at)
    catch err
        (err isa Refusal && err.code == "entry-malformed") || rethrow()
        _malformed(at, "$at: transport $(pyrepr(name)) built malformed data — $(err.hint)")
    end
end

function register_reader!(reg::Registry, name, factory; version="0.1.0", exist_ok=false)
    name == "derived" && refuse("already-registered", "reader 'derived' is kernel grammar and cannot be replaced")
    haskey(reg.readers, name) && !exist_ok && refuse("already-registered", "reader $(pyrepr(name)) is already registered")
    reg.readers[name] = Named(factory, version)
end

function named_reader(reg::Registry, spec)
    kind = get(spec, "kind", nothing)
    e = kind isa AbstractString ? get(reg.readers, kind, nothing) : nothing
    e === nothing && refuse("unknown-reader", "reader kind $(pyrepr(kind)) is neither the kernel reader 'derived' nor a registered reader — install the package that provides it";
        fix=jobj("action" => "install-vocabulary", "kind" => "reader", "name" => pystr(kind)))
    r = try
        e.factory(spec)
    catch err
        err isa Refusal && rethrow()
        _malformed("reader", "reader: $(pyrepr(kind)) rejects its spec: $(sprint(showerror, err))")
    end
    r isa Reader || _malformed("reader", "reader: $(pyrepr(kind)) built $(typeof(r)), not a Reader")
    r
end

_versions(m) = JObj(n => e.version for (n, e) in sort(collect(m); by=first))

function describe(reg::Registry)
    jobj("formats" => _versions(reg.formats),
        "type_bindings" => Any[jobj("type" => something(h.name, string(h.type)),
                                    "format" => h.binding === nothing ? nothing : h.binding isa Format ? something(h.binding.name, "(inline)") : h.binding[1],
                                    "shape" => something(h.shape, JObj()),
                                    "json" => Any[k for k in ("to_json", "from_json") if getfield(h, Symbol(k)) !== nothing])
                               for h in reg.type_bindings],
        "transports" => _versions(reg.transports),
        "readers" => merge(jobj("derived" => "kernel"), _versions(reg.readers)),
        "allow_udf" => reg.allow_udf,
        "extensions" => JObj(n => ext_describe(b) for (n, b) in sort(collect(reg.extensions); by=first)))
end

const _DEFAULT_REGISTRY = Ref{Union{Nothing,Registry}}(nothing)
"The registry `bind`, `load` and `dump` use when given none."
function default_registry()
    _DEFAULT_REGISTRY[] === nothing && (_DEFAULT_REGISTRY[] = Registry())
    _DEFAULT_REGISTRY[]
end

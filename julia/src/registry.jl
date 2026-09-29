# Extensions (kernel §10) and the registry: the sockets vocabulary plugs into.

const _EXT_NAME = r"^[a-z][a-z0-9_]*/[a-z][a-z0-9_-]*$"
const _SEMVER = r"^\d+\.\d+\.\d+$"
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
    Registry(; allow_udf=false, extensions=nothing)

Named formats, transports and readers (with versions), runtime type bindings,
and the extensions this runtime binds (`extensions=String[]` for a core-only
host; default every native binding). Explicit objects: `load` reads only the
one it is given.
"""
mutable struct Registry
    formats::OrderedDict{String,Named}
    type_bindings::Vector{Tuple{Any,Any,JObj}}      # (Julia type, Format or (use, options), shape)
    transports::OrderedDict{String,Named}
    readers::OrderedDict{String,Named}
    extensions::OrderedDict{String,ExtensionBinding}
    allow_udf::Bool
end

function Registry(; allow_udf::Bool=false, extensions=nothing)
    natives = OrderedDict(ext_name(b) => b for b in native_extensions())
    reg = Registry(OrderedDict{String,Named}(), Tuple{Any,Any,JObj}[], OrderedDict{String,Named}(), OrderedDict{String,Named}(),
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
    bind_type!(reg, T; write, read, describe, use, options, shape, kwargs...)

Bind a Julia type to a format, per runtime, never serialized: a format built
from functions, or a named one (`use="table", options=Dict(...)`). A type the
kernel cannot lower lowers to `shape` (default `{}`: structured, contents unknown).
"""
function bind_type!(reg::Registry, T; write=nothing, read=nothing, describe=nothing, use=nothing, options=nothing, shape=nothing, kwargs...)
    shp = shape === nothing ? JObj() : JObj(String(k) => v for (k, v) in shape)
    if use !== nothing
        push!(reg.type_bindings, (T, (use, options === nothing ? JObj() : options), shp))
        return named_format(reg, use, options)
    end
    write === nothing && _malformed("write", "a format needs at least write")
    fmt = make_format(; write=write, read=read, describe=describe, kwargs...)
    push!(reg.type_bindings, (T, fmt, shp))
    fmt
end

_matches(ann, T) = ann === T || ann == T || (ann isa Type && T isa Type && ann <: T)

function shape_of(reg::Registry, ann)
    for (T, _, shp) in reg.type_bindings
        ann !== nothing && _matches(ann, T) && return deepcopy_json(shp)
    end
    nothing
end

function type_binding(reg::Registry, ann)
    ann === nothing && return nothing
    for (T, b, _) in reg.type_bindings
        _matches(ann, T) || continue
        return b isa Format ? b : named_format(reg, b[1], b[2])
    end
    nothing
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
        "type_bindings" => Any[jobj("type" => string(T), "format" => b isa Format ? something(b.name, "(inline)") : b[1], "shape" => s)
                               for (T, b, s) in reg.type_bindings],
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

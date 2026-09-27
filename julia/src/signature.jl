# Signatures (kernel §1) and the Julia frontend.
#
# `signature_from_dict` is the plain-data form every implementation shares.
# `signature("…"; inputs=(q=String,), outputs=(a=Int,))` lowers Julia types
# mechanically: String, Integer, AbstractFloat, Bool, @enum, Vector{T},
# Union{T,Nothing}, NamedTuple, Dict and plain structs. A type it cannot lower
# resolves through the registry's type bindings, or refuses `unmapped-type`.
# Type names are Julia's (`String`, `Int64`, `Vector{String}`): the frontend
# spells them (§1), so a Julia signature and a Python one of the same
# function have different fingerprints; `signature_from_dict` never differs.

"""
    Signature(instructions, fields)

Instructions and ordered fields. Constructing one validates it
(`signature-malformed`, naming the offender): an invalid signature cannot exist.
"""
struct Signature
    instructions::String
    fields::Vector{Field}
    function Signature(instructions, fields::AbstractVector)
        _validate_signature(instructions, fields)
        new(String(instructions), Field[f isa Field ? f : _field_from(f) for f in fields])
    end
end

inputs(s::Signature) = [f for f in s.fields if f.direction == "input"]
outputs(s::Signature) = [f for f in s.fields if f.direction == "output"]
field_named(s::Signature, name) = (i = findfirst(f -> f.name == name, s.fields); i === nothing ? nothing : s.fields[i])

_fget(f::Field, k) = getfield(f, Symbol(k))
_fget(f::AbstractDict, k) = get(f, k, k == "purpose" ? "plain" : nothing)
_fhas(f::AbstractDict, k) = haskey(f, k)

function _fix_field(name)
    name isa AbstractString && !isempty(name) ? jobj("action" => "edit-signature", "field" => name) : jobj("action" => "edit-signature")
end

"The rules of schema/signature.schema.json plus name uniqueness, on raw fields."
function _validate_signature(instructions, fields)
    instructions isa AbstractString ||
        refuse("signature-malformed", "instructions must be text, not $(_typename(instructions))"; fix=jobj("action" => "edit-signature"))
    seen = Set{String}()
    for f in fields
        name = _fget(f, "name")
        fix = _fix_field(name)
        isidentifier(name) || refuse("signature-malformed", "field name $(pyrepr(name)) is not an ASCII identifier ([A-Za-z_][A-Za-z0-9_]*)"; fix=fix)
        name in seen && refuse("signature-malformed", "field $(pyrepr(name)) is declared twice"; fix=fix)
        push!(seen, name)
        d = _fget(f, "direction")
        d in ("input", "output") || refuse("signature-malformed", "field $(pyrepr(name)): direction $(pyrepr(d)) is not input/output"; fix=fix)
        isobj(_fget(f, "shape")) || refuse("signature-malformed", "field $(pyrepr(name)): shape must be an object"; fix=fix)
        p = _fget(f, "purpose")
        (p isa AbstractString && occursin(_PURPOSE, p)) ||
            refuse("signature-malformed", "field $(pyrepr(name)): purpose $(pyrepr(p)) is not a (dotted) identifier"; fix=fix)
        t = _fget(f, "type")
        (t === nothing || t isa AbstractString) || refuse("signature-malformed", "field $(pyrepr(name)): type must be a string"; fix=fix)
        d2 = _fget(f, "desc")
        (d2 === nothing || d2 isa AbstractString) || refuse("signature-malformed", "field $(pyrepr(name)): desc must be a string"; fix=fix)
    end
end

_field_from(f::AbstractDict) = Field(String(f["name"]), String(f["direction"]), JObj(String(k) => deepcopy_json(v) for (k, v) in f["shape"]);
    type=get(f, "type", nothing), purpose=get(f, "purpose", "plain"), desc=get(f, "desc", nothing), annotation=get(f, "annotation", nothing))

"Load a signature from its plain-data form (the corpus form)."
function signature_from_dict(data)
    (isobj(data) && isarr(get(data, "fields", Any[]))) ||
        refuse("signature-malformed", "a signature is an object with a fields list"; fix=jobj("action" => "edit-signature"))
    fields = Any[]
    for f in get(data, "fields", Any[])
        isobj(f) || refuse("signature-malformed", "each field is an object"; fix=jobj("action" => "edit-signature"))
        push!(fields, f)
    end
    Signature(get(data, "instructions", ""), fields)
end

function _field_to_dict(f::Field)
    d = jobj("name" => f.name, "direction" => f.direction, "shape" => f.shape)
    f.type !== nothing && !isempty(f.type) && (d["type"] = f.type)
    f.purpose != "plain" && (d["purpose"] = f.purpose)
    f.desc !== nothing && (d["desc"] = f.desc)
    d
end

signature_to_dict(sig::Signature) = jobj("instructions" => sig.instructions, "fields" => Any[_field_to_dict(f) for f in sig.fields])

# ------------------------------------------------------------- frontend

"A field spec: a Julia type or a JSON-Schema shape, plus purpose, description and type name."
struct FieldSpec
    annotation::Any
    purpose::String
    desc::Union{Nothing,String}
    type::Union{Nothing,String}
end

"""
    field(T; purpose="plain", desc=nothing, type=nothing)

Annotate a field: `field(String; purpose="reasoning")`. `T` is a Julia type or
a JSON-Schema shape (a Dict). `type` overrides the type name formats resolve by.
"""
field(ann; purpose="plain", desc=nothing, type=nothing) = FieldSpec(ann, purpose, desc, type)

function typename_of(T)
    T isa AbstractDict && return nothing
    T isa Type && return string(T)
    nothing
end

function _union_parts(T)
    T isa Union || return Any[T]
    Any[Base.uniontypes(T)...]
end

"""
    annotation_to_shape(T; registry=default_registry(), field_name="?")

A Julia type as a JSON-Schema shape, mechanically; a type only the runtime
knows resolves through `registry` (a binding made with `bind_type!`).
"""
function annotation_to_shape(T; registry=nothing, field_name="?")
    T isa AbstractDict && return JObj(String(k) => deepcopy_json(v) for (k, v) in T)
    T isa NamedTuple && return JObj(String(k) => deepcopy_json(v) for (k, v) in pairs(T))
    T isa Type || refuse("unmapped-type", "field $(pyrepr(field_name)): $(repr(T)) is not a type or a JSON-Schema shape";
        fix=jobj("action" => "edit-signature", "field" => field_name))
    T === Bool && return jobj("type" => "boolean")
    (T <: AbstractString) && T !== Union{} && return jobj("type" => "string")
    (T <: Integer) && T !== Union{} && return jobj("type" => "integer")
    (T <: AbstractFloat) && T !== Union{} && return jobj("type" => "number")
    if T isa Union
        parts = sort(_union_parts(T); by=p -> p === Nothing)      # the value first, null last, as Python writes Optional[T]
        return jobj("anyOf" => Any[p === Nothing ? jobj("type" => "null") : annotation_to_shape(p; registry=registry, field_name=field_name) for p in parts])
    end
    if T <: Enum && isconcretetype(T)
        return jobj("enum" => Any[string(x) for x in instances(T)], "type" => "string")
    end
    if T <: AbstractVector && T !== Union{}
        E = eltype(T)
        return E === Any ? jobj("type" => "array") : jobj("type" => "array", "items" => annotation_to_shape(E; registry=registry, field_name=field_name))
    end
    T <: AbstractDict && T !== Union{} && return jobj("type" => "object")
    if T <: NamedTuple && isconcretetype(T)
        names = [String(n) for n in fieldnames(T)]
        props = JObj(String(n) => annotation_to_shape(t; registry=registry, field_name="$field_name.$n") for (n, t) in zip(fieldnames(T), fieldtypes(T)))
        return jobj("type" => "object", "properties" => props, "required" => Any[names...])
    end
    reg = registry === nothing ? default_registry() : registry
    bound = shape_of(reg, T)
    bound !== nothing && return bound
    if isstructtype(T) && isconcretetype(T) && !(T <: Number) && fieldcount(T) > 0 && T.name.module !== Core && T.name.module !== Base
        props = JObj(String(n) => annotation_to_shape(t; registry=registry, field_name="$field_name.$n") for (n, t) in zip(fieldnames(T), fieldtypes(T)))
        return jobj("type" => "object", "properties" => props, "required" => Any[String(n) for n in fieldnames(T)])
    end
    refuse("unmapped-type", "field $(pyrepr(field_name)): cannot map $(T) to a shape; bind the type with bind_type!(registry, $(T), ...), pass a JSON-Schema Dict, or lower it in your frontend";
        fix=jobj("action" => "edit-signature", "field" => field_name))
end

"""
    signature(instructions; inputs=(;), outputs=(;), registry=nothing)

Build a signature from Julia types: `signature("Answer."; inputs=(question=String,),
outputs=(answer=String, score=Int))`. Values are types, JSON-Schema Dicts, or
`field(...)` specs. Inputs come first, then outputs, each in the order written.
"""
function signature(instructions::AbstractString; inputs=(;), outputs=(;), registry=nothing)
    fields = Field[]
    for (direction, entries) in (("input", inputs), ("output", outputs))
        for (k, spec) in pairs(entries)
            name = String(k)
            s = spec isa FieldSpec ? spec : FieldSpec(spec, "plain", nothing, nothing)
            shape = annotation_to_shape(s.annotation; registry=registry, field_name=name)
            push!(fields, Field(name, direction, shape; type=something(s.type, typename_of(s.annotation), Some(nothing)),
                purpose=s.purpose, desc=s.desc, annotation=s.annotation isa Type ? s.annotation : nothing))
        end
    end
    Signature(instructions, fields)
end

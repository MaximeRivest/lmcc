# Formats (kernel §5): how a type is written and read. A format is data plus
# functions: `write(value, field) → text | parts`, `read(capture, field)`,
# `describe(field)`. Shipped code (a UDF in an artifact) is admitted by the
# rules and never run by the loader; this runtime places no UDF language.

"""
    Format

`accepts` (type names, structural keys, `*`), `direction` (`in`, `out`,
`both`), `writes` (`text`, `parts`), `round_trip`, `reads` (capture kinds),
and the functions `write`, `read` (or `nothing`) and `describe`.
"""
mutable struct Format
    name::Union{Nothing,String}
    accepts::Vector{String}
    direction::String
    writes::String
    round_trip::Bool
    reads::Vector{String}
    write::Function
    read::Union{Nothing,Function}
    describe::Function
    shipped::Union{Nothing,JObj}
end

"""
    make_format(; write, read=nothing, describe=nothing, accepts=["*"], direction=nothing,
                writes="text", round_trip=true, reads=["text"], name=nothing)

A format from functions. `write(value, field)`, `read(capture, field)`,
`describe(field)`; `direction` defaults to `both` with a read, else `in`.
"""
function make_format(; write, read=nothing, describe=nothing, accepts=["*"], direction=nothing,
                     writes="text", round_trip=true, reads=["text"], name=nothing)
    acc = accepts isa AbstractString ? [String(accepts)] : String[a for a in accepts]
    Format(name, acc, something(direction, read === nothing ? "in" : "both"), writes, round_trip,
           String[r for r in reads], write, read, describe === nothing ? (f -> nothing) : describe, nothing)
end

format_describe(fmt::Format, f::Field) = fmt.describe(f)

const SCALAR_DEFAULT = Format("kernel-scalar", ["string", "integer", "number", "boolean", "enum"], "both", "text", true, ["*"],
    (v, f) -> spell_value(f.shape, v, "field $(pyrepr(f.name))"; field=f.name),
    (c, f) -> read_value(f.shape, text(c), "field $(pyrepr(f.name))"),
    f -> (s = shape_summary(f.shape); isempty(s) ? nothing : s), nothing)

const _MEDIA_MEMBERS = ["media_type", "data", "url", "file_id", "path", "continuation"]
"lm15's media parts and their members besides `type` (the pinned contract's spec/types.md); §7b writes these kinds exactly as lm15 serializes them."
media_part_members(kind) = kind == "image" ? ["media_type", "data", "url", "file_id", "path", "detail", "continuation"] :
    kind in ("audio", "video", "document", "binary") ? _MEDIA_MEMBERS : nothing
"lm15's omission rule: null, \"\", [] and {} are left out."
_empty_member(v) = v === nothing || (v isa AbstractString && isempty(v)) || ((v isa AbstractVector || v isa Tuple || v isa AbstractDict) && isempty(v))

function _media_write(value, f::Field)
    kind = f.shape["media"]
    isobj(value) || refuse("value-invalid", "field $(pyrepr(f.name)): a media value must be a Dict of part data")
    haskey(value, "type") && value["type"] != kind &&
        refuse("value-invalid", "field $(pyrepr(f.name)): a $(pyrepr(value["type"])) part given where a $(pyrepr(kind)) part is declared")
    part = jobj("type" => kind)
    members = media_part_members(kind)
    for (k, v) in value
        k = String(k)
        k == "type" && continue
        if members !== nothing          # §7b: exactly as lm15 serializes the part
            k in members || refuse("value-invalid", "field $(pyrepr(f.name)): $(pyrepr(k)) is not a member of lm15's $kind part ($(join(members, ", "))); give the part's data, or an lm15 part through its bridge")
            k != "media_type" && _empty_member(v) && continue   # lm15's omission rule
        end
        part[k] = v
    end
    Any[part]
end

function _media_read(c::Capture, f::Field)
    ps = parts_of(c, f.shape["media"])
    isempty(ps) && refuse("parse-value", "field $(pyrepr(f.name)): no $(pystr(f.shape["media"])) part in the capture")
    JObj(k => v for (k, v) in ps[1] if k != "type")
end

const MEDIA_DEFAULT = Format("kernel-media", ["media:*"], "both", "parts", true, ["*"], _media_write, _media_read,
    f -> "(" * pystr(f.shape["media"]) * ")", nothing)

function kernel_default(shape)
    base, _ = nullable_base(shape)
    is_media(base) && return MEDIA_DEFAULT
    (haskey(base, "enum") || get(base, "type", nothing) in SCALAR_TYPES) && return SCALAR_DEFAULT
    nothing
end

function format_accepts(fmt::Format, f::Field)
    keys = Set(vcat(structural_keys(f.shape), ["*"]))
    f.type !== nothing && push!(keys, f.type)
    any(a in keys for a in fmt.accepts)
end

"Kernel §5: this runtime places no shipped code; refuse by the admission rules."
load_udf(entry, where) = refuse("udf-unplaceable",
    "$where: this host places no UDF language (a Julia runtime does not admit $(pyrepr(get(entry, "language", nothing))) source); bind a runtime format for the type instead";
    fix=jobj("action" => "place-udf", "language" => pystr(get(entry, "language", nothing)), "path" => where))

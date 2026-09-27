# The neutral core (kernel §1, §3, §5, §7): shapes, values, parts, captures,
# responses. Messages and parts are lm15 canonical JSON: ordered objects
# `{"role", "parts": [{"type": "text", "text"}, …]}`.

const Shape = JObj
const SCALAR_TYPES = ("string", "integer", "number", "boolean")

"The capability facts a predicate or `requires` may name (spec/vocab/capabilities.md)."
const CAPABILITY_FACTS = Set(["instruct", "completion", "native_reasoning", "native_function_calling",
    "native_citations", "native_structured_output", "image_input", "stop_sequences", "assistant_prefill"])

"""
    Field

One signature field. `shape` is JSON Schema; `type` is the type's name as the
frontend spells it (formats resolve by it first); `annotation` is the Julia
type a frontend lowered, used for runtime format bindings, never serialized.
"""
struct Field
    name::String
    direction::String
    shape::JObj
    type::Union{Nothing,String}
    purpose::String
    desc::Union{Nothing,String}
    annotation::Any
end
Field(name, direction, shape; type=nothing, purpose="plain", desc=nothing, annotation=nothing) =
    Field(name, direction, shape, type, purpose, desc, annotation)

"Kernel §1: a nullable scalar/enum shape is that shape plus null. `(base, nullable)`."
function nullable_base(shape::AbstractDict)
    t = get(shape, "type", nothing)
    if isarr(t)
        others = [x for x in t if x != "null"]
        if "null" in t && length(others) == 1 && length(t) == 2
            base = JObj(k => v for (k, v) in shape if k != "type")
            base["type"] = others[1]
            return (base, true)
        end
        return (shape, false)
    end
    alts = get(shape, "anyOf", nothing)
    if isarr(alts) && length(alts) == 2 && length(shape) == 1
        isnull = a -> isobj(a) && json_equal(a, JObj("type" => "null"))
        nulls = [a for a in alts if isnull(a)]
        others = [a for a in alts if !isnull(a)]
        if length(nulls) == 1 && length(others) == 1 && isobj(others[1])
            base = others[1]
            (haskey(base, "enum") || get(base, "type", nothing) in SCALAR_TYPES) && return (base, true)
        end
    end
    (shape, false)
end

"A short human hint for a shape (`{f.schema}` when no format describes it)."
function shape_summary(shape::AbstractDict)
    base, _ = nullable_base(shape)
    haskey(base, "enum") && return "one of: " * join((pystr(v) for v in base["enum"]), ", ")
    haskey(base, "media") && return "(" * pystr(base["media"]) * ")"
    t = get(base, "type", nothing)
    t in ("integer", "number", "boolean") && return "($t)"
    ""
end

is_media(shape) = haskey(shape, "media")

function is_structured(shape)
    base, _ = nullable_base(shape)
    (is_media(base) || haskey(base, "enum")) && return false
    !(get(base, "type", nothing) in SCALAR_TYPES)
end

_inenum(members, v) = any(m -> json_equal(m, v), members)   # Python's `in`: 1 == 1.0, True == 1
_typename(v) = v === nothing ? "None" : isarr(v) ? "list" : isobj(v) ? "dict" : v isa AbstractString ? "str" :
               v isa Bool ? "bool" : v isa Integer ? "int" : v isa Real ? "float" : string(typeof(v))

"""
Kernel §7a, writing: strings verbatim, integers in decimal, numbers by the
ECMAScript spelling, booleans `true`/`false`, enums by member spelling, `null`
for nullable shapes; anything structured refuses `no-format`.
"""
function spell_value(shape, value, where::AbstractString; field=nothing)
    base, nullable = nullable_base(shape)
    if value === nothing
        nullable && return "null"
        refuse("value-invalid", "$where: null is not allowed by the shape")
    end
    value isa Enum && (value = string(value))
    value isa Symbol && (value = String(value))
    if haskey(base, "enum")
        (value isa Bool || !_inenum(base["enum"], value)) &&
            refuse("value-invalid", "$where: value $(pyrepr(value)) is not one of $(pyrepr(base["enum"]))")
        return pystr(value)
    end
    t = get(base, "type", nothing)
    if t == "string"
        value isa AbstractString && return String(value)
        value isa Bool && return value ? "true" : "false"
        value isa Real && return format_number(value)
        refuse("value-invalid", "$where: $(pyrepr(value)) is not text")
    elseif t == "integer"
        (value isa Integer && !(value isa Bool)) || refuse("value-invalid", "$where: $(pyrepr(value)) is not an integer")
        return string(value)
    elseif t == "number"
        isnum(value) || refuse("value-invalid", "$where: $(pyrepr(value)) is not a number")
        return format_number(value)
    elseif t == "boolean"
        value isa Bool || refuse("value-invalid", "$where: $(pyrepr(value)) is not a boolean")
        return value ? "true" : "false"
    end
    value isa AbstractString && return String(value)
    refuse("no-format", "$where: value of type $(_typename(value)) has no format bound and is not a scalar — bind a format for this field";
        fix=jobj("action" => "bind-format", "field" => something(field, where), "key" => format_key(nothing, shape)))
end

"Kernel §7a, reading. Vocabulary reuses it so one grammar rules everywhere."
function read_value(shape, text::AbstractString, where::AbstractString)
    base, nullable = nullable_base(shape)
    nullable && wstrip(text) == "null" && return nothing
    if haskey(base, "enum")
        s = wstrip(text)
        for v in base["enum"]
            pystr(v) == s && return v
        end
        refuse("parse-value", "$where: $(pyrepr(s)) is not one of $(pyrepr(base["enum"]))")
    end
    t = get(base, "type", nothing)
    t == "integer" && return read_integer(text, where)
    t == "number" && return read_number(text, where)
    t == "boolean" && return read_boolean(text, where)
    String(text)
end

const _QUOTES = ('"', '\'', '`')

"""
Kernel §7a, forgiving reads: called only after the exact read refused. The
text without one pair of matching quotes, then also without one trailing
period; then without the period and then the quotes; then a nullable's
`null`/`none` and an enum member in any ASCII case when exactly one matches.
"""
function forgive_value(shape, text::AbstractString, where::AbstractString)
    base, nullable = nullable_base(shape)
    unquote(s) = (ncodeunits(s) >= 2 && s[1] == s[end] && s[1] in _QUOTES) ? wstrip(bsl(s, 1, ncodeunits(s) - 1)) : s
    unperiod(s) = (endswith(s, ".") && !endswith(s, "..")) ? wstrip(bsl(s, 0, ncodeunits(s) - 1)) : s
    t = wstrip(text)
    t1 = unquote(t)
    t2 = unperiod(t1)
    t3 = unquote(unperiod(t))
    texts = unique([t1, t2, t3])
    for c in texts
        (c == t || isempty(c)) && continue
        try
            return read_value(shape, c, where)
        catch err
            err isa Refusal || rethrow()
        end
    end
    for c in texts
        low = asciilower(c)
        nullable && (low == "null" || low == "none") && return nothing
        if haskey(base, "enum")
            hits = [v for v in base["enum"] if v isa AbstractString && asciilower(v) == low]
            length(hits) == 1 && return hits[1]
        end
    end
    read_value(shape, text, where)
end

"The structural keys a shape answers to, most specific first, never `*` (§5)."
function structural_keys(shape)
    base, _ = nullable_base(shape)
    is_media(base) && return ["media:" * pystr(base["media"]), "media:*"]
    haskey(base, "enum") && return ["enum"]
    t = get(base, "type", nothing)
    t in SCALAR_TYPES && return [t]
    if t == "array"
        items = get(base, "items", nothing)
        items = pytruthy(items) ? items : JObj()
        inner = isobj(items) ? structural_keys(items) : String[]
        return [["list[$k]" for k in inner if !startswith(k, "media")]; "list[*]"]
    end
    t == "object" && return ["object"]
    String[]
end

"The artifact key a format for this field binds under (errors.md `bind-format`)."
function format_key(type, shape)
    type !== nothing && !isempty(type) && return type
    keys = structural_keys(shape)
    isempty(keys) ? "*" : keys[1]
end

# ------------------------------------------------------------ parts, captures

textpart(text::AbstractString) = jobj("type" => "text", "text" => String(text))

"""
    Capture

What a find rule or the reader captured for one field: parts. `text(c)` is the
text-bearing parts, each stripped, joined by newlines (§6); a reader capture
holding non-text parts keeps its section's text (§4b).
"""
struct Capture
    parts::Vector{Any}
    _text::Union{Nothing,String}
end
Capture(parts) = Capture(Vector{Any}(parts), nothing)
capture_of_text(t::AbstractString) = Capture(Any[textpart(t)])
function text(c::Capture)
    c._text !== nothing && return c._text
    join((wstrip(p["text"]) for p in c.parts if get(p, "text", nothing) isa AbstractString), "\n")
end
parts_of(c::Capture, type::AbstractString) = [p for p in c.parts if get(p, "type", nothing) == type]

"A format's `write` returns text (one text part) or a part list."
function as_parts(written, where::AbstractString)
    written isa AbstractString && return Any[textpart(written)]
    if isarr(written) && all(p -> isobj(p) && haskey(p, "type"), written)
        return Any[p for p in written]
    end
    refuse("format-write-error", "$where: write must return text or a list of parts, got $(_typename(written))")
end

make_message(role, parts) = jobj("role" => role, "parts" => parts)

"Adjacent text parts merge; empty text parts vanish."
function merge_text_parts(parts)
    out = Any[]
    for p in parts
        if get(p, "type", nothing) == "text"
            isempty(get(p, "text", "")) && continue
            if !isempty(out) && get(out[end], "type", nothing) == "text"
                out[end] = textpart(out[end]["text"] * p["text"])
                continue
            end
        end
        push!(out, p)
    end
    out
end

"The shared batch and part-delta boundary; no text coercion."
function validate_response_part(part)
    (isobj(part) && get(part, "type", nothing) isa AbstractString) ||
        refuse("response-malformed", "response part must be an object with a string 'type' (an lm15 part)")
    haskey(part, "text") && !(part["text"] isa AbstractString) && refuse("response-malformed", "a response part's 'text' must be text")
    part["type"] == "data" && !haskey(part, "value") &&
        refuse("response-malformed", "a data part carries a 'value' (lm15 DataPart), even when it is null")
end

"Kernel §3: a data part's value as the reply text in its place (§7a numbers)."
data_text(value) = json_text(value; code="response-malformed")

function part_text(part)
    t = get(part, "type", nothing)
    t == "text" && return get(part, "text", "")
    t == "data" && return data_text(part["value"])
    ""
end

_message_of(response) = (isobj(response) && isobj(get(response, "message", nothing))) ? response["message"] : response

"Kernel §3: `(probabilities, measured_by)` from the reply's data parts, checked on intake."
function reply_probabilities(response)
    message = _message_of(response)
    parts = isobj(message) ? get(message, "parts", nothing) : nothing
    probabilities = JObj()
    measured = JObj()
    for part in (isarr(parts) ? parts : Any[])
        (isobj(part) && get(part, "type", nothing) == "data") || continue
        dist = get(part, "probabilities", nothing)
        method = get(part, "method", nothing)
        dist === nothing && method === nothing && continue
        (dist === nothing || method === nothing) &&
            refuse("response-malformed", "a data part's 'probabilities' and 'method' come together (lm15 INV-052)")
        (method isa AbstractString && isobj(dist)) ||
            refuse("response-malformed", "a data part's 'method' is text and its 'probabilities' an object {field: {key: p}}")
        for (field, keys) in dist
            (isobj(keys) && all(p -> isnum(p) && 0 <= p <= 1, values(keys))) ||
                refuse("response-malformed", "probabilities for $(pyrepr(field)) must map each answer key to a number in [0, 1]")
            haskey(probabilities, field) &&
                refuse("parse-ambiguous", "two data parts carry probabilities for $(pyrepr(field)) — refusing to guess which measured the answer")
            probabilities[field] = JObj(k => v for (k, v) in keys)
            measured[field] = method
        end
    end
    (probabilities, measured)
end

"Coalesce text runs as §8 does; the caller's parts are not changed."
function normalize_response_parts(parts)
    out = Any[]
    texts = String[]
    for part in parts
        validate_response_part(part)
        has_text = get(part, "text", nothing) isa AbstractString
        if has_text && !isempty(texts) && out[end]["type"] == part["type"]
            push!(texts, part["text"])
            for (k, v) in part
                k in ("type", "text") || (out[end][k] = v)
            end
            continue
        end
        isempty(texts) || (out[end]["text"] = join(texts))
        push!(out, JObj(String(k) => v for (k, v) in part))
        texts = has_text ? String[part["text"]] : String[]
    end
    isempty(texts) || (out[end]["text"] = join(texts))
    out
end

"The lm15 `finish_reason` of a response; `nothing` for a text or a message."
function finish_reason(response)
    if isobj(response) && isobj(get(response, "message", nothing))
        r = get(response, "finish_reason", nothing)
        return r isa AbstractString ? String(r) : nothing
    end
    nothing
end

"The reply text, an lm15 message or an lm15 response → `(text, parts)` (§3)."
function response_text_and_parts(response)
    response isa AbstractString && return (String(response), Any[])
    message = _message_of(response)
    if isobj(message) && isarr(get(message, "parts", nothing))
        parts = normalize_response_parts(message["parts"])
        return (join(part_text(p) for p in parts), parts)
    end
    refuse("response-malformed", "response must be text, an lm15 message {role, parts}, or an lm15 response {message: ...}")
end

# Foundations: refusals, JSON (strict reading; the kernel's one writer),
# the §7a text rules, byte-offset string helpers, and the reference's
# `repr` spelling (fix locators are contract data: `transports['tools']`).
#
# Positions are 0-based byte offsets with exclusive ends, like Python slices
# but over UTF-8 code units. Every marker is a whole UTF-8 sequence, so a
# byte search never matches inside a character and every position the kernel
# derives lands on a character boundary.

# ------------------------------------------------------------------ refusals

"""
    Refusal(code, hint; fix=nothing, partial=nothing)

Every failure in lmcc: a stable `code` (contract/spec/errors.md), a `hint`
naming the offender, a `fix` (the next action as data, on every refusal
before render) and, for parse refusals, a `partial` with what was read.
"""
struct Refusal <: Exception
    code::String
    hint::String
    fix::Union{Nothing,OrderedDict{String,Any}}
    partial::Union{Nothing,OrderedDict{String,Any}}
end

Refusal(code, hint; fix=nothing, partial=nothing) = Refusal(String(code), String(hint), _fixdict(fix), _fixdict(partial))
_fixdict(::Nothing) = nothing
_fixdict(d::AbstractDict) = OrderedDict{String,Any}(String(k) => v for (k, v) in d)
_fixdict(p::NamedTuple) = OrderedDict{String,Any}(String(k) => v for (k, v) in pairs(p))

refuse(code, hint; fix=nothing, partial=nothing) = throw(Refusal(code, hint; fix=fix, partial=partial))

"The refusal as plain data: `code`, `hint`, `fix`, `partial`."
describe(r::Refusal) = OrderedDict{String,Any}("code" => r.code, "hint" => r.hint, "fix" => r.fix, "partial" => r.partial)
Base.showerror(io::IO, r::Refusal) = print(io, "[", r.code, "] ", r.hint)

isrefusal(x) = x isa Refusal

# ---------------------------------------------------------------- JSON values

const JObj = OrderedDict{String,Any}
jobj(pairs::Pair...) = JObj(String(k) => v for (k, v) in pairs)

isobj(x) = x isa AbstractDict
isarr(x) = x isa AbstractVector && !(x isa AbstractString)
isnum(x) = x isa Real && !(x isa Bool)

"Plain data: `NamedTuple`s become ordered objects, `Symbol` keys strings, tuples arrays."
function tojsonvalue(x)
    x isa NamedTuple && return JObj(String(k) => tojsonvalue(v) for (k, v) in pairs(x))
    x isa AbstractDict && return JObj(string(k) => tojsonvalue(v) for (k, v) in x)
    x isa Tuple && return Any[tojsonvalue(v) for v in x]
    isarr(x) && return Any[tojsonvalue(v) for v in x]
    x isa Symbol && return String(x)
    x isa AbstractString && return String(x)
    x isa Enum && return string(x)
    return x
end

deepcopy_json(x) = isobj(x) ? JObj(String(k) => deepcopy_json(v) for (k, v) in x) :
                   isarr(x) ? Any[deepcopy_json(v) for v in x] : x

"JSON equality as the reference compares values: objects unordered, numbers by value."
function json_equal(a, b)
    (a isa Real) && (b isa Real) && return a == b
    (a isa Real || b isa Real) && return false
    a === nothing && return b === nothing
    b === nothing && return false
    if isobj(a) && isobj(b)
        length(a) == length(b) || return false
        for (k, v) in a
            haskey(b, k) || return false
            json_equal(v, b[k]) || return false
        end
        return true
    end
    if isarr(a) && isarr(b)
        length(a) == length(b) || return false
        return all(json_equal(x, y) for (x, y) in zip(a, b))
    end
    (isobj(a) || isobj(b) || isarr(a) || isarr(b)) && return false
    return a == b
end

# ------------------------------------------------------------------ reading

struct JSONSyntaxError <: Exception
    msg::String
    pos::Int
end
Base.showerror(io::IO, e::JSONSyntaxError) = print(io, e.msg, " at ", e.pos)

mutable struct _JP
    s::Vector{UInt8}
    text::String
    i::Int              # 1-based
    reject_dups::Bool
end

_jfail(p::_JP, msg) = throw(JSONSyntaxError(msg, p.i - 1))
function _jws(p::_JP)
    s = p.s
    while p.i <= length(s) && (s[p.i] == 0x20 || s[p.i] == 0x09 || s[p.i] == 0x0a || s[p.i] == 0x0d)
        p.i += 1
    end
end

function _jvalue(p::_JP, depth::Int=0)
    depth > 512 && _jfail(p, "nesting too deep")
    p.i > length(p.s) && _jfail(p, "expected a value")
    c = p.s[p.i]
    c == UInt8('{') && return _jobject(p, depth)
    c == UInt8('[') && return _jarray(p, depth)
    c == UInt8('"') && return _jstring(p)
    c == UInt8('t') && return _jliteral(p, "true", true)
    c == UInt8('f') && return _jliteral(p, "false", false)
    c == UInt8('n') && return _jliteral(p, "null", nothing)
    (c == UInt8('-') || UInt8('0') <= c <= UInt8('9')) && return _jnumber(p)
    _jfail(p, "unexpected character")
end

function _jliteral(p::_JP, word, value)
    n = ncodeunits(word)
    if p.i + n - 1 <= length(p.s) && view(p.s, p.i:p.i+n-1) == codeunits(word)
        p.i += n
        return value
    end
    _jfail(p, "invalid literal")
end

_isdigit(c) = UInt8('0') <= c <= UInt8('9')

function _jnumber(p::_JP)
    s = p.s
    start = p.i
    p.i <= length(s) && s[p.i] == UInt8('-') && (p.i += 1)
    if p.i <= length(s) && s[p.i] == UInt8('0')
        p.i += 1
    elseif p.i <= length(s) && UInt8('1') <= s[p.i] <= UInt8('9')
        while p.i <= length(s) && _isdigit(s[p.i]); p.i += 1; end
    else
        _jfail(p, "invalid number")
    end
    integral = true
    if p.i <= length(s) && s[p.i] == UInt8('.')
        integral = false
        p.i += 1
        (p.i <= length(s) && _isdigit(s[p.i])) || _jfail(p, "invalid number")
        while p.i <= length(s) && _isdigit(s[p.i]); p.i += 1; end
    end
    if p.i <= length(s) && (s[p.i] == UInt8('e') || s[p.i] == UInt8('E'))
        integral = false
        p.i += 1
        p.i <= length(s) && (s[p.i] == UInt8('+') || s[p.i] == UInt8('-')) && (p.i += 1)
        (p.i <= length(s) && _isdigit(s[p.i])) || _jfail(p, "invalid number")
        while p.i <= length(s) && _isdigit(s[p.i]); p.i += 1; end
    end
    text = String(s[start:p.i-1])
    integral ? integer_value(text) : parse_f64(text)
end

"""
A decimal (JSON grammar) as binary64, correctly rounded; overflow gives ±Inf
and underflow ±0.0 as C's `strtod` and the reference do (Julia's own `parse`
refuses both).
"""
function parse_f64(t::AbstractString)
    v = tryparse(Float64, t)
    v !== nothing && return v
    big = Base.parse(BigFloat, t; base=10)
    neg = startswith(t, "-")
    abs(big) > 1 ? (neg ? -Inf : Inf) : (neg ? -0.0 : 0.0)
end

"An integer's decimal text: `Int64` when it fits, else `BigInt` (at least int64, §7a)."
function integer_value(text::AbstractString)
    v = tryparse(Int64, text)
    v === nothing ? Base.parse(BigInt, text) : v
end

function _jstring(p::_JP)
    s = p.s
    p.i += 1
    buf = IOBuffer()
    run = p.i
    while true
        p.i > length(s) && _jfail(p, "unterminated string")
        c = s[p.i]
        if c == UInt8('"')
            write(buf, view(s, run:p.i-1))
            p.i += 1
            str = String(take!(buf))
            isvalid(str) || _jfail(p, "invalid UTF-8")
            return str
        end
        c < 0x20 && _jfail(p, "control character in string")
        if c != UInt8('\\')
            p.i += 1
            continue
        end
        write(buf, view(s, run:p.i-1))
        p.i + 1 > length(s) && _jfail(p, "invalid escape")
        e = s[p.i+1]
        if e == UInt8('"'); write(buf, '"')
        elseif e == UInt8('\\'); write(buf, '\\')
        elseif e == UInt8('/'); write(buf, '/')
        elseif e == UInt8('b'); write(buf, '\b')
        elseif e == UInt8('f'); write(buf, '\f')
        elseif e == UInt8('n'); write(buf, '\n')
        elseif e == UInt8('r'); write(buf, '\r')
        elseif e == UInt8('t'); write(buf, '\t')
        elseif e == UInt8('u')
            p.i + 5 <= length(s) || _jfail(p, "invalid \\u escape")
            hex = String(s[p.i+2:p.i+5])
            all(ch -> isxdigit(ch), hex) || _jfail(p, "invalid \\u escape")
            u = Base.parse(UInt16, hex; base=16)
            if 0xd800 <= u <= 0xdbff && p.i + 11 <= length(s) && s[p.i+6] == UInt8('\\') && s[p.i+7] == UInt8('u')
                hex2 = String(s[p.i+8:p.i+11])
                if all(isxdigit, hex2)
                    l = Base.parse(UInt16, hex2; base=16)
                    if 0xdc00 <= l <= 0xdfff
                        write(buf, Char(0x10000 + ((UInt32(u) - 0xd800) << 10) + (UInt32(l) - 0xdc00)))
                        p.i += 6
                        p.i += 6
                        run = p.i
                        continue
                    end
                end
            end
            write(buf, 0xd800 <= u <= 0xdfff ? '\ufffd' : Char(u))
            p.i += 4
        else
            _jfail(p, "invalid escape")
        end
        p.i += 2
        run = p.i
    end
end

function _jarray(p::_JP, depth)
    p.i += 1
    out = Any[]
    _jws(p)
    if p.i <= length(p.s) && p.s[p.i] == UInt8(']')
        p.i += 1
        return out
    end
    while true
        _jws(p)
        push!(out, _jvalue(p, depth + 1))
        _jws(p)
        p.i > length(p.s) && _jfail(p, "expected ',' or ']'")
        c = p.s[p.i]
        p.i += 1
        c == UInt8(']') && return out
        c == UInt8(',') || (p.i -= 1; _jfail(p, "expected ',' or ']'"))
    end
end

function _jobject(p::_JP, depth)
    p.i += 1
    out = JObj()
    _jws(p)
    if p.i <= length(p.s) && p.s[p.i] == UInt8('}')
        p.i += 1
        return out
    end
    while true
        _jws(p)
        (p.i <= length(p.s) && p.s[p.i] == UInt8('"')) || _jfail(p, "expected a member name")
        key = _jstring(p)
        _jws(p)
        (p.i <= length(p.s) && p.s[p.i] == UInt8(':')) || _jfail(p, "expected ':'")
        p.i += 1
        _jws(p)
        value = _jvalue(p, depth + 1)
        haskey(out, key) && p.reject_dups && _jfail(p, "duplicate member \"$key\"")
        out[key] = value
        _jws(p)
        p.i > length(p.s) && _jfail(p, "expected ',' or '}'")
        c = p.s[p.i]
        p.i += 1
        c == UInt8('}') && return out
        c == UInt8(',') || (p.i -= 1; _jfail(p, "expected ',' or '}'"))
    end
end

"""
    parse_json(text; duplicates=:last)

Strict RFC 8259 JSON: objects as ordered `OrderedDict{String,Any}`, integers
as `Int64` (or `BigInt` beyond it), other numbers `Float64`, `null` as
`nothing`. `duplicates=:reject` refuses a member named twice.
"""
function parse_json(text::AbstractString; duplicates::Symbol=:last)
    str = String(text)
    p = _JP(codeunits(str) |> collect, str, 1, duplicates === :reject)
    _jws(p)
    v = _jvalue(p)
    _jws(p)
    p.i <= length(p.s) && _jfail(p, "trailing data")
    v
end

"One value starting exactly at 0-based byte offset `start`: `(value, end)`."
function parse_json_at(text::String, start::Int; duplicates::Symbol=:last)
    p = _JP(collect(codeunits(text)), text, start + 1, duplicates === :reject)
    v = _jvalue(p)
    (v, p.i - 1)
end

# ------------------------------------------------------------------ writing

"""
    format_number(x)

Kernel §7a: the ECMAScript `Number::toString` spelling over the shortest
round-trip digits (`3`, `0.5`, `1e-7`, `1e+21`); non-finite refuses
`value-invalid`.
"""
function format_number(x::Real; code::AbstractString="value-invalid")
    x isa Integer && !(x isa Bool) && return string(x)
    v = Float64(x)
    isfinite(v) || refuse(code, "$(x) has no portable number spelling")
    v == 0 && return "0"
    sign = v < 0 ? "-" : ""
    digits, n = _shortest(abs(v))
    k = length(digits)
    body = if k <= n <= 21
        digits * "0"^(n - k)
    elseif 0 < n <= 21
        digits[1:n] * "." * digits[n+1:end]
    elseif -6 < n <= 0
        "0." * "0"^(-n) * digits
    else
        e = n - 1
        (k == 1 ? digits : digits[1:1] * "." * digits[2:end]) * "e" * (e >= 0 ? "+" : "-") * string(abs(e))
    end
    sign * body
end

# Shortest round-trip digits of a positive double and n (value = 0.d1…dk × 10^n).
function _shortest(v::Float64)
    s = repr(v)                      # Julia prints the shortest round-trip digits
    mant, ex = occursin('e', s) ? split(s, 'e') : (s, "0")
    whole, frac = occursin('.', mant) ? split(mant, '.') : (mant, "")
    e = Base.parse(Int, ex)
    wz = lstrip(whole, '0')
    if !isempty(wz)
        digits = wz * frac
        n = length(wz) + e
    else
        fz = lstrip(frac, '0')
        digits = fz
        n = e - (length(frac) - length(fz))
    end
    digits = rstrip(digits, '0')
    (String(digits), n)
end

const _SHORT_ESC = OrderedDict('"' => "\\\"", '\\' => "\\\\", '\b' => "\\b", '\f' => "\\f", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t")

"A JSON string: `\"`, `\\` and U+0000–U+001F escaped, everything else verbatim."
function json_string(s::AbstractString)
    io = IOBuffer()
    write(io, '"')
    for c in s
        e = get(_SHORT_ESC, c, nothing)
        if e !== nothing
            write(io, e)
        elseif c < ' '
            write(io, "\\u", string(UInt32(c); base=16, pad=4))
        else
            write(io, c)
        end
    end
    write(io, '"')
    String(take!(io))
end

"""
    json_text(value; sort_keys=false, spaced=false, code="value-invalid")

JSON as the kernel writes it (§3, §3a, §6; D-54): numbers by §7a, strings
minimally escaped; `sort_keys` orders members by code point (canonical JSON),
`spaced` separates with `, ` and `: `. A value with no JSON form refuses `code`.
"""
function json_text(value; sort_keys::Bool=false, spaced::Bool=false, code::AbstractString="value-invalid")
    io = IOBuffer()
    item = spaced ? ", " : ","
    colon = spaced ? ": " : ":"
    function w(v)
        if v === nothing
            write(io, "null")
        elseif v isa Bool
            write(io, v ? "true" : "false")
        elseif v isa Integer
            write(io, string(v))
        elseif v isa Real
            isfinite(v) || refuse(code, "$(v) has no JSON spelling")
            write(io, format_number(v))
        elseif v isa AbstractString
            write(io, json_string(v))
        elseif v isa Symbol
            write(io, json_string(String(v)))
        elseif isobj(v) || v isa NamedTuple
            ks = v isa NamedTuple ? String[String(k) for k in keys(v)] : Any[k for k in keys(v)]
            for k in ks
                k isa AbstractString || refuse(code, "a JSON object key must be text, got $(repr(k))")
            end
            sort_keys && (ks = sort(String.(ks)))
            write(io, '{')
            for (i, k) in enumerate(ks)
                i > 1 && write(io, item)
                write(io, json_string(k), colon)
                w(v isa NamedTuple ? v[Symbol(k)] : v[k])
            end
            write(io, '}')
        elseif isarr(v) || v isa Tuple
            write(io, '[')
            for (i, x) in enumerate(v)
                i > 1 && write(io, item)
                w(x)
            end
            write(io, ']')
        else
            refuse(code, "a $(typeof(v)) is not JSON data")
        end
    end
    w(value)
    String(take!(io))
end

"A readable dump for messages (indented, not canonical)."
pretty(x) = json_text(x; spaced=true)

# ------------------------------------------------------------ text (§7a)

const WHITESPACE = " \t\n\r\f\v"
isws(c::Char) = c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'
isws(b::UInt8) = b == 0x20 || b == 0x09 || b == 0x0a || b == 0x0d || b == 0x0c || b == 0x0b

"Trim the six ASCII whitespace characters, nothing else."
wstrip(s::AbstractString) = String(Base.strip(isws, s))
wlstrip(s::AbstractString) = String(Base.lstrip(isws, s))
wrstrip(s::AbstractString) = String(Base.rstrip(isws, s))
cstrip(s::AbstractString, chars) = String(Base.strip(c -> c in chars, s))

const _IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"
const _PURPOSE = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
const _INTEGER = r"^-?[0-9]+$"
const _NUMBER = r"^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$"

isidentifier(x) = x isa AbstractString && occursin(_IDENT, x)

function read_integer(text::AbstractString, where::AbstractString)
    t = wstrip(text)
    occursin(_INTEGER, t) || refuse("parse-value", "$where: $(pyrepr(t)) is not an integer")
    integer_value(t)
end

function read_number(text::AbstractString, where::AbstractString)
    t = wstrip(text)
    occursin(_NUMBER, t) || refuse("parse-value", "$where: $(pyrepr(t)) is not a number")
    v = parse_f64(t)
    isfinite(v) || refuse("parse-value", "$where: $(pyrepr(t)) is not a finite number")
    v
end

asciilower(s::AbstractString) = map(c -> 'A' <= c <= 'Z' ? c + 32 : c, s)

function read_boolean(text::AbstractString, where::AbstractString)
    t = wstrip(text)
    low = asciilower(t)
    (low == "true" || low == "yes") && return true
    (low == "false" || low == "no") && return false
    refuse("parse-value", "$where: $(pyrepr(t)) is not a boolean")
end

"Truthiness as the reference host tests it: empty containers, `\"\"`, 0 and `nothing` are false."
pytruthy(x) = x === nothing ? false : x isa Bool ? x : x isa Number ? x != 0 :
              x isa AbstractString ? !isempty(x) : (isobj(x) || isarr(x)) ? !isempty(x) : true

# ------------------------------------------------------ byte-offset strings

blen(s::AbstractString) = ncodeunits(s)
"`s[a:b]` in 0-based byte offsets, end exclusive."
bsl(s::AbstractString, a::Integer, b::Integer=ncodeunits(s)) = a >= b ? "" : String(view(codeunits(s), a+1:b))
bsl_from(s::AbstractString, a::Integer) = bsl(s, a, ncodeunits(s))

"0-based byte offset of `needle` in `s` at or after `from`, or -1."
function bfind(s::AbstractString, needle::AbstractString, from::Integer=0)
    n = ncodeunits(needle)
    n == 0 && return from <= ncodeunits(s) ? from : -1
    from + n > ncodeunits(s) && return -1
    r = findnext(codeunits(needle), codeunits(s), from + 1)
    r === nothing ? -1 : first(r) - 1
end

"Non-overlapping occurrences (an empty needle counts `len + 1`)."
function bcount(s::AbstractString, needle::AbstractString)
    isempty(needle) && return length(s) + 1
    n = 0
    i = bfind(s, needle, 0)
    while i >= 0
        n += 1
        i = bfind(s, needle, i + ncodeunits(needle))
    end
    n
end

bstartswith(s::AbstractString, p::AbstractString, at::Integer=0) =
    at + ncodeunits(p) <= ncodeunits(s) && view(codeunits(s), at+1:at+ncodeunits(p)) == codeunits(p)

"The byte at 0-based offset `i` as a Char when ASCII, else '\\0' (only ASCII sets are ever tested)."
bchar(s::AbstractString, i::Integer) = (0 <= i < ncodeunits(s) && codeunit(s, i + 1) < 0x80) ? Char(codeunit(s, i + 1)) : '\0'

"Move a byte offset back to the start of the character holding it."
function boundary(s::AbstractString, i::Integer)
    while 0 < i < ncodeunits(s) && (codeunit(s, i + 1) & 0xc0) == 0x80
        i -= 1
    end
    i
end

"Byte length of the last `n` characters of `s`."
function lastchars_bytes(s::AbstractString, n::Integer)
    i = ncodeunits(s)
    k = 0
    while k < n && i > 0
        i = boundary(s, i - 1)
        k += 1
    end
    ncodeunits(s) - i
end

# ------------------------------------------------------ the reference's repr

function _printable(c::Char)
    c == ' ' && return true
    cat = Base.Unicode.category_code(c)
    # Python's str.isprintable: not Cc Cf Cs Co Cn Zl Zp Zs (space excepted)
    !(cat in (Base.Unicode.UTF8PROC_CATEGORY_CC, Base.Unicode.UTF8PROC_CATEGORY_CF, Base.Unicode.UTF8PROC_CATEGORY_CS,
              Base.Unicode.UTF8PROC_CATEGORY_CO, Base.Unicode.UTF8PROC_CATEGORY_CN, Base.Unicode.UTF8PROC_CATEGORY_ZL,
              Base.Unicode.UTF8PROC_CATEGORY_ZP, Base.Unicode.UTF8PROC_CATEGORY_ZS))
end

function _reprstr(s::AbstractString)
    q = ('\'' in s && !('"' in s)) ? '"' : '\''
    io = IOBuffer()
    write(io, q)
    for c in s
        cp = UInt32(c)
        if c == q || c == '\\'
            write(io, '\\', c)
        elseif c == '\t'; write(io, "\\t")
        elseif c == '\n'; write(io, "\\n")
        elseif c == '\r'; write(io, "\\r")
        elseif cp < 0x20 || cp == 0x7f
            write(io, "\\x", string(cp; base=16, pad=2))
        elseif cp < 0x7f || _printable(c)
            write(io, c)
        elseif cp <= 0xff
            write(io, "\\x", string(cp; base=16, pad=2))
        elseif cp <= 0xffff
            write(io, "\\u", string(cp; base=16, pad=4))
        else
            write(io, "\\U", string(cp; base=16, pad=8))
        end
    end
    write(io, q)
    String(take!(io))
end

function _reprfloat(x::Float64)
    isnan(x) && return "nan"
    isinf(x) && return x > 0 ? "inf" : "-inf"
    x == 0 && return signbit(x) ? "-0.0" : "0.0"
    digits, n = _shortest(abs(x))
    sign = x < 0 ? "-" : ""
    e = n - 1
    if -4 <= e < 16
        n <= 0 && return sign * "0." * "0"^(-n) * digits
        whole = rpad(digits[1:min(n, length(digits))], n, '0')
        frac = n < length(digits) ? digits[n+1:end] : "0"
        return sign * whole * "." * frac
    end
    sign * digits[1:1] * (length(digits) > 1 ? "." * digits[2:end] : "") * "e" * (e < 0 ? "-" : "+") * lpad(string(abs(e)), 2, '0')
end

"The reference host's `repr` of JSON-like data (`'a'`, `None`, `[1, 'b']`)."
function pyrepr(x)
    x === nothing && return "None"
    x === true && return "True"
    x === false && return "False"
    x isa AbstractString && return _reprstr(x)
    x isa Integer && return string(x)
    x isa Real && return _reprfloat(Float64(x))
    isarr(x) && return "[" * join((pyrepr(v) for v in x), ", ") * "]"
    isobj(x) && return "{" * join((_reprstr(string(k)) * ": " * pyrepr(v) for (k, v) in x), ", ") * "}"
    string(x)
end

"The reference host's `str`: text as itself, everything else as `pyrepr`."
pystr(x) = x isa AbstractString ? String(x) : pyrepr(x)

sortedrepr(xs) = pyrepr(sort(collect(String, xs)))

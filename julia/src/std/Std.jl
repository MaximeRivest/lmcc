"""
    LMCC.Std

The standard vocabulary pack: formats `json`, `table`, `scaled_number`,
`function_tool`, `tool_catalog`, `tool_calls`, `citations`, `source_list`,
`code_arguments`, `code_calls`; transports `prefix_cot`, `reasoning_tags`,
`native_reasoning`, `native_tools`, `fenced_tools`, `native_citations`,
`inline_citations`, `heredoc_tools`; reader `json_object`. It registers
through the same sockets your own vocabulary uses: nothing here is
privileged. `LMCC.Std.install!(registry)`.
"""
module Std

import ..LMCC
using ..LMCC: JObj, jobj, Format, Field, Capture, Transport, Registry, Reader, refuse, pyrepr, pystr, isobj, isarr, text,
    parts_of, wstrip, bsl, blen, format_number, json_string, read_value, register_format!, register_transport!, register_reader!,
    integer_value, pytruthy, tojsonvalue, Refusal

const VERSION = "0.1.0"

# ------------------------------------------------------------------ jsontext

"Indented layout (ECMAScript `JSON.stringify(v, null, n)`) when `indent` is an Int, else one line with `, ` / `: `; numbers by §7a."
function dumps(value, indent=2)
    io = IOBuffer()
    _dw(io, tojsonvalue(value), indent, 0)
    String(take!(io))
end

function _dw(io, v, indent, depth)
    if v === nothing; write(io, "null")
    elseif v isa Bool; write(io, v ? "true" : "false")
    elseif v isa Real; write(io, format_number(v))
    elseif v isa AbstractString; write(io, json_string(v))
    elseif isobj(v) || isarr(v)
        items = isobj(v) ? collect(pairs(v)) : [nothing => x for x in v]
        if isempty(items)
            write(io, isobj(v) ? "{}" : "[]")
            return
        end
        write(io, isobj(v) ? "{" : "[")
        pad = indent === nothing ? "" : "\n" * " "^(indent * (depth + 1))
        sep = indent === nothing ? ", " : "," * pad
        stop = indent === nothing ? "" : "\n" * " "^(indent * depth)
        for (i, (k, x)) in enumerate(items)
            write(io, i == 1 ? pad : sep)
            if isobj(v)
                k isa AbstractString || error("object keys must be strings")
                write(io, json_string(k), ": ")
            end
            _dw(io, x, indent, depth + 1)
        end
        write(io, stop, isobj(v) ? "}" : "]")
    else
        error("$(typeof(v)) is not JSON data")
    end
end

"Strict RFC 8259: no NaN/Infinity, no duplicate members."
loads(t::AbstractString) = LMCC.parse_json(t; duplicates=:reject)

_jws(s, i) = (while i < blen(s) && LMCC.bchar(s, i) in (' ', '\t', '\n', '\r'); i += 1; end; i)

"One JSON object's top-level members as `(key, value, source)`, document order, duplicates kept."
function members(t::AbstractString)
    s = String(t)
    i = _jws(s, 0)
    (i < blen(s) && LMCC.bchar(s, i) == '{') || error("not a JSON object")
    i = _jws(s, i + 1)
    out = Tuple{String,Any,String}[]
    finish(at) = _jws(s, at) == blen(s) || error("trailing data after the JSON object")
    if i < blen(s) && LMCC.bchar(s, i) == '}'
        finish(i + 1)
        return out
    end
    while true
        (i < blen(s) && LMCC.bchar(s, i) == '"') || error("expected a member name at $i")
        key, i = LMCC.parse_json_at(s, i; duplicates=:reject)
        i = _jws(s, i)
        (i < blen(s) && LMCC.bchar(s, i) == ':') || error("expected ':' at $i")
        i = _jws(s, i + 1)
        value, j = LMCC.parse_json_at(s, i; duplicates=:reject)
        push!(out, (key, value, bsl(s, i, j)))
        i = _jws(s, j)
        if i < blen(s) && LMCC.bchar(s, i) == ','
            i = _jws(s, i + 1)
            continue
        end
        if i < blen(s) && LMCC.bchar(s, i) == '}'
            finish(i + 1)
            return out
        end
        error("expected ',' or '}' at $i")
    end
end

_errmsg(err) = err isa Refusal ? err.hint : sprint(showerror, err)

# ------------------------------------------------------------------ formats

const _FENCE = r"^[ \t\n\r\f\v]*```[a-zA-Z0-9_-]*[ \t\n\r\f\v]*\n(.*?)\n?[ \t\n\r\f\v]*```[ \t\n\r\f\v]*$"s

"Values spelled as JSON (spec/vocab/format-json.md). Option `indent` (default 2)."
function json_format(options)
    indent = haskey(options, "indent") ? options["indent"] : 2
    Format(nothing, ["*"], "both", "text", true, ["text"],
        (v, f) -> dumps(v, indent),
        (c, f) -> begin
            t = text(c)
            m = match(_FENCE, t)
            m === nothing || (t = String(m.captures[1]))
            loads(t)
        end,
        f -> "JSON matching this schema: " * dumps(f.shape, nothing), nothing)
end

function _cell_read(shape, t, where)
    try
        return read_value(shape, t, where)
    catch err
        err isa Refusal ? error(err.hint) : rethrow()
    end
end

function _spell_cell(cell, col)
    cell isa AbstractString && return String(cell)
    cell isa Bool && return cell ? "true" : "false"
    cell isa Real && return format_number(cell)
    error("column $(pyrepr(col)): $(typeof(cell)) is not a cell value")
end

"A list of flat objects as a delimiter table (spec/vocab/format-table.md)."
function table_format(options)
    haskey(options, "columns") || error("table codec requires the 'columns' option")
    columns = String[c for c in options["columns"]]
    delim = get(options, "delimiter", "|")
    esc = get(options, "escape", "\\")
    nulltext = get(options, "null", "")
    function split_row(line)
        inner = bsl(line, blen(delim))
        endswith(inner, delim) && (inner = bsl(inner, 0, blen(inner) - blen(delim)))
        cells = String[]
        cur = IOBuffer()
        i = 0
        while i < blen(inner)
            if LMCC.bstartswith(inner, esc, i) && i + blen(esc) < blen(inner)
                nxt = nextind(inner, i + blen(esc) + 1) - 1
                write(cur, bsl(inner, i + blen(esc), nxt))
                i = nxt
                continue
            end
            if LMCC.bstartswith(inner, delim, i)
                push!(cells, String(take!(cur)))
                i += blen(delim)
                continue
            end
            nxt = nextind(inner, i + 1) - 1
            write(cur, bsl(inner, i, nxt))
            i = nxt
        end
        push!(cells, String(take!(cur)))
        cells
    end
    write_fn(v, f) = begin
        rows = String[]
        for item in tojsonvalue(v)
            cells = String[]
            for col in columns
                cell = get(item, col, nothing)
                c = cell === nothing ? nulltext : _spell_cell(cell, col)
                c = replace(c, esc => esc * esc)
                c = replace(c, delim => esc * delim)
                push!(cells, c)
            end
            push!(rows, "$delim " * join(cells, " $delim ") * " $delim")
        end
        join(rows, "\n")
    end
    read_fn(c, f) = begin
        items = something(get(f.shape, "items", nothing), JObj())
        props = pytruthy(items) ? get(items, "properties", JObj()) : JObj()
        t = text(c)
        lines = split(t, '\n')
        rows = [l for l in lines if startswith(wstrip(l), delim)]
        if isempty(rows) && !isempty(wstrip(t))
            preview = first(wstrip(t), 60)
            error("no table row (a line starting with $(pyrepr(delim))) in $(pyrepr(preview)); an empty table is written as nothing")
        end
        out = Any[]
        for line in lines
            line = wstrip(line)
            startswith(line, delim) || continue
            cells = split_row(line)
            [wstrip(x) for x in cells] == columns && continue
            length(cells) == length(columns) || error("row has $(length(cells)) cells, expected $(length(columns)) ($(pyrepr(Any[columns...]))): $(pyrepr(line))")
            item = JObj()
            for (col, cell) in zip(columns, cells)
                cell = wstrip(cell)
                item[col] = cell == nulltext ? nothing : _cell_read(get(props, col, JObj()), cell, "column $(pyrepr(col))")
            end
            push!(out, item)
        end
        out
    end
    Format(nothing, ["list[object]", "list[*]"], "both", "text", true, ["text"], write_fn, read_fn,
        f -> "$delim " * join(columns, " $delim ") * " $delim" * "  (one row per item)", nothing)
end

"Numbers at a friendlier scale, 0.78 ⇄ \"78%\" (spec/vocab/format-scaled_number.md)."
function scaled_number_format(options)
    scale = get(options, "scale", 1)
    suffix = get(options, "suffix", "")
    rnd = get(options, "round", nothing)
    Format(nothing, ["number", "integer"], "both", "text", rnd === nothing, ["text"],
        (v, f) -> begin
            x = Float64(v) * scale
            rnd === nothing || (p = 10.0^rnd; x = round(x * p) / p)
            format_number(x) * suffix
        end,
        (c, f) -> begin
            t = wstrip(text(c))
            !isempty(suffix) && endswith(t, suffix) && (t = bsl(t, 0, blen(t) - blen(suffix)))
            _cell_read(jobj("type" => "number"), t, "scaled_number") / scale
        end,
        f -> "a number like $(scale == 100 ? "83" : "0.83")$suffix", nothing)
end

# ------------------------------------------------------------------ reader

"The reply is one JSON object keyed by field name (spec/vocab/reader-json_object.md)."
struct JsonObjectReader <: Reader
    spec::JObj
end
const PROBABILITY_POLICIES = ("off", "if_available", "required")

function json_object_reader(spec)
    extra = sort([String(k) for k in keys(spec) if !(k in ("kind", "probabilities"))])
    policy = get(spec, "probabilities", nothing)
    (!isempty(extra) || (policy !== nothing && !(policy in PROBABILITY_POLICIES))) && refuse("entry-malformed",
        "reader: json_object takes 'probabilities' ($(join(PROBABILITY_POLICIES, " | ")))" * (isempty(extra) ? ", not $(pyrepr(policy))" : ", not $(pyrepr(Any[extra...]))");
        fix=jobj("action" => "edit-entry", "path" => "reader"))
    JsonObjectReader(JObj(String(k) => v for (k, v) in spec))
end

LMCC.reader_requires(::JsonObjectReader) = ["native_structured_output"]
LMCC.reader_spec(r::JsonObjectReader) = r.spec
function LMCC.reader_request_settings(r::JsonObjectReader, fields)
    props = JObj(f.name => (f.desc !== nothing && !isempty(f.desc) ? merge(copy(f.shape), jobj("description" => f.desc)) : copy(f.shape)) for f in fields)
    config = jobj("response_format" => jobj("type" => "json_schema",
        "schema" => jobj("type" => "object", "properties" => props, "required" => Any[f.name for f in fields], "additionalProperties" => false)))
    policy = get(r.spec, "probabilities", nothing)
    policy === nothing || (config["probabilities"] = policy)
    jobj("config" => config)
end

function _document(t)
    s = wstrip(t)
    if startswith(s, "```")
        nl = LMCC.bfind(s, "\n")
        closing = let k = -1, i = LMCC.bfind(s, "```"); while i >= 0; k = i; i = LMCC.bfind(s, "```", i + 1); end; k end
        nl >= 0 && closing > nl && (s = wstrip(bsl(s, nl + 1, closing)))
    end
    try
        return members(s)
    catch first_err
        first_err isa Refusal && rethrow()
        start = LMCC.bfind(s, "{")
        stop = let k = -1, i = LMCC.bfind(s, "}"); while i >= 0; k = i; i = LMCC.bfind(s, "}", i + 1); end; k end
        0 <= start < stop || refuse("reader-error", "json_object: reply contains no JSON object ($(_errmsg(first_err)))")
        try
            return members(bsl(s, start, stop + 1))
        catch err
            err isa Refusal && rethrow()
            refuse("reader-error", "json_object: reply is not a JSON object: $(_errmsg(err))")
        end
    end
end

function LMCC.reader_split(r::JsonObjectReader, t, names)
    wanted = Set(names)
    raw = JObj()
    for (key, value, source) in _document(t)
        key in wanted || continue
        haskey(raw, key) && refuse("parse-ambiguous", "json_object: member $(pyrepr(key)) appears more than once in the reply — refusing to guess which one is real")
        raw[key] = value isa AbstractString ? value : wstrip(source)
    end
    missing = [n for n in names if !haskey(raw, n)]
    isempty(missing) || refuse("parse-missing-fields", "reply object is missing key(s): " * join(pyrepr.(missing), ", "); partial=raw)
    raw
end

function LMCC.reader_join(r::JsonObjectReader, spelled)
    obj = JObj()
    for (name, t) in spelled
        v = t
        try
            parsed = loads(t)
            parsed isa AbstractString || (v = parsed)
        catch
        end
        obj[name] = v
    end
    dumps(obj, 2)
end

# ------------------------------------------------------------------ reasoning

prefix_cot(_) = Transport(requires=["instruct"], in_template=true,
    tell=jobj("system" => "Reason step by step in the '{field}' section before writing any other section."))

function reasoning_tags(options)
    o, c = get(options, "open", "<think>"), get(options, "close", "</think>")
    Transport(requires=["instruct"], in_template=false,
        tell=jobj("system" => "After every sentence of output, add your thinking inside $(o)...$(c) tags."),
        find=[jobj("from" => "text", "between" => Any[o, c], "to" => "@purpose", "remove" => true, "repair" => true)],
        spelling=jobj("position" => "before"))
end

function native_reasoning(options)
    reasoning = jobj("effort" => get(options, "effort", "medium"))
    haskey(options, "thinking_budget") && (reasoning["thinking_budget"] = options["thinking_budget"])
    Transport(requires=["native_reasoning"], in_template=false, request_settings=jobj("config" => jobj("reasoning" => reasoning)),
        find=[jobj("from" => "part:thinking", "to" => "@purpose")])
end

# ------------------------------------------------------------------ tools

const _TOOL_KEYS = ("name", "description", "parameters")
_default_parameters() = jobj("type" => "object", "properties" => JObj())

function _tool_items(value, f)
    items = isarr(value) ? value : Any[value]
    out = JObj[]
    for (i, item) in enumerate(items)
        spec = tojsonvalue(item)
        isobj(spec) || (spec = JObj())
        (get(spec, "name", nothing) isa AbstractString && !isempty(spec["name"])) ||
            refuse("format-write-error", "field $(pyrepr(f.name)): tools[$(i-1)] needs a string 'name'")
        unknown = sort([k for k in keys(spec) if !(k in _TOOL_KEYS) && k != "type"])
        isempty(unknown) || refuse("format-write-error", "field $(pyrepr(f.name)): tools[$(i-1)] has keys $(pyrepr(Any[unknown...])); a tool is name, description, parameters (lm15 FunctionTool)")
        push!(out, spec)
    end
    out
end

const _TOOL_ACCEPTS = ["list[Tool]", "Tool", "list[*]", "object", "*"]

function _function_part(s)
    part = jobj("type" => "function", "name" => s["name"])
    pytruthy(get(s, "description", nothing)) && (part["description"] = s["description"])
    part["parameters"] = pytruthy(get(s, "parameters", nothing)) ? s["parameters"] : _default_parameters()
    part
end

function_tool_format(_) = Format(nothing, _TOOL_ACCEPTS, "in", "parts", true, ["function"],
    (v, f) -> Any[_function_part(s) for s in _tool_items(v, f)],
    (c, f) -> Any[JObj(k => x for (k, x) in p if k != "type") for p in parts_of(c, "function")],
    f -> "tools", nothing)

tool_catalog_format(_) = Format(nothing, _TOOL_ACCEPTS, "in", "text", true, ["text"],
    (v, f) -> join(["- $(s["name"])($(dumps(pytruthy(get(s, "parameters", nothing)) ? s["parameters"] : _default_parameters(), nothing)))" *
                    (pytruthy(get(s, "description", nothing)) ? ": $(s["description"])" : "") for s in _tool_items(v, f)], "\n"),
    nothing, f -> "tools", nothing)

function _calls_read(c, f)
    calls = Any[]
    n = 0
    for p in c.parts
        if get(p, "type", nothing) == "tool_call"
            push!(calls, JObj(k => x for (k, x) in p if !(k in ("type", "continuation"))))
        elseif get(p, "text", nothing) isa AbstractString
            obj = try
                loads(p["text"])
            catch err
                err isa Refusal && rethrow()
                refuse("format-read-error", "field $(pyrepr(f.name)): a fenced call is not JSON: $(_errmsg(err))")
            end
            (isobj(obj) && get(obj, "name", nothing) isa AbstractString) || refuse("format-read-error", "field $(pyrepr(f.name)): a fenced call is {name, input}")
            n += 1
            push!(calls, jobj("id" => "call_$n", "name" => obj["name"], "input" => pytruthy(get(obj, "input", nothing)) ? obj["input"] : JObj()))
        end
    end
    calls
end

_call_part(c) = jobj("type" => "tool_call", "id" => c["id"], "name" => c["name"], "input" => get(c, "input", JObj()))

tool_calls_format(_) = Format(nothing, ["list[ToolCall]", "list[*]", "*"], "both", "parts", true, ["tool_call", "text"],
    (v, f) -> Any[_call_part(tojsonvalue(x)) for x in something(v, Any[])],
    _calls_read, f -> "tool calls", nothing)

function _citations_read(c, f)
    out = Any[]
    seen = Set{String}()
    for p in c.parts
        if get(p, "type", nothing) == "citation"
            push!(out, JObj(k => x for (k, x) in p if !(k in ("type", "continuation"))))
        elseif get(p, "text", nothing) isa AbstractString
            t = wstrip(p["text"])
            if !isempty(t) && all(ch -> '0' <= ch <= '9', t) && !(t in seen)
                push!(seen, t)
                push!(out, jobj("source" => integer_value(t)))
            end
        end
    end
    out
end

citations_format(_) = Format(nothing, ["list[Citation]", "list[*]", "*"], "out", "parts", true, ["citation", "text"],
    (v, f) -> error("format citations does not write"), _citations_read, f -> nothing, nothing)

function _source_line(s, i, f)
    (isobj(s) && get(s, "text", nothing) isa AbstractString) || refuse("format-write-error", "field $(pyrepr(f.name)): sources[$(i-1)] needs 'text'")
    title = pytruthy(get(s, "title", nothing)) ? s["title"] : pytruthy(get(s, "url", nothing)) ? s["url"] : "source $i"
    "[$i] $title: $(s["text"])"
end

source_list_format(_) = Format(nothing, ["list[Source]", "list[*]", "*"], "in", "text", true, ["text"],
    (v, f) -> join([_source_line(tojsonvalue(x), i, f) for (i, x) in enumerate(something(v, Any[]))], "\n"),
    nothing, f -> "numbered sources", nothing)

native_tools(_) = Transport(requires=["native_function_calling"], in_template=false, put=jobj("@purpose" => "request.tools"),
    find=[jobj("from" => "part:tool_call", "to" => "@purpose.calls", "complete_reply" => true)])

const FENCE_OPEN, FENCE_CLOSE = "```tool\n", "\n```"

fenced_tools(_) = Transport(requires=["instruct"], in_template=false, put=jobj("@purpose" => "message:system"),
    written_as=jobj("@purpose" => "tool_catalog"),
    tell=jobj("system" => "You may call a tool by replying with exactly one fenced block:\n```tool\n{\"name\": \"<tool>\", \"input\": {...}}\n```\nand nothing else; you will be given the result and asked again."),
    find=[jobj("from" => "text", "between" => Any[FENCE_OPEN, FENCE_CLOSE], "to" => "@purpose.calls", "remove" => true, "complete_reply" => true)],
    spelling=jobj("call" => "```tool\n{\"name\": \"{name}\", \"input\": {input}}\n```", "result" => "Result of {name} ({id}):\n{output}"))

function native_citations(options)
    t = Transport(requires=["native_citations"], in_template=false, find=[jobj("from" => "part:citation", "to" => "@purpose")])
    pytruthy(get(options, "search", true)) && (t.request_settings = jobj("tools" => Any[jobj("type" => "builtin", "name" => "web_search")]))
    t
end

inline_citations(_) = Transport(requires=["instruct"], in_template=false, put=jobj("@purpose.sources" => "message:user"),
    tell=jobj("system" => "Cite the numbered sources inline as [n] after each claim they support."),
    find=[jobj("from" => "text", "between" => Any["[", "]"], "to" => "@purpose", "remove" => false)])

# ------------------------------------------------------------------ code

const _IDENT_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"
function _code_options(opts; calls=false)
    allowed = calls ? ("marker", "tool") : ("marker",)
    unknown = sort([String(k) for k in keys(opts) if !(k in allowed)])
    isempty(unknown) || error("unknown options: $(pyrepr(Any[unknown...]))")
    marker, tool = get(opts, "marker", "PY_END"), get(opts, "tool", "run_python")
    for (k, v) in (("marker", marker), ("tool", tool))
        (v isa AbstractString && occursin(_IDENT_RE, v)) || error("$k must be a nonempty ASCII identifier")
    end
    (marker, tool)
end

function _code_of(v)
    (isobj(v) && length(v) == 1 && haskey(v, "code") && v["code"] isa AbstractString) || error("code arguments must be exactly {code: string}")
    v["code"]
end

function _code_write(marker, v)
    code = _code_of(v)
    occursin(marker, code) && refuse("value-collides", "code contains heredoc marker $(pyrepr(marker)); choose another marker")
    code
end

function _code_read(marker, c::Capture)
    any(p -> get(p, "type", nothing) != "text" || !(get(p, "text", nothing) isa AbstractString), c.parts) && error("code arguments need text parts")
    code = join(p["text"] for p in c.parts)          # not text(c): code whitespace is data
    occursin(marker, code) && error("code contains heredoc marker $(pyrepr(marker))")
    jobj("code" => code)
end

function code_arguments_format(opts)
    marker, _ = _code_options(opts)
    Format(nothing, ["object"], "both", "text", true, ["text"], (v, f) -> _code_write(marker, v), (c, f) -> _code_read(marker, c), f -> "raw code", nothing)
end

function code_calls_format(opts)
    marker, tool = _code_options(opts; calls=true)
    function native(call, writing)
        c = tojsonvalue(call)
        (isobj(c) && get(c, "name", nothing) == tool && get(c, "id", nothing) isa AbstractString && !isempty(c["id"])) ||
            error("expected a $(pyrepr(tool)) call with a nonempty id")
        body = if writing
            _code_write(marker, get(c, "input", nothing))
        else
            b = _code_of(get(c, "input", nothing))
            _code_read(marker, LMCC.capture_of_text(b))
            b
        end
        jobj("id" => c["id"], "name" => tool, "input" => jobj("code" => body))
    end
    Format(nothing, ["list[*]", "*"], "both", "parts", true, ["text", "tool_call"],
        (v, f) -> (isarr(v) || error("calls must be a list"); Any[merge(jobj("type" => "tool_call"), native(c, true)) for c in v]),
        (cap, f) -> begin
            calls = Any[]
            for p in cap.parts
                if get(p, "type", nothing) == "tool_call"
                    push!(calls, native(p, false))
                else
                    push!(calls, jobj("id" => "call_$(length(calls) + 1)", "name" => tool, "input" => _code_read(marker, Capture(Any[p]))))
                end
            end
            calls
        end,
        f -> "heredoc tool calls", nothing)
end

function heredoc_tools(opts)
    marker, tool = _code_options(opts; calls=true)
    opening, closing = "$tool <<'$marker'\n", "\n$marker"
    Transport(requires=["instruct"], in_template=false, put=jobj("@purpose" => "message:system"), written_as=jobj("@purpose" => "tool_catalog"),
        tell=jobj("system" => "To request $tool, emit this heredoc and wait for its result:\n$(opening)<code>$(closing)\nDo not put $marker anywhere in the code. Otherwise reply normally."),
        find=[jobj("from" => "text", "between" => Any[opening, closing], "to" => "@purpose.calls", "remove" => true, "complete_reply" => true)],
        spelling=jobj("call" => "{name} <<'" * marker * "'\n{input}" * closing, "result" => "Result of {name} ({id}):\n{output}",
            "input_format" => jobj("use" => "code_arguments", "options" => jobj("marker" => marker)),
            "probe" => jobj("name" => tool, "input" => jobj("code" => "print(6 * 7)\n"))))
end

# ------------------------------------------------------------------ install

"Register the standard vocabulary in `registry`, at the versions the corpus pins."
function install!(reg::Registry=LMCC.default_registry(); exist_ok=true)
    register_format!(reg, "json", json_format; version=VERSION, exist_ok=exist_ok)
    register_format!(reg, "table", table_format; version="0.2.0", exist_ok=exist_ok)
    register_format!(reg, "scaled_number", scaled_number_format; version="0.2.0", exist_ok=exist_ok)
    register_transport!(reg, "prefix_cot", prefix_cot; version=VERSION, exist_ok=exist_ok)
    register_transport!(reg, "reasoning_tags", reasoning_tags; version="0.3.0", exist_ok=exist_ok)
    register_transport!(reg, "native_reasoning", native_reasoning; version=VERSION, exist_ok=exist_ok)
    register_reader!(reg, "json_object", json_object_reader; version="0.2.0", exist_ok=exist_ok)
    for (n, fmt) in (("function_tool", function_tool_format), ("tool_catalog", tool_catalog_format), ("tool_calls", tool_calls_format),
                     ("citations", citations_format), ("source_list", source_list_format))
        register_format!(reg, n, fmt; version=VERSION, exist_ok=exist_ok)
    end
    for (n, t) in (("native_tools", native_tools), ("fenced_tools", fenced_tools), ("native_citations", native_citations),
                   ("inline_citations", inline_citations))
        register_transport!(reg, n, t; version=VERSION, exist_ok=exist_ok)
    end
    register_format!(reg, "code_arguments", code_arguments_format; version=VERSION, exist_ok=exist_ok)
    register_format!(reg, "code_calls", code_calls_format; version=VERSION, exist_ok=exist_ok)
    register_transport!(reg, "heredoc_tools", heredoc_tools; version=VERSION, exist_ok=exist_ok)
    reg
end

end

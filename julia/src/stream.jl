# Incremental, sans-I/O parsing (kernel §8): a reducer over response deltas,
# never a second parser. Every feed does work proportional to its delta;
# `finish!` hands the final checks and typed reads to the batch parser and
# proves the incremental projection agrees with it.
#
# Offsets are bytes. A hold is measured in whole characters and returned in
# bytes, so every cut lands on a character boundary.

"The events caused by EOF, and the same values, repairs and measurements as batch `read`."
struct StreamResult
    events::Vector{JObj}
    values::JObj
    repairs::Vector{JObj}
    probabilities::JObj
    measured_by::JObj
end

struct StreamBug <: Exception
    msg::String
end

"Every proper prefix of a marker set: can this suffix still grow into one?"
struct Prefixes
    table::Set{String}
    longest::Int                  # in characters
end
function Prefixes(markers)
    table = Set{String}()
    longest = 0
    for m in markers
        n = length(m)
        for k in 1:n-1
            push!(table, first(m, k))
        end
        longest = max(longest, n - 1)
    end
    Prefixes(table, longest)
end

"Bytes of the longest suffix of `text` that is a proper prefix of a marker."
function hold(p::Prefixes, text::AbstractString)
    p.longest == 0 && return 0
    best = 0
    i = ncodeunits(text)
    k = 0
    while k < p.longest && i > 0
        i = boundary(text, i - 1)
        k += 1
        bsl(text, i) in p.table && (best = ncodeunits(text) - i)
    end
    best
end

"Does a suffix of the text (whose tail is `window`, ending at `stop`) that can still grow start strictly between `lo` and `hi`?"
function grows_between(p::Prefixes, window::AbstractString, stop::Int, lo::Int, hi::Int)
    i = ncodeunits(window)
    k = 0
    while k < p.longest && i > 0
        i = boundary(window, i - 1)
        k += 1
        start = stop - (ncodeunits(window) - i)
        lo < start < hi && bsl(window, i) in p.table && return true
    end
    false
end

"Non-overlapping occurrences of one marker, by absolute start, as each completes."
mutable struct Scanner
    marker::String
    stop::Int
    pending::String
end
function scan!(s::Scanner, text::AbstractString)
    if isempty(text) || isempty(s.marker)
        s.stop += blen(text)
        return Int[]
    end
    buf = s.pending * text
    base = s.stop - blen(s.pending)
    found = Int[]
    i = 0
    while true
        j = bfind(buf, s.marker, i)
        j < 0 && break
        push!(found, base + j)
        i = j + blen(s.marker)
    end
    s.stop += blen(text)
    keep = boundary(buf, max(i, blen(buf) - (blen(s.marker) - 1)))
    keep = max(keep, i)
    s.pending = bsl(buf, keep)
    found
end

mutable struct FieldState
    name::String
    present::Bool
    started::Bool
    emitted::IOBuffer
    has_emitted::Bool
    pending::Vector{String}
end
FieldState(name) = FieldState(name, false, false, IOBuffer(), false, String[])
function emit!(f::FieldState, t::AbstractString)
    isempty(t) && return
    write(f.emitted, t)
    f.has_emitted = true
    push!(f.pending, String(t))
end
emitted_text(f::FieldState) = String(copy(f.emitted.data[1:f.emitted.size]))

# -------------------------------------------------------------- find rules

abstract type TextStage end

mutable struct BetweenStage <: TextStage
    open::String
    close::String
    remove::Bool
    holdt::Prefixes
    buf::String
    inside::Bool
    captures::Vector{String}
end
BetweenStage(r) = BetweenStage(r["between"][1], r["between"][2], pytruthy(get(r, "remove", false)), Prefixes([r["between"][1]]), "", false, String[])

function stage_feed!(s::BetweenStage, delta::String, final::Bool)
    out = IOBuffer()
    s.remove || write(out, delta)
    buf = s.buf * delta
    while true
        if !s.inside
            i = bfind(buf, s.open)
            if i < 0
                if s.remove
                    keep = final ? 0 : hold(s.holdt, buf)
                    write(out, bsl(buf, 0, blen(buf) - keep))
                    buf = bsl(buf, blen(buf) - keep)
                else
                    keep = min(blen(buf), max(blen(s.open) - 1, 0))
                    buf = bsl(buf, boundary(buf, blen(buf) - keep))
                end
                break
            end
            s.remove && write(out, bsl(buf, 0, i))
            buf = bsl(buf, i)
            s.inside = true
        end
        j = bfind(buf, s.close, blen(s.open))
        if j < 0
            if final && s.remove
                write(out, buf)
                buf = ""
            end
            break
        end
        push!(s.captures, wstrip(bsl(buf, blen(s.open), j)))
        buf = bsl(buf, j + blen(s.close))
        s.inside = false
    end
    s.buf = buf
    String(take!(out))
end

mutable struct LinePrefixedStage <: TextStage
    prefix::String
    remove::Bool
    line::String
    captures::Vector{String}
end
LinePrefixedStage(r) = LinePrefixedStage(r["line_prefixed"], pytruthy(get(r, "remove", false)), "", String[])

function stage_feed!(s::LinePrefixedStage, delta::String, final::Bool)
    out = IOBuffer()
    s.remove || write(out, delta)
    lines = split(s.line * delta, '\n')
    last = String(pop!(lines))
    for line in lines
        if startswith(line, s.prefix)
            push!(s.captures, wstrip(bsl(line, blen(s.prefix))))
            s.remove && write(out, "\n")
        elseif s.remove
            write(out, line, "\n")
        end
    end
    if final
        if startswith(last, s.prefix)
            push!(s.captures, wstrip(bsl(last, blen(s.prefix))))
        elseif s.remove
            write(out, last)
        end
        last = ""
    end
    s.line = last
    String(take!(out))
end

"A regex needs the whole text: later bytes can change any match."
mutable struct PatternStage <: TextStage
    rule::JObj
    pattern::Any
    remove::Bool
    pieces::IOBuffer
    captures::Vector{String}
end
PatternStage(r, pattern) = PatternStage(r, pattern, pytruthy(get(r, "remove", false)), IOBuffer(), String[])

function stage_feed!(s::PatternStage, delta::String, final::Bool)
    write(s.pieces, delta)
    final || return s.remove ? "" : delta
    t = String(take!(s.pieces))
    caps = text_captures(t, s.rule, s.pattern)
    s.captures = [wstrip(c) for (_, _, c) in caps]
    s.remove || return ""
    isempty(caps) && return t
    out = IOBuffer()
    pos = 0
    for (a, b, _) in caps
        write(out, bsl(t, pos, a))
        pos = b
    end
    write(out, bsl(t, pos))
    String(take!(out))
end

"Text of every part of one kind, each stripped, joined by newlines."
mutable struct PartSource
    kind::String
    texts::Vector{Vector{String}}
    any_part::Bool
    held::String
    has_emitted::Bool
end
PartSource(kind) = PartSource(kind, Vector{String}[], false, "", false)
stage_captures(s::PartSource) = [wstrip(join(p)) for p in s.texts]
stage_captures(s::TextStage) = s.captures

function part_delta!(s::PartSource, kind, t, new_part)
    kind == s.kind || return ""
    s.any_part = true
    t === nothing && return ""
    out = ""
    if new_part
        push!(s.texts, String[])
        s.held = ""
        s.has_emitted = false
        length(s.texts) > 1 && (out = "\n")
    end
    push!(s.texts[end], t)
    candidate = s.held * t
    s.has_emitted || (candidate = wlstrip(candidate))
    stable = wrstrip(candidate)
    s.held = bsl(candidate, blen(stable))
    isempty(stable) || (s.has_emitted = true)
    out * stable
end

# ---------------------------------------------------------- derived reader

mutable struct Section
    field::FieldState
    start::Int
    after::Int
    close::String
    scanner::Union{Nothing,Scanner}
    close_starts::Vector{Int}
    stop::Union{Nothing,Int}
    received::Int
    held::String
    fixed::Union{Nothing,String}
    holdt::Prefixes
end
Section(field, start, after, close, holdt) = Section(field, start, after, close, isempty(close) ? nothing : Scanner(close, after, ""),
    Int[], nothing, after, "", nothing, holdt)

function cut(s::Section, limit::Int)
    limit >= s.received && return s.held
    drop = s.received - limit
    if drop > blen(s.held)
        s.field.has_emitted && throw(StreamBug("stream projection for '$(s.field.name)' revised emitted text"))
        return ""
    end
    bsl(s.held, 0, blen(s.held) - drop)
end

function advance!(s::Section, limit)
    candidate = limit === nothing ? s.held : cut(s, limit)
    rest = limit === nothing ? "" : bsl(s.held, blen(candidate))
    s.field.has_emitted || (candidate = wlstrip(candidate))
    n = hold(s.holdt, candidate)
    stable = wrstrip(bsl(candidate, 0, blen(candidate) - n))
    emit!(s.field, stable)
    s.held = bsl(candidate, blen(stable)) * rest
end

function fix!(s::Section, limit::Int)
    candidate = cut(s, limit)
    s.field.has_emitted || (candidate = wlstrip(candidate))
    emit!(s.field, wrstrip(candidate))
    s.fixed = emitted_text(s.field)
    s.held = ""
end

mutable struct DerivedReducer
    fields::OrderedDict{String,FieldState}
    wanted::Vector{Tuple{String,String,String}}
    tail::String
    bounds::Prefixes
    holds::OrderedDict{String,Prefixes}
    scanners::OrderedDict{String,Scanner}
    first::OrderedDict{String,Int}
    duplicated::Set{String}
    sections::OrderedDict{String,Section}
    length::Int
    window::String
    poisoned::Bool
end

function DerivedReducer(r::DerivedReader, fields, names)
    wanted = [(n, wrstrip(p), wstrip(s)) for (n, p, s) in r.anchors if n in names]
    tail = wstrip(r.tail)
    markers = vcat([m for (_, m, _) in wanted], isempty(tail) ? String[] : [tail])
    holds = OrderedDict{String,Prefixes}()
    for (_, _, c) in wanted
        haskey(holds, c) || (holds[c] = Prefixes(vcat(markers, isempty(c) ? String[] : [c])))
    end
    scanners = OrderedDict{String,Scanner}()
    for m in markers
        haskey(scanners, m) || (scanners[m] = Scanner(m, 0, ""))
    end
    DerivedReducer(fields, wanted, tail, Prefixes(markers), holds, scanners, OrderedDict{String,Int}(), Set{String}(),
        OrderedDict{String,Section}(), 0, "", false)
end

function reducer_feed!(d::DerivedReducer, delta::String, final::Bool)
    a = d.length
    b = a + blen(delta)
    d.length = b
    if d.bounds.longest > 0
        w = d.window * delta
        d.window = bsl(w, blen(w) - lastchars_bytes(w, d.bounds.longest))
    end
    # 1. boundary occurrences (first position, duplicates)
    for (m, sc) in d.scanners
        for q in scan!(sc, delta)
            haskey(d.first, m) ? push!(d.duplicated, m) : (d.first[m] = q)
        end
    end
    # 2. sections in batch order: sorted first occurrences, tail last on ties
    bounds = Tuple{Int,Int,Union{Nothing,String},String}[]
    for (name, m, close) in d.wanted
        haskey(d.first, m) && push!(bounds, (d.first[m], d.first[m] + blen(m), name, close))
    end
    !isempty(d.tail) && haskey(d.first, d.tail) && push!(bounds, (d.first[d.tail], d.first[d.tail], nothing, ""))
    sort!(bounds; by=x -> (x[1], x[2]))
    for (i, (start, after, name, close)) in enumerate(bounds)
        name === nothing && continue
        sec = get(d.sections, name, nothing)
        if sec === nothing
            f = d.fields[name]
            f.present = true
            sec = Section(f, start, after, close, d.holds[close])
            d.sections[name] = sec
        end
        stop = i < length(bounds) ? bounds[i+1][1] : nothing
        sec.stop !== nothing && stop !== nothing && stop < sec.stop && sec.fixed !== nothing &&
            throw(StreamBug("stream projection for '$name' revised emitted text"))
        sec.stop = stop
    end
    # 3. route the delta into sections; feed close scanners
    for sec in values(d.sections)
        limit = sec.stop === nothing ? b : min(b, sec.stop)
        if sec.fixed !== nothing
        elseif sec.received < limit
            sec.held *= bsl(delta, max(0, sec.received - a), limit - a)
            sec.received = limit
        elseif sec.received > limit
            sec.held = cut(sec, limit)
            sec.received = limit
        end
        sc = sec.scanner
        if sc !== nothing && sc.stop < b && (sec.stop === nothing || sc.stop < sec.stop)
            append!(sec.close_starts, scan!(sc, bsl(delta, max(0, sc.stop - a))))
        end
    end
    # 4. the longest boundary prefix still growing at the end of the text
    grow_start = b - hold(d.bounds, d.window)
    # 5. resolve: duplicates, fixes, and stable emission
    poisoned = !isempty(d.duplicated)
    for sec in values(d.sections)
        stop = sec.stop
        closes = [q for q in sec.close_starts if stop === nothing || q + blen(sec.close) <= stop]
        length(closes) >= 2 && (poisoned = true)
        sec.fixed === nothing || continue
        s2 = stop === nothing ? b : stop
        if stop !== nothing && stop <= sec.after
            fix!(sec, sec.after)
        elseif final
            fix!(sec, isempty(closes) ? s2 : closes[1])
        elseif stop !== nothing && grow_start >= stop
            fix!(sec, isempty(closes) ? stop : closes[1])
        elseif !isempty(closes) && stop === nothing && grow_start >= closes[1] + blen(sec.close)
            fix!(sec, closes[1])
        elseif !grows_between(d.bounds, d.window, b, sec.start - 1, sec.after)
            advance!(sec, isempty(closes) ? nothing : closes[1])
        end
    end
    d.poisoned = poisoned
end

final_raw(d::DerivedReducer) = OrderedDict(n => s.fixed for (n, s) in d.sections if s.fixed !== nothing)

# ---------------------------------------------------------- marker repair

"§4a/§8: passes text on while nothing can need a repair; from the first misspelled span it holds everything until EOF."
mutable struct MarkerRepair
    markers::Vector{String}
    keys::Vector{Tuple{Vector{Char},String,Int}}
    lead::Int
    longest::Int
    prefixes::Prefixes
    pieces::IOBuffer
    buf::String
    before::Char
    released::Int
    length::Int
    run_start::Int
    window::Vector{Tuple{Char,Int,Int}}
    pending::Vector{Tuple{String,Int,Int,Int,Int}}
    held_from::Union{Nothing,Int}
end

function MarkerRepair(markers)
    keys = Tuple{Vector{Char},String,Int}[]
    for m in markers
        full = marker_key(m)
        k = _lead_strip(full)
        push!(keys, (collect(k), m, length(full) - length(k)))
    end
    MarkerRepair(collect(markers), keys, maximum(k[3] for k in keys), maximum(length(k[1]) for k in keys),
        Prefixes([String(k[1]) for k in keys]), IOBuffer(), "", '\0', 0, 0, 0, Tuple{Char,Int,Int}[], Tuple{String,Int,Int,Int,Int}[], nothing)
end

_mr_at(m::MarkerRepair, j) = j >= m.released ? bchar(m.buf, j - m.released) : m.before
_mr_text(m::MarkerRepair, a, b) = bsl(m.buf, a - m.released, b - m.released)

function repair_feed!(m::MarkerRepair, delta::String, final::Bool)
    a = m.length
    write(m.pieces, delta)
    m.buf *= delta
    m.length += blen(delta)
    if final
        t = String(take!(m.pieces))
        rewritten, _ = repair_markers(t, m.markers)
        bsl(rewritten, 0, m.released) == bsl(t, 0, m.released) || throw(StreamBug("marker repair revised text it had already passed on"))
        out = bsl(rewritten, m.released)
        m.released = blen(t)
        m.buf = ""
        return out
    end
    m.held_from === nothing || return ""
    for (off, c) in pairs(delta)
        i = a + off - 1
        c in IGNORABLE && continue
        push!(m.window, (fold(c), i, m.run_start))
        m.run_start = i + ncodeunits(c)
        length(m.window) > m.longest && popfirst!(m.window)
        for (key, marker, lead) in m.keys
            n = length(key)
            if n <= length(m.window) && key[end] == m.window[end][1] && all(key[j] == m.window[end-n+j][1] for j in 1:n)
                _, core_start, run = m.window[end-n+1]
                push!(m.pending, (marker, run, core_start, lead, i + ncodeunits(c)))
            end
        end
    end
    waiting = Tuple{String,Int,Int,Int,Int}[]
    for item in m.pending
        marker, run, core_start, lead, core_end = item
        left = nothing
        for j in run:core_start-1
            if _mr_at(m, j) in DECORATION && (j == 0 || isws(_mr_at(m, j - 1)))
                left = j
                break
            end
        end
        stop = core_end
        if left !== nothing && any(_mr_at(m, j) in EMPHASIS for j in left:core_start-1)
            while stop < m.length && _mr_at(m, stop) in EMPHASIS
                stop += 1
            end
            if stop == m.length
                push!(waiting, item)
                continue
            end
        end
        start = left === nothing ? core_start : left
        if lead > 0
            q = start
            while q > m.released && _mr_at(m, q - 1) in HORIZONTAL
                q -= 1
            end
            taken = 0
            while taken < lead && q > m.released && _mr_at(m, q - 1) == '\n'
                q -= 1
                taken += 1
            end
            taken > 0 && (start = q)
        end
        if _mr_text(m, start, stop) != marker
            m.held_from = start
            break
        end
    end
    m.pending = m.held_from === nothing ? waiting : Tuple{String,Int,Int,Int,Int}[]
    limit = m.held_from === nothing ? m.length : m.held_from
    m.run_start < m.length && (limit = min(limit, m.run_start))
    wtext = String([c for (c, _, _) in m.window])
    n = _hold_chars(m.prefixes, wtext)
    n > 0 && (limit = min(limit, m.window[end-n+1][3]))
    for (_, run, _, _, _) in m.pending
        limit = min(limit, run)
    end
    for _ in 1:m.lead
        while limit > m.released && _mr_at(m, limit - 1) in HORIZONTAL
            limit -= 1
        end
        limit > m.released && _mr_at(m, limit - 1) == '\n' && (limit -= 1)
    end
    limit = max(limit, m.released)
    out = bsl(m.buf, 0, limit - m.released)
    if !isempty(out)
        m.before = bchar(out, blen(out) - 1)
        m.buf = bsl(m.buf, blen(out))
        m.released = limit
    end
    out
end

"The hold in characters (the repair window counts characters)."
function _hold_chars(p::Prefixes, text)
    for n in min(length(text), p.longest):-1:1
        last(text, n) in p.table && return n
    end
    0
end

# -------------------------------------------------------------- describe

has_stream_face(r) = r isa DerivedReader || which(reader_stream, Tuple{typeof(r),Any}) !== which(reader_stream, Tuple{Reader,Any})

"The buffering choices, visible through `describe(plan)`."
function describe_streaming(p::Plan)
    counts = OrderedDict{String,Int}()
    for (f, _) in p.find_rules
        counts[f] = get(counts, f, 0) + 1
    end
    routes = Any[]
    modes = String[]
    removing_pattern = false
    for (f, r) in p.find_rules
        reason = nothing
        if haskey(r, "pattern")
            mode, reason = "buffered", "a pattern find rule waits for EOF"
            removing_pattern |= pytruthy(get(r, "remove", false))
        elseif counts[f] > 1
            mode, reason = "buffered", "multiple find rules concatenate by declaration order"
        else
            mode = "incremental"
        end
        item = jobj("field" => f, "from" => r["from"], "mode" => mode)
        reason === nothing || (item["reason"] = reason)
        push!(routes, item)
        push!(modes, mode)
    end
    face = has_stream_face(p.reader)
    rmode, rreason = face && !removing_pattern ? ("incremental", nothing) :
                     face ? ("buffered", "a removing pattern find rule can revise the reader's text") : ("buffered", "reader provides no streaming face")
    reader = jobj("mode" => rmode)
    rreason === nothing || (reader["reason"] = rreason)
    push!(modes, rmode)
    u = Set(modes)
    mode = u == Set(["incremental"]) ? "incremental" : u == Set(["buffered"]) ? "buffered" : "hybrid"
    jobj("mode" => mode, "reader" => reader, "find" => routes, "field_done" => "finish",
        "repairs" => p.adapter.strict ? jobj("mode" => "strict") :
                     jobj("mode" => "forgiving", "reason" => "from the first misspelled marker the rest of the reply waits for finish"))
end

# ----------------------------------------------------------------- stream

"""
    Stream

A plan-bound, sans-I/O streaming parser: `feed!(stream, delta)` (text, or one
lm15 part delta Dict) returns events; `finish!(stream, finish_reason)` returns
a `StreamResult`. Create with `stream(plan)`.
"""
mutable struct Stream
    plan::Plan
    pieces::IOBuffer
    parts::Vector{JObj}
    part_texts::Vector{Union{Nothing,Vector{String}}}
    part_mode::Bool
    finished::Bool
    fields::OrderedDict{String,FieldState}
    stages::Vector{Tuple{String,Any}}
    by_field::OrderedDict{String,Vector{Any}}
    counted::OrderedDict{String,Int}
    derived::Union{Nothing,DerivedReducer}
    repair::Union{Nothing,MarkerRepair}
    repair_find::Union{Nothing,MarkerRepair}
    reader_stream::Any
    reader_prefixes::OrderedDict{String,String}
    reader_final_names::Union{Nothing,Set{String}}
    opening::Vector{JObj}
end

"A pure, sans-I/O streaming parser for this plan (§8)."
function stream(p::Plan)
    fields = OrderedDict(f.name => FieldState(f.name) for f in p.signature.fields)
    names = [f.name for f in p.visible_outputs]
    stages = Tuple{String,Any}[]
    by_field = OrderedDict{String,Vector{Any}}()
    for (f, r) in p.find_rules
        src = r["from"]
        st = startswith(src, "part:") ? PartSource(src[6:end]) : haskey(r, "between") ? BetweenStage(r) :
             haskey(r, "line_prefixed") ? LinePrefixedStage(r) : PatternStage(r, pattern_binding(p))
        push!(stages, (f, st))
        push!(get!(by_field, f, Any[]), st)
    end
    derived = p.reader isa DerivedReader ? DerivedReducer(p.reader, fields, names) : nothing
    repair = derived !== nothing && !isempty(p.reader.repairable) ? MarkerRepair(p.reader.repairable) : nothing
    repair_find = isempty(p.find_repairable) ? nothing : MarkerRepair(p.find_repairable)
    rs = derived === nothing ? reader_stream(p.reader, names) : nothing
    s = Stream(p, IOBuffer(), JObj[], Union{Nothing,Vector{String}}[], false, false, fields, stages, by_field, OrderedDict{String,Int}(),
        derived, repair, repair_find, rs, OrderedDict{String,String}(), nothing, JObj[])
    if !isempty(p.prefill)
        _run!(s, p.prefill, nothing, false)
        s.opening = _events!(s, false)
    end
    s
end

"Feed one text delta or one lm15 part delta; the events it caused."
function feed!(s::Stream, delta)
    s.finished && error("stream is already finished")
    t, part = _append!(s, delta)
    _run!(s, t, part, false)
    opening = s.opening
    s.opening = JObj[]
    vcat(opening, _events!(s, false))
end

"End of stream. With `\"length\"` a cut output refuses `parse-truncated`, with `\"error\"` `parse-interrupted`; with `\"content_filter\"` the reply refuses `parse-filtered` (§4a)."
function finish!(s::Stream, finish_reason=nothing)
    s.finished && error("stream is already finished")
    s.finished = true
    response = s.part_mode ? jobj("role" => "assistant", "parts" => _materialized(s)) : String(take!(copy(s.pieces)))
    if finish_reason !== nothing
        message = response isa AbstractString ? jobj("role" => "assistant", "parts" => Any[textpart(response)]) : response
        response = jobj("message" => message, "finish_reason" => finish_reason)
    end
    probs, measured = reply_probabilities(response)
    values, captures, repairs = parse_with_captures(s.plan, response)
    _run!(s, "", nothing, true)
    events = _events!(s, true, captures, values)
    StreamResult(events, values, repairs, probs, measured)
end

function _append!(s::Stream, delta)
    if delta isa AbstractString
        write(s.pieces, delta)
        s.part_mode && return (String(delta), _append_part!(s, textpart(delta)))
        return (String(delta), nothing)
    end
    validate_response_part(delta)
    if !s.part_mode
        s.part_mode = true
        s.pieces.size > 0 && _append_part!(s, textpart(String(copy(s.pieces.data[1:s.pieces.size]))))
    end
    part = _append_part!(s, JObj(String(k) => v for (k, v) in delta))
    t = delta["type"] in ("text", "data") ? part_text(delta) : ""
    isempty(t) || write(s.pieces, t)
    (t, part)
end

function _append_part!(s::Stream, part::JObj)
    kind = part["type"]
    t = get(part, "text", nothing)
    has_text = t isa AbstractString
    if has_text && !isempty(s.parts) && s.parts[end]["type"] == kind && s.part_texts[end] !== nothing
        push!(s.part_texts[end], t)
        for (k, v) in part
            k in ("type", "text") || (s.parts[end][k] = v)
        end
        return (kind, String(t), false)
    end
    push!(s.parts, part)
    push!(s.part_texts, has_text ? String[t] : nothing)
    (kind, has_text ? String(t) : nothing, true)
end

_materialized(s::Stream) = Any[s.part_texts[i] === nothing ? p : merge(p, jobj("text" => join(s.part_texts[i]))) for (i, p) in enumerate(s.parts)]

function _run!(s::Stream, t::String, part, final::Bool)
    st = t
    s.repair_find === nothing || (st = repair_feed!(s.repair_find, st, final))
    for (field, stage) in s.stages
        f = s.fields[field]
        if stage isa PartSource
            if part !== nothing
                kind, ptext, new_part = part
                d = part_delta!(stage, kind, ptext, new_part)
                stage.any_part && (f.present = true)
                length(s.by_field[field]) == 1 && emit!(f, d)
            end
            continue
        end
        st = stage_feed!(stage, st, final)
        isempty(stage.captures) || (f.present = true)
        if length(s.by_field[field]) == 1
            done = get(s.counted, field, 0)
            for c in stage.captures[done+1:end]
                emit!(f, (done > 0 ? "\n" : "") * c)
                done += 1
            end
            s.counted[field] = done
        end
    end
    if s.derived !== nothing
        s.repair === nothing || (st = repair_feed!(s.repair, st, final))
        reducer_feed!(s.derived, st, final)
    elseif s.reader_stream !== nothing
        prefixes = (!isempty(st) || !final) ? s.reader_stream.feed(st) : OrderedDict{String,String}()
        if final
            prefixes = s.reader_stream.finish()
            s.reader_final_names = Set(keys(prefixes))
        end
        for (name, raw) in prefixes
            f = get(s.fields, name, nothing)
            f === nothing && continue
            f.present = true
            before = get(s.reader_prefixes, name, "")
            startswith(raw, before) || throw(StreamBug("reader stream prefix for '$name' revised emitted text"))
            s.reader_prefixes[name] = raw
            emit!(f, bsl(raw, blen(before)))
        end
    end
end

function _final_projection(s::Stream)
    out = OrderedDict{String,String}()
    if s.derived !== nothing
        merge!(out, final_raw(s.derived))
    elseif s.reader_stream !== nothing
        merge!(out, s.reader_prefixes)
    end
    for (field, stages) in s.by_field
        f = s.fields[field]
        f.present || continue
        out[field] = length(stages) > 1 ? join([c for st in stages for c in stage_captures(st)], "\n") : emitted_text(f)
    end
    out
end

function _events!(s::Stream, final::Bool, captures=nothing, values=nothing)
    s.derived !== nothing && s.derived.poisoned && !final && return JObj[]
    events = JObj[]
    if final
        projected = _final_projection(s)
        if s.reader_stream !== nothing
            Set(f.name for f in s.plan.visible_outputs) == something(s.reader_final_names, Set{String}()) ||
                throw(StreamBug("reader stream fields disagree with batch fields"))
        end
        for (name, raw) in projected
            haskey(captures, name) && raw != text(captures[name]) && throw(StreamBug("stream projection for '$name' disagrees with batch parse"))
        end
        for field in s.plan.signature.fields
            haskey(captures, field.name) || continue
            f = s.fields[field.name]
            if !f.started
                f.started = true
                push!(events, jobj("kind" => "field_started", "field" => field.name))
            end
            raw = text(captures[field.name])
            before = emitted_text(f)
            held_back = join(f.pending)
            already = bsl(before, 0, blen(before) - blen(held_back))
            startswith(raw, already) || throw(StreamBug("stream projection for '$(field.name)' revised emitted text"))
            d = bsl(raw, blen(already))
            isempty(d) || push!(events, jobj("kind" => "field_delta", "field" => field.name, "text" => d))
            push!(events, jobj("kind" => "field_done", "field" => field.name, "value" => values[field.name]))
        end
        return events
    end
    for field in s.plan.signature.fields
        f = s.fields[field.name]
        f.present || continue
        if !f.started
            f.started = true
            push!(events, jobj("kind" => "field_started", "field" => field.name))
        end
        if !isempty(f.pending)
            push!(events, jobj("kind" => "field_delta", "field" => field.name, "text" => join(f.pending)))
            empty!(f.pending)
        end
    end
    events
end

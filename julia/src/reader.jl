# Reading the reply (kernel §4, §4a, §6): find rules, the derived reader,
# marker repair. Offsets are 0-based bytes; `Edit` is `(start, end, new_len)`.

const Edit = Tuple{Int,Int,Int}

"The `pattern/*` binding interface a plan uses (kernel §10)."
abstract type PatternMatcher end

"`(start, end, capture)` for one text rule: the §6 plain scans, or the bound pattern."
function text_captures(text::AbstractString, rule, pattern)
    caps = Tuple{Int,Int,String}[]
    if haskey(rule, "between")
        open_, close = rule["between"]
        pos = 0
        while true
            i = bfind(text, open_, pos)
            i < 0 && break
            j = bfind(text, close, i + blen(open_))
            j < 0 && break
            push!(caps, (i, j + blen(close), bsl(text, i + blen(open_), j)))
            pos = j + blen(close)
        end
    elseif haskey(rule, "line_prefixed")
        prefix = rule["line_prefixed"]
        pos = 0
        for line in split(text, '\n')
            startswith(line, prefix) && push!(caps, (pos, pos + ncodeunits(line), bsl(line, blen(prefix))))
            pos += ncodeunits(line) + 1
        end
    else
        return pattern_captures(pattern, rule["pattern"], text)
    end
    caps
end

"Run all find rules: `(remaining text, Dict field => Capture)` (§6)."
function apply_find_rules(text::AbstractString, parts, find_rules, pattern; edits=nothing)
    found = OrderedDict{String,Capture}()
    for (name, r) in find_rules
        if startswith(r["from"], "part:")
            kind = r["from"][6:end]
            cap = Capture(Any[p for p in parts if get(p, "type", nothing) == kind])
        else
            caps = text_captures(text, r, pattern)
            cap = Capture(Any[textpart(c) for (_, _, c) in caps])
            if pytruthy(get(r, "remove", false)) && !isempty(caps)
                edits === nothing || push!(edits, Edit[(a, b, 0) for (a, b, _) in caps])
                io = IOBuffer()
                pos = 0
                for (a, b, _) in caps
                    write(io, bsl(text, pos, a))
                    pos = b
                end
                write(io, bsl(text, pos))
                text = String(take!(io))
            end
        end
        found[name] = haskey(found, name) ? Capture(vcat(found[name].parts, cap.parts)) : cap
    end
    (String(text), found)
end

# ------------------------------------------------------------------ readers

"""
One reply document form (§4) with three faces: `reader_split` reads,
`reader_join` writes turns, `reader_format` writes the `{format}` skeleton.
Vocabulary readers subtype it and may define `reader_requires`,
`reader_request_settings`, `reader_skeleton`, `reader_stream` and `reader_spec`.
"""
abstract type Reader end
reader_format(r::Reader, placeholders) = reader_join(r, placeholders)
reader_requires(::Reader) = String[]
reader_request_settings(::Reader, fields) = JObj()
reader_skeleton(::Reader) = JObj()
"Optional §8 face: an object with `feed(delta) → Dict` and `finish() → Dict`, or `nothing`."
reader_stream(::Reader, names) = nothing
reader_spec(::Reader) = nothing

function _cut_at_close(chunk, close, name)
    isempty(close) && return chunk
    n = bcount(chunk, close)
    n > 1 && refuse("parse-ambiguous", "close marker $(pyrepr(close)) for field $(pyrepr(name)) appears $n times in its section — refusing to guess where it ends")
    i = bfind(chunk, close)
    i < 0 ? chunk : bsl(chunk, 0, i)
end

function check_collisions(spelled, markers)
    for (name, value) in spelled, m in markers
        !isempty(m) && occursin(m, value) &&
            refuse("value-collides", "field $(pyrepr(name)): its spelled value contains the reader marker $(pyrepr(m)); the turn could not be read back as written")
    end
end

# ---------------------------------------------------------- marker repair

const IGNORABLE = Set(" \t\x0b\x0c\r*_#")
const DECORATION = Set("*_#")
const EMPHASIS = Set("*_")
const HORIZONTAL = Set(" \t\x0b\x0c\r")

fold(c::Char) = 'A' <= c <= 'Z' ? c + 32 : c

"The key a marker is matched by (§4a)."
marker_key(text) = String([fold(c) for c in text if !(c in IGNORABLE)])
_lead_strip(k) = String(Base.lstrip(==('\n'), k))

"`(repairable, unrepaired)`: markers with a non-empty key no other marker shares."
function repairable_markers(markers)
    distinct = unique([m for m in markers if !isempty(m)])
    key(m) = _lead_strip(marker_key(m))
    counts = Dict{String,Int}()
    for m in distinct
        counts[key(m)] = get(counts, key(m), 0) + 1
    end
    ok = [m for m in distinct if !isempty(key(m)) && counts[key(m)] == 1]
    (ok, [m for m in distinct if !(m in ok)])
end

function decoration_start(text, run_start, core_start)
    for i in run_start:core_start-1
        bchar(text, i) in DECORATION && (i == 0 || isws(bchar(text, i - 1))) && return i
    end
    nothing
end

function occurrence_span(text, core_start, core_end, run_start, lead)
    left = decoration_start(text, run_start, core_start)
    start, stop = core_start, core_end
    if left !== nothing
        start = left
        if any(bchar(text, i) in EMPHASIS for i in left:core_start-1)
            while stop < blen(text) && bchar(text, stop) in EMPHASIS
                stop += 1
            end
        end
    end
    if lead > 0
        q = start
        while q > 0 && bchar(text, q - 1) in HORIZONTAL
            q -= 1
        end
        taken = 0
        while taken < lead && q > 0 && bchar(text, q - 1) == '\n'
            q -= 1
            taken += 1
        end
        taken > 0 && (start = q)
    end
    (start, stop)
end

"The text without ignorables, folded; per kept character its byte position and the start of the ignorable run before it."
struct Normalized
    chars::String
    pos::Vector{Int}
    runs::Vector{Int}
    ordinal::Vector{Int}      # byte offset in `chars` (1-based index) → character ordinal
end

function normalized(text::AbstractString)
    io = IOBuffer()
    pos, runs, ordinal = Int[], Int[], Int[]
    run = 0
    for (i, c) in pairs(text)
        b = i - 1
        c in IGNORABLE && continue
        f = fold(c)
        for _ in 1:ncodeunits(f)
            push!(ordinal, length(pos) + 1)
        end
        write(io, f)
        push!(pos, b)
        push!(runs, run)
        run = b + ncodeunits(c)
    end
    Normalized(String(take!(io)), pos, runs, ordinal)
end

"Every loose occurrence of `marker` as its span, leftmost first, without overlap."
function loose_occurrences(text, marker, norm=nothing)
    full = marker_key(marker)
    key = _lead_strip(full)
    isempty(key) && return Tuple{Int,Int}[]
    lead = length(full) - length(key)
    nm = norm === nothing ? normalized(text) : norm
    out = Tuple{Int,Int}[]
    k = bfind(nm.chars, key, 0)
    while k >= 0
        first_ord = nm.ordinal[k+1]
        last_ord = nm.ordinal[k+ncodeunits(key)]
        last_char_start = nm.pos[last_ord]
        core_end = last_char_start + ncodeunits(string(text[last_char_start+1]))
        push!(out, occurrence_span(text, nm.pos[first_ord], core_end, nm.runs[first_ord], lead))
        k = bfind(nm.chars, key, k + ncodeunits(key))
    end
    out
end

function written_exactly(text, marker, spans)
    p = bfind(text, marker, 0)
    while p >= 0
        q = p + blen(marker)
        any(a <= p && q <= b && b - a > q - p for (a, b) in spans) || return true
        p = bfind(text, marker, q)
    end
    false
end

"§4a: rewrite every misspelled marker unless it is written exactly somewhere."
function repair_markers(text::AbstractString, markers; edits=nothing)
    norm = normalized(text)
    chosen = Tuple{Int,Int,String}[]
    for m in markers
        spans = loose_occurrences(text, m, norm)
        written_exactly(text, m, spans) && continue
        append!(chosen, [(a, b, m) for (a, b) in spans])
    end
    isempty(chosen) && return (String(text), JObj[])
    sort!(chosen)
    for i in 1:length(chosen)-1
        a1, b1, m1 = chosen[i]
        a2, b2, m2 = chosen[i+1]
        a2 < b1 && refuse("parse-ambiguous", "the reply's $(pyrepr(bsl(text, a1, b1))) and $(pyrepr(bsl(text, a2, b2))) overlap; read as the markers $(pyrepr(m1)) and $(pyrepr(m2)) they would share text — refusing to guess")
    end
    edits === nothing || push!(edits, Edit[(a, b, blen(m)) for (a, b, m) in chosen])
    io = IOBuffer()
    repairs = JObj[]
    pos = 0
    for (a, b, m) in chosen
        write(io, bsl(text, pos, a), m)
        push!(repairs, jobj("repair" => "marker", "marker" => m, "saw" => bsl(text, a, b)))
        pos = b
    end
    write(io, bsl(text, pos))
    (String(take!(io)), repairs)
end

function refuse_missing(raw, names)
    missing = [n for n in names if !haskey(raw, n)]
    isempty(missing) && return
    hint = "reply is missing pattern section(s): " * join(pyrepr.(missing), ", ")
    isempty(raw) && length(names) > 1 &&
        (hint *= " — it has none of the template's markers: the model did not follow the layout (reading values by their order would be a guess)")
    refuse("parse-missing-fields", hint; partial=raw)
end

"What the derived reader found: raw captures, tolerances, fields that ran to the end, spans."
struct ReaderResult
    raw::JObj
    repairs::Vector{JObj}
    to_end::Set{String}
    spans::OrderedDict{String,Tuple{Int,Int}}
    text::String
end

"The template read backwards (§4); `repair=false` for a strict adapter (§4a)."
mutable struct DerivedReader <: Reader
    anchors::Vector{Tuple{String,String,String}}
    tail::String
    repairable::Vector{String}
    unrepaired::Vector{String}
end
function DerivedReader(anchors, tail::AbstractString="", repair::Bool=true)
    searched = vcat([wrstrip(p) for (_, p, _) in anchors], [wstrip(s) for (_, _, s) in anchors], [wstrip(tail)])
    ok, rest = repair ? repairable_markers(searched) : (String[], String[])
    DerivedReader(collect(anchors), String(tail), ok, rest)
end

function reader_markers(r::DerivedReader)
    out = String[]
    for (_, p, s) in r.anchors
        push!(out, wrstrip(p), wstrip(s))
    end
    isempty(wstrip(r.tail)) || push!(out, wstrip(r.tail))
    [m for m in out if !isempty(m)]
end

reader_split(r::DerivedReader, text, names) = derived_read(r, text, names).raw

function derived_read(r::DerivedReader, text::AbstractString, names; allow_missing=false, edits=nothing)
    repairs = JObj[]
    isempty(r.repairable) || ((text, repairs) = repair_markers(text, r.repairable; edits=edits))
    bounds = Tuple{Int,Int,Union{Nothing,String},String}[]
    for (name, prefix, suffix) in r.anchors
        name in names || continue
        marker = wrstrip(prefix)
        if isempty(marker)
            push!(bounds, (0, 0, name, suffix))
            continue
        end
        n = bcount(text, marker)
        n > 1 && refuse("parse-ambiguous", "anchor $(pyrepr(marker)) for field $(pyrepr(name)) appears $n times in the reply — refusing to guess")
        i = bfind(text, marker)
        i < 0 && continue
        push!(bounds, (i, i + blen(marker), name, suffix))
    end
    tail = wstrip(r.tail)
    if !isempty(tail)
        n = bcount(text, tail)
        n > 1 && refuse("parse-ambiguous", "tail $(pyrepr(tail)) appears $n times in the reply — refusing to guess which one ends the reply")
        t = bfind(text, tail)
        t >= 0 && push!(bounds, (t, t, nothing, ""))
    end
    sort!(bounds; by=b -> (b[1], b[2]))
    raw = JObj()
    spans = OrderedDict{String,Tuple{Int,Int}}()
    to_end = Set{String}()
    notes = JObj[]
    ignored(piece) = isempty(wstrip(piece)) || push!(notes, jobj("repair" => "ignored", "saw" => wstrip(piece)))
    isempty(bounds) || ignored(bsl(text, 0, bounds[1][1]))
    for (i, (start, after, name, suffix)) in enumerate(bounds)
        last = i == length(bounds)
        if name === nothing
            last && ignored(bsl(text, start + blen(tail)))
            continue
        end
        chunk = bsl(text, after, last ? blen(text) : bounds[i+1][1])
        close = wstrip(suffix)
        cut = _cut_at_close(chunk, close, name)
        raw[name] = wstrip(cut)
        spans[name] = (after, after + blen(cut))
        idx = isempty(close) ? -1 : bfind(chunk, close)
        if idx >= 0
            ignored(bsl(chunk, idx + blen(close)))
        elseif last
            push!(to_end, name)
        elseif !isempty(close)
            push!(notes, jobj("repair" => "unclosed", "field" => name, "close" => close))
        end
    end
    allow_missing || refuse_missing(raw, names)
    ReaderResult(raw, vcat(repairs, notes), to_end, spans, String(text))
end

function reader_join(r::DerivedReader, spelled)
    by = Dict(spelled)
    check_collisions(spelled, reader_markers(r))
    pieces = [p * by[n] * s for (n, p, s) in r.anchors if haskey(by, n)]
    cstrip(join(pieces) * (isempty(pieces) ? "" : r.tail), ('\n',))
end

function reader_skeleton(r::DerivedReader)
    isempty(r.anchors) && return jobj("prefill" => "", "stops" => Any[])
    last_close = wstrip(r.anchors[end][3])
    stop = isempty(wstrip(r.tail)) ? last_close : wstrip(r.tail)
    jobj("prefill" => r.anchors[1][2], "stops" => isempty(stop) ? Any[] : Any[stop])
end

# Helpers you can autocomplete (kernel §6): each returns the plain data you
# could write by hand. A wrong argument is host misuse (ArgumentError), not a
# Refusal: the kernel validates what they produce like any other data.

function _to(sub)
    sub === nothing && return "@purpose"
    (sub isa AbstractString && !isempty(sub) && !startswith(sub, "@")) || throw(ArgumentError("to is a sub-purpose name like \"calls\" (nothing means the purpose itself)"))
    "@purpose.$sub"
end

"Text between two delimiters. `repair` reads misspelled delimiters (§4a); `whole_reply` makes a match a complete reply."
function find_between(open, close; to=nothing, remove=false, repair=false, whole_reply=false)
    (open isa AbstractString && !isempty(open) && close isa AbstractString && !isempty(close)) || throw(ArgumentError("find_between takes two non-empty strings"))
    r = jobj("from" => "text", "between" => Any[open, close], "to" => _to(to))
    remove && (r["remove"] = true); repair && (r["repair"] = true); whole_reply && (r["complete_reply"] = true)
    r
end
"Lines starting with `prefix`."
function find_lines(prefix; to=nothing, remove=false)
    (prefix isa AbstractString && !isempty(prefix)) || throw(ArgumentError("find_lines takes a non-empty prefix"))
    r = jobj("from" => "text", "line_prefixed" => prefix, "to" => _to(to))
    remove && (r["remove"] = true)
    r
end
"A regular expression (needs a declared `pattern/*` extension, §10)."
function find_pattern(regex; to=nothing, remove=false)
    (regex isa AbstractString && !isempty(regex)) || throw(ArgumentError("find_pattern takes a non-empty regex"))
    r = jobj("from" => "text", "pattern" => regex, "to" => _to(to))
    remove && (r["remove"] = true)
    r
end
"Reply parts of one lm15 type: `find_part(\"thinking\")`, `find_part(\"tool_call\"; to=\"calls\")`."
function find_part(type; to=nothing, whole_reply=false)
    (type isa AbstractString && !isempty(type)) || throw(ArgumentError("find_part takes an lm15 part type such as \"thinking\""))
    r = jobj("from" => "part:$type", "to" => _to(to))
    whole_reply && (r["complete_reply"] = true)
    r
end

put_system(field=nothing) = jobj(_to(field) => "message:system")
put_developer(field=nothing) = jobj(_to(field) => "message:developer")
put_user(field=nothing) = jobj(_to(field) => "message:user")
"Into the lm15 request: `put_request(\"tools\")`."
function put_request(path, field=nothing)
    (path isa AbstractString && !isempty(path)) || throw(ArgumentError("put_request takes a request path such as \"tools\""))
    jobj(_to(field) => "request.$path")
end

when_has(fact) = jobj("capability" => fact)
when_lacks(fact) = jobj("not" => jobj("capability" => fact))
when_all(ps...) = jobj("all" => Any[ps...])
when_any(ps...) = jobj("any" => Any[ps...])

"""
    choose(alternatives...; otherwise=nothing, registry=default_registry())

The first transport whose predicate holds: `choose(when_has("native_reasoning") => "native_reasoning"; otherwise="reasoning_tags")`.
"""
function choose(alternatives::Pair...; otherwise=nothing, registry::Registry=default_registry())
    resolve(t) = t isa Transport ? t : t isa AbstractString ? named_transport(registry, t, JObj()) :
                 isobj(t) ? transport_from_dict(t, "choose") : throw(ArgumentError("a choice is a Transport, a Dict or a registered transport name"))
    items = Any[(when=first(a), use=resolve(last(a))) for a in alternatives]
    otherwise === nothing || push!(items, (else_=resolve(otherwise),))
    t = Transport(choose=items)
    validate_transport(t, "choose")
    t
end

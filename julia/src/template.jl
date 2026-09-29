# The template language (kernel §2): slots, loops, guards, escapes. A bare
# brace outside them is `template-syntax`.

const _S = "[ \\t\\n\\r\\f\\v]"
const _ID = "[A-Za-z_][A-Za-z0-9_]*"
const TOKEN = Regex("(?<esc>\\{\\{|\\}\\})" *
    "|(?<loop>\\{%$(_S)*for$(_S)+(?<lvar>$(_ID))$(_S)+in$(_S)+(?<lsrc>$(_ID))$(_S)*%\\})" *
    "|(?<endfor>\\{%$(_S)*endfor$(_S)*%\\})" *
    "|(?<guard>\\{%$(_S)*if$(_S)+(?<gname>$(_ID))$(_S)*%\\})" *
    "|(?<orelse>\\{%$(_S)*else$(_S)*%\\})" *
    "|(?<endif>\\{%$(_S)*endif$(_S)*%\\})" *
    "|(?<slot>\\{(?<path>[A-Za-z_][A-Za-z0-9_.]*)\\})")

const LOOP_SOURCES = ("inputs", "outputs")
const LOOP_ATTRS = ["name", "desc", "type", "schema", "purpose", "value"]
const TURN_ATTRS = ("role", "kind", "text")
const RESERVED_SLOTS = ("inputs", "outputs", "instruction", "format")

abstract type Node end
struct TextNode <: Node
    text::String
end
struct SlotNode <: Node
    path::String
end
struct LoopNode <: Node
    var::String
    source::String
    body::Vector{Node}
end
mutable struct GuardNode <: Node
    slot::String
    body::Vector{Node}
    orelse::Vector{Node}
    has_else::Bool
end

over_turns(l::LoopNode) = !(l.source in LOOP_SOURCES)
over_turns(::Node) = false
branches(g::GuardNode) = vcat(g.body, g.orelse)

_syntax(where, hint) = refuse("template-syntax", "$where: $hint"; fix=jobj("action" => "edit-template", "path" => where))

function _check_literal(lit, where)
    for ch in ("{", "}")
        occursin(ch, lit) && _syntax(where, "bare $(pyrepr(ch)) — use $(pyrepr(ch^2)) to render a literal brace")
    end
end

"Compile template text to nodes, refusing loudly on any bad syntax."
function compile_template(text::AbstractString, where::AbstractString="template")
    root = Node[]
    stack = Tuple{Node,Vector{Node}}[]
    current = root
    pos = 1
    in_turn_loop() = any(n isa LoopNode && over_turns(n) for (n, _) in stack)
    for m in eachmatch(TOKEN, text)
        lit = text[pos:prevind(text, m.offset)]
        _check_literal(lit, where)
        isempty(lit) || push!(current, TextNode(lit))
        if m[:esc] !== nothing
            push!(current, TextNode(string(m[:esc][1])))
        elseif m[:loop] !== nothing
            src = String(m[:lsrc])
            src in ("instruction", "format") && _syntax(where, "$(pyrepr(src)) is reserved; a loop runs over inputs, outputs, or a turn slot")
            in_turn_loop() && _syntax(where, "a turn loop's body holds text and m.role/m.kind/m.text only; no nested loop")
            loop = LoopNode(String(m[:lvar]), src, Node[])
            push!(current, loop)
            push!(stack, (loop, current))
            current = loop.body
        elseif m[:guard] !== nothing
            name = String(m[:gname])
            name in RESERVED_SLOTS && _syntax(where, "a guard names a turn slot, not $(pyrepr(name))")
            in_turn_loop() && _syntax(where, "no guard inside a turn loop")
            g = GuardNode(name, Node[], Node[], false)
            push!(current, g)
            push!(stack, (g, current))
            current = g.body
        elseif m[:orelse] !== nothing
            top = isempty(stack) ? nothing : stack[end][1]
            (top isa GuardNode && !top.has_else) || _syntax(where, "{% else %} outside an {% if %}, or twice")
            top.has_else = true
            current = top.orelse
        elseif m[:endfor] !== nothing || m[:endif] !== nothing
            want = m[:endfor] !== nothing ? LoopNode : GuardNode
            word = m[:endfor] !== nothing ? "endfor" : "endif"
            top = isempty(stack) ? nothing : stack[end][1]
            top isa want || _syntax(where, "{% $word %} without an open $(want === LoopNode ? "loop" : "guard")")
            current = pop!(stack)[2]
        else
            push!(current, SlotNode(String(m[:path])))
        end
        pos = m.offset + ncodeunits(m.match)
    end
    tail = text[pos:end]
    _check_literal(tail, where)
    isempty(tail) || push!(current, TextNode(tail))
    isempty(stack) || _syntax(where, "unclosed $(stack[end][1] isa LoopNode ? "{% for %} loop" : "{% if %} guard")")
    _check_turn_loops(root, where)
    root
end

function _check_turn_loops(nodes, where)
    for node in nodes
        if node isa LoopNode && over_turns(node)
            for n in node.body
                n isa SlotNode || continue
                v, _, attr = _partition(n.path, '.')
                (v == node.var && attr in TURN_ATTRS) ||
                    _syntax(where, "in a loop over turn slot $(pyrepr(node.source)) only {$(node.var).role}, {$(node.var).kind} and {$(node.var).text} exist; got {$(n.path)}")
            end
        elseif node isa LoopNode
            _check_turn_loops(node.body, where)
        elseif node isa GuardNode
            _check_turn_loops(branches(node), where)
        end
    end
end

function _partition(s::AbstractString, c::Char)
    i = findfirst(c, s)
    i === nothing ? (String(s), "", "") : (s[1:prevind(s, i)], string(c), s[nextind(s, i):end])
end

"`(slots placed as text by turn loops, slots named by guards)`, in order."
function node_turn_slots(nodes)
    placed, guarded = String[], String[]
    for node in nodes
        if node isa LoopNode && over_turns(node)
            push!(placed, node.source)
        elseif node isa GuardNode
            push!(guarded, node.slot)
            p, g = node_turn_slots(branches(node))
            append!(placed, p); append!(guarded, g)
        elseif node isa LoopNode
            p, g = node_turn_slots(node.body)
            append!(placed, p); append!(guarded, g)
        end
    end
    (placed, guarded)
end

"Check every slot resolves against the signature; the input fields covered."
function validate_nodes(nodes; known_fields, input_fields, where, in_loop_var=nothing, slots=Set{String}())
    covered = Set{String}()
    for node in nodes
        if node isa SlotNode
            path = node.path
            if in_loop_var !== nothing && startswith(path, in_loop_var * ".")
                attr = path[ncodeunits(in_loop_var)+2:end]
                attr in LOOP_ATTRS || refuse("unknown-slot", "$where: {$path} — loop attributes are $(pyrepr(Any[LOOP_ATTRS...]))";
                    fix=jobj("action" => "edit-template", "path" => where, "slot" => path))
                continue
            end
            path in ("instruction", "format") && continue
            occursin('.', path) && refuse("unknown-slot", "$where: {$path} — dotted slots are only valid inside their loop";
                fix=jobj("action" => "edit-template", "path" => where, "slot" => path))
            if path in input_fields
                push!(covered, path)
                continue
            end
            path in known_fields && continue
            refuse("unknown-slot", "$where: {$path} names no field in the signature"; fix=jobj("action" => "edit-template", "path" => where, "slot" => path))
        elseif node isa LoopNode && over_turns(node)
            continue
        elseif node isa GuardNode
            (node.slot in slots || node.slot in input_fields) || refuse("unknown-slot",
                "$where: {% if $(node.slot) %} names neither a turn slot this template places nor an input field";
                fix=jobj("action" => "edit-template", "path" => where, "slot" => node.slot))
            node.slot in input_fields && push!(covered, node.slot)
            union!(covered, validate_nodes(branches(node); known_fields, input_fields, where, in_loop_var, slots))
        elseif node isa LoopNode
            union!(covered, validate_nodes(node.body; known_fields, input_fields, where, in_loop_var=node.var, slots))
            node.source == "inputs" && union!(covered, input_fields)
        end
    end
    covered
end

"""
Render nodes into parts; text accumulates in `buf`. `env` answers
`instruction`, `reply_format`, `loop_fields`, `value_of`, `schema_of`,
`field_named`, `turn_messages` and `guard`.
"""
function render_nodes(nodes, env, out::Vector{Any}, buf::IOBuffer, loop_ctx=nothing)
    for node in nodes
        if node isa TextNode
            write(buf, node.text)
        elseif node isa SlotNode
            _render_slot(node, env, out, buf, loop_ctx)
        elseif node isa GuardNode
            state = env_guard(env, node.slot)
            state === nothing || render_nodes(state ? node.body : node.orelse, env, out, buf, loop_ctx)
        elseif over_turns(node)
            for (role, kind, text) in env_turn_messages(env, node.source)
                attrs = OrderedDict("role" => role, "kind" => kind, "text" => text)
                for n in node.body
                    write(buf, n isa TextNode ? n.text : attrs[_partition(n.path, '.')[3]])
                end
            end
        else
            for f in env_loop_fields(env, node.source)
                ctx = loop_ctx === nothing ? OrderedDict{String,Field}() : copy(loop_ctx)
                ctx[node.var] = f
                render_nodes(node.body, env, out, buf, ctx)
            end
        end
    end
end

function _render_slot(node::SlotNode, env, out, buf, loop_ctx)
    path = node.path
    if loop_ctx !== nothing
        v, _, attr = _partition(path, '.')
        if !isempty(attr) && haskey(loop_ctx, v)
            f = loop_ctx[v]
            if attr == "name"; write(buf, f.name)
            elseif attr == "desc"; write(buf, something(f.desc, ""))
            elseif attr == "purpose"; write(buf, f.purpose)
            elseif attr == "type"; write(buf, something(f.type, ""))
            elseif attr == "schema"; write(buf, env_schema_of(env, f))
            elseif attr == "value"; _emit(env_value_of(env, f), out, buf)
            end
            return
        end
    end
    path == "instruction" && return write(buf, env_instruction(env))
    path == "format" && return write(buf, env_reply_format(env))
    _emit(env_value_of(env, env_field_named(env, path)), out, buf)
end

function _emit(rendered, out, buf)
    kind, payload = rendered
    kind == :text && return write(buf, payload)
    for part in payload
        if get(part, "type", nothing) == "text"
            write(buf, get(part, "text", ""))
            continue
        end
        if buf.size > 0
            push!(out, textpart(String(take!(buf))))
        end
        push!(out, part)
    end
end

# The template language (kernel section 2): slots, loops, guards, escapes.

TOKEN_RE <- paste0(
  "(?<esc>\\{\\{|\\}\\})",
  "|(?<loop>\\{%[ \\t\\n\\r\\f\\v]*for[ \\t\\n\\r\\f\\v]+(?<lvar>[A-Za-z_][A-Za-z0-9_]*)[ \\t\\n\\r\\f\\v]+in[ \\t\\n\\r\\f\\v]+(?<lsrc>[A-Za-z_][A-Za-z0-9_]*)[ \\t\\n\\r\\f\\v]*%\\})",
  "|(?<endfor>\\{%[ \\t\\n\\r\\f\\v]*endfor[ \\t\\n\\r\\f\\v]*%\\})",
  "|(?<guard>\\{%[ \\t\\n\\r\\f\\v]*if[ \\t\\n\\r\\f\\v]+(?<gname>[A-Za-z_][A-Za-z0-9_]*)[ \\t\\n\\r\\f\\v]*%\\})",
  "|(?<orelse>\\{%[ \\t\\n\\r\\f\\v]*else[ \\t\\n\\r\\f\\v]*%\\})",
  "|(?<endif>\\{%[ \\t\\n\\r\\f\\v]*endif[ \\t\\n\\r\\f\\v]*%\\})",
  "|(?<slot>\\{(?<path>[A-Za-z_][A-Za-z0-9_.]*)\\})")

LOOP_SOURCES <- c("inputs", "outputs")
LOOP_ATTRS <- c("name", "desc", "type", "schema", "purpose", "value")
TURN_ATTRS <- c("role", "kind", "text")
RESERVED_SLOTS <- c("inputs", "outputs", "instruction", "format")

over_turns <- function(n) identical(n$kind, "loop") && !(n$source %in% LOOP_SOURCES)
branches <- function(g) c(g$body, g$orelse)

syntax_error <- function(where, hint) refuse("template-syntax", paste0(where, ": ", hint), fix = jobj(action = "edit-template", path = where))

check_literal <- function(lit, where) {
  for (ch in c("{", "}")) if (grepl(ch, lit, fixed = TRUE)) syntax_error(where, sprintf("bare %s \u2014 use %s to render a literal brace", pyrepr(ch), pyrepr(strrep(ch, 2))))
}

partition_dot <- function(path) {
  i <- regexpr(".", path, fixed = TRUE)
  if (i < 0L) c(path, "", "") else c(substr(path, 1L, i - 1L), ".", substring(path, i + 1L))
}

tokenize <- function(text) {
  m <- gregexpr(TOKEN_RE, text, perl = TRUE, useBytes = TRUE)[[1]]
  if (m[[1]] < 0L) return(list(list(lit = text, tok = NULL)))
  starts <- attr(m, "capture.start"); lens <- attr(m, "capture.length"); cn <- attr(m, "capture.names")
  group <- function(k, name) { j <- which(cn == name); if (starts[k, j] <= 0L) NULL else substr(as_bytes_enc(text), starts[k, j], starts[k, j] + lens[k, j] - 1L) }
  out <- list(); pos <- 0L
  for (k in seq_along(m)) {
    a <- m[[k]] - 1L; b <- a + attr(m, "match.length")[[k]]
    kind <- NULL
    for (g in c("esc", "loop", "endfor", "guard", "orelse", "endif", "slot")) if (!is.null(group(k, g))) { kind <- g; break }
    tok <- list(kind = kind, esc = group(k, "esc"), lvar = group(k, "lvar"), lsrc = group(k, "lsrc"), gname = group(k, "gname"), path = group(k, "path"))
    out[[length(out) + 1L]] <- list(lit = bsl(text, pos, a), tok = tok)
    pos <- b
  }
  out[[length(out) + 1L]] <- list(lit = bsl(text, pos), tok = NULL)
  out
}

#' Compile template text to nodes, refusing loudly on any bad syntax.
#' @noRd
compile_template <- function(text, where = "template") {
  items <- tokenize(text)
  k <- 0L
  parse_block <- function(ctx, in_turn_loop) {
    nodes <- list()
    repeat {
      k <<- k + 1L
      if (k > length(items)) {
        if (!is.null(ctx)) syntax_error(where, if (ctx == "loop") "unclosed {% for %} loop" else "unclosed {% if %} guard")
        return(list(nodes = nodes, end = "eof"))
      }
      it <- items[[k]]
      check_literal(it$lit, where)
      if (nzchar(it$lit)) nodes[[length(nodes) + 1L]] <- list(kind = "text", text = it$lit)
      tok <- it$tok
      if (is.null(tok)) next
      if (tok$kind == "esc") {
        nodes[[length(nodes) + 1L]] <- list(kind = "text", text = substr(tok$esc, 1L, 1L))
      } else if (tok$kind == "loop") {
        if (tok$lsrc %in% c("instruction", "format")) syntax_error(where, sprintf("%s is reserved; a loop runs over inputs, outputs, or a turn slot", pyrepr(tok$lsrc)))
        if (in_turn_loop) syntax_error(where, "a turn loop's body holds text and m.role/m.kind/m.text only; no nested loop")
        turn <- !(tok$lsrc %in% LOOP_SOURCES)
        body <- parse_block("loop", in_turn_loop || turn)
        nodes[[length(nodes) + 1L]] <- list(kind = "loop", var = tok$lvar, source = tok$lsrc, body = body$nodes)
      } else if (tok$kind == "guard") {
        if (tok$gname %in% RESERVED_SLOTS) syntax_error(where, sprintf("a guard names a turn slot, not %s", pyrepr(tok$gname)))
        if (in_turn_loop) syntax_error(where, "no guard inside a turn loop")
        body <- parse_block("guard", in_turn_loop)
        orelse <- list()
        if (body$end == "else") {
          rest <- parse_block("else", in_turn_loop)
          orelse <- rest$nodes
        }
        nodes[[length(nodes) + 1L]] <- list(kind = "guard", slot = tok$gname, body = body$nodes, orelse = orelse)
      } else if (tok$kind == "orelse") {
        if (!identical(ctx, "guard")) syntax_error(where, "{% else %} outside an {% if %}, or twice")
        return(list(nodes = nodes, end = "else"))
      } else if (tok$kind == "endfor") {
        if (!identical(ctx, "loop")) syntax_error(where, "{% endfor %} without an open loop")
        return(list(nodes = nodes, end = "endfor"))
      } else if (tok$kind == "endif") {
        if (!(identical(ctx, "guard") || identical(ctx, "else"))) syntax_error(where, "{% endif %} without an open guard")
        return(list(nodes = nodes, end = "endif"))
      } else {
        nodes[[length(nodes) + 1L]] <- list(kind = "slot", path = tok$path)
      }
    }
  }
  root <- parse_block(NULL, FALSE)$nodes
  check_turn_loops(root, where)
  root
}

check_turn_loops <- function(nodes, where) {
  for (node in nodes) {
    if (over_turns(node)) {
      for (n in node$body) {
        if (n$kind != "slot") next
        p <- partition_dot(n$path)
        if (p[[1]] != node$var || !(p[[3]] %in% TURN_ATTRS))
          syntax_error(where, sprintf("in a loop over turn slot %s only {%s.role}, {%s.kind} and {%s.text} exist; got {%s}", pyrepr(node$source), node$var, node$var, node$var, n$path))
      }
    } else if (node$kind == "loop") check_turn_loops(node$body, where)
    else if (node$kind == "guard") check_turn_loops(branches(node), where)
  }
}

node_turn_slots <- function(nodes) {
  placed <- character(0); guarded <- character(0)
  for (node in nodes) {
    if (over_turns(node)) placed <- c(placed, node$source)
    else if (node$kind == "guard") {
      guarded <- c(guarded, node$slot)
      r <- node_turn_slots(branches(node)); placed <- c(placed, r[[1]]); guarded <- c(guarded, r[[2]])
    } else if (node$kind == "loop") {
      r <- node_turn_slots(node$body); placed <- c(placed, r[[1]]); guarded <- c(guarded, r[[2]])
    }
  }
  list(placed, guarded)
}

validate_nodes <- function(nodes, known_fields, input_fields, where, in_loop_var = NULL, slots = character(0)) {
  covered <- character(0)
  for (node in nodes) {
    if (node$kind == "slot") {
      path <- node$path
      if (!is.null(in_loop_var) && startsWith(path, paste0(in_loop_var, "."))) {
        attr <- substring(path, nchar(in_loop_var) + 2L)
        if (!(attr %in% LOOP_ATTRS)) refuse("unknown-slot", sprintf("%s: {%s} \u2014 loop attributes are %s", where, path, pyrepr(as.list(LOOP_ATTRS))),
                                            fix = jobj(action = "edit-template", path = where, slot = path))
        next
      }
      if (path %in% c("instruction", "format")) next
      if (grepl(".", path, fixed = TRUE)) refuse("unknown-slot", sprintf("%s: {%s} \u2014 dotted slots are only valid inside their loop", where, path),
                                                 fix = jobj(action = "edit-template", path = where, slot = path))
      if (path %in% input_fields) { covered <- c(covered, path); next }
      if (path %in% known_fields) next
      refuse("unknown-slot", sprintf("%s: {%s} names no field in the signature", where, path), fix = jobj(action = "edit-template", path = where, slot = path))
    } else if (over_turns(node)) {
      next
    } else if (node$kind == "guard") {
      if (!(node$slot %in% slots) && !(node$slot %in% input_fields))
        refuse("unknown-slot", sprintf("%s: {%% if %s %%} names neither a turn slot this template places nor an input field", where, node$slot),
               fix = jobj(action = "edit-template", path = where, slot = node$slot))
      if (node$slot %in% input_fields) covered <- c(covered, node$slot)
      covered <- c(covered, validate_nodes(branches(node), known_fields, input_fields, where, in_loop_var, slots))
    } else if (node$kind == "loop") {
      covered <- c(covered, validate_nodes(node$body, known_fields, input_fields, where, node$var, slots))
      if (node$source == "inputs") covered <- c(covered, input_fields)
    }
  }
  unique(covered)
}

#' Render nodes into parts. `env` is a list of functions: instruction(),
#' reply_format(), loop_fields(source), value_of(field), schema_of(field),
#' field_named(name), turn_messages(slot), guard(name). State (`out`, `buf`)
#' lives in an environment `st`.
#' @noRd
render_nodes <- function(nodes, env, st, loop_ctx = NULL) {
  for (node in nodes) {
    if (node$kind == "text") st$buf <- c(st$buf, node$text)
    else if (node$kind == "slot") render_slot(node, env, st, loop_ctx)
    else if (node$kind == "guard") {
      state <- env$guard(node$slot)
      if (!is.null(state)) render_nodes(if (state) node$body else node$orelse, env, st, loop_ctx)
    } else if (over_turns(node)) {
      for (m in env$turn_messages(node$source)) {
        attrs <- list(role = m[[1]], kind = m[[2]], text = m[[3]])
        for (n in node$body) st$buf <- c(st$buf, if (n$kind == "text") n$text else attrs[[partition_dot(n$path)[[3]]]])
      }
    } else {
      for (f in env$loop_fields(node$source)) {
        ctx <- if (is.null(loop_ctx)) list() else loop_ctx
        ctx[[node$var]] <- f
        render_nodes(node$body, env, st, ctx)
      }
    }
  }
}

render_slot <- function(node, env, st, loop_ctx) {
  path <- node$path
  if (!is.null(loop_ctx)) {
    p <- partition_dot(path)
    if (nzchar(p[[3]]) && p[[1]] %in% names(loop_ctx)) {
      f <- loop_ctx[[p[[1]]]]
      attr <- p[[3]]
      if (attr == "name") st$buf <- c(st$buf, f$name)
      else if (attr == "desc") st$buf <- c(st$buf, f$desc %||% "")
      else if (attr == "purpose") st$buf <- c(st$buf, f$purpose)
      else if (attr == "type") st$buf <- c(st$buf, f$type %||% "")
      else if (attr == "schema") st$buf <- c(st$buf, env$schema_of(f))
      else if (attr == "value") emit_value(env$value_of(f), st)
      return(invisible())
    }
  }
  if (path == "instruction") { st$buf <- c(st$buf, env$instruction()); return(invisible()) }
  if (path == "format") { st$buf <- c(st$buf, env$reply_format()); return(invisible()) }
  emit_value(env$value_of(env$field_named(path)), st)
}

emit_value <- function(rendered, st) {
  if (rendered[[1]] == "text") { st$buf <- c(st$buf, rendered[[2]]); return(invisible()) }
  for (part in rendered[[2]]) {
    if (identical(get_key(part, "type"), "text")) { st$buf <- c(st$buf, get_key(part, "text", "")); next }
    if (length(st$buf)) {
      st$out[[length(st$out) + 1L]] <- textpart(paste(st$buf, collapse = ""))
      st$buf <- character(0)
    }
    st$out[[length(st$out) + 1L]] <- part
  }
}

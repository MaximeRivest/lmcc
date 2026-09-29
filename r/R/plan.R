# Bind (kernel sections 3-6): the adapter, the signature and the model's
# declared facts meet; every refusal fires here. The plan does pure things
# only: render, read, stream, describe, skeleton, prefix.

PART_SPOT <- "\uFFFC"

#' A rendered request
#'
#' The lm15 request minus its model (section 3), as canonical JSON.
#' @param r A render result from [render()].
#' @param model A model name, or `NULL`.
#' @export
request_of <- function(r, model = NULL) {
  out <- jobj()
  if (!is.null(model)) out[["model"]] <- model
  if (!is.null(r$system)) out[["system"]] <- r$system
  out[["messages"]] <- r$messages
  for (m in members_of(r$request_settings)) out <- set_key(out, m[[1]], m[[2]])
  out
}

#' Record a reply as the turn's next model step (section 3a)
#'
#' The reply to this request, parsed, with the message as it came and the
#' request's hash. Pure.
#' @param r A render result.
#' @param reply Text, an lm15 message or an lm15 response (lists).
#' @export
record_step <- function(r, reply) {
  message <- as_message(reply)
  values <- parse_reply(r$plan, reply)
  if (nzchar(r$plan$prefill)) message <- make_message(message[["role"]], merge_text_parts(c(list(textpart(r$plan$prefill)), message[["parts"]])))
  with_step(r$turn, model_step(values, message, sha256_of(request_of(r)), r$plan$calls_field))
}

reading_to_list <- function(x) jobj(values = x$values, repairs = x$repairs, probabilities = x$probabilities, measured_by = x$measured_by)

# ---------------------------------------------------------------- formats

format_for <- function(p, f) p$formats[[f$name]]$format

schema_hint <- function(p, f) {
  d <- p$formats[[f$name]]$described %||% format_for(p, f)$describe(f)
  if (is.null(d) || !nzchar(d)) shape_summary(f$shape) else d
}

placeholder <- function(p, f) {
  if (!is.null(f$desc) && nzchar(f$desc)) return(f$desc)
  c <- p$formats[[f$name]]
  d <- c$described %||% c$format$describe(f)
  if (!is.null(d) && nzchar(d)) return(d)
  if (c$resolved_by != "kernel" && !is.null(f$type) && nzchar(f$type)) return(f$type)
  s <- shape_summary(f$shape)
  if (nzchar(s)) s else "..."
}

reply_format <- function(p) p$reader$format(lapply(p$visible_outputs, function(f) list(f$name, placeholder(p, f))))

write_value <- function(p, f, value, fmt = NULL) {
  format <- fmt %||% format_for(p, f)
  written <- tryCatch(format$write(value, f), error = function(e) if (is_refusal(e)) stop(e) else refuse("format-write-error", sprintf("field %s: format failed to write: %s", pyrepr(f$name), conditionMessage(e))))
  as_parts(written, sprintf("field %s", pyrepr(f$name)))
}

read_field <- function(p, f, c) {
  fmt <- format_for(p, f)
  tryCatch({
    if (is.null(fmt$read)) stop(sprintf("format %s does not read", fmt$name %||% "(inline)"))
    list(fmt$read(c, f))
  }, error = function(e) if (is_refusal(e)) stop(e) else refuse("format-read-error", sprintf("field %s: format failed to read: %s", pyrepr(f$name), conditionMessage(e))))[[1]]
}

spelled_text <- function(p, f, value) {
  fmt <- format_for(p, f)
  if (!isTRUE(fmt$round_trip)) refuse("turn-not-renderable", sprintf("field %s: format %s does not round-trip, so a turn written with it could not be read back", pyrepr(f$name), fmt$name %||% "(inline)"))
  parts <- write_value(p, f, value)
  if (any(vapply(parts, function(x) !identical(get_key(x, "type"), "text"), TRUE)))
    refuse("turn-not-renderable", sprintf("field %s: its format writes non-text parts, which a text pattern cannot hold", pyrepr(f$name)))
  paste(vapply(parts, function(x) x[["text"]], ""), collapse = "")
}

# ----------------------------------------------------------------- turns

plan_fingerprint <- function(p) signature_fingerprint(p$signature)

#' Turns of a plan's signature
#'
#' `new_turn()` has no steps; `example_turn()` has inputs and outputs (an
#' example); `load_turn()` reads a turn record, checked against the plan.
#' @param p A plan.
#' @param inputs,outputs Named lists.
#' @param data A turn record.
#' @export
new_turn <- function(p, inputs = list()) {
  inputs <- as_obj(inputs)
  check_names(p, inputs, "input", "inputs")
  new_turn_record(plan_fingerprint(p), inputs)
}
#' @rdname new_turn
#' @export
example_turn <- function(p, inputs, outputs) {
  inputs <- as_obj(inputs); outputs <- as_obj(outputs)
  check_names(p, inputs, "input", "inputs"); check_names(p, outputs, "output", "outputs")
  new_turn_record(plan_fingerprint(p), inputs, list(), outputs)
}
#' @rdname new_turn
#' @export
load_turn <- function(p, data) check_turn(p, turn_from_list(data), "turn", FALSE, TRUE)

check_names <- function(p, values, direction, where) {
  if (!is_obj(values)) refuse("turn-invalid", sprintf("%s: an object of %s field values", where, direction))
  known <- vapply(Filter(function(f) f$direction == direction, p$signature$fields), function(f) f$name, "")
  for (k in names(values)) if (!(k %in% known)) refuse("turn-invalid", sprintf("%s.%s: not an %s field of this signature", where, k, direction))
}

check_turn <- function(p, t, where, past, pending_ok = FALSE) {
  if (is_obj(t) && !inherits(t, "lmcc_turn")) t <- turn_from_list(t, where)
  if (!inherits(t, "lmcc_turn")) refuse("turn-invalid", sprintf("%s: expected a turn, got %s", where, class(t)[[1]]))
  if (!identical(t$signature, plan_fingerprint(p))) refuse("turn-invalid", sprintf("%s: recorded for signature %s, but this plan's is %s", where, t$signature, plan_fingerprint(p)))
  check_names(p, t$inputs, "input", paste0(where, ".inputs"))
  if (!is.null(t$outputs)) check_names(p, t$outputs, "output", paste0(where, ".outputs"))
  pending <- list()
  for (i in seq_along(t$steps)) {
    s <- t$steps[[i]]; at <- sprintf("%s.steps[%d]", where, i - 1L)
    if (s$kind == "model") {
      if (length(pending)) refuse("turn-invalid", sprintf("%s: call %s has no tool step", at, pyrepr(call_id(pending[[1]]))))
      check_names(p, s$outputs, "output", paste0(at, ".outputs"))
      pending <- step_calls(s)
    } else {
      if (!length(pending) || !identical(call_id(pending[[1]]), s$id)) refuse("turn-invalid", sprintf("%s: tool step %s answers no pending call", at, pyrepr(s$id)))
      pending <- pending[-1L]
    }
  }
  if (length(pending) && !pending_ok) refuse("turn-invalid", paste0(sprintf("%s: call %s has no tool step", where, pyrepr(call_id(pending[[1]]))),
                                                              if (past) "" else "; answer it with tool_result(turn, id, output) first"))
  t
}

# ----------------------------------------------------------------- render

#' Render a turn into an lm15 request
#'
#' This turn in the context of those turns (section 3a).
#' @param p A plan.
#' @param inputs A named list of inputs, or a turn.
#' @param turns A named list slot to turns, or an unnamed list for the slot `turns`.
#' @export
render <- function(p, inputs = list(), turns = NULL) {
  current <- if (inherits(inputs, "lmcc_turn")) check_turn(p, inputs, "turn", FALSE) else new_turn(p, inputs)
  render_turn(p, current, slot_values(p, turns))
}

slot_values <- function(p, turns) {
  out <- list()
  if (is.null(turns)) return(out)
  if (!length(turns)) return(out)
  by_slot <- if (is_arr(turns)) list(turns = turns) else turns
  if (!is_obj(by_slot) && !(is.list(by_slot) && !is.null(names(by_slot)))) refuse("turn-invalid", "turns is {slot: [turn]} or a list for the slot 'turns'")
  # Slot names are data: found by position, so a slot "" is seen and refused.
  for (m in members_of(by_slot)) {
    name <- m[[1]]; ts <- m[[2]]
    if (!length(ts)) next
    if (name == "steps" || !has_key(p$slots, name))
      refuse("turns-unplaced", paste0(sprintf("turns given for slot %s, which ", pyrepr(name)), if (name == "steps") "is the current turn's own steps" else "the template does not place",
                                      "; placed slots: ", if (length(p$slots)) sorted_repr(names(p$slots)) else "none"))
    out[[name]] <- lapply(seq_along(ts), function(i) check_turn(p, ts[[i]], sprintf("turns[%s][%d]", pyrepr(name), i - 1L), TRUE))
  }
  out
}

render_turn <- function(p, current, slot_vals, stop_at = NULL) {
  if (length(current$steps) && !length(p$slots)) refuse("turns-unplaced", "the current turn has steps, but the template places no turn slot to write them; add turns_slot()")
  ctx <- new.env(); ctx$model_steps <- 0L
  texts <- list()
  for (name in names(p$slots)) {
    if (p$slots[[name]][[1]] != "text") next
    tmp <- new.env(); tmp$model_steps <- 0L
    msgs <- slot_messages(p, name, current, slot_vals, tmp)
    texts[[name]] <- lapply(msgs, function(m) list(m[[1]][["role"]], m[[2]], text_of(m[[1]], name)))
  }
  filled <- Filter(function(name) if (name == "steps") length(current$steps) > 0L else length(slot_vals[[name]]) > 0L, names(p$slots))
  messages <- list(); own <- integer(0)
  sys_tell <- get_key(p$tell, "system")
  tell_done <- is.null(sys_tell)
  compiled <- p$adapter$compiled
  if (!is.null(adapter_prefill(p$adapter))) compiled <- compiled[-length(compiled)]
  for (i in seq_along(compiled)) {
    if (!is.null(stop_at) && i - 1L >= stop_at) break
    msg <- compiled[[i]]$msg; nodes <- compiled[[i]]$nodes
    if (is.null(nodes)) {
      for (m in slot_messages(p, get_key(msg, "slot", "turns"), current, slot_vals, ctx)) messages[[length(messages) + 1L]] <- m[[1]]
      next
    }
    parts <- render_message(p, nodes, current$inputs, texts = texts, filled = filled)
    if (msg[["role"]] == "system" && !tell_done) { parts <- merge_text_parts(c(parts, list(textpart(paste0("\n\n", sys_tell))))); tell_done <- TRUE }
    if (length(parts)) { messages[[length(messages) + 1L]] <- make_message(msg[["role"]], parts); own <- c(own, length(messages)) }
  }
  if (is.null(stop_at) && is.null(p$slots[["steps"]]) && length(p$slots)) for (m in write_steps(p, current, ctx)) messages[[length(messages) + 1L]] <- m[[1]]
  if (!tell_done) { messages <- c(list(make_message("system", list(textpart(sys_tell)))), messages); own <- c(1L, own + 1L) }
  find_own <- function(role) { for (k in own) if (messages[[k]][["role"]] == role) return(k); NULL }
  for (role in names(p$tell)) {
    if (role == "system") next
    k <- find_own(role)
    if (is.null(k)) { messages[[length(messages) + 1L]] <- make_message(role, list(textpart(p$tell[[role]]))); own <- c(own, length(messages)) }
    else messages[[k]][["parts"]] <- merge_text_parts(c(messages[[k]][["parts"]], list(textpart(paste0("\n\n", p$tell[[role]])))))
  }
  settings <- p$request_settings
  for (pp in p$puts) {
    fname <- pp[[1]]; place <- pp[[2]]
    f <- field_named(p$signature, fname)
    if (f$direction != "input" || !has_key(current$inputs, fname)) next
    parts <- write_value(p, f, current$inputs[[fname]], p$written_as[[fname]])
    if (startsWith(place, "request.")) settings <- set_path(settings, substring(place, 9L), parts)
    else {
      role <- sub("^message:", "", place)
      k <- find_own(role)
      if (is.null(k)) { messages[[length(messages) + 1L]] <- make_message(role, parts); own <- c(own, length(messages)) }
      else messages[[k]][["parts"]] <- merge_text_parts(c(messages[[k]][["parts"]], list(textpart("\n\n")), parts))
    }
  }
  if (nzchar(p$prefill) && is.null(stop_at)) messages[[length(messages) + 1L]] <- make_message("assistant", list(textpart(p$prefill)))
  sys_parts <- do.call(c, lapply(Filter(function(m) m[["role"]] == "system", messages), function(m) m[["parts"]]))
  system <- if (!length(sys_parts)) NULL else if (length(sys_parts) == 1L && identical(get_key(sys_parts[[1]], "type"), "text")) sys_parts[[1]][["text"]] else sys_parts
  structure(list(messages = Filter(function(m) m[["role"]] != "system", messages), request_settings = settings, system = system, plan = p, turn = current),
            class = "lmcc_render_result")
}

render_message <- function(p, nodes, values, partial = FALSE, texts = list(), filled = character(0)) {
  st <- new.env(); st$out <- list(); st$buf <- character(0)
  env <- list(
    instruction = function() p$signature$instructions,
    reply_format = function() reply_format(p),
    loop_fields = function(source) {
      if (source != "inputs") return(p$visible_outputs)
      if (partial) Filter(function(f) has_key(values, f$name), p$visible_inputs) else p$visible_inputs
    },
    field_named = function(name) field_named(p$signature, name),
    schema_of = function(f) schema_hint(p, f),
    turn_messages = function(slot) texts[[slot]] %||% list(),
    guard = function(name) {
      f <- field_named(p$signature, name)
      if (!is.null(f) && f$direction == "input") {
        v <- get_key(values, name)
        return(!(is.null(v) || identical(v, FALSE) || identical(v, "") || (is.list(v) && !is_obj(v) && !length(v))))
      }
      if (partial) return(NULL)
      name %in% filled
    },
    value_of = function(f) {
      if (f$direction == "output") return(list("text", placeholder(p, f)))
      if (!has_key(values, f$name)) refuse("missing-input", sprintf("no value supplied for field %s", pyrepr(f$name)))
      parts <- write_value(p, f, values[[f$name]])
      if (length(parts) == 1L && identical(get_key(parts[[1]], "type"), "text")) return(list("text", parts[[1]][["text"]]))
      list("parts", parts)
    })
  render_nodes(nodes, env, st)
  if (length(st$buf)) st$out[[length(st$out) + 1L]] <- textpart(paste(st$buf, collapse = ""))
  merge_text_parts(st$out)
}

text_of <- function(m, slot) {
  for (x in m[["parts"]]) if (!identical(get_key(x, "type"), "text"))
    refuse("turn-not-renderable", sprintf("slot %s is placed as text, but a %s message of its turns holds a %s part, which text cannot hold; place the slot as messages (turns_slot(%s)) or use a text transport",
                                          pyrepr(slot), m[["role"]], pyrepr(get_key(x, "type")), pyrepr(slot)))
  paste(vapply(m[["parts"]], function(x) x[["text"]], ""), collapse = "")
}

slot_messages <- function(p, name, current, slot_vals, ctx) {
  if (name == "steps") return(write_steps(p, current, ctx))
  out <- list()
  for (t in slot_vals[[name]]) {
    for (m in user_side(p, t$inputs)) out[[length(out) + 1L]] <- list(m, "input")
    if (length(t$steps)) out <- c(out, write_steps(p, t, ctx))
    else if (!is.null(t$outputs) && length(t$outputs)) {
      m <- model_message(p, model_step(t$outputs), ctx)[[1]]
      if (!is.null(m)) out[[length(out) + 1L]] <- list(m, "model")
    }
  }
  out
}

user_side <- function(p, inputs) {
  out <- list()
  for (c in p$adapter$compiled) {
    if (is.null(c$nodes) || !identical(c$msg[["role"]], "user")) next
    parts <- render_message(p, c$nodes, inputs, partial = TRUE)
    if (length(parts)) out[[length(out) + 1L]] <- make_message("user", parts)
  }
  out
}

write_steps <- function(p, t, ctx) {
  out <- list(); ids <- list()
  for (s in t$steps) {
    if (s$kind == "model") {
      r <- model_message(p, s, ctx)
      ids <- r[[2]]
      if (!is.null(r[[1]])) out[[length(out) + 1L]] <- list(r[[1]], "model")
    } else out[[length(out) + 1L]] <- list(tool_message(p, s, ids[[s$id]] %||% s$id), "tool")
  }
  out
}

model_message <- function(p, s, ctx) {
  if (p$adapter$replay == "verbatim" && !is.null(s$message)) {
    ctx$model_steps <- ctx$model_steps + 1L
    return(list(make_message("assistant", s$message[["parts"]]), list()))
  }
  if (p$adapter$replay == "recorded" && !is.null(s$message)) {
    same <- tryCatch({
      r <- parse_with_captures(p, s$message, continued = FALSE)
      json_equal(to_json(r[[1]]), to_json(s$outputs)) && !any(vapply(r[[3]], function(x) x[["repair"]] %in% c("marker", "unclosed", "value"), TRUE))
    }, lmcc_refusal = function(e) FALSE)
    if (same) {
      ctx$model_steps <- ctx$model_steps + 1L
      return(list(make_message("assistant", s$message[["parts"]]), list()))
    }
  }
  write_model_step(p, s, ctx)
}

write_model_step <- function(p, s, ctx) {
  outs <- s$outputs
  recorded <- if (is.null(s$message)) list() else s$message[["parts"]]
  parts <- Filter(function(x) isTRUE(get_key(x, "type") %in% p$replay_types), recorded)
  before <- character(0); after <- character(0)
  for (fname in names(p$turn_writers)) {
    w <- p$turn_writers[[fname]]
    v <- get_key(outs, fname)
    if (w[["by"]] %in% c("dropped", "projection", "replayed", "spelling.call", "format:parts") || is.null(v) || identical(v, "") || (is.list(v) && !is_obj(v) && !length(v))) next
    t <- spelled_text(p, field_named(p$signature, fname), v)
    piece <- if (w[["by"]] == "derived:between") {
      close <- w[["between"]][[2]]
      if (grepl(close, t, fixed = TRUE)) refuse("value-collides", sprintf("field %s: its written value contains %s, the marker that ends it", pyrepr(fname), pyrepr(close)))
      paste0(w[["between"]][[1]], t, close)
    } else if (w[["by"]] == "derived:line_prefixed") paste(paste0(w[["prefix"]], split_lines(t)), collapse = "\n")
    else spell_turn(w[["template"]], list(value = t))
    if (identical(get_key(w, "position", "after"), "before")) before <- c(before, piece) else after <- c(after, piece)
  }
  spelled <- list(); placed <- list()
  for (f in p$visible_outputs) {
    if (!has_key(outs, f$name)) next
    fmt <- format_for(p, f)
    if (fmt$writes == "parts" && inherits(p$reader, "lmcc_derived_reader")) {
      if (!isTRUE(fmt$round_trip)) refuse("turn-not-renderable", sprintf("field %s: format %s does not round-trip", pyrepr(f$name), fmt$name %||% "(inline)"))
      placed[[length(placed) + 1L]] <- write_value(p, f, outs[[f$name]])
      spelled[[length(spelled) + 1L]] <- list(f$name, PART_SPOT)
    } else {
      tv <- spelled_text(p, f, outs[[f$name]])
      if (grepl(PART_SPOT, tv, fixed = TRUE)) refuse("value-collides", sprintf("field %s: its value contains U+FFFC, which marks where a part goes", pyrepr(f$name)))
      spelled[[length(spelled) + 1L]] <- list(f$name, tv)
    }
  }
  body <- if (length(spelled)) p$reader$join(spelled) else ""
  pieces <- c(before, body, after)
  text <- paste(pieces[nzchar(pieces)], collapse = "\n")
  ids <- list()
  calls <- if (is.null(p$calls_field)) NULL else get_key(outs, p$calls_field)
  call_parts <- list()
  if (pytruthy(calls)) {
    f <- field_named(p$signature, p$calls_field)
    written <- tryCatch(write_value(p, f, calls), lmcc_refusal = function(e) {
      if (e$code != "format-write-error") stop(e)
      refuse("turn-not-renderable", sprintf("field %s: %s", pyrepr(p$calls_field), e$hint))
    })
    for (x in written) if (!identical(get_key(x, "type"), "tool_call") || !is_str(get_key(x, "id")) || !is_str(get_key(x, "name")) || !is_obj(get_key(x, "input")))
      refuse("turn-not-renderable", sprintf("field %s: its format must write lm15 tool_call parts {type, id, name, input}; got %s", pyrepr(p$calls_field), pyrepr(x)))
    owner <- p$calls_owner
    if (!is.null(owner) && has_key(owner$transport$spelling, "call")) {
      ct <- paste(vapply(written, function(x) call_text(p, owner, x), ""), collapse = "\n")
      text <- if (nzchar(text)) paste0(text, "\n", ct) else ct
    } else {
      assigned <- !any(vapply(recorded, function(x) identical(get_key(x, "type"), "tool_call"), TRUE))
      k <- ctx$model_steps
      for (x in written) {
        if (assigned) { ids[[x[["id"]]]] <- sprintf("s%d_%s", k, x[["id"]]); x[["id"]] <- ids[[x[["id"]]]] }
        call_parts[[length(call_parts) + 1L]] <- x
      }
    }
  }
  if (length(placed)) {
    pcs <- strsplit(paste0(text, "\u0001"), PART_SPOT, fixed = TRUE)[[1]]
    pcs[[length(pcs)]] <- sub("\u0001$", "", pcs[[length(pcs)]])
    tails <- c(placed, list(list()))
    for (i in seq_len(min(length(pcs), length(tails)))) {
      if (nzchar(pcs[[i]])) parts[[length(parts) + 1L]] <- textpart(pcs[[i]])
      parts <- c(parts, tails[[i]])
    }
  } else if (nzchar(text)) parts[[length(parts) + 1L]] <- textpart(text)
  parts <- c(parts, call_parts)
  if (!length(parts)) return(list(NULL, ids))
  ctx$model_steps <- ctx$model_steps + 1L
  list(make_message("assistant", parts), ids)
}

tool_message <- function(p, s, written_id) {
  owner <- p$calls_owner
  if (!is.null(owner) && has_key(owner$transport$spelling, "result")) {
    texts <- Filter(function(x) identical(get_key(x, "type"), "text") && is_str(get_key(x, "text")), s$output)
    output <- paste(vapply(texts, function(x) x[["text"]], ""), collapse = "\n")
    t <- spell_turn(owner$transport$spelling[["result"]], list(id = s$id, name = s$name, output = output))
    return(make_message("user", c(list(textpart(t)), Filter(function(x) !identical(get_key(x, "type"), "text"), s$output))))
  }
  make_message("tool", list(jobj(type = "tool_result", id = written_id, name = s$name, content = s$output)))
}

INPUT_FIELD <- new_field("input", "input", jobj(type = "object"))

call_text <- function(p, r, call) {
  fmt <- p$turn_input_formats[[r$purpose]]
  input <- get_key(call, "input") %||% jobj()
  body <- if (is.null(fmt)) json_text(input, spaced = TRUE, code = "format-write-error") else tryCatch({
    ps <- as_parts(fmt$write(input, INPUT_FIELD), "spelling.input_format")
    if (any(vapply(ps, function(x) !identical(get_key(x, "type"), "text") || !is_str(get_key(x, "text")), TRUE))) stop("argument writer must return only text parts")
    paste(vapply(ps, function(x) x[["text"]], ""), collapse = "")
  }, error = function(e) if (is_refusal(e)) stop(e) else refuse("format-write-error", sprintf("spelling.input_format on purpose %s: %s", pyrepr(r$purpose), conditionMessage(e))))
  spell_turn(r$transport$spelling[["call"]], list(id = pystr(get_key(call, "id") %||% ""), name = pystr(get_key(call, "name") %||% ""), input = body))
}

#' The cache-stable request prefix and the reply skeleton (section 3)
#' @param p A plan.
#' @param turns Slot values, as for [render()].
#' @export
prefix <- function(p, turns = NULL) {
  stop <- NULL
  names_in <- vapply(p$visible_inputs, function(f) f$name, "")
  compiled <- p$adapter$compiled
  for (i in seq_along(compiled)) if (!is.null(compiled[[i]]$nodes) && depends_on_inputs(compiled[[i]]$nodes, names_in)) { stop <- i - 1L; break }
  put_roles <- unique(unlist(lapply(p$puts, function(pp) if (startsWith(pp[[2]], "message:") && field_named(p$signature, pp[[1]])$direction == "input") sub("^message:", "", pp[[2]]) else NULL)))
  for (i in seq_along(compiled)) if (!is.null(compiled[[i]]$nodes) && isTRUE(compiled[[i]]$msg[["role"]] %in% put_roles)) { stop <- if (is.null(stop)) i - 1L else min(stop, i - 1L); break }
  varies <- "system" %in% put_roles || (!is.null(stop) && any(vapply(compiled[(stop + 1L):length(compiled)], function(c) !is.null(c$nodes) && identical(c$msg[["role"]], "system"), TRUE)))
  if (varies) return(jobj(messages = list()))
  r <- render_turn(p, new_turn_record(plan_fingerprint(p), jobj()), slot_values(p, turns), stop)
  out <- jobj()
  if (!is.null(r$system)) out[["system"]] <- r$system
  out[["messages"]] <- r$messages
  out
}

#' @rdname prefix
#' @export
skeleton <- function(p) p$reader$skeleton()

# ------------------------------------------------------------------ parse

parse_with_captures <- function(p, response, continued = TRUE) {
  cut <- identical(finish_reason_of(response), "length")
  tp <- response_text_and_parts(response); text <- tp[[1]]; parts <- tp[[2]]
  lead <- if (continued && nzchar(p$prefill)) p$prefill else ""
  text <- paste0(lead, text)
  atoms <- atoms_of(parts, p$find_rules, blen(lead))
  edits <- new.env(); edits$stages <- list()
  repairs <- list()
  if (length(p$find_repairable)) { rr <- repair_markers(text, p$find_repairable, edits); text <- rr[[1]]; repairs <- rr[[2]] }
  fr <- apply_find_rules(text, parts, p$find_rules, pattern_binding(p), edits); text <- fr[[1]]; found <- fr[[2]]
  complete <- any(vapply(p$find_rules, function(x) pytruthy(get_key(x[[2]], "complete_reply")) && !is.null(found[[x[[1]]]]) && length(found[[x[[1]]]]$parts) > 0L, TRUE))
  names_out <- vapply(p$visible_outputs, function(f) f$name, "")
  derived <- inherits(p$reader, "lmcc_derived_reader")
  to_end <- character(0); missing_err <- NULL; result <- NULL
  raw <- tryCatch({
    if (derived) {
      result <- p$reader$read(text, names_out, allow_missing = TRUE, edits = edits)
      to_end <- result$to_end
      repairs <- c(repairs, result$repairs)
      result$raw
    } else as_obj(p$reader$split(text, names_out))
  }, error = function(e) {
    if (is_refusal(e)) {
      if (cut && !derived) refuse_cut(p, "", jobj(), e$hint)
      if (!(e$code == "parse-missing-fields" && is_obj(e$partial))) stop(e)
      missing_err <<- e
      return(as_obj(e$partial))
    }
    if (cut && !derived) refuse_cut(p, "", jobj(), conditionMessage(e))
    refuse("reader-error", sprintf("reader %s failed to read the reply: %s", pyrepr(p$adapter$reader[["kind"]]), conditionMessage(e)))
  })
  missing <- names_out[!vapply(names_out, function(n) has_key(raw, n), TRUE)]
  if (cut) {
    ended <- as_obj(raw[setdiff(names(raw), to_end)])
    if (length(missing)) refuse_cut(p, sprintf("before field %s", pyrepr(missing[[1]])), ended)
    if (length(to_end)) refuse_cut(p, sprintf("inside field %s", pyrepr(names_out[names_out %in% to_end][[1]])), ended)
    if (!derived) refuse_cut(p, "", ended)
  }
  if (length(missing) && !complete) {
    if (!is.null(missing_err)) stop(missing_err)
    refuse_missing(raw, names_out)
  }
  captures <- list()
  for (f in p$visible_outputs) if (has_key(raw, f$name)) captures[[f$name]] <- capture_of_text(raw[[f$name]])
  if (length(atoms) && derived) {
    pa <- place_atoms(atoms, edits$stages, result)
    for (name in names(pa[[1]])) if (!is.null(captures[[name]])) captures[[name]] <- interleaved(result$text, result$spans[[name]], pa[[1]][[name]], raw[[name]])
    for (x in pa[[2]]) repairs[[length(repairs) + 1L]] <- jobj(repair = "ignored", part = get_key(x, "type"))
  }
  for (n in names(found)) captures[[n]] <- found[[n]]
  values <- jobj()
  rep_env <- new.env(); rep_env$repairs <- repairs
  for (f in p$visible_outputs) if (!is.null(captures[[f$name]])) values <- set_key(values, f$name, read_forgiving(p, f, captures[[f$name]], rep_env))
  for (n in names(found)) values <- set_key(values, n, read_forgiving(p, field_named(p$signature, n), found[[n]], rep_env))
  list(values, captures, rep_env$repairs)
}

read_forgiving <- function(p, f, c, rep_env) {
  tryCatch(read_field(p, f, c), lmcc_refusal = function(e) {
    if (isTRUE(p$adapter$strict) || e$code != "parse-value" || !identical(format_for(p, f)$name, "kernel-scalar")) stop(e)
    v <- forgive_value(f$shape, capture_text(c), sprintf("field %s", pyrepr(f$name)))
    rep_env$repairs[[length(rep_env$repairs) + 1L]] <- jobj(repair = "value", field = f$name, saw = wstrip(capture_text(c)),
                                                             as = spell_value(f$shape, v, sprintf("field %s", pyrepr(f$name))))
    v
  })
}

refuse_cut <- function(p, where, partial, why = "") {
  hint <- if (nzchar(where)) paste0("the provider cut the reply at its length limit ", where)
          else paste0(sprintf("the provider cut the reply at its length limit; reader %s cannot tell which outputs ended before it", pyrepr(p$adapter$reader[["kind"]])),
                      if (nzchar(why)) sprintf(" (%s)", why) else "")
  refuse("parse-truncated", paste0(hint, "; raise max_tokens or ask for less"), partial = partial)
}

#' Read a reply
#'
#' `read_reply()` returns the typed values, every repair made to read them
#' (section 4a) and what the reply's data parts measured (section 3);
#' `parse_reply()` returns the values. Pure.
#' @param p A plan.
#' @param response Text, an lm15 message or an lm15 response (lists).
#' @export
read_reply <- function(p, response) {
  pm <- reply_probabilities(response)
  r <- parse_with_captures(p, response)
  structure(list(values = r[[1]], repairs = r[[3]], probabilities = pm[[1]], measured_by = pm[[2]]), class = "lmcc_reading")
}
#' @rdname read_reply
#' @export
parse_reply <- function(p, response) read_reply(p, response)$values

pattern_binding <- function(p) { for (r in p$extensions) if (identical(r$binding$family, "pattern")) return(r$binding); NULL }

# ------------------------------------------------------------ atoms (4b)

atoms_of <- function(parts, find_rules, shift) {
  claimed <- unlist(lapply(find_rules, function(x) if (startsWith(x[[2]][["from"]], "part:")) substring(x[[2]][["from"]], 6L) else NULL))
  out <- list(); pos <- shift
  for (x in parts) {
    t <- get_key(x, "type")
    if (t %in% c("text", "data")) pos <- pos + blen(part_text(x))
    else if (!(t %in% claimed)) out[[length(out) + 1L]] <- list(pos, x)
  }
  out
}

map_offset <- function(offset, stages) {
  for (stage in stages) {
    shift <- 0L
    for (e in stage) {
      if (offset <= e[[1]]) break
      if (offset < e[[2]]) return(NULL)
      shift <- shift + e[[3]] - (e[[2]] - e[[1]])
    }
    offset <- offset + shift
  }
  offset
}

place_atoms <- function(atoms, stages, result) {
  placed <- list(); ignored <- list()
  for (a in atoms) {
    o <- map_offset(a[[1]], stages)
    owner <- NULL
    if (!is.null(o)) for (name in names(result$spans)) { s <- result$spans[[name]]; if (s[[1]] <= o && o <= s[[2]]) { owner <- name; break } }
    if (is.null(owner)) ignored[[length(ignored) + 1L]] <- a[[2]]
    else { cur <- placed[[owner]] %||% list(); cur[[length(cur) + 1L]] <- list(o, a[[2]]); placed[[owner]] <- cur }
  }
  list(placed, ignored)
}

interleaved <- function(text, span, inside, raw) {
  seq <- list(); pos <- span[[1]]
  inside <- inside[order(vapply(inside, `[[`, 0, 1), method = "radix")]
  for (a in inside) { seq[[length(seq) + 1L]] <- textpart(bsl(text, pos, a[[1]])); seq[[length(seq) + 1L]] <- a[[2]]; pos <- a[[1]] }
  seq[[length(seq) + 1L]] <- textpart(bsl(text, pos, span[[2]]))
  if (identical(get_key(seq[[1]], "type"), "text")) seq[[1]] <- textpart(wlstrip(seq[[1]][["text"]]))
  n <- length(seq)
  if (identical(get_key(seq[[n]], "type"), "text")) seq[[n]] <- textpart(wrstrip(seq[[n]][["text"]]))
  new_capture(Filter(function(x) !identical(get_key(x, "type"), "text") || nzchar(x[["text"]]), seq), raw)
}

bare_slots <- function(nodes) {
  out <- character(0)
  for (n in nodes) {
    if (n$kind == "slot" && !grepl(".", n$path, fixed = TRUE)) out <- c(out, n$path)
    else if (n$kind == "guard") out <- c(out, bare_slots(branches(n)))
  }
  unique(out)
}

depends_on_inputs <- function(nodes, names_in) {
  for (n in nodes) {
    if (n$kind == "slot" && n$path %in% names_in) return(TRUE)
    if (n$kind == "loop" && !over_turns(n) && (n$source == "inputs" || depends_on_inputs(n$body, names_in))) return(TRUE)
    if (n$kind == "guard" && (n$slot %in% names_in || depends_on_inputs(branches(n), names_in))) return(TRUE)
  }
  FALSE
}

MISSING <- structure(list(), class = "lmcc_missing")
get_path <- function(target, path) {
  for (k in strsplit(path, ".", fixed = TRUE)[[1]]) {
    i <- if (is_obj(target)) key_index(target, k) else 0L
    if (!i) return(MISSING)
    target <- target[[i]]
  }
  target
}
set_path <- function(target, path, value) {
  keys <- strsplit(path, ".", fixed = TRUE)[[1]]
  if (length(keys) == 1L) return(set_key(target, keys, value))
  set_key(target, keys[[1]], set_path(get_key(target, keys[[1]], jobj()), paste(keys[-1L], collapse = "."), value))
}

merge_setting <- function(p, path, value, owner, setting_owner, conflict_path) {
  existing <- get_path(p$request_settings, path)
  if (!inherits(existing, "lmcc_missing") && !json_equal(existing, value))
    refuse("setting-conflict", sprintf("%s and %s disagree on request control %s", pyrepr(owner), pyrepr(setting_owner[[path]]), pyrepr(path)),
           fix = jobj(action = "edit-entry", path = conflict_path))
  p$request_settings <- set_path(p$request_settings, path, value)
  if (is.null(setting_owner[[path]])) setting_owner[[path]] <- owner
}

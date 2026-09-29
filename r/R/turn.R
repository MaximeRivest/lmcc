# The turn record (kernel section 3a). Immutable: every operation returns a
# new turn. `turn_to_list()` is schema/turn.schema.json, the same record in
# every language.

#' Canonical JSON and its hash
#'
#' Keys by code point, no whitespace, numbers by section 7a (D-54):
#' signature fingerprints and request hashes, byte-identical in every lmcc.
#' @param value A JSON value.
#' @export
canonical_json <- function(value) json_text(value, sort_keys = TRUE)
#' @rdname canonical_json
#' @export
sha256_of <- function(value) paste0("sha256:", sha256_hex(canonical_json(value)))
#' @rdname canonical_json
#' @param text Text, hashed as UTF-8.
#' @export
sha256_hex <- function(text) .Call(lmcc_sha256, charToRaw(enc2utf8(text)))

#' A signature's fingerprint (section 3a)
#' @param sig A signature.
#' @export
signature_fingerprint <- function(sig) {
  sha256_of(lapply(sig$fields, function(f) jobj(direction = f$direction, name = f$name, purpose = if (nzchar(f$purpose)) f$purpose else "plain",
                                                shape = f$shape, type = f$type %||% "")))
}

#' A value as JSON data; anything without a JSON form refuses `turn-invalid`.
#' @noRd
to_json <- function(value, where = "turn") {
  if (is.null(value) || is_str(value) || is_bool(value)) return(value)
  if (is_num(value)) {
    v <- num_value(value)
    if (is.double(v) && !is.finite(v)) refuse("turn-invalid", sprintf("%s: %s has no JSON form", where, format(v)))
    return(v)
  }
  if (is.factor(value) && length(value) == 1L) return(as.character(value))
  if (is_obj(value)) {
    out <- jobj()
    for (m in members_of(value)) out <- set_key(out, m[[1]], to_json(m[[2]], paste0(where, ".", m[[1]])))
    return(out)
  }
  if (is.list(value)) return(lapply(seq_along(value), function(i) to_json(value[[i]], sprintf("%s[%d]", where, i - 1L))))
  refuse("turn-invalid", sprintf("%s: a %s of length %d has no JSON form; a turn holds JSON values in their fields' shapes (use jarr() for an array)", where, class(value)[[1]], length(value)))
}

call_id <- function(c) if (is_obj(c)) get_key(c, "id") else NULL
call_name <- function(c) if (is_obj(c)) get_key(c, "name") else NULL

as_message <- function(reply) {
  if (is_str(reply)) return(make_message("assistant", list(textpart(reply))))
  r <- message_of(reply)
  if (is_obj(r) && is_arr(get_key(r, "parts"))) return(make_message(get_key(r, "role", "assistant"), lapply(r[["parts"]], function(p) if (is_obj(p)) as_obj(p) else p)))
  refuse("response-malformed", "a reply is text, an lm15 message {role, parts}, or an lm15 response {message: ...}")
}

model_step <- function(outputs, message = NULL, request = NULL, calls_field = NULL)
  structure(list(kind = "model", outputs = as_obj(outputs), message = message, request = request, calls_field = calls_field), class = "lmcc_model_step")
tool_step <- function(id, name, output, children = list())
  structure(list(kind = "tool", id = id, name = name, output = output, children = children), class = "lmcc_tool_step")

step_calls <- function(s) {
  v <- if (is.null(s$calls_field)) NULL else get_key(s$outputs, s$calls_field)
  if (is_arr(v)) v else list()
}

step_to_list <- function(s) {
  if (s$kind == "model") {
    d <- jobj(kind = "model", outputs = to_json(s$outputs, "step.outputs"))
    if (!is.null(s$message)) d[["message"]] <- s$message
    if (!is.null(s$request)) d[["request"]] <- s$request
    if (!is.null(s$calls_field)) d[["calls_field"]] <- s$calls_field
    return(d)
  }
  d <- jobj(kind = "tool", id = s$id, name = s$name, output = s$output)
  if (length(s$children)) d[["children"]] <- lapply(s$children, turn_to_list)
  d
}

output_parts <- function(output) {
  if (is_str(output)) return(list(textpart(output)))
  if (!is_arr(output)) refuse("turn-invalid", "a tool output is a text or a list of lm15 parts")
  for (p in output) if (!is_obj(p) || !is_str(get_key(p, "type"))) refuse("turn-invalid", sprintf("a tool output part must be an lm15 part with a type, got %s", pyrepr(p)))
  lapply(output, as_obj)
}

new_turn_record <- function(signature, inputs, steps = list(), outputs = NULL, score = NULL, meta = jobj())
  structure(list(signature = signature, inputs = as_obj(inputs), steps = steps, outputs = outputs, score = score, meta = as_obj(meta)), class = "lmcc_turn")

#' Turns: calls still pending, tool results, finishing, notes
#' @param turn A turn.
#' @param id,output The call answered and its result (text or lm15 parts).
#' @param children Turns made while producing the result (never written).
#' @export
pending_calls <- function(turn) {
  pending <- list()
  for (s in turn$steps) {
    if (s$kind == "model") pending <- step_calls(s)
    else if (length(pending) && identical(call_id(pending[[1]]), s$id)) pending <- pending[-1L]
  }
  pending
}

#' @rdname pending_calls
#' @export
tool_result <- function(turn, id, output, children = list()) {
  pending <- pending_calls(turn)
  if (!length(pending)) refuse("turn-invalid", sprintf("tool result %s answers no pending call", pyrepr(id)))
  if (!identical(call_id(pending[[1]]), id)) refuse("turn-invalid", sprintf("tool result %s is out of order: the next pending call is %s", pyrepr(id), pyrepr(call_id(pending[[1]]))))
  for (c in children) if (!inherits(c, "lmcc_turn")) refuse("turn-invalid", "tool step children are turns")
  turn$steps <- c(turn$steps, list(tool_step(as.character(id), pystr(call_name(pending[[1]])), output_parts(output), children)))
  turn
}

#' @rdname pending_calls
#' @export
finish_turn <- function(turn) {
  pending <- pending_calls(turn)
  if (length(pending)) refuse("turn-invalid", sprintf("cannot finish with unanswered call %s", pyrepr(call_id(pending[[1]]))))
  last <- NULL
  for (s in turn$steps) if (s$kind == "model") last <- s
  if (is.null(last)) refuse("turn-invalid", "cannot finish a turn with no model step")
  turn$outputs <- last$outputs
  turn
}

with_step <- function(turn, s) { turn$steps <- c(turn$steps, list(s)); turn }

#' @rdname pending_calls
#' @param meta A named list, checked for JSON form now.
#' @export
with_meta <- function(turn, meta) {
  if (!is_obj(meta)) refuse("turn-invalid", "turn.meta: an object")
  turn["meta"] <- list(to_json(as_obj(meta), "turn.meta"))
  turn
}

#' @rdname pending_calls
#' @param score A finite number, or `NULL`.
#' @export
with_score <- function(turn, score) {
  if (!is.null(score) && !(is_num(score) && is.finite(num_value(score)))) refuse("turn-invalid", sprintf("turn.score: a finite number or None, not %s", pyrepr(score)))
  turn["score"] <- list(score)
  turn
}

#' A turn as JSON data, and back (schema/turn.schema.json)
#' @param turn A turn.
#' @param data Turn data.
#' @param where The path named in refusals.
#' @export
turn_to_list <- function(turn) {
  d <- jobj(signature = turn$signature, inputs = to_json(turn$inputs, "turn.inputs"), steps = lapply(turn$steps, step_to_list))
  if (!is.null(turn$outputs)) d[["outputs"]] <- to_json(turn$outputs, "turn.outputs")
  if (!is.null(turn$score)) d[["score"]] <- turn$score
  if (length(turn$meta)) d[["meta"]] <- to_json(turn$meta, "turn.meta")
  d
}

#' @rdname turn_to_list
#' @export
turn_from_list <- function(data, where = "turn") {
  if (!is_obj(data)) refuse("turn-invalid", sprintf("%s: a turn is an object", where))
  unknown <- ssort(setdiff(names(data), c("signature", "inputs", "steps", "outputs", "score", "meta")))
  if (length(unknown)) refuse("turn-invalid", sprintf("%s: unknown key(s) %s", where, pyrepr(as.list(unknown))))
  sig <- get_key(data, "signature"); ins <- get_key(data, "inputs")
  if (!is_str(sig) || !is_obj(ins)) refuse("turn-invalid", sprintf("%s: a turn needs a signature fingerprint and an inputs object", where))
  outs <- get_key(data, "outputs")
  if (!is.null(outs) && !is_obj(outs)) refuse("turn-invalid", sprintf("%s.outputs: an object or null", where))
  steps <- list()
  raw_steps <- get_key(data, "steps") %||% list()
  for (i in seq_along(raw_steps)) {
    s <- raw_steps[[i]]; at <- sprintf("%s.steps[%d]", where, i - 1L)
    if (!is_obj(s) || !isTRUE(get_key(s, "kind") %in% c("model", "tool"))) refuse("turn-invalid", sprintf("%s: a step is {kind: model|tool, ...}", at))
    if (s[["kind"]] == "model") {
      if (length(setdiff(names(s), c("kind", "outputs", "message", "request", "calls_field"))) || !is_obj(get_key(s, "outputs")))
        refuse("turn-invalid", sprintf("%s: a model step is {kind, outputs, message?, request?, calls_field?}", at))
      msg <- get_key(s, "message")
      if (!is.null(msg)) { msg <- as_message(msg); for (p in msg[["parts"]]) validate_response_part(p) }
      steps[[length(steps) + 1L]] <- model_step(s[["outputs"]], msg, get_key(s, "request"), get_key(s, "calls_field"))
    } else {
      if (length(setdiff(names(s), c("kind", "id", "name", "output", "children"))) ||
          !all(vapply(c("id", "name"), function(k) is_str(get_key(s, k)) && nzchar(s[[k]]), TRUE)))
        refuse("turn-invalid", sprintf("%s: a tool step is {kind, id, name, output, children?}", at))
      kids <- get_key(s, "children") %||% list()
      children <- lapply(seq_along(kids), function(j) turn_from_list(kids[[j]], sprintf("%s.children[%d]", at, j - 1L)))
      steps[[length(steps) + 1L]] <- tool_step(s[["id"]], s[["name"]], output_parts(get_key(s, "output", list())), children)
    }
  }
  meta <- get_key(data, "meta") %||% jobj()
  if (!is_obj(meta)) refuse("turn-invalid", sprintf("%s.meta: an object", where))
  new_turn_record(sig, ins, steps, if (is.null(outs)) NULL else as_obj(outs), get_key(data, "score"), meta)
}

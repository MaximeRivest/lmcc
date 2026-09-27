# Transports (kernel section 6): how a meaning travels, as data.

TKEYS <- c("when", "requires", "in_template", "tell", "request_settings", "put", "written_as", "find", "spelling")
PRED_KEYS <- c("capability", "not", "all", "any")
TO_RE <- "^@purpose(\\.[A-Za-z_][A-Za-z0-9_]*)?$"
PUT_RE <- "^(request\\.[a-z_][a-z0-9_.]*|message:(system|developer|user|assistant))$"
FROM_RE <- "^(text|part:[a-z_]+)$"
LM15_CONFIG_FIELDS <- c("max_tokens", "temperature", "top_p", "top_k", "stop", "response_format", "tool_choice", "reasoning", "cache",
                        "seed", "frequency_penalty", "presence_penalty", "service_tier", "user_id", "store", "logprobs", "probabilities", "extensions")

malformed <- function(path, hint) refuse("entry-malformed", hint, fix = jobj(action = "edit-entry", path = path))

validate_setting_path <- function(path, where) {
  seg <- strsplit(path, ".", fixed = TRUE)[[1]]
  ok <- seg[[1]] == "tools" || (seg[[1]] == "config" && length(seg) >= 2L && seg[[2]] %in% LM15_CONFIG_FIELDS)
  if (!ok) malformed(where, sprintf("%s: %s is not a field of an lm15 request \u2014 request settings 'config.<field>' (%s) or 'tools'; provider-native knobs go under config.extensions",
                                    where, pyrepr(path), paste(ssort(LM15_CONFIG_FIELDS), collapse = ", ")))
}

setting_leaves <- function(settings, prefix = "") {
  out <- list()
  for (k in names(settings)) {
    v <- settings[[k]]
    if (k == "config" && !nzchar(prefix) && is_obj(v)) out <- c(out, setting_leaves(v, "config."))
    else out[[length(out) + 1L]] <- list(paste0(prefix, k), v)
  }
  out
}

#' A transport
#'
#' A transport as data (section 6); [transport_from_list()] reads the
#' artifact form. Named with [use_vocab()] instead when registered.
#' @param when A predicate over capability facts, or `NULL`.
#' @param requires Capability facts it needs.
#' @param in_template Whether the field stays in the template.
#' @param tell Text appended to messages, by role.
#' @param request_settings Partial lm15 request settings.
#' @param put Where fields go instead of a slot (`@purpose` to `request.<key>` or `message:<role>`).
#' @param find Find rules.
#' @param spelling How past calls, results and values are written.
#' @param written_as A put's own format, by target.
#' @param choose Alternatives: `list(when = predicate, use = transport)`, last `list(else_ = transport)`.
#' @export
new_transport <- function(when = NULL, requires = character(0), in_template = TRUE, tell = jobj(), request_settings = jobj(),
                          put = jobj(), find = list(), spelling = jobj(), written_as = jobj(), choose = NULL) {
  structure(list(when = when, requires = requires, in_template = in_template, tell = as_obj(tell), request_settings = as_obj(request_settings),
                 put = as_obj(put), find = find, spelling = as_obj(spelling), written_as = as_obj(written_as), choose = choose), class = "lmcc_transport")
}
is_transport <- function(x) inherits(x, "lmcc_transport")

transport_to_list <- function(t) {
  if (!is.null(t$choose)) return(jobj(choose = lapply(t$choose, function(a) if (!is.null(a$else_)) jobj(`else` = transport_to_list(a$else_)) else jobj(when = a$when, use = transport_to_list(a$use)))))
  d <- jobj()
  if (!is.null(t$when)) d[["when"]] <- t$when
  if (length(t$requires)) d[["requires"]] <- as.list(t$requires)
  if (!t$in_template) d[["in_template"]] <- FALSE
  if (length(t$tell)) d[["tell"]] <- t$tell
  if (length(t$request_settings)) d[["request_settings"]] <- t$request_settings
  if (length(t$put)) d[["put"]] <- t$put
  if (length(t$written_as)) d[["written_as"]] <- t$written_as
  if (length(t$find)) d[["find"]] <- t$find
  if (length(t$spelling)) d[["spelling"]] <- t$spelling
  d
}

as_list_py <- function(x) if (is.null(x)) list() else if (is_obj(x)) as.list(names(x)) else if (is.list(x)) x else if (is_str(x)) as.list(strsplit(x, "")[[1]]) else list(x)
as_dict_py <- function(x, where, key) {
  if (is.null(x)) return(jobj())
  if (!is_obj(x)) malformed(paste0(where, ".", key), sprintf("%s.%s: must be an object", where, key))
  as_obj(x)
}

#' @rdname new_transport
#' @param data Transport data (the artifact form).
#' @param where The path named in refusals.
#' @export
transport_from_list <- function(data, where = "transport") {
  if (is_transport(data)) { validate_transport(data, where); return(data) }
  if (!is_obj(data)) malformed(where, sprintf("%s: a transport is an object", where))
  if (has_key(data, "choose")) {
    ch <- data[["choose"]]
    if (length(data) != 1L || !is_arr(ch) || !length(ch)) malformed(where, sprintf("%s: choose is a non-empty list and stands alone", where))
    alts <- list()
    for (i in seq_along(ch)) {
      alt <- ch[[i]]; aw <- sprintf("%s.choose[%d]", where, i - 1L)
      if (!is_obj(alt)) malformed(aw, sprintf("%s: an alternative is an object", aw))
      if (has_key(alt, "else")) {
        if (length(alt) != 1L || i != length(ch)) malformed(aw, sprintf("%s: else stands alone and comes last", aw))
        alts[[length(alts) + 1L]] <- list(else_ = transport_from_list(alt[["else"]], aw))
      } else if (identical(ssort(names(alt)), c("use", "when"))) {
        validate_predicate(alt[["when"]], paste0(aw, ".when"))
        alts[[length(alts) + 1L]] <- list(when = alt[["when"]], use = transport_from_list(alt[["use"]], aw))
      } else malformed(aw, sprintf("%s: an alternative is {when, use} or {else}", aw))
    }
    return(new_transport(choose = alts))
  }
  unknown <- setdiff(names(data), TKEYS)
  if (length(unknown)) malformed(where, sprintf("%s: unknown transport key(s) %s; known keys are %s", where, sorted_repr(unknown), pyrepr(as.list(TKEYS))))
  if (has_key(data, "spelling") && !is_obj(data[["spelling"]])) malformed(paste0(where, ".spelling"), sprintf("%s.spelling: must be an object", where))
  find <- as_list_py(get_key(data, "find"))
  for (i in seq_along(find)) if (!is_obj(find[[i]])) malformed(sprintf("%s.find[%d]", where, i - 1L), sprintf("%s.find[%d]: a rule is an object", where, i - 1L))
  t <- new_transport(when = get_key(data, "when"), requires = as_list_py(get_key(data, "requires")),
                     in_template = pytruthy(if (has_key(data, "in_template")) data[["in_template"]] else TRUE),
                     tell = as_dict_py(get_key(data, "tell"), where, "tell"), request_settings = as_dict_py(get_key(data, "request_settings"), where, "request_settings"),
                     put = as_dict_py(get_key(data, "put"), where, "put"), find = lapply(find, as_obj),
                     spelling = as_dict_py(get_key(data, "spelling"), where, "spelling"), written_as = as_dict_py(get_key(data, "written_as"), where, "written_as"))
  validate_transport(t, where)
  t
}

validate_transport <- function(t, where) {
  if (!is.null(t$choose)) {
    for (i in seq_along(t$choose)) {
      a <- t$choose[[i]]
      if (!is.null(a$when)) validate_predicate(a$when, sprintf("%s.choose[%d].when", where, i - 1L))
      validate_transport(a$else_ %||% a$use, sprintf("%s.choose[%d]", where, i - 1L))
    }
    return(invisible())
  }
  if (!is.null(t$when)) validate_predicate(t$when, paste0(where, ".when"))
  for (i in seq_along(t$requires)) {
    fact <- t$requires[[i]]
    if (!(is_str(fact) && fact %in% CAPABILITY_FACTS)) malformed(sprintf("%s.requires[%d]", where, i - 1L),
      sprintf("%s.requires: %s is not a capability fact; known: %s", where, pyrepr(fact), sorted_repr(CAPABILITY_FACTS)))
  }
  for (i in seq_along(t$find)) validate_find_rule(t$find[[i]], sprintf("%s.find[%d]", where, i - 1L))
  for (target in names(t$put)) {
    place <- t$put[[target]]
    if (!grepl(TO_RE, target, perl = TRUE) || !is_str(place) || !grepl(PUT_RE, place, perl = TRUE))
      malformed(paste0(where, ".put"), sprintf("%s.put: %s: %s \u2014 a put is '@purpose' or '@purpose.<sub>' \u2192 'request.<key>' or 'message:<role>'", where, pyrepr(target), pyrepr(place)))
  }
  for (leaf in setting_leaves(t$request_settings)) validate_setting_path(leaf[[1]], sprintf("%s.request_settings[%s]", where, pyrepr(leaf[[1]])))
  for (place in t$put) if (startsWith(place, "request.")) validate_setting_path(substring(place, 9L), paste0(where, ".put"))
  for (target in names(t$written_as)) {
    nm <- t$written_as[[target]]
    if (!has_key(t$put, target) || !is_str(nm) || !nzchar(nm)) malformed(paste0(where, ".written_as"), sprintf("%s.written_as: %s must name a placed field and a format name", where, pyrepr(target)))
  }
  validate_spelling(t$spelling, paste0(where, ".spelling"))
  for (k in names(t$tell)) if (!(k %in% c("system", "developer", "user", "assistant")) || !is_str(t$tell[[k]]))
    malformed(paste0(where, ".tell"), sprintf("%s.tell: %s must name a message role, text", where, pyrepr(k)))
  if (!t$in_template && !length(t$find) && !length(t$put))
    malformed(where, sprintf("%s: in_template=false but no rule or put serves the field \u2014 the value would be unrecoverable", where))
}

select_transport <- function(t, caps, purpose, name) {
  s <- t
  while (!is.null(s$choose)) {
    chosen <- NULL
    for (a in s$choose) if (!is.null(a$else_) || eval_predicate(a$when, caps)) { chosen <- a$else_ %||% a$use; break }
    if (is.null(chosen)) refuse("capability-missing", sprintf("purpose %s: transport %s: no alternative of 'choose' holds for the declared capabilities and there is no else", pyrepr(purpose), pyrepr(name)),
                                fix = jobj(action = "satisfy-predicate", purpose = purpose, predicate = jobj(any = lapply(s$choose, function(a) a$when))))
    s <- chosen
  }
  if (!is.null(s$when) && !eval_predicate(s$when, caps))
    refuse("capability-missing", sprintf("purpose %s: transport %s: 'when' %s is false for the declared capabilities", pyrepr(purpose), pyrepr(name), pyrepr(s$when)),
           fix = jobj(action = "satisfy-predicate", purpose = purpose, predicate = s$when))
  for (fact in s$requires) if (!pytruthy(get_key(caps, fact)))
    refuse("capability-missing", sprintf("purpose %s: transport %s requires capability %s, which the model does not declare", pyrepr(purpose), pyrepr(name), pyrepr(fact)),
           fix = jobj(action = "declare-capability", fact = fact))
  s
}

bound_transport <- function(t, field_name) {
  t$tell <- as_obj(lapply(t$tell, function(v) gsub("{field}", field_name, v, fixed = TRUE)))
  t
}

write_slots <- function(template) {
  out <- character(0); i <- 0L; n <- blen(template)
  while (i < n) {
    if (bstarts(template, "{{", i) || bstarts(template, "}}", i)) { i <- i + 2L; next }
    c <- bchar(template, i)
    if (c == "{") {
      j <- bfind(template, "}", i)
      if (j < 0L) return("?")
      out <- c(out, bsl(template, i + 1L, j)); i <- j + 1L; next
    }
    if (c == "}") return("?")
    i <- i + 1L
  }
  out
}

validate_spelling <- function(sp, where) {
  valid <- is_obj(sp)
  if (valid) {
    valid <- all(names(sp) %in% c("call", "result", "input_format", "probe", "value", "position"))
    valid <- valid && all(vapply(c("call", "result"), function(k) !has_key(sp, k) || is_str(sp[[k]]), TRUE))
    if (has_key(sp, "value")) { w <- sp[["value"]]; valid <- valid && (is.null(w) || (is_str(w) && identical(write_slots(w), "value"))) }
    if (has_key(sp, "position")) valid <- valid && isTRUE(sp[["position"]] %in% c("before", "after"))
    if (has_key(sp, "input_format")) {
      ref <- sp[["input_format"]]
      valid <- valid && has_key(sp, "call") && is_obj(ref) && all(names(ref) %in% c("use", "options")) &&
        is_str(get_key(ref, "use")) && nzchar(ref[["use"]]) && is_obj(get_key(ref, "options", jobj()))
    }
    if (has_key(sp, "probe")) {
      pr <- sp[["probe"]]
      id <- if (is_obj(pr) && has_key(pr, "id")) pr[["id"]] else "probe"
      valid <- valid && has_key(sp, "call") && is_obj(pr) && all(names(pr) %in% c("id", "name", "input")) &&
        is_str(get_key(pr, "name")) && nzchar(pr[["name"]]) && is_obj(get_key(pr, "input")) && is_str(id) && nzchar(id)
    }
  }
  if (!valid) malformed(where, sprintf("%s: expected call/result text, input_format {use, options?}, probe {name, input: object, id?} (formatter and probe require call), value (text with one {value} slot, or null) and position (before|after)", where))
}

#' Kernel section 6 spelling: the closed slot set, {{ }} escapes.
#' @noRd
spell_turn <- function(template, slots) {
  out <- character(0); i <- 0L; n <- blen(template); run <- 0L
  flush <- function(to) if (to > run) out <<- c(out, bsl(template, run, to))
  while (i < n) {
    c <- bchar(template, i)
    if (c == "{" && bstarts(template, "{{", i)) { flush(i); out <- c(out, "{"); i <- i + 2L; run <- i; next }
    if (c == "}" && bstarts(template, "}}", i)) { flush(i); out <- c(out, "}"); i <- i + 2L; run <- i; next }
    if (c == "{") {
      j <- bfind(template, "}", i)
      name <- if (j > i) bsl(template, i + 1L, j) else ""
      if (nzchar(name) && name %in% names(slots)) { flush(i); out <- c(out, slots[[name]]); i <- j + 1L; run <- i; next }
    }
    i <- i + 1L
  }
  flush(n)
  paste(out, collapse = "")
}

validate_find_rule <- function(r, where) {
  if (!is_obj(r)) malformed(where, sprintf("%s: a rule is an object", where))
  src <- get_key(r, "from"); to <- get_key(r, "to")
  if (!is_str(src) || !grepl(FROM_RE, src, perl = TRUE)) malformed(where, sprintf("%s: 'from' is 'text' or 'part:<part kind>'", where))
  if (!is_str(to) || !grepl(TO_RE, to, perl = TRUE)) malformed(where, sprintf("%s: 'to' is '@purpose' or '@purpose.<sub>'", where))
  unknown <- setdiff(names(r), c("from", "to", "remove", "between", "pattern", "line_prefixed", "complete_reply", "repair"))
  if (length(unknown)) malformed(where, sprintf("%s: unknown rule key(s) %s", where, sorted_repr(unknown)))
  kinds <- intersect(c("between", "pattern", "line_prefixed"), names(r))
  if (src == "text") {
    if (length(kinds) != 1L) malformed(where, sprintf("%s: a text rule needs exactly one of between/pattern/line_prefixed", where))
    v <- r[[kinds]]
    if (kinds == "between") {
      if (!(is_arr(v) && length(v) == 2L && all(vapply(v, function(x) is_str(x) && nzchar(x), TRUE)))) malformed(where, sprintf("%s: between is [open, close], non-empty strings", where))
    } else if (!is_str(v) || !nzchar(v)) malformed(where, sprintf("%s: %s is a non-empty string", where, kinds))
  }
  if (has_key(r, "repair") && (!is_bool(r[["repair"]]) || src != "text" || !has_key(r, "between")))
    malformed(where, sprintf("%s: 'repair' is true or false, on a between rule only (its delimiters are repaired like markers, kernel \u00a74a)", where))
  if (src != "text" && (length(kinds) || pytruthy(get_key(r, "remove")))) malformed(where, sprintf("%s: a channel rule takes no text extractor and no remove", where))
}

validate_predicate <- function(p, where) {
  if (!is_obj(p) || length(p) != 1L) malformed(where, sprintf("%s: a predicate is one of %s, one key", where, pyrepr(as.list(PRED_KEYS))))
  key <- names(p)[[1]]; value <- p[[1]]
  if (key == "capability") {
    if (is_str(value) && !(value %in% CAPABILITY_FACTS)) malformed(where, sprintf("%s: %s is not a capability fact; known: %s", where, pyrepr(value), sorted_repr(CAPABILITY_FACTS)))
    if (!is_str(value)) malformed(where, sprintf("%s: 'capability' names a fact", where))
  } else if (key == "not") validate_predicate(value, paste0(where, ".not"))
  else if (key %in% c("all", "any")) {
    if (!is_arr(value)) malformed(where, sprintf("%s: %s takes a list", where, pyrepr(key)))
    for (j in seq_along(value)) validate_predicate(value[[j]], sprintf("%s.%s[%d]", where, key, j - 1L))
  } else malformed(where, sprintf("%s: unknown predicate key %s; known: %s", where, pyrepr(key), pyrepr(as.list(PRED_KEYS))))
}

eval_predicate <- function(p, caps) {
  key <- names(p)[[1]]; value <- p[[1]]
  if (key == "capability") return(pytruthy(get_key(caps, value)))
  if (key == "not") return(!eval_predicate(value, caps))
  if (key == "all") return(all(vapply(value, eval_predicate, TRUE, caps = caps)))
  any(vapply(value, eval_predicate, TRUE, caps = caps))
}

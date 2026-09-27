# The neutral core (kernel sections 1, 3, 5, 7): shapes, values, parts,
# captures, responses. Messages and parts are lm15 canonical JSON.

SCALAR_TYPES <- c("string", "integer", "number", "boolean")
CAPABILITY_FACTS <- c("instruct", "completion", "native_reasoning", "native_function_calling",
                      "native_citations", "native_structured_output", "image_input", "stop_sequences", "assistant_prefill")

new_field <- function(name, direction, shape, type = NULL, purpose = "plain", desc = NULL) {
  structure(list(name = name, direction = direction, shape = shape, type = type, purpose = purpose, desc = desc), class = "lmcc_field")
}

#' Kernel section 1: a nullable scalar/enum shape is that shape plus null.
#' @noRd
nullable_base <- function(shape) {
  t <- get_key(shape, "type")
  if (is.list(t) || (is.character(t) && length(t) > 1L)) {
    tt <- unlist(t)
    others <- tt[tt != "null"]
    if ("null" %in% tt && length(others) == 1L && length(tt) == 2L) {
      base <- drop_key(shape, "type")
      base[["type"]] <- others[[1]]
      return(list(base, TRUE))
    }
    return(list(shape, FALSE))
  }
  alts <- get_key(shape, "anyOf")
  if (is_arr(alts) && length(alts) == 2L && length(shape) == 1L) {
    isnull <- vapply(alts, function(a) is_obj(a) && json_equal(a, jobj(type = "null")), TRUE)
    others <- alts[!isnull]
    if (sum(isnull) == 1L && length(others) == 1L && is_obj(others[[1]])) {
      base <- others[[1]]
      if (has_key(base, "enum") || isTRUE(get_key(base, "type") %in% SCALAR_TYPES)) return(list(base, TRUE))
    }
  }
  list(shape, FALSE)
}

shape_summary <- function(shape) {
  base <- nullable_base(shape)[[1]]
  if (has_key(base, "enum")) return(paste0("one of: ", paste(vapply(base[["enum"]], pystr, ""), collapse = ", ")))
  if (has_key(base, "media")) return(paste0("(", pystr(base[["media"]]), ")"))
  t <- get_key(base, "type")
  if (is_str(t) && t %in% c("integer", "number", "boolean")) return(paste0("(", t, ")"))
  ""
}

is_media <- function(shape) has_key(shape, "media")

in_enum <- function(members, v) any(vapply(members, function(m) json_equal(m, v), TRUE))

#' Kernel section 7a, writing.
#' @noRd
spell_value <- function(shape, value, where, field = NULL) {
  nb <- nullable_base(shape); base <- nb[[1]]; nullable <- nb[[2]]
  if (is.null(value)) {
    if (nullable) return("null")
    refuse("value-invalid", sprintf("%s: null is not allowed by the shape", where))
  }
  if (is.factor(value) && length(value) == 1L) value <- as.character(value)
  if (has_key(base, "enum")) {
    if (is_bool(value) || !in_enum(base[["enum"]], value))
      refuse("value-invalid", sprintf("%s: value %s is not one of %s", where, pyrepr(value), pyrepr(base[["enum"]])))
    return(pystr(value))
  }
  t <- get_key(base, "type")
  if (identical(t, "string")) {
    if (is_str(value)) return(value)
    if (is_bool(value)) return(if (value) "true" else "false")
    if (is_num(value)) return(format_number(value))
    refuse("value-invalid", sprintf("%s: %s is not text", where, pyrepr(value)))
  }
  if (identical(t, "integer")) {
    if (!is_int_value(value)) refuse("value-invalid", sprintf("%s: %s is not an integer", where, pyrepr(value)))
    v <- num_value(value)
    return(if (is.double(v)) sprintf("%.0f", v) else num_text(v))
  }
  if (identical(t, "number")) {
    if (!is_num(value)) refuse("value-invalid", sprintf("%s: %s is not a number", where, pyrepr(value)))
    return(format_number(value))
  }
  if (identical(t, "boolean")) {
    if (!is_bool(value)) refuse("value-invalid", sprintf("%s: %s is not a boolean", where, pyrepr(value)))
    return(if (value) "true" else "false")
  }
  if (is_str(value)) return(value)
  refuse("no-format", sprintf("%s: value of type %s has no format bound and is not a scalar \u2014 bind a format for this field", where, typename_of(value)),
         fix = jobj(action = "bind-format", field = field %||% where, key = format_key(NULL, shape)))
}

#' Kernel section 7a, reading.
#' @noRd
read_value <- function(shape, text, where) {
  nb <- nullable_base(shape); base <- nb[[1]]
  if (nb[[2]] && wstrip(text) == "null") return(NULL)
  if (has_key(base, "enum")) {
    s <- wstrip(text)
    for (v in base[["enum"]]) if (identical(pystr(v), s)) return(v)
    refuse("parse-value", sprintf("%s: %s is not one of %s", where, pyrepr(s), pyrepr(base[["enum"]])))
  }
  t <- get_key(base, "type")
  if (identical(t, "integer")) return(read_integer(text, where))
  if (identical(t, "number")) return(read_number(text, where))
  if (identical(t, "boolean")) return(read_boolean(text, where))
  text
}

QUOTES <- c('"', "'", "`")

#' Kernel section 7a forgiving reads, after the exact read refused.
#' @noRd
forgive_value <- function(shape, text, where) {
  nb <- nullable_base(shape); base <- nb[[1]]; nullable <- nb[[2]]
  unquote <- function(s) {
    n <- blen(s)
    if (n >= 2L && bchar(s, 0L) %in% QUOTES && bchar(s, n - 1L) == bchar(s, 0L)) wstrip(bsl(s, 1L, n - 1L)) else s
  }
  unperiod <- function(s) if (endsWith(s, ".") && !endsWith(s, "..")) wstrip(bsl(s, 0L, blen(s) - 1L)) else s
  t <- wstrip(text)
  t1 <- unquote(t); t2 <- unperiod(t1); t3 <- unquote(unperiod(t))
  texts <- unique(c(t1, t2, t3))
  for (c in texts) {
    if (c == t || !nzchar(c)) next
    r <- tryCatch(list(read_value(shape, c, where)), lmcc_refusal = function(e) NULL)
    if (!is.null(r)) return(r[[1]])
  }
  for (c in texts) {
    low <- ascii_lower(c)
    if (nullable && low %in% c("null", "none")) return(NULL)
    if (has_key(base, "enum")) {
      hits <- Filter(function(v) is_str(v) && ascii_lower(v) == low, base[["enum"]])
      if (length(hits) == 1L) return(hits[[1]])
    }
  }
  read_value(shape, text, where)
}

#' The structural keys a shape answers to, most specific first (section 5).
#' @noRd
structural_keys <- function(shape) {
  base <- nullable_base(shape)[[1]]
  if (is_media(base)) return(c(paste0("media:", pystr(base[["media"]])), "media:*"))
  if (has_key(base, "enum")) return("enum")
  t <- get_key(base, "type")
  if (is_str(t) && t %in% SCALAR_TYPES) return(t)
  if (identical(t, "array")) {
    items <- get_key(base, "items")
    items <- if (pytruthy(items)) items else jobj()
    inner <- if (is_obj(items)) structural_keys(items) else character(0)
    inner <- inner[!startsWith(inner, "media")]
    return(c(if (length(inner)) paste0("list[", inner, "]") else character(0), "list[*]"))
  }
  if (identical(t, "object")) return("object")
  character(0)
}

format_key <- function(type, shape) {
  if (!is.null(type) && nzchar(type)) return(type)
  k <- structural_keys(shape)
  if (length(k)) k[[1]] else "*"
}

# ------------------------------------------------------------ parts, captures

textpart <- function(text) jobj(type = "text", text = text)

new_capture <- function(parts, text = NULL) structure(list(parts = parts, text_override = text), class = "lmcc_capture")
capture_of_text <- function(t) new_capture(list(textpart(t)))

#' The text of a capture
#'
#' Its text-bearing parts, each stripped, joined by newlines (section 6); a
#' reader capture holding non-text parts keeps its section's text (section 4b).
#' @param c A capture.
#' @export
capture_text <- function(c) {
  if (!is.null(c$text_override)) return(c$text_override)
  ts <- vapply(Filter(function(p) is_str(get_key(p, "text")), c$parts), function(p) wstrip(p[["text"]]), "")
  paste(ts, collapse = "\n")
}
capture_parts_of <- function(c, type) Filter(function(p) identical(get_key(p, "type"), type), c$parts)

as_parts <- function(written, where) {
  if (is_str(written)) return(list(textpart(written)))
  if (is.list(written) && !is_obj(written) && all(vapply(written, function(p) is_obj(p) && has_key(p, "type"), TRUE))) return(unname(written))
  refuse("format-write-error", sprintf("%s: write must return text or a list of parts, got %s", where, typename_of(written)))
}

make_message <- function(role, parts) jobj(role = role, parts = parts)

merge_text_parts <- function(parts) {
  out <- list()
  for (p in parts) {
    if (identical(get_key(p, "type"), "text")) {
      if (!nzchar(get_key(p, "text", ""))) next
      n <- length(out)
      if (n && identical(get_key(out[[n]], "type"), "text")) {
        out[[n]] <- textpart(paste0(out[[n]][["text"]], p[["text"]]))
        next
      }
    }
    out[[length(out) + 1L]] <- p
  }
  out
}

validate_response_part <- function(part) {
  if (!is_obj(part) || !is_str(get_key(part, "type")))
    refuse("response-malformed", "response part must be an object with a string 'type' (an lm15 part)")
  if (has_key(part, "text") && !is_str(part[["text"]])) refuse("response-malformed", "a response part's 'text' must be text")
  if (identical(part[["type"]], "data") && !has_key(part, "value"))
    refuse("response-malformed", "a data part carries a 'value' (lm15 DataPart), even when it is null")
  invisible(TRUE)
}

data_text <- function(value) json_text(value, code = "response-malformed")

part_text <- function(part) {
  t <- get_key(part, "type")
  if (identical(t, "text")) return(get_key(part, "text", ""))
  if (identical(t, "data")) return(data_text(part[["value"]]))
  ""
}

message_of <- function(response) if (is_obj(response) && is_obj(get_key(response, "message"))) response[["message"]] else response

reply_probabilities <- function(response) {
  message <- message_of(response)
  parts <- if (is_obj(message)) get_key(message, "parts") else NULL
  probabilities <- jobj(); measured <- jobj()
  for (part in if (is_arr(parts)) parts else list()) {
    if (!is_obj(part) || !identical(get_key(part, "type"), "data")) next
    dist <- get_key(part, "probabilities"); method <- get_key(part, "method")
    if (is.null(dist) && is.null(method)) next
    if (is.null(dist) || is.null(method)) refuse("response-malformed", "a data part's 'probabilities' and 'method' come together (lm15 INV-052)")
    if (!is_str(method) || !is_obj(dist)) refuse("response-malformed", "a data part's 'method' is text and its 'probabilities' an object {field: {key: p}}")
    for (field in names(dist)) {
      keys <- dist[[field]]
      ok <- is_obj(keys) && all(vapply(keys, function(p) is_num(p) && { v <- num_value(p); !is_bigint(v) && v >= 0 && v <= 1 }, TRUE))
      if (!ok) refuse("response-malformed", sprintf("probabilities for %s must map each answer key to a number in [0, 1]", pyrepr(field)))
      if (has_key(probabilities, field))
        refuse("parse-ambiguous", sprintf("two data parts carry probabilities for %s \u2014 refusing to guess which measured the answer", pyrepr(field)))
      probabilities[[field]] <- as_obj(keys)
      measured[[field]] <- method
    }
  }
  list(probabilities, measured)
}

normalize_response_parts <- function(parts) {
  out <- list(); texts <- character(0)
  for (part in parts) {
    validate_response_part(part)
    part <- as_obj(part)
    has_text <- is_str(get_key(part, "text"))
    n <- length(out)
    if (has_text && length(texts) && identical(out[[n]][["type"]], part[["type"]])) {
      texts <- c(texts, part[["text"]])
      for (k in setdiff(names(part), c("type", "text"))) out[[n]] <- set_key(out[[n]], k, part[[k]])
      next
    }
    if (length(texts)) out[[n]][["text"]] <- paste(texts, collapse = "")
    out[[length(out) + 1L]] <- part
    texts <- if (has_text) part[["text"]] else character(0)
  }
  if (length(texts)) out[[length(out)]][["text"]] <- paste(texts, collapse = "")
  out
}

finish_reason_of <- function(response) {
  if (is_obj(response) && is_obj(get_key(response, "message"))) {
    r <- get_key(response, "finish_reason")
    return(if (is_str(r)) r else NULL)
  }
  NULL
}

response_text_and_parts <- function(response) {
  if (is_str(response)) return(list(response, list()))
  message <- message_of(response)
  if (is_obj(message) && is_arr(get_key(message, "parts"))) {
    parts <- normalize_response_parts(message[["parts"]])
    return(list(paste(vapply(parts, part_text, ""), collapse = ""), parts))
  }
  refuse("response-malformed", "response must be text, an lm15 message {role, parts}, or an lm15 response {message: ...}")
}

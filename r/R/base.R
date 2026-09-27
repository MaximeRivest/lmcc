# Foundations: refusals, JSON values (reading and the kernel's one writer),
# byte-offset strings, the section 7a text rules, the reference's repr.
#
# JSON in R: an object is a named list (an empty one keeps names =
# character(0)), an array an unnamed list, null is NULL (kept in lists with
# x[k] <- list(NULL)), a string character(1), true/false logical(1), an
# integer integer(1) within 32 bits, a whole double up to 2^53, and beyond
# that an "lmcc_int" decimal string (the contract requires at least int64;
# base R has no 64-bit integer). lm15's classed objects, arrays and numbers
# are read as the same values, so the lm15 bridge passes JSON straight in.
#
# Positions are 0-based byte offsets with exclusive ends: character offsets
# in R are quadratic on non-ASCII text, and every marker is a whole UTF-8
# sequence, so a byte search never matches inside a character.

#' @useDynLib lmcc, .registration = TRUE
NULL

# ------------------------------------------------------------------ refusals

#' A refusal
#'
#' Every failure in lmcc is a condition of class `lmcc_refusal` with a stable
#' `code` (contract/spec/errors.md), a `hint` naming the offender, a `fix` (the
#' next action as data, on every refusal before render) and, for parse
#' refusals, a `partial` with what was read. Catch it with
#' `tryCatch(..., lmcc_refusal = function(e) e$code)`.
#' @param code,hint The stable code and the human hint.
#' @param fix,partial Named lists, or `NULL`.
#' @export
refusal <- function(code, hint, fix = NULL, partial = NULL) {
  structure(class = c("lmcc_refusal", "error", "condition"),
            list(message = paste0("[", code, "] ", hint), call = NULL, code = code, hint = hint, fix = fix, partial = partial))
}

refuse <- function(code, hint, fix = NULL, partial = NULL) stop(refusal(code, hint, fix, partial))

#' @rdname refusal
#' @param x Any value.
#' @export
is_refusal <- function(x) inherits(x, "lmcc_refusal")

#' @rdname refusal
#' @param r A refusal.
#' @export
describe_refusal <- function(r) jobj(code = r$code, hint = r$hint, fix = r$fix, partial = r$partial)

# ------------------------------------------------------------ JSON values

#' JSON objects and arrays that stay distinct when empty
#' @param ... Members (named for an object) or elements.
#' @export
jobj <- function(...) {
  x <- list(...)
  if (!length(x)) names(x) <- character(0)
  x
}

#' @rdname jobj
#' @export
jarr <- function(...) unname(list(...))

as_obj <- function(x) {
  if (is.null(x)) return(jobj())
  x <- unclass_json(x)
  if (!length(x)) names(x) <- character(0)
  x
}

unclass_json <- function(x) {
  if (inherits(x, c("lm15_json_object", "lm15_json_array", "lmcc_object", "lmcc_array"))) {
    n <- names(x)
    x <- unclass(x)
    attributes(x) <- NULL
    if (!is.null(n)) names(x) <- n
  }
  x
}

is_obj <- function(x) is.list(x) && !is_num(x) && (inherits(x, c("lm15_json_object", "lmcc_object")) ||
  (!inherits(x, c("lm15_json_array", "lmcc_array")) && !is.null(names(x))))
is_arr <- function(x) is.list(x) && !is_obj(x) && !inherits(x, "lm15_value")
is_bigint <- function(x) inherits(x, c("lmcc_int", "lm15_integer"))
is_num <- function(x) {
  if (inherits(x, c("lmcc_int", "lm15_integer", "lm15_json_number"))) return(TRUE)
  (is.integer(x) || is.double(x)) && !is.object(x) && length(x) == 1L && !is.na(x)
}
is_str <- function(x) is.character(x) && length(x) == 1L && !is.na(x)
is_bool <- function(x) is.logical(x) && length(x) == 1L && !is.na(x)
is_int_value <- function(x) {
  if (is_bigint(x)) return(TRUE)
  if (inherits(x, "lm15_json_number")) return(grepl("^-?[0-9]+$", unclass(x)))
  is.integer(x) && length(x) == 1L && !is.na(x) || (is.double(x) && length(x) == 1L && is.finite(x) && x == trunc(x) && !is.object(x))
}

has_key <- function(x, k) !is.null(names(x)) && k %in% names(x)
get_key <- function(x, k, default = NULL) if (has_key(x, k)) x[[k]] else default
set_key <- function(x, k, v) {
  if (is.null(v)) x[k] <- list(NULL) else x[[k]] <- v
  x
}
drop_key <- function(x, k) {
  if (has_key(x, k)) x <- x[names(x) != k]
  if (!length(x)) names(x) <- character(0)
  x
}
`%||%` <- function(a, b) if (is.null(a)) b else a

#' A decimal integer's text as a value: integer within 32 bits, a whole
#' double up to 2^53, else an exact "lmcc_int" decimal.
#' @noRd
integer_value <- function(t) {
  neg <- startsWith(t, "-")
  digits <- sub("^-?0*", "", t)
  if (!nzchar(digits)) return(0L)
  if (nchar(digits) <= 9) return(as.integer(t))
  if (nchar(digits) <= 15 || (nchar(digits) == 16 && digits <= "9007199254740991")) {
    v <- parse_f64(t)
    if (abs(v) <= .Machine$integer.max) return(as.integer(v))
    return(v)
  }
  structure(paste0(if (neg) "-" else "", digits), class = "lmcc_int")
}

#' @export
print.lmcc_int <- function(x, ...) cat(unclass(x), "\n")

parse_f64 <- function(t) .Call(lmcc_strtod, t)

num_value <- function(x) {
  if (inherits(x, "lm15_json_number")) {
    t <- unclass(x)
    return(if (grepl("^-?[0-9]+$", t)) integer_value(t) else parse_f64(t))
  }
  if (inherits(x, "lm15_integer")) return(integer_value(unclass(x)))
  x
}

num_text <- function(x) {
  x <- num_value(x)
  if (is_bigint(x)) return(unclass(x)[[1]])
  if (is.integer(x)) return(as.character(x))
  format_number(x)
}

#' JSON equality as the reference compares values: objects unordered,
#' numbers by value, TRUE == 1 as in Python.
#' @noRd
json_equal <- function(a, b) {
  numlike <- function(x) is_num(x) || is_bool(x)
  if (numlike(a) || numlike(b)) {
    if (!numlike(a) || !numlike(b)) return(FALSE)
    a <- if (is_bool(a)) as.integer(a) else num_value(a)
    b <- if (is_bool(b)) as.integer(b) else num_value(b)
    if (is_bigint(a) || is_bigint(b)) return(identical(num_text(a), num_text(b)))
    return(isTRUE(a == b))
  }
  if (is.null(a) || is.null(b)) return(is.null(a) && is.null(b))
  if (is_obj(a) && is_obj(b)) {
    if (length(a) != length(b)) return(FALSE)
    for (k in names(a)) if (!has_key(b, k) || !json_equal(a[[k]], b[[k]])) return(FALSE)
    return(TRUE)
  }
  if (is_arr(a) && is_arr(b)) {
    if (length(a) != length(b)) return(FALSE)
    for (i in seq_along(a)) if (!json_equal(a[[i]], b[[i]])) return(FALSE)
    return(TRUE)
  }
  if (is.list(a) || is.list(b)) return(FALSE)
  identical(a, b)
}

# ------------------------------------------------------------------ reading

json_fail <- function(msg, pos) stop(structure(class = c("lmcc_json_error", "error", "condition"),
  list(message = sprintf("%s at %d", msg, pos), call = NULL)))

#' Strict RFC 8259 JSON
#'
#' Objects as named lists, arrays as unnamed lists, `null` as `NULL`,
#' integers exact (32-bit integer, a whole double to 2^53, else an
#' `lmcc_int` decimal), other numbers correctly rounded doubles.
#' @param text One string.
#' @param duplicates `"last"`, or `"reject"` to refuse a member named twice.
#' @export
parse_json <- function(text, duplicates = c("last", "reject")) {
  duplicates <- match.arg(duplicates)
  p <- json_parser(text, duplicates == "reject")
  v <- p$value(0L)
  p$ws()
  if (p$pos() < p$n) json_fail("trailing data", p$pos())
  v
}

#' One value starting exactly at 0-based byte `start`: list(value, end).
#' @noRd
parse_json_at <- function(text, start, duplicates = "last") {
  p <- json_parser(text, duplicates == "reject", start)
  v <- p$value(0L)
  list(v, p$pos())
}

json_parser <- function(text, reject, start = 0L) {
  bytes <- charToRaw(enc2utf8(text))
  n <- length(bytes)
  i <- start + 1L
  b <- function(k = i) if (k <= n) as.integer(bytes[[k]]) else -1L
  ws <- function() while (i <= n && b() %in% c(32L, 9L, 10L, 13L)) i <<- i + 1L
  str_at <- function(a, z) if (z < a) "" else { s <- rawToChar(bytes[a:z]); Encoding(s) <- "UTF-8"; s }
  value <- function(depth) {
    if (depth > 512L) json_fail("nesting too deep", i - 1L)
    ws()
    c <- b()
    if (c < 0L) json_fail("expected a value", i - 1L)
    if (c == 123L) return(object(depth))
    if (c == 91L) return(array(depth))
    if (c == 34L) return(string())
    if (c == 116L) return(literal("true", TRUE))
    if (c == 102L) return(literal("false", FALSE))
    if (c == 110L) return(literal("null", NULL))
    if (c == 45L || (c >= 48L && c <= 57L)) return(number())
    json_fail("unexpected character", i - 1L)
  }
  literal <- function(word, v) {
    w <- charToRaw(word)
    if (i + length(w) - 1L <= n && identical(bytes[i:(i + length(w) - 1L)], w)) { i <<- i + length(w); return(v) }
    json_fail("invalid literal", i - 1L)
  }
  digit <- function(k = i) { c <- b(k); c >= 48L && c <= 57L }
  number <- function() {
    s <- i
    if (b() == 45L) i <<- i + 1L
    if (b() == 48L) i <<- i + 1L
    else if (b() >= 49L && b() <= 57L) while (digit()) i <<- i + 1L
    else json_fail("invalid number", i - 1L)
    integral <- TRUE
    if (b() == 46L) {
      integral <- FALSE; i <<- i + 1L
      if (!digit()) json_fail("invalid number", i - 1L)
      while (digit()) i <<- i + 1L
    }
    if (b() %in% c(101L, 69L)) {
      integral <- FALSE; i <<- i + 1L
      if (b() %in% c(43L, 45L)) i <<- i + 1L
      if (!digit()) json_fail("invalid number", i - 1L)
      while (digit()) i <<- i + 1L
    }
    t <- str_at(s, i - 1L)
    if (integral) integer_value(t) else parse_f64(t)
  }
  string <- function() {
    i <<- i + 1L
    parts <- character(0)
    run <- i
    repeat {
      if (i > n) json_fail("unterminated string", i - 1L)
      c <- b()
      if (c == 34L) {
        parts <- c(parts, str_at(run, i - 1L))
        i <<- i + 1L
        out <- paste(parts, collapse = "")
        if (!validUTF8(out)) json_fail("invalid UTF-8", i - 1L)
        return(out)
      }
      if (c < 32L) json_fail("control character in string", i - 1L)
      if (c != 92L) { i <<- i + 1L; next }
      parts <- c(parts, str_at(run, i - 1L))
      e <- b(i + 1L)
      esc <- switch(rawToChar(as.raw(max(e, 1L))), '"' = '"', "\\" = "\\", "/" = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t", NULL)
      if (!is.null(esc)) {
        parts <- c(parts, esc)
        i <<- i + 2L
      } else if (e == 117L) {
        hex <- if (i + 5L <= n) rawToChar(bytes[(i + 2L):(i + 5L)]) else ""
        if (!grepl("^[0-9A-Fa-f]{4}$", hex)) json_fail("invalid \\u escape", i - 1L)
        u <- strtoi(hex, 16L)
        i <<- i + 6L
        if (u >= 0xD800 && u <= 0xDBFF && b() == 92L && b(i + 1L) == 117L && i + 5L <= n) {
          hex2 <- rawToChar(bytes[(i + 2L):(i + 5L)])
          l <- if (grepl("^[0-9A-Fa-f]{4}$", hex2)) strtoi(hex2, 16L) else -1L
          if (l >= 0xDC00 && l <= 0xDFFF) {
            u <- 0x10000 + (u - 0xD800) * 1024 + (l - 0xDC00)
            i <<- i + 6L
          }
        }
        if (u == 0L) json_fail("R strings cannot hold U+0000", i - 7L)
        parts <- c(parts, if (u >= 0xD800 && u <= 0xDFFF) "\uFFFD" else intToUtf8(u))
      } else {
        json_fail("invalid escape", i - 1L)
      }
      run <- i
    }
  }
  array <- function(depth) {
    i <<- i + 1L
    out <- list()
    ws()
    if (b() == 93L) { i <<- i + 1L; return(out) }
    repeat {
      v <- value(depth + 1L)
      out[length(out) + 1L] <- list(v)
      ws()
      c <- b()
      i <<- i + 1L
      if (c == 93L) return(out)
      if (c != 44L) { i <<- i - 1L; json_fail("expected ',' or ']'", i - 1L) }
    }
  }
  object <- function(depth) {
    i <<- i + 1L
    out <- jobj()
    ws()
    if (b() == 125L) { i <<- i + 1L; return(out) }
    repeat {
      ws()
      if (b() != 34L) json_fail("expected a member name", i - 1L)
      key <- string()
      ws()
      if (b() != 58L) json_fail("expected ':'", i - 1L)
      i <<- i + 1L
      v <- value(depth + 1L)
      if (has_key(out, key) && reject) json_fail(sprintf("duplicate member \"%s\"", key), i - 1L)
      out <- set_key(out, key, v)
      ws()
      c <- b()
      i <<- i + 1L
      if (c == 125L) return(out)
      if (c != 44L) { i <<- i - 1L; json_fail("expected ',' or '}'", i - 1L) }
    }
  }
  list(value = value, ws = ws, pos = function() i - 1L, n = n)
}

# ------------------------------------------------------------------ writing

#' Kernel section 7a number spelling (ECMAScript Number::toString)
#' @param x A finite number.
#' @param code The refusal code for a non-finite one.
#' @export
format_number <- function(x, code = "value-invalid") {
  x <- num_value(x)
  if (is_bigint(x)) return(unclass(x)[[1]])
  if (is.integer(x)) return(as.character(x))
  if (!is.finite(x)) refuse(code, sprintf("%s has no portable number spelling", format(x)))
  .Call(lmcc_format_number, as.double(x))
}

#' A JSON string: `"`, `\` and U+0000-U+001F escaped, all else verbatim.
#' @noRd
json_string <- function(s) {
  s <- enc2utf8(s)
  if (!grepl('["\\\\[:cntrl:]]', s, useBytes = TRUE)) return(paste0('"', s, '"'))
  cps <- utf8ToInt(s)
  out <- character(length(cps))
  for (k in seq_along(cps)) {
    c <- cps[[k]]
    out[[k]] <- if (c == 34L) '\\"' else if (c == 92L) "\\\\" else if (c == 8L) "\\b" else if (c == 12L) "\\f" else
      if (c == 10L) "\\n" else if (c == 13L) "\\r" else if (c == 9L) "\\t" else if (c < 32L) sprintf("\\u%04x", c) else intToUtf8(c)
  }
  paste0('"', paste(out, collapse = ""), '"')
}

#' JSON as the kernel writes it
#'
#' Numbers by section 7a, strings minimally escaped; `sort_keys` orders members
#' by code point (canonical JSON), `spaced` separates with `, ` and `: `.
#' @param value A JSON value.
#' @param sort_keys,spaced Layout.
#' @param code The refusal code for a value with no JSON form.
#' @export
json_text <- function(value, sort_keys = FALSE, spaced = FALSE, code = "value-invalid") {
  item <- if (spaced) ", " else ","
  colon <- if (spaced) ": " else ":"
  w <- function(v) {
    if (is.null(v)) return("null")
    if (is_bool(v)) return(if (v) "true" else "false")
    if (is_num(v)) {
      v <- num_value(v)
      if (is.double(v) && !is.finite(v)) refuse(code, sprintf("%s has no JSON spelling", format(v)))
      return(num_text(v))
    }
    if (is_str(v)) return(json_string(v))
    if (is_obj(v)) {
      ks <- names(v)
      if (anyNA(ks) || any(!nzchar(ks)) && length(ks)) {
        if (any(is.na(ks))) refuse(code, "a JSON object key must be text")
      }
      idx <- seq_along(v)
      if (sort_keys) idx <- idx[order(ks, method = "radix")]
      return(paste0("{", paste(vapply(idx, function(k) paste0(json_string(ks[[k]]), colon, w(v[[k]])), ""), collapse = item), "}"))
    }
    if (is.list(v)) return(paste0("[", paste(vapply(v, w, ""), collapse = item), "]"))
    if (is.factor(v) && length(v) == 1L) return(json_string(as.character(v)))
    refuse(code, sprintf("a %s of length %d is not JSON data (use jarr() for an array)", class(v)[[1]], length(v)))
  }
  w(value)
}

# ------------------------------------------------------------ text (7a)

WHITESPACE <- " \t\n\r\f\v"
wstrip <- function(s) sub("^[ \t\n\r\f\v]+", "", sub("[ \t\n\r\f\v]+$", "", s, perl = TRUE), perl = TRUE)
wlstrip <- function(s) sub("^[ \t\n\r\f\v]+", "", s, perl = TRUE)
wrstrip <- function(s) sub("[ \t\n\r\f\v]+$", "", s, perl = TRUE)
nlstrip <- function(s) sub("^\n+", "", sub("\n+$", "", s, perl = TRUE), perl = TRUE)
is_ws_char <- function(ch) ch %in% c(" ", "\t", "\n", "\r", "\f", "\v")

is_identifier <- function(x) is_str(x) && grepl("^[A-Za-z_][A-Za-z0-9_]*$", x, perl = TRUE)
PURPOSE_RE <- "^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)*$"

read_integer <- function(text, where) {
  t <- wstrip(text)
  if (!grepl("^-?[0-9]+$", t, perl = TRUE)) refuse("parse-value", sprintf("%s: %s is not an integer", where, pyrepr(t)))
  integer_value(t)
}

read_number <- function(text, where) {
  t <- wstrip(text)
  if (!grepl("^-?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?$", t, perl = TRUE)) refuse("parse-value", sprintf("%s: %s is not a number", where, pyrepr(t)))
  v <- parse_f64(t)
  if (!is.finite(v)) refuse("parse-value", sprintf("%s: %s is not a finite number", where, pyrepr(t)))
  v
}

ascii_lower <- function(s) chartr("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz", s)

read_boolean <- function(text, where) {
  t <- wstrip(text)
  low <- ascii_lower(t)
  if (low %in% c("true", "yes")) return(TRUE)
  if (low %in% c("false", "no")) return(FALSE)
  refuse("parse-value", sprintf("%s: %s is not a boolean", where, pyrepr(t)))
}

#' Truthiness as the reference host tests it.
#' @noRd
pytruthy <- function(x) {
  if (is.null(x)) return(FALSE)
  if (is_bool(x)) return(x)
  if (is_num(x)) { v <- num_value(x); return(if (is_bigint(v)) unclass(v) != "0" else v != 0) }
  if (is_str(x)) return(nzchar(x))
  if (is.list(x)) return(length(x) > 0)
  TRUE
}

# ------------------------------------------------------ byte-offset strings

blen <- function(s) nchar(s, type = "bytes")
as_bytes_enc <- function(s) { Encoding(s) <- "bytes"; s }
#' `s[a:b]`, 0-based byte offsets, end exclusive.
#' @noRd
bsl <- function(s, a, b = blen(s)) {
  if (a >= b) return("")
  r <- substr(as_bytes_enc(s), a + 1L, b)
  Encoding(r) <- "UTF-8"
  r
}
#' 0-based byte offset of `needle` at or after `from`, or -1.
#' @noRd
bfind <- function(s, needle, from = 0L) {
  n <- blen(s)
  if (!nzchar(needle)) return(if (from <= n) from else -1L)
  if (from + blen(needle) > n) return(-1L)
  hay <- if (from > 0L) bsl(s, from) else s
  m <- regexpr(needle, hay, fixed = TRUE, useBytes = TRUE)
  if (m < 0L) -1L else from + as.integer(m) - 1L
}
#' Every non-overlapping 0-based byte offset of `needle`.
#' @noRd
ball <- function(s, needle) {
  if (!nzchar(needle) || !nzchar(s)) return(integer(0))
  m <- gregexpr(needle, s, fixed = TRUE, useBytes = TRUE)[[1]]
  if (m[[1]] < 0L) integer(0) else as.integer(m) - 1L
}
bcount <- function(s, needle) if (!nzchar(needle)) nchar(s) + 1L else length(ball(s, needle))
bstarts <- function(s, p, at = 0L) at + blen(p) <= blen(s) && bsl(s, at, at + blen(p)) == p
"%+%" <- function(a, b) paste0(a, b)

#' The byte at 0-based offset `i` as a one-character string when ASCII, else "".
#' @noRd
bchar <- function(s, i) {
  if (i < 0L || i >= blen(s)) return("")
  r <- charToRaw(s)[[i + 1L]]
  if (as.integer(r) < 128L) rawToChar(r) else ""
}

#' Characters of `s` with their 0-based byte offsets and byte lengths.
#' @noRd
chars_of <- function(s) {
  cps <- utf8ToInt(enc2utf8(s))
  if (!length(cps)) return(list(ch = character(0), start = integer(0), len = integer(0)))
  len <- ifelse(cps < 0x80, 1L, ifelse(cps < 0x800, 2L, ifelse(cps < 0x10000, 3L, 4L)))
  start <- c(0L, cumsum(len))[seq_along(len)]
  list(ch = intToUtf8(cps, multiple = TRUE), start = as.integer(start), len = as.integer(len))
}

#' Byte length of the last `n` characters.
#' @noRd
lastchars_bytes <- function(s, n) {
  if (n <= 0L || !nzchar(s)) return(0L)
  raw <- charToRaw(s)
  i <- length(raw)
  k <- 0L
  while (k < n && i > 0L) {
    i <- i - 1L
    while (i > 0L && bitwAnd(as.integer(raw[[i + 1L]]), 0xC0) == 0x80) i <- i - 1L
    k <- k + 1L
  }
  length(raw) - i
}

#' Move a byte offset back to the start of the character holding it.
#' @noRd
boundary <- function(s, i) {
  if (i <= 0L || i >= blen(s)) return(i)
  raw <- charToRaw(s)
  while (i > 0L && bitwAnd(as.integer(raw[[i + 1L]]), 0xC0) == 0x80) i <- i - 1L
  i
}

split_lines <- function(s) {
  if (!nzchar(s)) return("")
  parts <- strsplit(s, "\n", fixed = TRUE)[[1]]
  if (endsWith(s, "\n")) parts <- c(parts, "")
  parts
}

# ------------------------------------------------------ the reference's repr

nonprintable <- function(c) {
  (c >= 0x80 && c <= 0xA0) || c == 0xAD || (c >= 0x2000 && c <= 0x200F) || (c >= 0x2028 && c <= 0x202F) ||
    (c >= 0x205F && c <= 0x206F) || c == 0x3000 || c == 0x1680 || c == 0xFEFF || (c >= 0xE000 && c <= 0xF8FF) ||
    (c >= 0xFFF0 && c <= 0xFFFB) || c >= 0xF0000 || c == 0x180E
}

repr_str <- function(s) {
  cps <- utf8ToInt(enc2utf8(s))
  q <- if (39L %in% cps && !(34L %in% cps)) 34L else 39L
  out <- vapply(cps, function(c) {
    if (c == q || c == 92L) return(paste0("\\", intToUtf8(c)))
    if (c == 9L) return("\\t")
    if (c == 10L) return("\\n")
    if (c == 13L) return("\\r")
    if (c < 32L || c == 127L) return(sprintf("\\x%02x", c))
    if (c < 127L || !nonprintable(c)) return(intToUtf8(c))
    if (c <= 0xFF) return(sprintf("\\x%02x", c))
    if (c <= 0xFFFF) return(sprintf("\\u%04x", c))
    sprintf("\\U%08x", c)
  }, "")
  paste0(intToUtf8(q), paste(out, collapse = ""), intToUtf8(q))
}

repr_float <- function(x) {
  if (is.nan(x)) return("nan")
  if (is.infinite(x)) return(if (x > 0) "inf" else "-inf")
  if (x == 0) return(if (1 / x < 0) "-0.0" else "0.0")
  sd <- .Call(lmcc_shortest, x)
  digits <- sd[[1]]; n <- sd[[2]]
  sign <- if (x < 0) "-" else ""
  e <- n - 1L
  if (e >= -4L && e < 16L) {
    if (n <= 0L) return(paste0(sign, "0.", strrep("0", -n), digits))
    whole <- substr(paste0(digits, strrep("0", max(0L, n - nchar(digits)))), 1L, n)
    frac <- if (n < nchar(digits)) substr(digits, n + 1L, nchar(digits)) else "0"
    return(paste0(sign, whole, ".", frac))
  }
  paste0(sign, substr(digits, 1L, 1L), if (nchar(digits) > 1L) paste0(".", substring(digits, 2L)) else "",
         "e", if (e < 0L) "-" else "+", sprintf("%02d", abs(e)))
}

#' The reference host's repr of JSON-like data ('a', None, [1, 'b']).
#' @noRd
pyrepr <- function(x) {
  if (is.null(x)) return("None")
  if (is_bool(x)) return(if (x) "True" else "False")
  if (is_str(x)) return(repr_str(x))
  if (is_num(x)) {
    v <- num_value(x)
    if (is_bigint(v) || is.integer(v)) return(num_text(v))
    return(repr_float(v))
  }
  if (is_obj(x)) return(paste0("{", paste(vapply(names(x), function(k) paste0(repr_str(k), ": ", pyrepr(x[[k]])), ""), collapse = ", "), "}"))
  if (is.list(x)) return(paste0("[", paste(vapply(x, pyrepr, ""), collapse = ", "), "]"))
  if (is.character(x)) return(paste0("[", paste(vapply(x, repr_str, ""), collapse = ", "), "]"))
  paste(format(x), collapse = " ")
}

#' The reference host's str: text as itself, everything else as pyrepr.
#' @noRd
pystr <- function(x) if (is_str(x)) x else pyrepr(x)
sorted_repr <- function(xs) pyrepr(as.list(ssort(unlist(xs))))
typename_of <- function(v) if (is.null(v)) "None" else if (is_bool(v)) "bool" else if (is_str(v)) "str" else
  if (is_num(v)) (if (is_int_value(v) && !is.double(num_value(v))) "int" else "float") else if (is_obj(v)) "dict" else if (is.list(v)) "list" else class(v)[[1]]

#' Sort text by code point (the reference's order), empty-safe.
#' @noRd
ssort <- function(x) if (length(x)) sort(as.character(unlist(x)), method = "radix") else character(0)

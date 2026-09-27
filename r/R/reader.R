# Reading the reply (kernel sections 4, 4a, 6): find rules, the derived
# reader, marker repair. Offsets are 0-based bytes; an edit is c(start, end, new_len).

text_captures <- function(text, rule, pattern) {
  caps <- list()
  if (has_key(rule, "between")) {
    open <- rule[["between"]][[1]]; close <- rule[["between"]][[2]]
    pos <- 0L
    repeat {
      i <- bfind(text, open, pos); if (i < 0L) break
      j <- bfind(text, close, i + blen(open)); if (j < 0L) break
      caps[[length(caps) + 1L]] <- list(i, j + blen(close), bsl(text, i + blen(open), j))
      pos <- j + blen(close)
    }
  } else if (has_key(rule, "line_prefixed")) {
    prefix <- rule[["line_prefixed"]]
    pos <- 0L
    for (line in split_lines(text)) {
      if (startsWith(line, prefix)) caps[[length(caps) + 1L]] <- list(pos, pos + blen(line), bsl(line, blen(prefix)))
      pos <- pos + blen(line) + 1L
    }
  } else {
    return(pattern$captures(rule[["pattern"]], text))
  }
  caps
}

apply_find_rules <- function(text, parts, find_rules, pattern, edits = NULL) {
  found <- list()
  for (fr in find_rules) {
    name <- fr[[1]]; r <- fr[[2]]
    if (startsWith(r[["from"]], "part:")) {
      kind <- substring(r[["from"]], 6L)
      cap <- new_capture(Filter(function(p) identical(get_key(p, "type"), kind), parts))
    } else {
      caps <- text_captures(text, r, pattern)
      cap <- new_capture(lapply(caps, function(c) textpart(c[[3]])))
      if (pytruthy(get_key(r, "remove")) && length(caps)) {
        if (!is.null(edits)) edits$stages[[length(edits$stages) + 1L]] <- lapply(caps, function(c) c(c[[1]], c[[2]], 0L))
        pieces <- character(0); pos <- 0L
        for (c in caps) { pieces <- c(pieces, bsl(text, pos, c[[1]])); pos <- c[[2]] }
        text <- paste(c(pieces, bsl(text, pos)), collapse = "")
      }
    }
    found[[name]] <- if (!is.null(found[[name]])) new_capture(c(found[[name]]$parts, cap$parts)) else cap
  }
  list(text, found)
}

# ------------------------------------------------------------------ readers

#' A reader
#'
#' One reply document form (section 4): `split(text, names)` reads,
#' `join(spelled)` writes turns, `format(placeholders)` writes the
#' `\{format\}` skeleton; optionally `requires()`, `request_settings(fields)`,
#' `skeleton()`, `stream(names)` and `spec`. Vocabulary readers are lists
#' of these functions with class `lmcc_reader`.
#' @param ... The faces, named.
#' @export
new_reader <- function(...) {
  r <- list(...)
  if (is.null(r$format)) r$format <- function(placeholders) r$join(placeholders)
  if (is.null(r$requires)) r$requires <- function() character(0)
  if (is.null(r$request_settings)) r$request_settings <- function(fields) jobj()
  if (is.null(r$skeleton)) r$skeleton <- function() jobj()
  structure(r, class = "lmcc_reader")
}

cut_at_close <- function(chunk, close, name) {
  if (!nzchar(close)) return(chunk)
  n <- bcount(chunk, close)
  if (n > 1L) refuse("parse-ambiguous", sprintf("close marker %s for field %s appears %d times in its section \u2014 refusing to guess where it ends", pyrepr(close), pyrepr(name), n))
  i <- bfind(chunk, close)
  if (i < 0L) chunk else bsl(chunk, 0L, i)
}

check_collisions <- function(spelled, markers) {
  for (s in spelled) for (m in markers) if (nzchar(m) && grepl(m, s[[2]], fixed = TRUE))
    refuse("value-collides", sprintf("field %s: its spelled value contains the reader marker %s; the turn could not be read back as written", pyrepr(s[[1]]), pyrepr(m)))
}

# ---------------------------------------------------------- marker repair

IGNORABLE <- c(" ", "\t", "\v", "\f", "\r", "*", "_", "#")
DECORATION <- c("*", "_", "#")
EMPHASIS <- c("*", "_")
HORIZONTAL <- c(" ", "\t", "\v", "\f", "\r")

marker_key <- function(text) {
  ch <- chars_of(text)$ch
  ascii_lower(paste(ch[!(ch %in% IGNORABLE)], collapse = ""))
}
lead_strip <- function(k) sub("^\n+", "", k)

repairable_markers <- function(markers) {
  distinct <- unique(markers[nzchar(markers)])
  keys <- vapply(distinct, function(m) lead_strip(marker_key(m)), "", USE.NAMES = FALSE)
  ok <- distinct[nzchar(keys) & vapply(keys, function(k) sum(keys == k) == 1L, TRUE)]
  list(ok, distinct[!(distinct %in% ok)])
}

decoration_start <- function(text, run_start, core_start) {
  if (core_start > run_start) for (i in run_start:(core_start - 1L))
    if (bchar(text, i) %in% DECORATION && (i == 0L || is_ws_char(bchar(text, i - 1L)))) return(i)
  NULL
}

occurrence_span <- function(text, core_start, core_end, run_start, lead) {
  left <- decoration_start(text, run_start, core_start)
  start <- core_start; stop <- core_end
  if (!is.null(left)) {
    start <- left
    if (any(vapply(left:(core_start - 1L), function(i) bchar(text, i) %in% EMPHASIS, TRUE)))
      while (stop < blen(text) && bchar(text, stop) %in% EMPHASIS) stop <- stop + 1L
  }
  if (lead > 0L) {
    q <- start
    while (q > 0L && bchar(text, q - 1L) %in% HORIZONTAL) q <- q - 1L
    taken <- 0L
    while (taken < lead && q > 0L && bchar(text, q - 1L) == "\n") { q <- q - 1L; taken <- taken + 1L }
    if (taken > 0L) start <- q
  }
  c(start, stop)
}

#' The text without ignorables, folded: per kept character its byte start,
#' byte length and the start of the ignorable run before it.
#' @noRd
normalized <- function(text) {
  cs <- chars_of(text)
  keep <- !(cs$ch %in% IGNORABLE)
  run <- integer(length(cs$ch))
  r <- 0L
  for (k in seq_along(cs$ch)) {
    if (keep[[k]]) { run[[k]] <- r; r <- cs$start[[k]] + cs$len[[k]] }
  }
  list(chars = ascii_lower(cs$ch[keep]), pos = cs$start[keep], len = cs$len[keep], runs = run[keep])
}

match_all_chars <- function(hay, needle) {
  n <- length(needle); h <- length(hay)
  out <- integer(0)
  if (!n || n > h) return(out)
  k <- 1L
  cand <- which(hay == needle[[1]])
  for (s in cand) {
    if (s < k || s + n - 1L > h) next
    if (all(hay[s:(s + n - 1L)] == needle)) { out <- c(out, s); k <- s + n }
  }
  out
}

loose_occurrences <- function(text, marker, norm = NULL) {
  full <- marker_key(marker)
  key <- lead_strip(full)
  if (!nzchar(key)) return(list())
  lead <- nchar(full) - nchar(key)
  nm <- if (is.null(norm)) normalized(text) else norm
  kc <- chars_of(key)$ch
  lapply(match_all_chars(nm$chars, kc), function(s) {
    last <- s + length(kc) - 1L
    occurrence_span(text, nm$pos[[s]], nm$pos[[last]] + nm$len[[last]], nm$runs[[s]], lead)
  })
}

written_exactly <- function(text, marker, spans) {
  for (p in ball(text, marker)) {
    q <- p + blen(marker)
    inside <- any(vapply(spans, function(s) s[[1]] <= p && q <= s[[2]] && s[[2]] - s[[1]] > q - p, TRUE))
    if (!inside) return(TRUE)
  }
  FALSE
}

#' Section 4a: rewrite every misspelled marker unless written exactly somewhere.
#' @noRd
repair_markers <- function(text, markers, edits = NULL) {
  norm <- normalized(text)
  chosen <- list()
  for (m in markers) {
    spans <- loose_occurrences(text, m, norm)
    if (written_exactly(text, m, spans)) next
    for (s in spans) chosen[[length(chosen) + 1L]] <- list(s[[1]], s[[2]], m)
  }
  if (!length(chosen)) return(list(text, list()))
  o <- order(vapply(chosen, `[[`, 0, 1), vapply(chosen, `[[`, 0, 2), vapply(chosen, `[[`, "", 3), method = "radix")
  chosen <- chosen[o]
  if (length(chosen) > 1L) for (k in 1:(length(chosen) - 1L)) {
    a <- chosen[[k]]; b <- chosen[[k + 1L]]
    if (b[[1]] < a[[2]]) refuse("parse-ambiguous", sprintf("the reply's %s and %s overlap; read as the markers %s and %s they would share text \u2014 refusing to guess",
      pyrepr(bsl(text, a[[1]], a[[2]])), pyrepr(bsl(text, b[[1]], b[[2]])), pyrepr(a[[3]]), pyrepr(b[[3]])))
  }
  if (!is.null(edits)) edits$stages[[length(edits$stages) + 1L]] <- lapply(chosen, function(c) c(c[[1]], c[[2]], blen(c[[3]])))
  pieces <- character(0); repairs <- list(); pos <- 0L
  for (c in chosen) {
    pieces <- c(pieces, bsl(text, pos, c[[1]]), c[[3]])
    repairs[[length(repairs) + 1L]] <- jobj(repair = "marker", marker = c[[3]], saw = bsl(text, c[[1]], c[[2]]))
    pos <- c[[2]]
  }
  list(paste(c(pieces, bsl(text, pos)), collapse = ""), repairs)
}

refuse_missing <- function(raw, names_) {
  missing <- names_[!vapply(names_, function(n) has_key(raw, n), TRUE)]
  if (!length(missing)) return(invisible())
  hint <- paste0("reply is missing pattern section(s): ", paste(vapply(missing, pyrepr, ""), collapse = ", "))
  if (!length(raw) && length(names_) > 1L) hint <- paste0(hint, " \u2014 it has none of the template's markers: the model did not follow the layout (reading values by their order would be a guess)")
  refuse("parse-missing-fields", hint, partial = as_obj(raw))
}

#' The template read backwards (section 4); repair = FALSE for a strict adapter.
#' @noRd
derived_reader <- function(anchors, tail = "", repair = TRUE) {
  searched <- c(vapply(anchors, function(a) wrstrip(a[[2]]), ""), vapply(anchors, function(a) wstrip(a[[3]]), ""), wstrip(tail))
  rm <- if (repair) repairable_markers(searched) else list(character(0), character(0))
  self <- list(kind = "derived", anchors = anchors, tail = tail, repairable = rm[[1]], unrepaired = rm[[2]])
  self$markers <- function() {
    out <- character(0)
    for (a in anchors) out <- c(out, wrstrip(a[[2]]), wstrip(a[[3]]))
    if (nzchar(wstrip(tail))) out <- c(out, wstrip(tail))
    out[nzchar(out)]
  }
  self$read <- function(text, names_, allow_missing = FALSE, edits = NULL) derived_read(self, text, names_, allow_missing, edits)
  self$split <- function(text, names_) self$read(text, names_)$raw
  self$join <- function(spelled) {
    check_collisions(spelled, self$markers())
    by <- list(); for (s in spelled) by[[s[[1]]]] <- s[[2]]
    pieces <- character(0)
    for (a in anchors) if (!is.null(by[[a[[1]]]])) pieces <- c(pieces, paste0(a[[2]], by[[a[[1]]]], a[[3]]))
    nlstrip(paste0(paste(pieces, collapse = ""), if (length(pieces)) tail else ""))
  }
  self$format <- self$join
  self$requires <- function() character(0)
  self$request_settings <- function(fields) jobj()
  self$skeleton <- function() {
    if (!length(anchors)) return(jobj(prefill = "", stops = list()))
    stop <- if (nzchar(wstrip(tail))) wstrip(tail) else wstrip(anchors[[length(anchors)]][[3]])
    jobj(prefill = anchors[[1]][[2]], stops = if (nzchar(stop)) list(stop) else list())
  }
  structure(self, class = c("lmcc_derived_reader", "lmcc_reader"))
}

derived_read <- function(r, text, names_, allow_missing = FALSE, edits = NULL) {
  repairs <- list()
  if (length(r$repairable)) { rr <- repair_markers(text, r$repairable, edits); text <- rr[[1]]; repairs <- rr[[2]] }
  bounds <- list()
  for (a in r$anchors) {
    name <- a[[1]]
    if (!(name %in% names_)) next
    marker <- wrstrip(a[[2]])
    if (!nzchar(marker)) { bounds[[length(bounds) + 1L]] <- list(0L, 0L, name, a[[3]]); next }
    n <- bcount(text, marker)
    if (n > 1L) refuse("parse-ambiguous", sprintf("anchor %s for field %s appears %d times in the reply \u2014 refusing to guess", pyrepr(marker), pyrepr(name), n))
    i <- bfind(text, marker)
    if (i < 0L) next
    bounds[[length(bounds) + 1L]] <- list(i, i + blen(marker), name, a[[3]])
  }
  tail <- wstrip(r$tail)
  if (nzchar(tail)) {
    n <- bcount(text, tail)
    if (n > 1L) refuse("parse-ambiguous", sprintf("tail %s appears %d times in the reply \u2014 refusing to guess which one ends the reply", pyrepr(tail), n))
    t <- bfind(text, tail)
    if (t >= 0L) bounds[[length(bounds) + 1L]] <- list(t, t, NULL, "")
  }
  if (length(bounds)) bounds <- bounds[order(vapply(bounds, `[[`, 0, 1), vapply(bounds, `[[`, 0, 2), method = "radix")]
  raw <- jobj(); spans <- list(); to_end <- character(0); notes <- list()
  ignored <- function(piece) if (nzchar(wstrip(piece))) notes[[length(notes) + 1L]] <<- jobj(repair = "ignored", saw = wstrip(piece))
  if (length(bounds)) ignored(bsl(text, 0L, bounds[[1]][[1]]))
  for (k in seq_along(bounds)) {
    b <- bounds[[k]]; last <- k == length(bounds)
    if (is.null(b[[3]])) { if (last) ignored(bsl(text, b[[1]] + blen(tail))); next }
    name <- b[[3]]
    chunk <- bsl(text, b[[2]], if (last) blen(text) else bounds[[k + 1L]][[1]])
    close <- wstrip(b[[4]])
    cut <- cut_at_close(chunk, close, name)
    raw[[name]] <- wstrip(cut)
    spans[[name]] <- c(b[[2]], b[[2]] + blen(cut))
    idx <- if (nzchar(close)) bfind(chunk, close) else -1L
    if (idx >= 0L) ignored(bsl(chunk, idx + blen(close)))
    else if (last) to_end <- c(to_end, name)
    else if (nzchar(close)) notes[[length(notes) + 1L]] <- jobj(repair = "unclosed", field = name, close = close)
  }
  if (!allow_missing) refuse_missing(raw, names_)
  list(raw = raw, repairs = c(repairs, notes), to_end = to_end, spans = spans, text = text)
}

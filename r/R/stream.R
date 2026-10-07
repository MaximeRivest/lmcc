# Incremental, sans-I/O parsing (kernel section 8). A reducer over deltas,
# not a second parser; finish() hands the final checks to the batch parser
# and proves the projection agrees. Offsets are bytes; a hold is counted in
# characters and returned in bytes, so every cut lands on a boundary.

prefixes_new <- function(markers) {
  table <- character(0); longest <- 0L
  for (m in markers) {
    ch <- chars_of(m)$ch
    n <- length(ch)
    if (n > 1L) for (k in 1:(n - 1L)) table <- c(table, paste(ch[1:k], collapse = ""))
    longest <- max(longest, n - 1L)
  }
  list(table = unique(table), longest = longest)
}

#' Bytes of the longest suffix of `text` that is a proper prefix of a marker.
#' @noRd
hold_bytes <- function(pf, text) {
  if (pf$longest == 0L || !nzchar(text)) return(0L)
  best <- 0L; n <- blen(text); k <- 0L; i <- n
  while (k < pf$longest && i > 0L) {
    i <- boundary(text, i - 1L); k <- k + 1L
    if (bsl(text, i) %in% pf$table) best <- n - i
  }
  best
}

grows_between <- function(pf, window, stop, lo, hi) {
  n <- blen(window); k <- 0L; i <- n
  while (k < pf$longest && i > 0L) {
    i <- boundary(window, i - 1L); k <- k + 1L
    start <- stop - (n - i)
    if (lo < start && start < hi && bsl(window, i) %in% pf$table) return(TRUE)
  }
  FALSE
}

scanner_new <- function(marker, start) { s <- new.env(); s$marker <- marker; s$stop <- start; s$pending <- ""; s }
scan <- function(s, text) {
  if (!nzchar(text) || !nzchar(s$marker)) { s$stop <- s$stop + blen(text); return(integer(0)) }
  buf <- paste0(s$pending, text)
  base <- s$stop - blen(s$pending)
  hits <- ball(buf, s$marker)
  i <- if (length(hits)) hits[[length(hits)]] + blen(s$marker) else 0L
  s$stop <- s$stop + blen(text)
  keep <- max(boundary(buf, max(i, blen(buf) - (blen(s$marker) - 1L))), i)
  s$pending <- bsl(buf, keep)
  base + hits
}

field_state <- function(name) { f <- new.env(); f$name <- name; f$present <- FALSE; f$started <- FALSE; f$emitted <- character(0); f$has_emitted <- FALSE; f$pending <- character(0); f }
emit <- function(f, t) if (nzchar(t)) { f$emitted <- c(f$emitted, t); f$has_emitted <- TRUE; f$pending <- c(f$pending, t) }
emitted_text <- function(f) paste(f$emitted, collapse = "")

# -------------------------------------------------------------- find rules

between_stage <- function(r) {
  s <- new.env(); s$type <- "between"
  s$open <- r[["between"]][[1]]; s$close <- r[["between"]][[2]]; s$remove <- pytruthy(get_key(r, "remove"))
  s$holdt <- prefixes_new(s$open); s$buf <- ""; s$inside <- FALSE; s$captures <- character(0)
  s$feed <- function(delta, final) {
    out <- if (s$remove) character(0) else delta
    buf <- paste0(s$buf, delta)
    repeat {
      if (!s$inside) {
        i <- bfind(buf, s$open)
        if (i < 0L) {
          if (s$remove) {
            keep <- if (final) 0L else hold_bytes(s$holdt, buf)
            out <- c(out, bsl(buf, 0L, blen(buf) - keep)); buf <- bsl(buf, blen(buf) - keep)
          } else {
            keep <- min(blen(buf), max(blen(s$open) - 1L, 0L))
            buf <- bsl(buf, boundary(buf, blen(buf) - keep))
          }
          break
        }
        if (s$remove) out <- c(out, bsl(buf, 0L, i))
        buf <- bsl(buf, i); s$inside <- TRUE
      }
      j <- bfind(buf, s$close, blen(s$open))
      if (j < 0L) { if (final && s$remove) { out <- c(out, buf); buf <- "" }; break }
      s$captures <- c(s$captures, wstrip(bsl(buf, blen(s$open), j)))
      buf <- bsl(buf, j + blen(s$close)); s$inside <- FALSE
    }
    s$buf <- buf
    paste(out, collapse = "")
  }
  s
}

line_stage <- function(r) {
  s <- new.env(); s$type <- "line"
  s$prefix <- r[["line_prefixed"]]; s$remove <- pytruthy(get_key(r, "remove")); s$line <- ""; s$captures <- character(0)
  s$feed <- function(delta, final) {
    out <- if (s$remove) character(0) else delta
    lines <- split_lines(paste0(s$line, delta))
    last <- lines[[length(lines)]]
    for (line in lines[-length(lines)]) {
      if (startsWith(line, s$prefix)) { s$captures <- c(s$captures, wstrip(bsl(line, blen(s$prefix)))); if (s$remove) out <- c(out, "\n") }
      else if (s$remove) out <- c(out, line, "\n")
    }
    if (final) {
      if (startsWith(last, s$prefix)) s$captures <- c(s$captures, wstrip(bsl(last, blen(s$prefix))))
      else if (s$remove) out <- c(out, last)
      last <- ""
    }
    s$line <- last
    paste(out, collapse = "")
  }
  s
}

pattern_stage <- function(r, pattern) {
  s <- new.env(); s$type <- "pattern"; s$remove <- pytruthy(get_key(r, "remove")); s$pieces <- character(0); s$captures <- character(0)
  s$feed <- function(delta, final) {
    s$pieces <- c(s$pieces, delta)
    if (!final) return(if (s$remove) "" else delta)
    t <- paste(s$pieces, collapse = "")
    caps <- text_captures(t, r, pattern)
    s$captures <- vapply(caps, function(c) wstrip(c[[3]]), "")
    if (!s$remove) return("")
    if (!length(caps)) return(t)
    out <- character(0); pos <- 0L
    for (c in caps) { out <- c(out, bsl(t, pos, c[[1]])); pos <- c[[2]] }
    paste(c(out, bsl(t, pos)), collapse = "")
  }
  s
}

part_source <- function(kind) {
  s <- new.env(); s$type <- "part"; s$kind <- kind; s$texts <- list(); s$any_part <- FALSE; s$held <- ""; s$has_emitted <- FALSE
  s$caps <- function() vapply(s$texts, function(p) wstrip(paste(p, collapse = "")), "")
  s$part <- function(k, t, new_part) {
    if (k != s$kind) return("")
    s$any_part <- TRUE
    if (is.null(t)) return("")
    out <- ""
    if (new_part) { s$texts[[length(s$texts) + 1L]] <- character(0); s$held <- ""; s$has_emitted <- FALSE; if (length(s$texts) > 1L) out <- "\n" }
    s$texts[[length(s$texts)]] <- c(s$texts[[length(s$texts)]], t)
    candidate <- paste0(s$held, t)
    if (!s$has_emitted) candidate <- wlstrip(candidate)
    stable <- wrstrip(candidate)
    s$held <- bsl(candidate, blen(stable))
    if (nzchar(stable)) s$has_emitted <- TRUE
    paste0(out, stable)
  }
  s
}
stage_captures <- function(s) if (s$type == "part") s$caps() else s$captures

# ---------------------------------------------------------- derived reader

section_new <- function(field, start, after, close, holdt) {
  s <- new.env()
  s$field <- field; s$start <- start; s$after <- after; s$close <- close; s$holdt <- holdt
  s$scanner <- if (nzchar(close)) scanner_new(close, after) else NULL
  s$close_starts <- integer(0); s$stop <- NULL; s$received <- after; s$held <- ""; s$fixed <- NULL
  s
}

section_cut <- function(s, limit) {
  if (limit >= s$received) return(s$held)
  drop <- s$received - limit
  if (drop > blen(s$held)) {
    if (s$field$has_emitted) stop(sprintf("stream projection for '%s' revised emitted text", s$field$name))
    return("")
  }
  bsl(s$held, 0L, blen(s$held) - drop)
}

section_advance <- function(s, limit) {
  candidate <- if (is.null(limit)) s$held else section_cut(s, limit)
  rest <- if (is.null(limit)) "" else bsl(s$held, blen(candidate))
  if (!s$field$has_emitted) candidate <- wlstrip(candidate)
  n <- hold_bytes(s$holdt, candidate)
  stable <- wrstrip(bsl(candidate, 0L, blen(candidate) - n))
  emit(s$field, stable)
  s$held <- paste0(bsl(candidate, blen(stable)), rest)
}

section_fix <- function(s, limit) {
  candidate <- section_cut(s, limit)
  if (!s$field$has_emitted) candidate <- wlstrip(candidate)
  emit(s$field, wrstrip(candidate))
  s$fixed <- emitted_text(s$field)
  s$held <- ""
}

derived_reducer <- function(reader, fields, names_) {
  d <- new.env()
  d$fields <- fields
  d$wanted <- Filter(Negate(is.null), lapply(reader$anchors, function(a) if (a[[1]] %in% names_) list(a[[1]], wrstrip(a[[2]]), wstrip(a[[3]])) else NULL))
  d$tail <- wstrip(reader$tail)
  markers <- c(vapply(d$wanted, `[[`, "", 2), if (nzchar(d$tail)) d$tail)
  d$bounds <- prefixes_new(markers)
  d$holds <- list()
  for (w in d$wanted) { key <- paste0("k", w[[3]]); if (is.null(d$holds[[key]])) d$holds[[key]] <- prefixes_new(c(markers, if (nzchar(w[[3]])) w[[3]])) }
  d$scanners <- list()
  for (m in unique(markers)) d$scanners[[paste0("k", m)]] <- scanner_new(m, 0L)
  d$scan_markers <- unique(markers)
  d$first <- list(); d$duplicated <- character(0); d$sections <- list(); d$length <- 0L; d$window <- ""; d$poisoned <- FALSE
  d
}

reducer_feed <- function(d, delta, final) {
  a <- d$length; b <- a + blen(delta); d$length <- b
  if (d$bounds$longest > 0L) { w <- paste0(d$window, delta); d$window <- bsl(w, blen(w) - lastchars_bytes(w, d$bounds$longest)) }
  for (m in d$scan_markers) for (q in scan(d$scanners[[paste0("k", m)]], delta)) {
    key <- paste0("k", m)
    if (!is.null(d$first[[key]])) d$duplicated <- unique(c(d$duplicated, m)) else d$first[[key]] <- q
  }
  bounds <- list()
  for (w in d$wanted) { q <- d$first[[paste0("k", w[[2]])]]; if (!is.null(q)) bounds[[length(bounds) + 1L]] <- list(q, q + blen(w[[2]]), w[[1]], w[[3]]) }
  if (nzchar(d$tail) && !is.null(d$first[[paste0("k", d$tail)]])) { q <- d$first[[paste0("k", d$tail)]]; bounds[[length(bounds) + 1L]] <- list(q, q, NULL, "") }
  if (length(bounds)) bounds <- bounds[order(vapply(bounds, `[[`, 0, 1), vapply(bounds, `[[`, 0, 2), method = "radix")]
  for (i in seq_along(bounds)) {
    bd <- bounds[[i]]
    if (is.null(bd[[3]])) next
    name <- bd[[3]]
    sec <- d$sections[[name]]
    if (is.null(sec)) {
      f <- d$fields[[name]]; f$present <- TRUE
      sec <- section_new(f, bd[[1]], bd[[2]], bd[[4]], d$holds[[paste0("k", bd[[4]])]])
      d$sections[[name]] <- sec
    }
    stop_at <- if (i < length(bounds)) bounds[[i + 1L]][[1]] else NULL
    if (!is.null(sec$stop) && !is.null(stop_at) && stop_at < sec$stop && !is.null(sec$fixed)) stop(sprintf("stream projection for '%s' revised emitted text", name))
    sec$stop <- stop_at
  }
  for (sec in d$sections) {
    limit <- if (is.null(sec$stop)) b else min(b, sec$stop)
    if (!is.null(sec$fixed)) {
    } else if (sec$received < limit) {
      sec$held <- paste0(sec$held, bsl(delta, max(0L, sec$received - a), limit - a)); sec$received <- limit
    } else if (sec$received > limit) {
      sec$held <- section_cut(sec, limit); sec$received <- limit
    }
    sc <- sec$scanner
    if (!is.null(sc) && sc$stop < b && (is.null(sec$stop) || sc$stop < sec$stop))
      sec$close_starts <- c(sec$close_starts, scan(sc, bsl(delta, max(0L, sc$stop - a))))
  }
  grow_start <- b - hold_bytes(d$bounds, d$window)
  poisoned <- length(d$duplicated) > 0L
  for (sec in d$sections) {
    st <- sec$stop
    closes <- sec$close_starts[if (is.null(st)) rep(TRUE, length(sec$close_starts)) else sec$close_starts + blen(sec$close) <= st]
    if (length(closes) >= 2L) poisoned <- TRUE
    if (!is.null(sec$fixed)) next
    s2 <- if (is.null(st)) b else st
    if (!is.null(st) && st <= sec$after) section_fix(sec, sec$after)
    else if (final) section_fix(sec, if (length(closes)) closes[[1]] else s2)
    else if (!is.null(st) && grow_start >= st) section_fix(sec, if (length(closes)) closes[[1]] else st)
    else if (length(closes) && is.null(st) && grow_start >= closes[[1]] + blen(sec$close)) section_fix(sec, closes[[1]])
    else if (!grows_between(d$bounds, d$window, b, sec$start - 1L, sec$after)) section_advance(sec, if (length(closes)) closes[[1]] else NULL)
  }
  d$poisoned <- poisoned
}

final_raw <- function(d) { out <- list(); for (n in names(d$sections)) if (!is.null(d$sections[[n]]$fixed)) out[[n]] <- d$sections[[n]]$fixed; out }

# ---------------------------------------------------------- marker repair

marker_repair <- function(markers) {
  m <- new.env()
  m$markers <- markers
  m$keys <- lapply(markers, function(x) { full <- marker_key(x); k <- lead_strip(full); list(chars_of(k)$ch, x, nchar(full) - nchar(k)) })
  m$lead <- max(vapply(m$keys, `[[`, 0L, 3))
  m$longest <- max(vapply(m$keys, function(k) length(k[[1]]), 0L))
  m$prefixes <- prefixes_new(vapply(m$keys, function(k) paste(k[[1]], collapse = ""), ""))
  m$pieces <- character(0); m$buf <- ""; m$before <- ""; m$released <- 0L; m$length <- 0L; m$run_start <- 0L
  m$window <- list(); m$pending <- list(); m$held_from <- NULL
  m
}

mr_at <- function(m, j) if (j >= m$released) bchar(m$buf, j - m$released) else m$before

repair_feed <- function(m, delta, final) {
  a <- m$length
  m$pieces <- c(m$pieces, delta); m$buf <- paste0(m$buf, delta); m$length <- m$length + blen(delta)
  if (final) {
    t <- paste(m$pieces, collapse = "")
    rewritten <- repair_markers(t, m$markers)[[1]]
    if (bsl(rewritten, 0L, m$released) != bsl(t, 0L, m$released)) stop("marker repair revised text it had already passed on")
    out <- bsl(rewritten, m$released)
    m$released <- blen(t); m$buf <- ""
    return(out)
  }
  if (!is.null(m$held_from)) return("")
  cs <- chars_of(delta)
  for (k in seq_along(cs$ch)) {
    c <- cs$ch[[k]]; i <- a + cs$start[[k]]
    if (c %in% IGNORABLE) next
    m$window[[length(m$window) + 1L]] <- list(ascii_lower(c), i, m$run_start)
    m$run_start <- i + cs$len[[k]]
    if (length(m$window) > m$longest) m$window <- m$window[-1L]
    wn <- length(m$window)
    for (key in m$keys) {
      kc <- key[[1]]; n <- length(kc)
      if (n <= wn && kc[[n]] == m$window[[wn]][[1]] && all(vapply(1:n, function(j) kc[[j]] == m$window[[wn - n + j]][[1]], TRUE))) {
        e <- m$window[[wn - n + 1L]]
        m$pending[[length(m$pending) + 1L]] <- list(key[[2]], e[[3]], e[[2]], key[[3]], i + cs$len[[k]])
      }
    }
  }
  waiting <- list()
  for (item in m$pending) {
    marker <- item[[1]]; run <- item[[2]]; core_start <- item[[3]]; lead <- item[[4]]; core_end <- item[[5]]
    left <- NULL
    if (core_start > run) for (j in run:(core_start - 1L)) if (mr_at(m, j) %in% DECORATION && (j == 0L || is_ws_char(mr_at(m, j - 1L)))) { left <- j; break }
    stop_ <- core_end
    if (!is.null(left) && any(vapply(left:(core_start - 1L), function(j) mr_at(m, j) %in% EMPHASIS, TRUE))) {
      while (stop_ < m$length && mr_at(m, stop_) %in% EMPHASIS) stop_ <- stop_ + 1L
      if (stop_ == m$length) { waiting[[length(waiting) + 1L]] <- item; next }
    }
    start <- if (is.null(left)) core_start else left
    if (lead > 0L) {
      q <- start
      while (q > m$released && mr_at(m, q - 1L) %in% HORIZONTAL) q <- q - 1L
      taken <- 0L
      while (taken < lead && q > m$released && mr_at(m, q - 1L) == "\n") { q <- q - 1L; taken <- taken + 1L }
      if (taken > 0L) start <- q
    }
    if (bsl(m$buf, start - m$released, stop_ - m$released) != marker) { m$held_from <- start; break }
  }
  m$pending <- if (is.null(m$held_from)) waiting else list()
  limit <- if (is.null(m$held_from)) m$length else m$held_from
  if (m$run_start < m$length) limit <- min(limit, m$run_start)
  wtext <- vapply(m$window, `[[`, "", 1)
  n <- 0L
  if (length(wtext)) for (k in min(length(wtext), m$prefixes$longest):1) {
    if (k < 1L) break
    if (paste(wtext[(length(wtext) - k + 1L):length(wtext)], collapse = "") %in% m$prefixes$table) { n <- k; break }
  }
  if (n > 0L) limit <- min(limit, m$window[[length(m$window) - n + 1L]][[3]])
  for (it in m$pending) limit <- min(limit, it[[2]])
  for (k in seq_len(m$lead)) {
    while (limit > m$released && mr_at(m, limit - 1L) %in% HORIZONTAL) limit <- limit - 1L
    if (limit > m$released && mr_at(m, limit - 1L) == "\n") limit <- limit - 1L
  }
  limit <- max(limit, m$released)
  out <- bsl(m$buf, 0L, limit - m$released)
  if (nzchar(out)) { m$before <- bchar(out, blen(out) - 1L); m$buf <- bsl(m$buf, blen(out)); m$released <- limit }
  out
}

# -------------------------------------------------------------- describe

describe_streaming <- function(p) {
  fields <- vapply(p$find_rules, `[[`, "", 1)
  routes <- list(); modes <- character(0); removing_pattern <- FALSE
  for (fr in p$find_rules) {
    r <- fr[[2]]; reason <- NULL
    if (has_key(r, "pattern")) { mode <- "buffered"; reason <- "a pattern find rule waits for EOF"; removing_pattern <- removing_pattern || pytruthy(get_key(r, "remove")) }
    else if (sum(fields == fr[[1]]) > 1L) { mode <- "buffered"; reason <- "multiple find rules concatenate by declaration order" }
    else mode <- "incremental"
    item <- jobj(field = fr[[1]], from = r[["from"]], mode = mode)
    if (!is.null(reason)) item[["reason"]] <- reason
    routes[[length(routes) + 1L]] <- item; modes <- c(modes, mode)
  }
  face <- inherits(p$reader, "lmcc_derived_reader") || !is.null(p$reader$stream)
  if (face && !removing_pattern) reader <- jobj(mode = "incremental")
  else if (face) reader <- jobj(mode = "buffered", reason = "a removing pattern find rule can revise the reader's text")
  else reader <- jobj(mode = "buffered", reason = "reader provides no streaming face")
  modes <- unique(c(modes, reader[["mode"]]))
  mode <- if (identical(modes, "incremental")) "incremental" else if (identical(modes, "buffered")) "buffered" else "hybrid"
  jobj(mode = mode, reader = reader, find = routes, field_done = "finish",
       repairs = if (isTRUE(p$adapter$strict)) jobj(mode = "strict") else jobj(mode = "forgiving", reason = "from the first misspelled marker the rest of the reply waits for finish"))
}

# ----------------------------------------------------------------- stream

#' Stream a reply
#'
#' A pure, sans-I/O parser (section 8): `feed()` takes one text delta or one
#' lm15 part delta and returns events; `finish()` returns the EOF events and
#' the same values, repairs and measurements as [read_reply()].
#' @param p A plan.
#' @export
reply_stream <- function(p) {
  s <- new.env()
  s$plan <- p; s$pieces <- character(0); s$parts <- list(); s$part_texts <- list(); s$part_mode <- FALSE; s$finished <- FALSE
  s$fields <- list(); for (f in p$signature$fields) s$fields[[f$name]] <- field_state(f$name)
  names_out <- vapply(p$visible_outputs, function(f) f$name, "")
  s$stages <- list(); s$by_field <- list()
  for (fr in p$find_rules) {
    r <- fr[[2]]; src <- r[["from"]]
    st <- if (startsWith(src, "part:")) part_source(substring(src, 6L)) else if (has_key(r, "between")) between_stage(r) else if (has_key(r, "line_prefixed")) line_stage(r) else pattern_stage(r, pattern_binding(p))
    s$stages[[length(s$stages) + 1L]] <- list(fr[[1]], st)
    s$by_field[[fr[[1]]]] <- c(s$by_field[[fr[[1]]]], list(st))
  }
  s$counted <- list()
  s$derived <- if (inherits(p$reader, "lmcc_derived_reader")) derived_reducer(p$reader, s$fields, names_out) else NULL
  s$repair <- if (!is.null(s$derived) && length(p$reader$repairable)) marker_repair(p$reader$repairable) else NULL
  s$repair_find <- if (length(p$find_repairable)) marker_repair(p$find_repairable) else NULL
  s$reader_stream <- if (is.null(s$derived) && !is.null(p$reader$stream)) p$reader$stream(names_out) else NULL
  s$reader_prefixes <- list(); s$reader_final_names <- NULL
  s$opening <- list()
  class(s) <- "lmcc_stream"
  if (nzchar(p$prefill)) { stream_run(s, p$prefill, NULL, FALSE); s$opening <- stream_events(s, FALSE) }
  s
}

#' @rdname reply_stream
#' @param s A stream.
#' @param delta Text, or one lm15 part delta (a named list).
#' @export
feed <- function(s, delta) {
  if (s$finished) stop("stream is already finished")
  r <- stream_append(s, delta)
  stream_run(s, r[[1]], r[[2]], FALSE)
  opening <- s$opening; s$opening <- list()
  c(opening, stream_events(s, FALSE))
}

#' @rdname reply_stream
#' @param finish_reason The lm15 stream end's; `"length"` means cut, `"content_filter"` means stopped (refuses `parse-filtered`).
#' @export
finish <- function(s, finish_reason = NULL) {
  if (s$finished) stop("stream is already finished")
  s$finished <- TRUE
  response <- if (s$part_mode) jobj(role = "assistant", parts = materialized(s)) else paste(s$pieces, collapse = "")
  if (!is.null(finish_reason)) {
    message <- if (is_str(response)) jobj(role = "assistant", parts = list(textpart(response))) else response
    response <- jobj(message = message, finish_reason = finish_reason)
  }
  pm <- reply_probabilities(response)
  r <- parse_with_captures(s$plan, response)
  stream_run(s, "", NULL, TRUE)
  events <- stream_events(s, TRUE, r[[2]], r[[1]])
  structure(list(events = events, values = r[[1]], repairs = r[[3]], probabilities = pm[[1]], measured_by = pm[[2]]), class = "lmcc_stream_result")
}

stream_append <- function(s, delta) {
  if (is_str(delta)) {
    s$pieces <- c(s$pieces, delta)
    if (s$part_mode) return(list(delta, append_part(s, textpart(delta))))
    return(list(delta, NULL))
  }
  validate_response_part(delta)
  if (!s$part_mode) {
    s$part_mode <- TRUE
    if (length(s$pieces)) append_part(s, textpart(paste(s$pieces, collapse = "")))
  }
  part <- append_part(s, as_obj(delta))
  t <- if (delta[["type"]] %in% c("text", "data")) part_text(delta) else ""
  if (nzchar(t)) s$pieces <- c(s$pieces, t)
  list(t, part)
}

append_part <- function(s, part) {
  kind <- part[["type"]]; t <- get_key(part, "text"); has_text <- is_str(t)
  n <- length(s$parts)
  if (has_text && n && identical(s$parts[[n]][["type"]], kind) && !is.null(s$part_texts[[n]])) {
    s$part_texts[[n]] <- c(s$part_texts[[n]], t)
    for (m in members_of(part)) if (!(m[[1]] %in% c("type", "text"))) s$parts[[n]] <- set_key(s$parts[[n]], m[[1]], m[[2]])
    return(list(kind, t, FALSE))
  }
  s$parts[[n + 1L]] <- part
  s$part_texts[n + 1L] <- list(if (has_text) t else NULL)
  list(kind, if (has_text) t else NULL, TRUE)
}

materialized <- function(s) lapply(seq_along(s$parts), function(i) if (is.null(s$part_texts[[i]])) s$parts[[i]] else set_key(s$parts[[i]], "text", paste(s$part_texts[[i]], collapse = "")))

stream_run <- function(s, t, part, final) {
  st <- t
  if (!is.null(s$repair_find)) st <- repair_feed(s$repair_find, st, final)
  for (x in s$stages) {
    field <- x[[1]]; stage <- x[[2]]; f <- s$fields[[field]]
    if (stage$type == "part") {
      if (!is.null(part)) {
        dlt <- stage$part(part[[1]], part[[2]], part[[3]])
        if (stage$any_part) f$present <- TRUE
        if (length(s$by_field[[field]]) == 1L) emit(f, dlt)
      }
      next
    }
    st <- stage$feed(st, final)
    if (length(stage$captures)) f$present <- TRUE
    if (length(s$by_field[[field]]) == 1L) {
      done <- s$counted[[field]] %||% 0L
      caps <- stage$captures
      if (length(caps) > done) for (c in caps[(done + 1L):length(caps)]) { emit(f, paste0(if (done > 0L) "\n" else "", c)); done <- done + 1L }
      s$counted[[field]] <- done
    }
  }
  if (!is.null(s$derived)) {
    if (!is.null(s$repair)) st <- repair_feed(s$repair, st, final)
    reducer_feed(s$derived, st, final)
  } else if (!is.null(s$reader_stream)) {
    prefixes <- if (nzchar(st) || !final) s$reader_stream$feed(st) else list()
    if (final) { prefixes <- s$reader_stream$finish(); s$reader_final_names <- names(prefixes) }
    for (name in names(prefixes)) {
      f <- s$fields[[name]]
      if (is.null(f)) next
      f$present <- TRUE
      raw <- prefixes[[name]]; before <- s$reader_prefixes[[name]] %||% ""
      if (!startsWith(raw, before)) stop(sprintf("reader stream prefix for '%s' revised emitted text", name))
      s$reader_prefixes[[name]] <- raw
      emit(f, bsl(raw, blen(before)))
    }
  }
}

final_projection <- function(s) {
  out <- if (!is.null(s$derived)) final_raw(s$derived) else if (!is.null(s$reader_stream)) s$reader_prefixes else list()
  for (field in names(s$by_field)) {
    f <- s$fields[[field]]
    if (!f$present) next
    stages <- s$by_field[[field]]
    out[[field]] <- if (length(stages) > 1L) paste(unlist(lapply(stages, stage_captures)), collapse = "\n") else emitted_text(f)
  }
  out
}

stream_events <- function(s, final, captures = NULL, values = NULL) {
  if (!is.null(s$derived) && s$derived$poisoned && !final) return(list())
  events <- list()
  if (final) {
    projected <- final_projection(s)
    for (name in names(projected)) if (!is.null(captures[[name]]) && projected[[name]] != capture_text(captures[[name]]))
      stop(sprintf("stream projection for '%s' disagrees with batch parse", name))
    for (field in s$plan$signature$fields) {
      if (is.null(captures[[field$name]])) next
      f <- s$fields[[field$name]]
      if (!f$started) { f$started <- TRUE; events[[length(events) + 1L]] <- jobj(kind = "field_started", field = field$name) }
      raw <- capture_text(captures[[field$name]])
      before <- emitted_text(f); held_back <- paste(f$pending, collapse = "")
      already <- bsl(before, 0L, blen(before) - blen(held_back))
      if (!startsWith(raw, already)) stop(sprintf("stream projection for '%s' revised emitted text", field$name))
      dlt <- bsl(raw, blen(already))
      if (nzchar(dlt)) events[[length(events) + 1L]] <- jobj(kind = "field_delta", field = field$name, text = dlt)
      ev <- jobj(kind = "field_done", field = field$name)
      events[[length(events) + 1L]] <- set_key(ev, "value", values[[field$name]])
    }
    return(events)
  }
  for (field in s$plan$signature$fields) {
    f <- s$fields[[field$name]]
    if (!f$present) next
    if (!f$started) { f$started <- TRUE; events[[length(events) + 1L]] <- jobj(kind = "field_started", field = field$name) }
    if (length(f$pending)) { events[[length(events) + 1L]] <- jobj(kind = "field_delta", field = field$name, text = paste(f$pending, collapse = "")); f$pending <- character(0) }
  }
  events
}

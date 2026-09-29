# The R kernel behind the harness's driver protocol (kernel section 9):
#
#     R CMD INSTALL --library=r/.lib r
#     cd python && python ../contract/harness/runner.py --driver 'Rscript ../r/conform/driver.R'
#
# One case per line on stdin, one {ok, detail?, unclaimed?, stream_trace?} per
# line on stdout; the same stages and stream replays as the reference driver.
# Input is read as UTF-8 and output written as UTF-8 bytes whatever the locale.

lib <- Sys.getenv("LMCC_R_LIB", file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1]])), "..", ".lib"))
suppressPackageStartupMessages(library(lmcc, lib.loc = lib))
# R's `$` and argument matching complete a partial name (`x$id` finds a member
# "identifier" when "id" is absent): the kernel reads data by exact name, and
# any partial match, like any other warning, fails the run here.
options(warnPartialMatchDollar = TRUE, warnPartialMatchArgs = TRUE, warnPartialMatchAttr = TRUE, warn = 2)
ns <- asNamespace("lmcc")
for (n in c("is_obj", "is_arr", "is_str", "json_equal", "get_key", "has_key", "set_key", "bsl", "blen", "chars_of", "parse_with_captures",
            "native_extensions", "capture_text", "describe_refusal", "members_of")) assign(n, get(n, envir = ns))

case_turns <- function(c) {
  fp <- signature_fingerprint(signature_from_list(c$signature))
  current <- jobj(signature = fp, inputs = get_key(c, "inputs", jobj()), steps = get_key(c, "steps", list()))
  slots <- jobj()
  # Slot names are data: a slot named "" is found and written by position.
  for (m in members_of(get_key(c, "turns", jobj()))) slots <- set_key(slots, m[[1]], lapply(m[[2]], function(t) if (has_key(t, "signature")) t else c(jobj(signature = fp), t)))
  list(current, slots)
}

registry_for <- function(c) {
  req <- as.character(unlist(get_key(c, "requires", list())))
  reg <- lmcc_registry(extensions = as.character(req[!startsWith(req, "udf:")]), allow_udf = "udf:python" %in% req)
  if ("std" %in% unlist(get_key(c, "vocab", list()))) install_std(reg)
  reg
}

unclaimed_of <- function(c) {
  for (r in unlist(get_key(c, "requires", list()))) {
    if (startsWith(r, "udf:")) return(r)            # this runtime places no UDF language
    if (!(r %in% names(native_extensions()))) return(r)
  }
  NULL
}

ok <- function() jobj(ok = TRUE, detail = "")
# Whether every object lists its members in the same order (kernel section 1), recursively.
same_order <- function(a, b) {
  if (is_obj(a) && is_obj(b)) {
    if (!identical(as.character(names(a)), as.character(names(b)))) return(FALSE)
    for (i in seq_along(a)) if (!same_order(a[[i]], b[[i]])) return(FALSE)
    return(TRUE)
  }
  if (is_arr(a) && is_arr(b) && length(a) == length(b)) { for (i in seq_along(a)) if (!same_order(a[[i]], b[[i]])) return(FALSE) }
  TRUE
}
compare <- function(expected, got, what, ordered = FALSE) {
  detail <- function(why) paste0(what, why, "\n--- expected\n", json_text(expected, spaced = TRUE), "\n--- got\n", json_text(got, spaced = TRUE))
  if (!json_equal(expected, got)) return(jobj(ok = FALSE, detail = detail(" mismatch")))
  if (ordered && !same_order(expected, got)) return(jobj(ok = FALSE, detail = detail(": member order differs (the case is ordered, kernel section 9)")))
  ok()
}

message_parts <- function(r) { m <- if (is_obj(r) && is_obj(get_key(r, "message"))) r$message else r; if (is_obj(m) && is_arr(get_key(m, "parts"))) m$parts else list() }
finish_reason_of <- function(r) if (is_obj(r) && is_obj(get_key(r, "message"))) get_key(r, "finish_reason") else NULL
with_text <- function(part, t) set_key(part, "text", t)

chunkings <- function(response) {
  if (is_str(response)) {
    cs <- chars_of(response)
    out <- list(list(response), as.list(cs$ch))
    for (o in c(0L, cumsum(cs$len))) out[[length(out) + 1L]] <- list(bsl(response, 0L, o), bsl(response, o))
    return(out)
  }
  parts <- message_parts(response)
  out <- list(parts)
  for (pi in seq_along(parts)) {
    part <- parts[[pi]]
    t <- if (is_obj(part)) get_key(part, "text") else NULL
    if (!is_str(t)) next
    cs <- chars_of(t)
    each <- lapply(cs$ch, function(ch) with_text(part, ch))
    if (!length(each)) each <- list(part)
    out[[length(out) + 1L]] <- c(parts[seq_len(pi - 1L)], each, parts[-seq_len(pi)])
    for (o in c(0L, cumsum(cs$len))) out[[length(out) + 1L]] <- c(parts[seq_len(pi - 1L)], list(with_text(part, bsl(t, 0L, o)), with_text(part, bsl(t, o))), parts[-seq_len(pi)])
  }
  out
}

feed_chunk <- function(plan, s, response, chunk) {
  if (!is_str(response) && is_str(chunk)) parse_reply(plan, jobj(role = "assistant", parts = list(chunk)))
  feed(s, chunk)
}

delta_text <- function(events) {
  out <- jobj()
  for (e in events) if (e$kind == "field_delta") out[[e$field]] <- paste0(get_key(out, e$field, ""), e$text)
  out
}

check_stream_success <- function(plan, response, reading, raw) {
  baseline <- NULL; chs <- chunkings(response)
  for (n in seq_along(chs)) {
    s <- reply_stream(plan); events <- list()
    res <- tryCatch({
      for (ch in chs[[n]]) events <- c(events, feed_chunk(plan, s, response, ch))
      r <- finish(s, finish_reason_of(response)); events <- c(events, r$events); r
    }, error = function(e) e)
    if (inherits(res, "error")) return(jobj(ok = FALSE, detail = sprintf("stream split %d refused/failed: %s", n - 1L, conditionMessage(res))))
    for (k in c("values", "repairs", "probabilities", "measured_by")) if (!json_equal(reading[[k]], res[[k]])) return(compare(reading[[k]], res[[k]], sprintf("stream split %d %s", n - 1L, k)))
    d <- delta_text(events)
    if (!json_equal(d, raw)) return(compare(raw, d, sprintf("stream split %d deltas against batch raw text", n - 1L)))
    if (is.null(baseline)) baseline <- d else if (!json_equal(d, baseline)) return(compare(baseline, d, sprintf("stream split %d field deltas", n - 1L)))
  }
  ok()
}

check_stream_refusal <- function(plan, response, batch) {
  expected <- describe_refusal(batch); chs <- chunkings(response)
  for (n in seq_along(chs)) {
    s <- reply_stream(plan)
    res <- tryCatch({ for (ch in chs[[n]]) feed_chunk(plan, s, response, ch); finish(s, finish_reason_of(response)); NULL }, error = function(e) e)
    if (is.null(res)) return(jobj(ok = FALSE, detail = sprintf("stream split %d: expected refusal [%s]", n - 1L, batch$code)))
    if (!is_refusal(res)) return(jobj(ok = FALSE, detail = sprintf("stream split %d failed outside Refusal: %s", n - 1L, conditionMessage(res))))
    if (!json_equal(describe_refusal(res), expected)) return(compare(expected, describe_refusal(res), sprintf("stream split %d refusal", n - 1L)))
  }
  ok()
}

trace_chunking <- function(response) {
  if (is_str(response)) return(as.list(chars_of(response)$ch))
  out <- list()
  for (part in message_parts(response)) {
    t <- if (is_obj(part)) get_key(part, "text") else NULL
    if (is_str(t) && nzchar(t)) out <- c(out, lapply(chars_of(t)$ch, function(ch) with_text(part, ch))) else out[[length(out) + 1L]] <- part
  }
  out
}

digest <- function(e) if (e$kind == "field_delta") list(e$kind, e$field, e$text) else list(e$kind, e$field)

stream_trace <- function(plan, response) {
  s <- reply_stream(plan); trace <- list()
  res <- tryCatch({
    for (ch in trace_chunking(response)) trace[[length(trace) + 1L]] <- lapply(feed_chunk(plan, s, response, ch), digest)
    trace[[length(trace) + 1L]] <- lapply(finish(s, finish_reason_of(response))$events, digest)
    NULL
  }, lmcc_refusal = function(e) e)
  if (!is.null(res)) trace[[length(trace) + 1L]] <- jobj(refusal = res$code)
  trace
}

run_case <- function(c) {
  expect <- c$expect; kind <- c$kind; ordered <- isTRUE(get_key(c, "ordered"))
  u <- unclaimed_of(c)
  if (!is.null(u)) return(jobj(ok = TRUE, detail = "", unclaimed = u))
  reg <- registry_for(c)
  stage <- "load"; plan <- NULL
  tryCatch({
    a <- load_adapter(c$entry, reg)
    if (kind == "roundtrip") return(compare(expect$entry, dump_adapter(a, reg), "entry", ordered))
    stage <- "signature"
    sig <- signature_from_list(c$signature)
    stage <- "bind"
    plan <- lmcc_bind(a, sig, get_key(c, "capabilities", jobj()), reg)
    if (kind == "plan") {
      slots <- case_turns(c)[[2]]
      return(compare(jobj(skeleton = expect$skeleton, prefix = expect$prefix), jobj(skeleton = skeleton(plan), prefix = prefix(plan, slots)), "plan", ordered))
    }
    if (kind == "render") {
      ct <- case_turns(c)
      return(compare(expect$request, request_of(render(plan, turn_from_list(ct[[1]]), ct[[2]])), "request", ordered))
    }
    if (kind == "parse") {
      reading <- read_reply(plan, c$response)
      r <- compare(expect$values, reading$values, "values", ordered)
      if (!r$ok) return(r)
      for (k in c("repairs", "probabilities", "measured_by")) if (has_key(expect, k)) { r <- compare(get_key(expect, k), get_key(reading, k), k, ordered); if (!r$ok) return(r) }
      caps <- parse_with_captures(plan, c$response)[[2]]
      raw <- jobj()
      for (n in names(caps)) { t <- capture_text(caps[[n]]); if (nzchar(t)) raw[[n]] <- t }
      result <- check_stream_success(plan, c$response, reading, raw)
      if (result$ok) result$stream_trace <- stream_trace(plan, c$response)
      return(result)
    }
    if (kind == "refuse") {
      if (has_key(c, "inputs")) { stage <- "render"; ct <- case_turns(c); render(plan, turn_from_list(ct[[1]]), ct[[2]]) }
      if (has_key(c, "response")) { stage <- "parse"; parse_reply(plan, c$response) }
      return(jobj(ok = FALSE, detail = sprintf("expected refusal '%s', but nothing refused", expect$code)))
    }
    jobj(ok = FALSE, detail = sprintf("unknown case kind '%s'", kind))
  }, lmcc_refusal = function(err) {
    if (kind == "refuse" && err$code == expect$code && has_key(expect, "at") && stage != expect$at)
      return(jobj(ok = FALSE, detail = sprintf("refusal [%s] fired at %s, the case says %s", err$code, stage, expect$at)))
    if (kind == "refuse" && err$code == expect$code) {
      if (has_key(expect, "fix")) { r <- compare(expect$fix, err$fix, sprintf("fix of [%s]", err$code), ordered); if (!r$ok) return(r) }
      if (identical(get_key(expect, "at"), "parse") && has_key(c, "response") && !is.null(plan)) {
        r <- check_stream_refusal(plan, c$response, err)
        if (r$ok) r$stream_trace <- stream_trace(plan, c$response)
        return(r)
      }
      return(ok())
    }
    jobj(ok = FALSE, detail = sprintf("unexpected refusal [%s]: %s", err$code, err$hint))
  }, error = function(err) jobj(ok = FALSE, detail = sprintf("host error at %s: %s\n%s", stage, conditionMessage(err), paste(deparse(conditionCall(err)), collapse = " "))))
}

con <- file("stdin", encoding = "UTF-8")
open(con)
while (length(line <- readLines(con, n = 1L, encoding = "UTF-8", warn = FALSE)) > 0L) {
  if (!nzchar(trimws(line))) next
  answer <- tryCatch(run_case(parse_json(line)), error = function(e) jobj(ok = FALSE, detail = paste("driver error:", conditionMessage(e))))
  writeLines(enc2utf8(json_text(answer)), stdout(), useBytes = TRUE)
  flush(stdout())
}

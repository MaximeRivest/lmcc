# Observations of the R kernel on each case, for the differential check
# against the Python reference (contract/harness/differential.py).
#
#     Rscript r/tools/probe.R < cases.jsonl

lib <- Sys.getenv("LMCC_R_LIB", file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1]])), "..", ".lib"))
suppressPackageStartupMessages(library(lmcc, lib.loc = lib))
# R's `$` and argument matching complete a partial name (`x$id` finds a member
# "identifier" when "id" is absent): the kernel reads data by exact name, and
# any partial match, like any other warning, fails the run here.
options(warnPartialMatchDollar = TRUE, warnPartialMatchArgs = TRUE, warnPartialMatchAttr = TRUE, warn = 2)
ns <- asNamespace("lmcc")
for (n in c("is_obj", "is_str", "get_key", "has_key", "set_key", "members_of", "pytruthy", "reading_to_list", "step_to_list", "model_step", "as_message")) assign(n, get(n, envir = ns))

refusal_of <- function(e) jobj(code = e$code, fix = e$fix, partial = e$partial, hint = e$hint)
attempt <- function(expr) tryCatch(jobj(ok = expr), lmcc_refusal = function(e) jobj(refused = refusal_of(e)))

observe <- function(c) {
  req <- as.character(unlist(get_key(c, "requires", list())))
  if (any(startsWith(req, "udf:"))) return(jobj(skipped = "udf"))
  reg <- lmcc_registry(extensions = req)
  if ("std" %in% unlist(get_key(c, "vocab", list()))) install_std(reg)
  out <- jobj()
  a <- tryCatch(load_adapter(c$entry, reg), lmcc_refusal = function(e) e)
  if (is_refusal(a)) return(jobj(load = jobj(refused = refusal_of(a))))
  out$dump <- attempt(dump_adapter(a, reg))
  if (!pytruthy(get_key(c, "signature"))) return(out)
  sig <- tryCatch(signature_from_list(c$signature), lmcc_refusal = function(e) e)
  if (is_refusal(sig)) { out$signature <- jobj(refused = refusal_of(sig)); return(out) }
  out$fingerprint <- signature_fingerprint(sig)
  out$signature_dict <- signature_to_list(sig)
  plan <- tryCatch(lmcc_bind(a, sig, get_key(c, "capabilities", jobj()), reg), lmcc_refusal = function(e) e)
  if (is_refusal(plan)) { out$bind <- jobj(refused = refusal_of(plan)); return(out) }
  out$describe <- describe_plan(plan)
  fp <- signature_fingerprint(sig)
  slots <- jobj()
  # Slot names are data: a slot "" is found and written by position.
  for (m in members_of(get_key(c, "turns", jobj()))) slots <- set_key(slots, m[[1]], lapply(m[[2]], function(t) if (has_key(t, "signature")) t else c(jobj(signature = fp), t)))
  out$prefix <- attempt(prefix(plan, slots))
  out$skeleton <- skeleton(plan)
  if (has_key(c, "inputs")) {
    current <- jobj(signature = fp, inputs = c$inputs, steps = get_key(c, "steps", list()))
    out$turn_json <- attempt(turn_to_list(turn_from_list(current)))
    out$slot_json <- attempt({ r <- jobj(); for (m in members_of(slots)) r <- set_key(r, m[[1]], lapply(m[[2]], function(t) turn_to_list(turn_from_list(t)))); r })
    out$render <- attempt({ r <- render(plan, turn_from_list(current), slots); jobj(request = request_of(r, "m"), hash = sha256_of(request_of(r))) })
  }
  if (has_key(c, "response")) {
    resp <- c$response
    out$read <- attempt(reading_to_list(read_reply(plan, resp)))
    out$step <- attempt(step_to_list(model_step(parse_reply(plan, resp), as_message(resp), sha256_of(jobj(messages = list())), plan$calls_field)))
    out$stream <- attempt({
      s <- reply_stream(plan); events <- list()
      parts <- if (is_str(resp)) list(resp) else (if (is_obj(get_key(resp, "message"))) resp$message else resp)$parts
      for (p in parts) events <- c(events, feed(s, p))
      reason <- if (is_obj(resp) && has_key(resp, "message")) get_key(resp, "finish_reason") else NULL
      e <- finish(s, reason)
      jobj(events = c(events, e$events), result = jobj(events = e$events, values = e$values, repairs = e$repairs, probabilities = e$probabilities, measured_by = e$measured_by))
    })
  }
  out
}

con <- file("stdin", encoding = "UTF-8")
open(con)
while (length(line <- readLines(con, n = 1L, encoding = "UTF-8", warn = FALSE)) > 0L) {
  if (!nzchar(trimws(line))) next
  answer <- tryCatch(observe(parse_json(line)), error = function(e) jobj(crash = paste(conditionMessage(e), paste(deparse(conditionCall(e)), collapse = " "))))
  writeLines(enc2utf8(json_text(answer)), stdout(), useBytes = TRUE)
  flush(stdout())
}

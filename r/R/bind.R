# Bind (kernel sections 3-6, 3a): every decision before any money is spent.

output_holes <- function(nodes, sig, holes) {
  for (node in nodes) {
    if (node$kind == "guard") {
      inner <- output_holes(branches(node), sig, list())
      if (length(inner)) refuse("not-readable", "the output pattern cannot sit inside a {% if %} guard: the reply's shape must not depend on which turns were given",
                                fix = jobj(action = "edit-template", path = "template"))
    } else if (over_turns(node)) next
    else if (node$kind == "loop") {
      if (node$source == "outputs" && any(vapply(node$body, function(n) n$kind == "slot" && n$path == paste0(node$var, ".value"), TRUE)))
        holes[[length(holes) + 1L]] <- list("loop", node)
      else holes <- output_holes(node$body, sig, holes)
    } else if (node$kind == "slot") {
      f <- field_named(sig, node$path)
      if (!is.null(f) && f$direction == "output") holes[[length(holes) + 1L]] <- list("slot", node)
    }
  }
  holes
}

derive_reader <- function(p) {
  sig <- p$signature
  found <- list()
  for (i in seq_along(p$adapter$compiled)) {
    nodes <- p$adapter$compiled[[i]]$nodes
    if (is.null(nodes)) next
    holes <- output_holes(nodes, sig, list())
    if (length(holes)) found[[length(found) + 1L]] <- list(i - 1L, nodes, holes)
  }
  if (!length(found)) refuse("not-readable", "parse kind 'derived' needs an output pattern \u2014 an outputs loop containing {f.value}, or output slots \u2014 and the template has none",
                             fix = jobj(action = "edit-template", path = "template"))
  if (length(found) > 1L) refuse("not-readable", sprintf("the output pattern must live in one message; found holes in messages %s", pyrepr(lapply(found, `[[`, 1))),
                                 fix = jobj(action = "edit-template", path = sprintf("template[%d]", found[[2]][[1]])))
  index <- found[[1]][[1]]; nodes <- found[[1]][[2]]; holes <- found[[1]][[3]]
  here <- jobj(action = "edit-template", path = sprintf("template[%d]", index))
  loops <- Filter(function(h) h[[1]] == "loop", holes)
  if (length(loops) > 1L) refuse("not-readable", sprintf("the template has %d output-pattern loops; one pattern", length(loops)), fix = here)
  anchors <- list(); tail <- ""; texts <- list()
  visible <- vapply(p$visible_outputs, function(f) f$name, "")
  if (length(loops)) {
    if (length(holes) != 1L) refuse("not-readable", "an outputs loop and bare output slots cannot both form the pattern", fix = here)
    loop <- loops[[1]][[2]]
    for (f in p$visible_outputs) { pp <- instantiate(loop, f, p, here); anchors[[length(anchors) + 1L]] <- list(f$name, pp[[1]], pp[[2]]) }
    tail <- tail_after(nodes, loop)
  } else {
    texts <- literal_segments(nodes, sig)
    for (h in holes) {
      path <- h[[2]]$path
      if (!(path %in% visible)) next
      anchors[[length(anchors) + 1L]] <- list(path, texts[[paste0("before\u0001", path)]] %||% "", texts[[paste0("after\u0001", path)]] %||% "")
    }
  }
  for (a in anchors) {
    whole <- !length(loops) && length(anchors) == 1L && !nzchar(wstrip(texts[[paste0("rest\u0001", holes[[1]][[2]]$path)]] %||% "x"))
    if (!nzchar(wrstrip(a[[2]])) && !whole) {
      hint <- sprintf("field %s: no literal text before its hole \u2014 nothing anchors the parser; put the field's marker before the hole", pyrepr(a[[1]]))
      if (!length(loops)) hint <- paste0(hint, sprintf(", on the same line: a bare slot's marker is the text on its own line (write 'Answer: {%s}' or '<%s>{%s}</%s>', not a marker on the line above), or use an outputs loop", a[[1]], a[[1]], a[[1]], a[[1]]))
      refuse("not-readable", hint, fix = c(here, jobj(field = a[[1]])))
    }
  }
  seen <- list()
  for (a in anchors) {
    key <- wrstrip(a[[2]])
    if (!is.null(seen[[paste0("k", key)]])) refuse("not-readable", sprintf("fields %s and %s share the anchor %s; anchors must tell fields apart", pyrepr(seen[[paste0("k", key)]]), pyrepr(a[[1]]), pyrepr(key)),
                                                   fix = c(here, jobj(field = a[[1]])))
    seen[[paste0("k", key)]] <- a[[1]]
  }
  derived_reader(anchors, tail, !isTRUE(p$adapter$strict))
}

instantiate <- function(loop, f, p, fix) {
  pre <- character(0); post <- character(0); in_post <- FALSE
  add <- function(s) if (in_post) post <<- c(post, s) else pre <<- c(pre, s)
  for (node in loop$body) {
    if (node$kind == "text") add(node$text)
    else if (node$kind == "slot") {
      pd <- partition_dot(node$path)
      if (!nzchar(pd[[2]])) refuse("not-readable", sprintf("slot {%s} inside the output pattern is not invertible", node$path), fix = c(fix, jobj(slot = node$path)))
      attr <- pd[[3]]
      if (attr == "value") {
        if (in_post) refuse("not-readable", "the output-pattern block has two {f.value} holes per field; one value, one hole", fix = fix)
        in_post <- TRUE
      } else if (attr == "name") add(f$name)
      else if (attr == "desc") add(f$desc %||% "")
      else if (attr == "type") add(f$type %||% "")
      else if (attr == "schema") add(schema_hint(p, f))
      else if (attr == "purpose") add(f$purpose)
      else refuse("not-readable", sprintf("slot {%s} inside the output pattern is not invertible", node$path), fix = c(fix, jobj(slot = node$path)))
    } else refuse("not-readable", "nested loops inside the output-pattern block are not invertible", fix = fix)
  }
  list(paste(pre, collapse = ""), paste(post, collapse = ""))
}

tail_after <- function(nodes, loop) {
  seen <- FALSE; out <- character(0)
  for (node in nodes) {
    if (!seen) { if (identical(node, loop)) seen <- TRUE; next }
    if (node$kind == "text") out <- c(out, node$text) else break
  }
  literal <- paste(out, collapse = "")
  stripped <- sub("^\n+", "", literal)
  if (grepl("\n", stripped, fixed = TRUE)) return(paste0(substr(literal, 1L, nchar(literal) - nchar(stripped)), sub("\n.*$", "", stripped), "\n"))
  literal
}

literal_segments <- function(nodes, sig) {
  out <- list(); prev <- ""; last <- NULL
  firstline <- function(s) sub("\n[\\s\\S]*$", "", s, perl = TRUE)
  for (node in nodes) {
    if (node$kind == "text") { prev <- paste0(prev, node$text); next }
    if (!is.null(last)) out[[paste0("after\u0001", last)]] <- firstline(prev)
    f <- if (node$kind == "slot") field_named(sig, node$path) else NULL
    if (node$kind == "slot" && !is.null(f) && f$direction == "output") {
      out[[paste0("before\u0001", node$path)]] <- if (!is.null(last)) prev else sub("^[\\s\\S]*\n", "", prev, perl = TRUE)
      last <- node$path
    } else last <- NULL
    prev <- ""
  }
  if (!is.null(last)) { out[[paste0("after\u0001", last)]] <- firstline(prev); out[[paste0("rest\u0001", last)]] <- prev }
  out
}

resolve_format <- function(p, f) {
  adp <- p$adapter; reg <- p$registry
  materialize <- function(b, key) if (is_format(b)) b else if (is_reference(b)) named_format(reg, b[["use"]], get_key(b, "options"), sprintf("formats[%s]", pyrepr(key))) else load_udf(b, sprintf("formats[%s]", pyrepr(key)))
  check <- function(fmt, by, key) {
    rebind <- jobj(action = "bind-format", field = f$name, key = key)
    if (!format_accepts(fmt, f)) refuse("format-shape-mismatch", sprintf("field %s: format %s accepts %s, but the field's type/shape is %s", pyrepr(f$name), fmt$name %||% by, pyrepr(as.list(fmt$accepts)), f$type %||% pyrepr(f$shape)), fix = rebind)
    if ((fmt$direction == "in" && f$direction == "output") || (fmt$direction == "out" && f$direction == "input"))
      refuse("format-direction", sprintf("field %s: format %s is %s-only, but the field is an %s", pyrepr(f$name), fmt$name %||% by, fmt$direction, f$direction), fix = rebind)
    list(format = fmt, resolved_by = by, described = NULL, described_by = NULL)
  }
  has <- function(k) !is.null(k) && nzchar(k) && !is.null(adp$formats[[k]]) && !is_description(adp$formats[[k]])
  choice <- NULL
  if (has(f$type)) choice <- check(materialize(adp$formats[[f$type]], f$type), paste0("artifact:", f$type), f$type)
  if (is.null(choice)) for (key in structural_keys(f$shape)) if (has(key)) { choice <- check(materialize(adp$formats[[key]], key), paste0("artifact:", key), key); break }
  if (is.null(choice)) {
    bound <- type_binding(reg, f$type)
    if (!is.null(bound)) choice <- check(bound, paste0("runtime:", f$type), format_key(f$type, f$shape))
  }
  if (is.null(choice)) {
    d <- kernel_default(f$shape)
    if (!is.null(d)) choice <- list(format = d, resolved_by = "kernel", described = NULL, described_by = NULL)
    else if (!is.null(adp$formats[["*"]])) choice <- check(materialize(adp$formats[["*"]], "*"), "artifact:*", "*")
    else refuse("no-format", sprintf("field %s (%s) has a structured shape and no format \u2014 bind one in the artifact under its type name or a structural key, register one for its type at runtime, or ship one",
                                     pyrepr(f$name), f$type %||% pyrepr(f$shape)), fix = jobj(action = "bind-format", field = f$name, key = format_key(f$type, f$shape)))
  }
  keys <- c(if (!is.null(f$type) && nzchar(f$type)) f$type, structural_keys(f$shape), if (choice$resolved_by == "artifact:*") "*")
  for (key in keys) {
    e <- adp$formats[[key]]
    if (is_obj(e) && !is_format(e) && !has_key(e, "language") && has_key(e, "describe")) { choice$described <- e[["describe"]]; choice$described_by <- paste0("artifact:", key); break }
  }
  choice
}

#' Bind an adapter to a signature
#'
#' Joins an adapter, a signature and the model's declared facts into a plan.
#' Every refusal fires here, before any request is sent.
#' @param adapter An adapter.
#' @param signature A signature.
#' @param capabilities A named list of declared facts (`list(instruct = TRUE)`).
#' @param registry A registry.
#' @export
lmcc_bind <- function(adapter, signature, capabilities = list(), registry = default_registry()) {
  p <- new.env(parent = emptyenv())
  class(p) <- "lmcc_plan"
  p$adapter <- adapter; p$signature <- signature; p$capabilities <- as_obj(capabilities); p$registry <- registry
  p$resolved <- list(); p$find_rules <- list(); p$rule_owner <- list(); p$puts <- list(); p$written_as <- list()
  p$tell <- jobj(); p$request_settings <- jobj(); p$formats <- list(); p$turn_input_formats <- list(); p$turn_writers <- list()
  p$calls_field <- NULL; p$calls_owner <- NULL; p$replay_types <- character(0); p$prefill <- ""
  caps <- p$capabilities; sig <- signature
  p$extensions <- resolve_extensions(adapter, registry)

  by_purpose <- list()
  for (f in sig$fields) {
    if (f$purpose == "plain") next
    if (!is.null(by_purpose[[f$purpose]])) refuse("purpose-ambiguous", sprintf("purpose %s appears on both %s and %s; a purpose may bind to one field", pyrepr(f$purpose), pyrepr(by_purpose[[f$purpose]]$name), pyrepr(f$name)),
                                                  fix = jobj(action = "edit-signature", field = f$name, purpose = f$purpose))
    by_purpose[[f$purpose]] <- f
  }
  hidden <- character(0)
  setting_owner <- new.env()
  for (f in sig$fields) {
    if (f$purpose == "plain") next
    b <- adapter$transports[[f$purpose]]
    if (is.null(b)) next
    if (is_transport(b)) { t <- b; name <- "(inline)" }
    else { name <- b[["use"]]; t <- named_transport(registry, name, get_key(b, "options"), sprintf("transports[%s]", pyrepr(f$purpose))) }
    t <- bound_transport(select_transport(t, caps, f$purpose, name), f$name)
    res <- list(purpose = f$purpose, field = f, transport = t, name = name)
    p$resolved[[length(p$resolved) + 1L]] <- res
    target <- function(ref, what) {
      if (ref == "@purpose") return(f)
      sub <- substring(ref, 10L)
      tf <- by_purpose[[paste0(f$purpose, ".", sub)]]
      if (is.null(tf)) refuse("unknown-slot", sprintf("purpose %s: transport %s %s targets %s, but no field bears the purpose %s", pyrepr(f$purpose), pyrepr(name), what, pyrepr(ref), pyrepr(paste0(f$purpose, ".", sub))),
                              fix = jobj(action = "assign-purpose", purpose = paste0(f$purpose, ".", sub)))
      tf
    }
    if (!t$in_template || length(t$put)) hidden <- c(hidden, f$name)
    for (r in t$find) {
      tf <- target(r[["to"]], "rule")
      p$find_rules[[length(p$find_rules) + 1L]] <- list(tf$name, drop_key(r, "to"))
      p$rule_owner[[length(p$rule_owner) + 1L]] <- res
      if (tf$name != f$name) hidden <- c(hidden, tf$name)
      if (r[["to"]] == "@purpose.calls" && tf$direction == "output") { p$calls_field <- tf$name; p$calls_owner <- res }
    }
    for (ref in names(t$put)) {
      tf <- target(ref, "put")
      p$puts[[length(p$puts) + 1L]] <- list(tf$name, t$put[[ref]])
      hidden <- c(hidden, tf$name)
      if (has_key(t$written_as, ref)) p$written_as[[tf$name]] <- named_format(registry, t$written_as[[ref]], jobj(), sprintf("transports[%s].written_as", pyrepr(f$purpose)))
    }
    for (role in names(t$tell)) {
      existing <- get_key(p$tell, role)
      p$tell[[role]] <- if (pytruthy(existing)) paste0(existing, "\n", t$tell[[role]]) else t$tell[[role]]
    }
    for (leaf in setting_leaves(t$request_settings))
      merge_setting(p, leaf[[1]], leaf[[2]], f$purpose, setting_owner, sprintf("transports[%s].request_settings[%s]", pyrepr(f$purpose), pyrepr(leaf[[1]])))
  }

  p$visible_inputs <- Filter(function(f) !(f$name %in% hidden), sig_inputs(sig))
  p$visible_outputs <- Filter(function(f) !(f$name %in% hidden), sig_outputs(sig))

  for (f in sig$fields) p$formats[[f$name]] <- resolve_format(p, f)
  routed <- list()
  for (fr in p$find_rules) {
    kind <- if (startsWith(fr[[2]][["from"]], "part:")) substring(fr[[2]][["from"]], 6L) else "text"
    routed[[fr[[1]]]] <- unique(c(routed[[fr[[1]]]], kind))
  }
  for (fname in names(routed)) {
    fmt <- p$formats[[fname]]$format; f <- field_named(sig, fname)
    if (!("*" %in% fmt$reads) && !all(routed[[fname]] %in% fmt$reads))
      refuse("format-capture-mismatch", sprintf("field %s: its find rules deliver %s parts, but its format %s reads %s", pyrepr(fname), sorted_repr(routed[[fname]]), fmt$name %||% "(inline)", pyrepr(as.list(fmt$reads))),
             fix = jobj(action = "bind-format", field = fname, key = format_key(f$type, f$shape)))
  }
  for (pp in p$puts) {
    fname <- pp[[1]]; place <- pp[[2]]
    fmt <- p$written_as[[fname]] %||% p$formats[[fname]]$format; f <- field_named(sig, fname)
    if (startsWith(place, "request.") && fmt$writes != "parts")
      refuse("format-put-mismatch", sprintf("field %s: put %s needs parts, but its format %s writes text", pyrepr(fname), pyrepr(place), fmt$name %||% "(inline)"),
             fix = jobj(action = "bind-format", field = fname, key = format_key(f$type, f$shape)))
  }

  p$reader <- if (adapter$reader[["kind"]] == "derived") derive_reader(p) else named_reader(registry, adapter$reader)
  delims <- unlist(lapply(p$find_rules, function(fr) if (pytruthy(get_key(fr[[2]], "repair"))) unlist(fr[[2]][["between"]]) else NULL))
  rm <- if (isTRUE(adapter$strict)) list(character(0), character(0)) else repairable_markers(as.character(delims))
  p$find_repairable <- rm[[1]]; p$find_unrepaired <- rm[[2]]
  for (fact in p$reader$requires()) if (!pytruthy(get_key(caps, fact)))
    refuse("capability-missing", sprintf("reader %s requires capability %s, which the model does not declare \u2014 use an invertible pattern instead", pyrepr(adapter$reader[["kind"]]), pyrepr(fact)),
           fix = jobj(action = "declare-capability", fact = fact))
  for (leaf in setting_leaves(p$reader$request_settings(p$visible_outputs) %||% jobj())) {
    validate_setting_path(leaf[[1]], "parse")
    merge_setting(p, leaf[[1]], leaf[[2]], "(reader)", setting_owner, sprintf("transports[%s].request_settings[%s]", pyrepr(setting_owner[[leaf[[1]]]]), pyrepr(leaf[[1]])))
  }
  stops <- get_key(p$reader$skeleton(), "stops") %||% list()
  if (pytruthy(get_key(caps, "stop_sequences")) && length(stops))
    merge_setting(p, "config.stop", stops, "(skeleton)", setting_owner, sprintf("transports[%s].request_settings['config.stop']", pyrepr(setting_owner[["config.stop"]])))

  overlaps <- function(a, b) a == b || startsWith(a, paste0(b, ".")) || startsWith(b, paste0(a, "."))
  fixed <- vapply(setting_leaves(p$request_settings), `[[`, "", 1)
  seen_puts <- list()
  for (pp in p$puts) {
    fname <- pp[[1]]; place <- pp[[2]]
    if (!startsWith(place, "request.")) next
    path <- substring(place, 9L)
    where <- sprintf("transports[%s].put", pyrepr(strsplit(field_named(sig, fname)$purpose, ".", fixed = TRUE)[[1]][[1]]))
    clash <- Filter(function(q) overlaps(path, q), fixed)
    other <- Filter(function(sp) overlaps(path, sp[[2]]), seen_puts)
    if (length(clash) || length(other))
      refuse("setting-conflict", paste0(sprintf("field %s is put at request %s, which ", pyrepr(fname), pyrepr(path)),
                                        if (length(clash)) sprintf("the request setting %s also sets", pyrepr(clash[[1]])) else sprintf("field %s is also put at", pyrepr(other[[1]][[1]])),
                                        " \u2014 one would silently overwrite the other"), fix = jobj(action = "edit-entry", path = where))
    seen_puts[[length(seen_puts) + 1L]] <- list(fname, path)
  }

  known <- vapply(sig$fields, function(f) f$name, "")
  input_names <- vapply(p$visible_inputs, function(f) f$name, "")
  covered <- character(0)
  slot_names <- names(adapter_turn_slots(adapter))
  for (i in seq_along(adapter$compiled)) {
    nodes <- adapter$compiled[[i]]$nodes
    if (!is.null(nodes)) covered <- c(covered, validate_nodes(nodes, known, input_names, sprintf("template[%d]", i - 1L), slots = slot_names))
  }
  uncovered <- ssort(setdiff(input_names, covered))
  if (length(uncovered)) refuse("field-uncovered", paste0("input field(s) never rendered by the template: ", paste(vapply(uncovered, pyrepr, ""), collapse = ", ")),
                                fix = jobj(action = "edit-template", path = "template", field = uncovered[[1]]))

  put_inputs <- unique(unlist(lapply(p$puts, function(pp) if (field_named(sig, pp[[1]])$direction == "input") pp[[1]] else NULL)))
  for (i in seq_along(adapter$compiled)) {
    nodes <- adapter$compiled[[i]]$nodes
    if (is.null(nodes)) next
    for (fname in ssort(intersect(bare_slots(nodes), put_inputs)))
      refuse("field-double-covered", sprintf("template[%d]: input %s has a slot here and is also put by its transport \u2014 it would be sent twice; drop the slot or the put", i - 1L, pyrepr(fname)),
             fix = jobj(action = "edit-template", path = sprintf("template[%d]", i - 1L), field = fname))
  }
  visible_out <- vapply(p$visible_outputs, function(f) f$name, "")
  for (fr in p$find_rules) if (fr[[1]] %in% visible_out)
    refuse("field-double-covered", sprintf("field %s is both a parsed section and a rule target \u2014 hide it (in_template: false) or drop the rule", pyrepr(fr[[1]])),
           fix = jobj(action = "edit-entry", path = sprintf("transports[%s].in_template", pyrepr(field_named(sig, fr[[1]])$purpose))))

  if (!is.null(p$calls_owner)) for (r in p$resolved) {
    if (!identical(r$purpose, p$calls_owner$purpose) && (has_key(r$transport$spelling, "call") || has_key(r$transport$spelling, "result"))) {
      where <- sprintf("transports[%s].spelling", pyrepr(r$purpose))
      malformed(where, sprintf("%s: spelling.call/spelling.result belong to the transport that owns the calls field (%s); here they would be a second spelling of one call, or a spelling nothing uses", where, pyrepr(p$calls_owner$purpose)))
    }
  }
  for (r in p$resolved) {
    if (!has_key(r$transport$spelling, "call")) next
    cf <- Filter(function(fr) field_named(sig, fr[[1]])$purpose == paste0(r$purpose, ".calls"), p$find_rules)
    calls_field <- if (length(cf)) cf[[1]][[1]] else NULL
    ref <- get_key(r$transport$spelling, "input_format")
    if (!is.null(ref)) {
      where <- sprintf("transports[%s].spelling.input_format", pyrepr(r$purpose))
      fmt <- named_format(registry, ref[["use"]], get_key(ref, "options"), where)
      if (fmt$writes != "text" || !(fmt$direction %in% c("in", "both")) || !format_accepts(fmt, INPUT_FIELD)) malformed(where, sprintf("%s: must write an object as text", where))
      p$turn_input_formats[[r$purpose]] <- fmt
    }
    if (is.null(calls_field)) {
      if (!is.null(ref) || has_key(r$transport$spelling, "probe"))
        refuse("spelling-drift", sprintf("purpose %s: formatted turns need an @purpose.calls target", pyrepr(r$purpose)), fix = jobj(action = "edit-entry", path = sprintf("transports[%s].spelling", pyrepr(r$purpose))))
      next
    }
    probe <- c(jobj(id = "probe"), get_key(r$transport$spelling, "probe") %||% jobj(name = "probe", input = jobj(probe = TRUE)))
    probe <- probe[!duplicated(names(probe), fromLast = TRUE)]
    own <- Filter(function(fr) fr[[1]] == calls_field && fr[[2]][["from"]] == "text", p$find_rules)
    read_back <- NULL; spelled <- "(writer refused)"
    tryCatch({
      spelled <- call_text(p, r, probe)
      got <- apply_find_rules(spelled, list(), own, pattern_binding(p))[[2]]
      if (!is.null(got[[calls_field]]) && length(got[[calls_field]]$parts)) read_back <- read_field(p, field_named(sig, calls_field), got[[calls_field]])
    }, lmcc_refusal = function(e) NULL)
    first <- if (is_arr(read_back) && length(read_back) == 1L) read_back[[1]] else NULL
    ok <- is_obj(first) && identical(get_key(first, "name"), probe[["name"]]) && json_equal(get_key(first, "input"), probe[["input"]])
    if (!ok) refuse("spelling-drift", sprintf("purpose %s: transport %s: spelling.call spells a call as %s, and its own find rule and format read back %s \u2014 the spelling and the reader disagree",
                                              pyrepr(r$purpose), pyrepr(r$name), pyrepr(spelled), pyrepr(read_back)),
                    fix = jobj(action = "edit-entry", path = sprintf("transports[%s].spelling", pyrepr(r$purpose))))
  }

  p$slots <- adapter_turn_slots(adapter)
  p$prefill <- if (pytruthy(get_key(caps, "assistant_prefill"))) wrstrip(adapter_prefill(adapter) %||% "") else ""
  bind_turns(p)
  p
}

bind_turns <- function(p) {
  sig <- p$signature; compiled <- p$adapter$compiled
  for (name in names(p$slots)) if (!is.null(field_named(sig, name)))
    refuse("turns-layout", sprintf("template[%d]: turn slot %s has the name of a signature field; rename the slot", p$slots[[name]][[2]], pyrepr(name)),
           fix = jobj(action = "edit-template", path = sprintf("template[%d]", p$slots[[name]][[2]])))
  names_in <- vapply(p$visible_inputs, function(f) f$name, "")
  live <- NULL
  for (i in seq_along(compiled)) if (!is.null(compiled[[i]]$nodes) && !identical(compiled[[i]]$msg[["role"]], "system") && depends_on_inputs(compiled[[i]]$nodes, names_in)) { live <- i - 1L; break }
  for (name in names(p$slots)) {
    form <- p$slots[[name]][[1]]; i <- p$slots[[name]][[2]]
    if (form != "messages" || is.null(live)) next
    if (name != "steps" && i > live) refuse("turns-layout", sprintf("template[%d]: turn slot %s comes after the message that renders the live input (template[%d]); past turns go before it", i, pyrepr(name), live),
                                            fix = jobj(action = "edit-template", path = sprintf("template[%d]", i)))
    if (name == "steps" && i < live) refuse("turns-layout", sprintf("template[%d]: the current turn's steps come after the message that renders its input (template[%d])", i, live),
                                            fix = jobj(action = "edit-template", path = sprintf("template[%d]", i)))
  }
  if (!length(p$slots)) return(invisible())
  drift <- function(field, owner, why) refuse("spelling-drift", sprintf("field %s: %s", pyrepr(field), why), fix = jobj(action = "edit-entry", path = sprintf("transports[%s].spelling", pyrepr(owner$purpose))))
  groups <- list()
  for (k in seq_along(p$find_rules)) {
    fname <- p$find_rules[[k]][[1]]; r <- p$find_rules[[k]][[2]]
    if (field_named(sig, fname)$direction != "output") next
    key <- if (startsWith(r[["from"]], "part:")) paste0("channel\u0001", r[["from"]]) else {
      kk <- intersect(c("between", "line_prefixed", "pattern"), names(r))[[1]]
      paste0(kk, "\u0001", json_text(r[[kk]]))
    }
    groups[[key]] <- c(groups[[key]], list(list(fname, r, p$rule_owner[[k]])))
  }
  writers <- list(); replay <- character(0)
  for (key in names(groups)) {
    if (!startsWith(key, "channel\u0001")) next
    nms <- vapply(groups[[key]], `[[`, "", 1)
    if (!is.null(p$calls_field) && p$calls_field %in% nms) {
      writers[[p$calls_field]] <- jobj(by = "format:parts")
      for (o in nms) if (o != p$calls_field) writers[[o]] <- jobj(by = "projection", of = p$calls_field)
    } else {
      replay <- c(replay, sub("^part:", "", sub("^channel\u0001", "", key)))
      for (n in nms) writers[[n]] <- jobj(by = "replayed")
    }
  }
  p$replay_types <- replay
  for (key in names(groups)) {
    if (startsWith(key, "channel\u0001")) next
    members <- groups[[key]]
    nms <- vapply(members, `[[`, "", 1)
    if (!is.null(p$calls_field) && p$calls_field %in% nms) {
      owner <- p$calls_owner
      if (!has_key(owner$transport$spelling, "call")) drift(p$calls_field, owner, "calls are read from text, but the transport has no spelling.call to write past calls")
      writers[[p$calls_field]] <- jobj(by = "spelling.call", position = "after")
      for (o in nms) if (o != p$calls_field) writers[[o]] <- jobj(by = "projection", of = p$calls_field)
      next
    }
    distinct <- unique(nms)
    if (length(distinct) > 1L) drift(nms[[2]], members[[2]][[3]], sprintf("fields %s read the same capture and none of them is the calls field; which writes it is ambiguous", sorted_repr(distinct)))
    fname <- members[[1]][[1]]; r <- members[[1]][[2]]; owner <- members[[1]][[3]]
    sp <- owner$transport$spelling
    position <- get_key(sp, "position", "after")
    if (has_key(sp, "value")) writers[[fname]] <- if (is.null(sp[["value"]])) jobj(by = "dropped") else jobj(by = "spelling.value", template = sp[["value"]], position = position)
    else if (!pytruthy(get_key(r, "remove"))) { writers[[fname]] <- jobj(by = "projection", of = "the reader body"); next }
    else if (has_key(r, "between")) writers[[fname]] <- jobj(by = "derived:between", between = r[["between"]], position = position)
    else if (has_key(r, "line_prefixed")) writers[[fname]] <- jobj(by = "derived:line_prefixed", prefix = r[["line_prefixed"]], position = position)
    else drift(fname, owner, "a pattern rule has a reader but no writer; declare spelling.value (text with {value}) or spelling.value: null to drop it on purpose")
    if (writers[[fname]][["by"]] != "dropped") {
      fmt <- format_for(p, field_named(sig, fname))
      if (!isTRUE(fmt$round_trip) || fmt$writes != "text" || !(fmt$direction %in% c("both", "in")))
        drift(fname, owner, sprintf("its format %s cannot write the value back as text (it reads only, is lossy, or writes parts), so a past value cannot be written into a turn; give it a write, or spelling.value: null", fmt$name %||% "(inline)"))
    }
  }
  if (!is.null(p$calls_field)) {
    fmt <- format_for(p, field_named(sig, p$calls_field))
    if (!(fmt$direction %in% c("both", "in"))) drift(p$calls_field, p$calls_owner, sprintf("its format %s only reads, so past calls cannot be written", fmt$name %||% "(inline)"))
  }
  p$turn_writers <- writers
  invisible()
}

#' @rdname describe_registry
#' @export
describe_plan <- function(x) {
  p <- x
  found <- vapply(p$find_rules, `[[`, "", 1)
  info <- function(f) {
    c <- p$formats[[f$name]]
    d <- jobj(name = f$name, type = f$type, shape = f$shape, format = c$format$name %||% "(inline)", resolved_by = c$resolved_by)
    d <- set_key(d, "type", f$type)
    if (!is.null(c$described_by)) d[["described_by"]] <- c$described_by
    d
  }
  vi <- vapply(p$visible_inputs, function(f) f$name, ""); vo <- vapply(p$visible_outputs, function(f) f$name, "")
  out <- jobj(adapter = p$adapter$name, reader = jobj(kind = p$adapter$reader[["kind"]]), capabilities = p$capabilities,
    inputs = lapply(p$visible_inputs, info), outputs = lapply(p$visible_outputs, function(f) c(info(f), jobj(found = f$name %in% found))),
    hidden = as.list(Filter(function(n) !(n %in% c(vi, vo)), vapply(p$signature$fields, function(f) f$name, ""))),
    transports = as_obj(structure(lapply(p$resolved, function(r) r$name), names = vapply(p$resolved, function(r) r$purpose, ""))),
    extensions = as_obj(lapply(p$extensions[ssort(names(p$extensions))], function(r) jobj(needs = r$needs, provides = r$binding$version, binding = r$binding$binding))),
    find = lapply(p$find_rules, function(fr) c(jobj(field = fr[[1]]), fr[[2]])), puts = lapply(p$puts, function(pp) jobj(field = pp[[1]], at = pp[[2]])),
    tell = p$tell, request_settings = p$request_settings, strict = isTRUE(p$adapter$strict))
  pf <- adapter_prefill(p$adapter)
  if (!is.null(pf)) out[["prefill"]] <- jobj(text = wrstrip(pf), sent = nzchar(p$prefill))
  out[["skeleton"]] <- skeleton(p)
  out[["streaming"]] <- describe_streaming(p)
  if (inherits(p$reader, "lmcc_derived_reader")) {
    out[["reader"]][["anchors"]] <- lapply(p$reader$anchors, function(a) list(a[[1]], a[[2]], a[[3]]))
    if (length(p$reader$unrepaired)) out[["reader"]][["unrepaired"]] <- as.list(p$reader$unrepaired)
    if (nzchar(p$reader$tail)) out[["reader"]][["tail"]] <- p$reader$tail
  } else if (!is.null(p$reader$spec)) for (k in setdiff(names(p$reader$spec), "kind")) out[["reader"]] <- set_key(out[["reader"]], k, p$reader$spec[[k]])
  vocab <- jobj()
  for (c in p$formats) if (!is.null(c$format$name) && !is.null(p$registry$formats[[c$format$name]])) vocab[[paste0("format/", c$format$name)]] <- p$registry$formats[[c$format$name]]$version
  for (r in p$resolved) if (!is.null(p$registry$transports[[r$name]])) vocab[[paste0("transport/", r$name)]] <- p$registry$transports[[r$name]]$version
  k <- p$adapter$reader[["kind"]]
  if (!is.null(p$registry$readers[[k]])) vocab[[paste0("reader/", k)]] <- p$registry$readers[[k]]$version
  turn_info <- jobj()
  for (r in p$resolved) if (!is.null(p$turn_input_formats[[r$purpose]])) {
    ref <- r$transport$spelling[["input_format"]]
    v <- p$registry$formats[[ref[["use"]]]]$version
    vocab[[paste0("format/", ref[["use"]])]] <- v
    turn_info[[r$purpose]] <- jobj(input_format = ref, version = v)
  }
  w <- p$turn_writers
  out[["turns"]] <- jobj(slots = lapply(names(p$slots), function(n) jobj(name = n, form = p$slots[[n]][[1]])),
    steps = if (!length(p$slots)) NULL else if (!is.null(p$slots[["steps"]])) "placed" else "after the template",
    replay = p$adapter$replay,
    writers = as_obj(w[vapply(w, function(v) !(v[["by"]] %in% c("projection", "replayed")), TRUE)]),
    projections = as_obj(lapply(w[vapply(w, function(v) v[["by"]] == "projection", TRUE)], function(v) v[["of"]])),
    replayed = as.list(ssort(names(w)[vapply(w, function(v) v[["by"]] == "replayed", TRUE)])),
    input_formats = turn_info)
  out <- set_key(out, "turns", out[["turns"]])
  out[["turns"]] <- set_key(out[["turns"]], "steps", if (!length(p$slots)) NULL else if (!is.null(p$slots[["steps"]])) "placed" else "after the template")
  out[["versions"]] <- jobj(kernel = KERNEL_VERSION, vocab = vocab)
  out
}

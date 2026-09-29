# The adapter (kernel section 2) and the artifact (serde: sections 5, 6, 9, 10).

KERNEL_VERSION <- "0.8.4"
REPLAY <- c("recorded", "values", "verbatim")

#' Template messages and the turn slot directive
#' @param text Template text.
#' @param slot A turn slot name.
#' @export
system_msg <- function(text) jobj(role = "system", text = text)
#' @rdname system_msg
#' @export
developer_msg <- function(text) jobj(role = "developer", text = text)
#' @rdname system_msg
#' @export
user_msg <- function(text) jobj(role = "user", text = text)
#' @rdname system_msg
#' @export
assistant_msg <- function(text) jobj(role = "assistant", text = text)
#' @rdname system_msg
#' @export
turns_slot <- function(slot = "turns") if (slot == "turns") jobj(directive = "turns") else jobj(directive = "turns", slot = slot)
#' A reference to a named format or transport
#' @param name The registered name.
#' @param ... Options.
#' @export
use_vocab <- function(name, ...) jobj(use = name, options = jobj(...))

is_description <- function(b) is_obj(b) && length(b) == 1L && identical(names(b), "describe")
is_reference <- function(b) is_obj(b) && has_key(b, "use")

adapter_prefill <- function(a) {
  n <- length(a$template)
  if (!n) return(NULL)
  last <- a$template[[n]]
  if (identical(get_key(last, "role"), "assistant")) last[["text"]] else NULL
}

adapter_turn_slots <- function(a) {
  slots <- list(); guards <- list()
  for (i in seq_along(a$compiled)) {
    msg <- a$compiled[[i]]$msg; nodes <- a$compiled[[i]]$nodes; idx <- i - 1L
    if (is.null(nodes)) { placed <- get_key(msg, "slot", "turns"); guarded <- character(0); form <- "messages" }
    else { r <- node_turn_slots(nodes); placed <- r[[1]]; guarded <- r[[2]]; form <- "text" }
    for (name in placed) {
      if (!is.null(slots[[name]])) refuse("template-syntax", sprintf("template[%d]: turn slot %s is already placed at template[%d]; a slot is placed once", idx, pyrepr(name), slots[[name]][[2]]),
                                          fix = jobj(action = "edit-template", path = sprintf("template[%d]", idx)))
      slots[[name]] <- list(form, idx)
    }
  }
  slots
}

description_of <- function(value, where) {
  if (!has_key(value, "describe")) return(jobj())
  t <- value[["describe"]]
  if (!is_str(t) || !nzchar(t)) malformed(paste0(where, ".describe"), sprintf("%s.describe: a description is non-empty text", where))
  jobj(describe = t)
}

format_entry <- function(key, value) {
  where <- sprintf("formats[%s]", pyrepr(key))
  if (is_str(value)) return(jobj(use = value, options = jobj()))
  if (is_format(value)) return(value)
  if (is_obj(value) && has_key(value, "use")) {
    extra <- ssort(setdiff(names(value), c("use", "options", "describe")))
    if (length(extra) || !is_obj(get_key(value, "options", jobj())))
      malformed(where, paste0(where, ": a reference is {use, options?, describe?}", if (length(extra)) paste0(", not ", pyrepr(as.list(extra))) else ""))
    return(c(jobj(use = value[["use"]], options = as_obj(get_key(value, "options", jobj()))), description_of(value, where)))
  }
  if (is_obj(value) && has_key(value, "language")) return(as_obj(value))
  if (is_obj(value) && has_key(value, "describe")) {
    if (length(value) != 1L) malformed(where, sprintf("%s: a description is {describe} alone, not %s", where, sorted_repr(setdiff(names(value), "describe"))))
    d <- description_of(value, where)
    if (key == "*") malformed(where, sprintf("%s: a description alone under '*' describes nothing \u2014 '*' reaches only fields no other step spells, and a description chooses no format; put it on the reference ({\"use\": ..., \"describe\": ...}) or under a type or key", where))
    return(d)
  }
  malformed(where, sprintf("%s: expected a name, use_vocab(...), a shipped format, a description {describe}, or a format", where))
}

#' An adapter
#'
#' A template, a reader, transports by purpose, formats by type — never a
#' field name. It meets a signature at [lmcc_bind()].
#' @param messages Template messages and directives ([system_msg()], [turns_slot()], ...).
#' @param reader `list(kind = "derived")` (default) or a registered reader's spec.
#' @param transports Named list: purpose to a name, [use_vocab()], [new_transport()] or transport data.
#' @param formats Named list: type name or structural key to a name, [use_vocab()], a description or a format.
#' @param name,extensions,replay,strict The artifact's other keys.
#' @param declare_defaults An inline `pattern` rule declares `pattern/legacy-re2` (section 10).
#' @export
adapter <- function(messages, reader = NULL, transports = NULL, formats = NULL, name = "adapter", extensions = NULL,
                    replay = "recorded", strict = FALSE, declare_defaults = TRUE) {
  if (!is.list(messages) || is_obj(messages)) malformed("template", "template must be a list of messages and directives")
  for (i in seq_along(messages)) {
    m <- messages[[i]]; at <- sprintf("template[%d]", i - 1L)
    if (!is_obj(m) || !((has_key(m, "role") && has_key(m, "text")) || has_key(m, "directive"))) malformed(at, sprintf("%s: a message is {role, text} or {directive}", at))
    if (has_key(m, "directive")) {
      slot <- get_key(m, "slot", "turns")
      if (!identical(m[["directive"]], "turns") || length(setdiff(names(m), c("directive", "slot"))) || !is_str(slot) || !grepl("^[A-Za-z_][A-Za-z0-9_]*$", slot, perl = TRUE))
        malformed(at, sprintf("%s: a directive is {\"directive\": \"turns\", \"slot\"?: name} (demos and history are turn slots since kernel 0.7)", at))
      if (slot %in% RESERVED_SLOTS) refuse("template-syntax", sprintf("%s: %s is reserved, not a turn slot", at, pyrepr(slot)), fix = jobj(action = "edit-template", path = at))
    }
    if (has_key(m, "role") && !isTRUE(m[["role"]] %in% c("system", "developer", "user", "assistant"))) malformed(at, sprintf("%s: role must be system/developer/user/assistant", at))
    if (identical(get_key(m, "role"), "system") && i > 1L &&
        any(vapply(messages[seq_len(i - 1L)], function(x) (has_key(x, "role") && !identical(x[["role"]], "system")) || has_key(x, "directive"), TRUE)))
      malformed(at, sprintf("%s: system messages lead the template (they become the lm15 request's system field); put later instructions in a developer message", at))
  }
  if (!(is_str(replay) && replay %in% REPLAY)) malformed("replay", sprintf("replay must be one of %s, not %s", pyrepr(as.list(REPLAY)), pyrepr(replay)))
  rd <- if (is.null(reader)) jobj(kind = "derived") else reader
  if (!is_obj(rd)) malformed("reader", "entry.reader must be an object")
  kind <- get_key(rd, "kind")
  if (!is_str(kind) || !nzchar(kind)) refuse("unknown-reader", "reader.kind must name a reader", fix = jobj(action = "edit-entry", path = "reader"))
  if (kind == "derived" && length(rd) != 1L) malformed("reader", sprintf("reader: the derived reader takes only 'kind', not %s", sorted_repr(setdiff(names(rd), "kind"))))
  if (!is_bool(strict)) malformed("strict", sprintf("strict must be true or false, not %s", pyrepr(strict)))
  sb <- list()
  for (purpose in names(transports)) {
    value <- transports[[purpose]]; where <- sprintf("transports[%s]", pyrepr(purpose))
    sb[[purpose]] <- if (is_str(value)) jobj(use = value, options = jobj())
      else if (is_transport(value)) { validate_transport(value, where); value }
      else if (is_obj(value) && has_key(value, "use")) jobj(use = value[["use"]], options = as_obj(get_key(value, "options")))
      else if (is_obj(value)) transport_from_list(value, where)
      else malformed(where, sprintf("%s: expected a name, a transport, use_vocab(...), or transport data", where))
  }
  fb <- list()
  for (m in members_of(formats)) fb <- set_key(fb, m[[1]], format_entry(m[[1]], m[[2]]))
  declared <- validate_declaration(extensions)
  if (declare_defaults) declared <- default_declaration(sb, declared)
  a <- list(template = lapply(messages, as_obj), reader = as_obj(rd), transports = sb, formats = fb, name = name,
            extensions = declared, replay = replay, strict = strict)
  a$compiled <- lapply(seq_along(a$template), function(i) {
    m <- a$template[[i]]
    list(msg = m, nodes = if (has_key(m, "directive")) NULL else compile_template(m[["text"]], sprintf("template[%d]", i - 1L)))
  })
  n <- length(a$compiled)
  if (n) {
    last <- a$compiled[[n]]
    if (identical(get_key(last$msg, "role"), "assistant") && !is.null(last$nodes) && any(vapply(last$nodes, function(x) x$kind != "text", TRUE)))
      refuse("template-syntax", sprintf("template[%d]: a last assistant message is the reply's prefill (kernel \u00a73) and holds literal text only, no slots, loops or guards", n - 1L),
             fix = jobj(action = "edit-template", path = sprintf("template[%d]", n - 1L)))
  }
  a <- structure(a, class = "lmcc_adapter")
  adapter_turn_slots(a)
  a
}

# --------------------------------------------------------------------- serde

parse_version <- function(v, what) {
  if (!is_str(v)) malformed("versions", sprintf("%s: version must be a string", what))
  parts <- strsplit(v, ".", fixed = TRUE)[[1]]
  if (length(parts) != 3L || !all(grepl("^[0-9]+$", parts)) || endsWith(v, ".")) malformed("versions", sprintf("%s: version %s is not MAJOR.MINOR.PATCH", what, pyrepr(v)))
  as.numeric(parts)
}

check_compatible <- function(kind, theirs, ours) {
  t <- parse_version(theirs, kind); o <- parse_version(ours, kind)
  ok <- t[[1]] == o[[1]] && (if (t[[1]] > 0) t[[2]] <= o[[2]] else t[[2]] == o[[2]])
  if (!ok) refuse("version-incompatible", sprintf("%s: artifact needs %s, this implementation provides %s", kind, theirs, ours),
                  fix = jobj(action = "match-version", entry = kind, needs = theirs, provides = ours))
}

check_vocab <- function(ref, declared, provided) if (has_key(declared, ref)) check_compatible(ref, declared[[ref]], provided)

transport_of <- function(reg, binding, where) if (is_transport(binding)) binding else named_transport(reg, binding[["use"]], get_key(binding, "options"), where)

spelling_format_refs <- function(a, reg) {
  out <- list()
  walk <- function(t, where) {
    if (!is.null(t$choose)) { for (i in seq_along(t$choose)) walk(t$choose[[i]]$else_ %||% t$choose[[i]]$use, sprintf("%s.choose[%d]", where, i - 1L)); return(invisible()) }
    validate_spelling(t$spelling, paste0(where, ".spelling"))
    if (has_key(t$spelling, "input_format")) out[[length(out) + 1L]] <<- list(paste0(where, ".spelling.input_format"), t$spelling[["input_format"]])
  }
  for (purpose in names(a$transports)) {
    where <- sprintf("transports[%s]", pyrepr(purpose))
    walk(transport_of(reg, a$transports[[purpose]], where), where)
  }
  out
}

resolve_extensions <- function(a, reg) {
  declared <- validate_declaration(a$extensions)
  resolved <- list()
  for (name in names(declared)) {
    needs <- declared[[name]]
    b <- reg$extensions[[name]]
    if (is.null(b)) refuse("extension-unsupported", sprintf("the artifact declares extension %s %s, and this runtime binds no implementation of it (describe_registry(registry)$extensions lists what it binds)", pyrepr(name), needs),
                           fix = jobj(action = "bind-extension", name = name, needs = needs))
    check_compatible(name, needs, b$version)
    resolved[[name]] <- list(name = name, needs = needs, binding = b)
  }
  by_family <- list(); for (r in resolved) by_family[[family_of(r$name)]] <- r
  for (purpose in names(a$transports)) {
    where <- sprintf("transports[%s]", pyrepr(purpose))
    walk_rules(transport_of(reg, a$transports[[purpose]], where), function(r, path) {
      if (!has_key(r, "pattern")) return(invisible())
      p <- by_family[["pattern"]]
      if (is.null(p)) refuse("extension-undeclared", sprintf("%s: 'pattern' needs a pattern/* extension and the artifact declares none (kernel \u00a710; pattern/legacy-re2 is what 0.2 did)", path),
                             fix = jobj(action = "declare-extension", family = "pattern", path = path))
      p$binding$admit(r[["pattern"]], path)
    }, where)
  }
  resolved
}

#' Load an adapter from its artifact
#'
#' Names resolve only through `registry`; unknown names, malformed structure,
#' incompatible versions and shipped code refuse, naming the path. Loading
#' never runs a UDF.
#' @param entry The artifact (a named list, e.g. from [parse_json()]).
#' @param registry A registry.
#' @export
load_adapter <- function(entry, registry = default_registry()) {
  reg <- registry
  if (!is_obj(entry)) malformed("", "entry must be a JSON object")
  for (key in c("template", "reader", "versions")) if (!has_key(entry, key)) malformed(key, sprintf("entry is missing required key %s", pyrepr(key)))
  versions <- entry[["versions"]]
  if (!is_obj(versions)) malformed("versions", "versions must be an object")
  check_compatible("kernel", if (has_key(versions, "kernel")) versions[["kernel"]] else "0.0.0", KERNEL_VERSION)
  vocab <- get_key(versions, "vocab")
  vocab <- if (pytruthy(vocab)) vocab else jobj()
  template <- entry[["template"]]
  if (is_obj(template) && has_key(template, "messages")) malformed("template", "template is a list in kernel 0.2 (the 0.1 {\"messages\": [...]} form is gone)")
  if (!is_arr(template)) malformed("template", "template must be a list")
  rs <- entry[["reader"]]
  if (!is_obj(rs)) malformed("reader", "entry.reader must be an object")
  kind <- get_key(rs, "kind")
  if (!identical(kind, "derived")) {
    named <- if (is_str(kind)) reg$readers[[kind]] else NULL
    if (is.null(named)) refuse("unknown-reader", sprintf("reader.kind %s is neither the kernel reader 'derived' nor a registered reader", pyrepr(kind)),
                               fix = jobj(action = "install-vocabulary", kind = "reader", name = pystr(kind)))
    check_vocab(paste0("reader/", kind), vocab, named$version)
    named_reader(reg, rs)
  }
  transports <- list()
  ets <- get_key(entry, "transports")
  for (purpose in names(if (pytruthy(ets)) ets else list())) {
    s <- ets[[purpose]]; where <- sprintf("transports[%s]", pyrepr(purpose))
    if (!is_obj(s)) malformed(where, sprintf("%s: must be an object", where))
    if (has_key(s, "use")) {
      name <- s[["use"]]
      named <- if (is_str(name)) reg$transports[[name]] else NULL
      if (is.null(named)) refuse("unknown-transport", sprintf("%s: transport %s is not registered", where, pyrepr(name)),
                                 fix = jobj(action = "install-vocabulary", kind = "transport", name = pystr(name)))
      check_vocab(paste0("transport/", name), vocab, named$version)
      options <- as_obj(get_key(s, "options"))
      named_transport(reg, name, options, where)
      transports[[purpose]] <- jobj(use = name, options = options)
    } else transports[[purpose]] <- transport_from_list(s, where)
  }
  formats <- list()
  efs <- get_key(entry, "formats")
  for (m in members_of(if (pytruthy(efs)) efs else list())) {
    key <- m[[1]]; f <- m[[2]]; where <- sprintf("formats[%s]", pyrepr(key))
    if (!is_obj(f)) malformed(where, sprintf("%s: must be an object", where))
    if (has_key(f, "use")) {
      name <- f[["use"]]
      named <- if (is_str(name)) reg$formats[[name]] else NULL
      if (is.null(named)) refuse("unknown-format", sprintf("%s: format %s is not registered", where, pyrepr(name)),
                                 fix = jobj(action = "install-vocabulary", kind = "format", name = pystr(name)))
      check_vocab(paste0("format/", name), vocab, named$version)
      options <- as_obj(get_key(f, "options"))
      named_format(reg, name, options, where)
      f[["options"]] <- options
      formats <- set_key(formats, key, f)
    } else if (has_key(f, "language")) {
      for (req in c("write", "sha256")) if (!has_key(f, req)) malformed(paste0(where, ".", req), sprintf("%s: a shipped format needs %s", where, pyrepr(req)))
      if (!reg$allow_udf) refuse("format-untrusted", sprintf("%s: the artifact ships a %s UDF and this runtime will not place code (an R runtime places no UDF language; bind a runtime format for the type with bind_type())", where, pystr(f[["language"]])),
                                 fix = jobj(action = "place-udf", language = pystr(f[["language"]]), path = where))
      load_udf(f, where)
    } else if (has_key(f, "describe")) formats <- set_key(formats, key, f)
    else malformed(where, sprintf("%s: a format entry is {use}, a shipped UDF, or a description {describe}", where))
  }
  a <- adapter(template, reader = rs, transports = transports, formats = formats, name = get_key(entry, "name", "adapter"),
               extensions = get_key(entry, "extensions"), replay = get_key(entry, "replay", "recorded"),
               strict = if (has_key(entry, "strict")) entry[["strict"]] else FALSE, declare_defaults = FALSE)
  resolve_extensions(a, reg)
  for (ref in spelling_format_refs(a, reg)) {
    named_format(reg, ref[[2]][["use"]], get_key(ref[[2]], "options"), ref[[1]])
    check_vocab(paste0("format/", ref[[2]][["use"]]), vocab, reg$formats[[ref[[2]][["use"]]]]$version)
  }
  a
}

ref_of <- function(b) {
  out <- jobj(use = b[["use"]])
  if (pytruthy(get_key(b, "options"))) out[["options"]] <- b[["options"]]
  if (has_key(b, "describe")) out[["describe"]] <- b[["describe"]]
  out
}

#' The artifact of an adapter
#'
#' Pins the kernel and each referenced vocabulary entry's version. A format
#' built from R functions refuses: a closure is not portable source.
#' @param a An adapter.
#' @param registry A registry.
#' @export
dump_adapter <- function(a, registry = default_registry()) {
  reg <- registry
  vocab <- jobj(); transports <- jobj()
  for (purpose in names(a$transports)) {
    b <- a$transports[[purpose]]
    if (is_transport(b)) transports[[purpose]] <- transport_to_list(b)
    else {
      named <- reg$transports[[b[["use"]]]]
      if (is.null(named)) refuse("unknown-transport", sprintf("cannot dump: transport %s is not registered (its version is part of the artifact)", pyrepr(b[["use"]])),
                                 fix = jobj(action = "install-vocabulary", kind = "transport", name = b[["use"]]))
      vocab[[paste0("transport/", b[["use"]])]] <- named$version
      transports[[purpose]] <- ref_of(b)
    }
  }
  for (ref in spelling_format_refs(a, reg)) {
    named_format(reg, ref[[2]][["use"]], get_key(ref[[2]], "options"), ref[[1]])
    vocab[[paste0("format/", ref[[2]][["use"]])]] <- reg$formats[[ref[[2]][["use"]]]]$version
  }
  formats <- jobj()
  for (m in members_of(a$formats)) {
    key <- m[[1]]; b <- m[[2]]
    if (is_format(b)) {
      if (!is.null(b$shipped)) { formats <- set_key(formats, key, b$shipped); next }
      refuse("format-not-self-contained", sprintf("cannot dump formats[%s]: an R format is a closure, not shippable source; bind it at runtime with bind_type() (never serialized) or reference a registered format by name", pyrepr(key)),
             fix = jobj(action = "reship-udf", path = sprintf("formats[%s]", pyrepr(key))))
    } else if (is_reference(b)) {
      named <- reg$formats[[b[["use"]]]]
      if (is.null(named)) refuse("unknown-format", sprintf("cannot dump: format %s is not registered", pyrepr(b[["use"]])),
                                 fix = jobj(action = "install-vocabulary", kind = "format", name = b[["use"]]))
      vocab[[paste0("format/", b[["use"]])]] <- named$version
      formats <- set_key(formats, key, ref_of(b))
    } else formats <- set_key(formats, key, b)
  }
  kind <- a$reader[["kind"]]
  if (kind != "derived") {
    named <- reg$readers[[kind]]
    if (is.null(named)) refuse("unknown-reader", sprintf("cannot dump: reader %s is not registered (its version is part of the artifact)", pyrepr(kind)),
                               fix = jobj(action = "install-vocabulary", kind = "reader", name = pystr(kind)))
    vocab[[paste0("reader/", kind)]] <- named$version
  }
  entry <- jobj(name = a$name, versions = jobj(kernel = KERNEL_VERSION, vocab = vocab))
  if (length(a$extensions)) entry[["extensions"]] <- a$extensions
  entry[["template"]] <- a$template
  entry[["reader"]] <- a$reader
  if (a$replay != "recorded") entry[["replay"]] <- a$replay
  if (isTRUE(a$strict)) entry[["strict"]] <- TRUE
  if (length(transports)) entry[["transports"]] <- transports
  if (length(formats)) entry[["formats"]] <- formats
  entry
}

# Extensions (kernel section 10) and the registry: the sockets.

EXT_NAME_RE <- "^[a-z][a-z0-9_]*/[a-z][a-z0-9_-]*$"
family_of <- function(name) strsplit(name, "/", fixed = TRUE)[[1]][[1]]
NON_RE2 <- "\\(\\?[=!>]|\\(\\?P?<|\\\\[1-9]|\\\\k<|[*+?}]\\+"

#' The `pattern/legacy-re2` binding through R's PCRE2
#'
#' `pattern/legacy-re2` 0.1.0 with R's `perl = TRUE` engine (PCRE2) and
#' DOTALL. The contract's lexical exclusion check refuses what it names;
#' inputs the contract leaves unspecified may differ from `python:re`.
#' @export
legacy_re2 <- function() {
  groups_of <- function(regex) {
    m <- regexpr(paste0("(?s)(?:", regex, ")|"), "", perl = TRUE)
    length(attr(m, "capture.start"))
  }
  list(extension = "pattern/legacy-re2", version = "0.1.0", binding = "r:PCRE2", family = "pattern",
    admit = function(regex, where) {
      unescaped <- gsub("\\\\[^1-9k]", "", regex, perl = TRUE)
      m <- regmatches(unescaped, regexpr(NON_RE2, unescaped, perl = TRUE))
      if (length(m)) malformed(where, sprintf("%s: regex %s uses %s, which is outside the pattern/legacy-re2 dialect (no lookaround, backreferences, named groups, atomic or possessive constructs)", where, pyrepr(regex), pyrepr(m)))
      ok <- tryCatch({ regexpr(paste0("(?s)", regex), "", perl = TRUE); TRUE }, error = function(e) conditionMessage(e), warning = function(w) conditionMessage(w))
      if (!isTRUE(ok)) malformed(where, sprintf("%s: regex %s does not compile: %s", where, pyrepr(regex), ok))
      invisible()
    },
    captures = function(regex, text) {
      m <- gregexpr(paste0("(?s)", regex), text, perl = TRUE, useBytes = TRUE)[[1]]
      if (m[[1]] < 0L) return(list())
      lens <- attr(m, "match.length")
      g <- groups_of(regex) > 0L
      out <- list()
      for (k in seq_along(m)) {
        if (lens[[k]] == 0L) next
        a <- m[[k]] - 1L
        cap <- if (g) {
          cs <- attr(m, "capture.start")[k, 1]; cl <- attr(m, "capture.length")[k, 1]
          if (cs <= 0L) "" else bsl(text, cs - 1L, cs - 1L + cl)
        } else bsl(text, a, a + lens[[k]])
        out[[length(out) + 1L]] <- list(a, a + lens[[k]], cap)
      }
      out
    })
}

native_extensions <- function() list(`pattern/legacy-re2` = legacy_re2())

uses_family <- function(transports, family) {
  found <- FALSE
  for (s in transports) if (is_transport(s)) walk_rules(s, function(r, path) if (family == "pattern" && has_key(r, "pattern")) found <<- TRUE, "")
  found
}

walk_rules <- function(t, visit, where) {
  if (!is.null(t$choose)) {
    for (i in seq_along(t$choose)) walk_rules(t$choose[[i]]$else_ %||% t$choose[[i]]$use, visit, sprintf("%s.choose[%d]", where, i - 1L))
    return(invisible())
  }
  for (i in seq_along(t$find)) visit(t$find[[i]], sprintf("%s.find[%d]", where, i - 1L))
}

default_declaration <- function(transports, declared) {
  if (uses_family(transports, "pattern") && !any(vapply(names(declared), family_of, "") == "pattern")) declared[["pattern/legacy-re2"]] <- "0.1.0"
  declared
}

validate_declaration <- function(ext) {
  if (is.null(ext)) return(jobj())
  if (!is_obj(ext)) malformed("extensions", "extensions must be an object of '<family>/<name>': version")
  seen <- list()
  for (m in members_of(ext)) {
    name <- m[[1]]; version <- m[[2]]
    if (!grepl(EXT_NAME_RE, name, perl = TRUE)) malformed("extensions", sprintf("extensions: %s is not an extension name ('<family>/<name>', lowercase)", pyrepr(name)))
    if (!is_str(version) || !grepl("^[0-9]+\\.[0-9]+\\.[0-9]+$", version, perl = TRUE)) malformed("extensions", sprintf("extensions: %s: version %s is not MAJOR.MINOR.PATCH", pyrepr(name), pyrepr(version)))
    fam <- family_of(name)
    if (has_key(seen, fam)) malformed("extensions", sprintf("extensions: %s and %s both govern family %s; declare one contract per family", pyrepr(get_key(seen, fam)), pyrepr(name), pyrepr(fam)))
    seen <- set_key(seen, fam, name)
  }
  as_obj(ext)
}

# ------------------------------------------------------------------ registry

#' A registry
#'
#' Named formats, transports and readers with versions, runtime type
#' bindings, and the extensions this runtime binds (`extensions =
#' character(0)` for a core-only host; default every native binding).
#' @param extensions Extension names to bind, or `NULL` for all native ones.
#' @param allow_udf This runtime places no UDF language either way; `TRUE`
#'   only changes which refusal a shipped format meets.
#' @export
lmcc_registry <- function(extensions = NULL, allow_udf = FALSE) {
  natives <- native_extensions()
  reg <- new.env(parent = emptyenv())
  reg$formats <- list(); reg$transports <- list(); reg$readers <- list(); reg$type_bindings <- list()
  reg$allow_udf <- allow_udf
  reg$extensions <- list()
  for (name in if (is.null(extensions)) names(natives) else extensions) {
    if (is.null(natives[[name]])) stop(sprintf("no native binding for extension '%s'", name), call. = FALSE)
    reg$extensions[[name]] <- natives[[name]]
  }
  class(reg) <- "lmcc_registry"
  reg
}

.default <- new.env(parent = emptyenv())
#' The registry `lmcc_bind`, `load_adapter` and `dump_adapter` use by default
#' @export
default_registry <- function() {
  if (is.null(.default$reg)) .default$reg <- lmcc_registry()
  .default$reg
}

#' Register vocabulary
#' @param reg A registry.
#' @param name The name artifacts reference.
#' @param factory `function(options)` returning a format or transport, or `function(spec)` returning a reader.
#' @param version Its version.
#' @param exist_ok Replace an existing entry instead of refusing.
#' @export
register_format <- function(reg, name, factory, version = "0.1.0", exist_ok = FALSE) {
  if (has_key(reg$formats, name) && !exist_ok) refuse("already-registered", sprintf("format %s is already registered", pyrepr(name)))
  reg$formats <- set_key(reg$formats, name, list(factory = factory, version = version))
  invisible(reg)
}
#' @rdname register_format
#' @export
register_transport <- function(reg, name, factory, version = "0.1.0", exist_ok = FALSE) {
  if (has_key(reg$transports, name) && !exist_ok) refuse("already-registered", sprintf("transport %s is already registered", pyrepr(name)))
  reg$transports <- set_key(reg$transports, name, list(factory = factory, version = version))
  invisible(reg)
}
#' @rdname register_format
#' @export
register_reader <- function(reg, name, factory, version = "0.1.0", exist_ok = FALSE) {
  if (name == "derived") refuse("already-registered", "reader 'derived' is kernel grammar and cannot be replaced")
  if (has_key(reg$readers, name) && !exist_ok) refuse("already-registered", sprintf("reader %s is already registered", pyrepr(name)))
  reg$readers <- set_key(reg$readers, name, list(factory = factory, version = version))
  invisible(reg)
}

#' Bind a type name to a format, per runtime (never serialized)
#' @param reg A registry.
#' @param type The type name as a signature's field spells it.
#' @param format A format ([make_format()]), or `NULL` with `use`.
#' @param use,options A registered format's name and options.
#' @export
bind_type <- function(reg, type, format = NULL, use = NULL, options = jobj()) {
  reg$type_bindings <- set_key(reg$type_bindings, type, if (!is.null(use)) list(use = use, options = options) else format)
  invisible(reg)
}

type_binding <- function(reg, type) {
  if (!is_str(type) || !has_key(reg$type_bindings, type)) return(NULL)
  b <- get_key(reg$type_bindings, type)
  if (is_format(b)) b else named_format(reg, b$use, b$options)
}

named_format <- function(reg, name, options, where = NULL) {
  e <- if (is_str(name)) get_key(reg$formats, name) else NULL
  if (is.null(e)) refuse("unknown-format", sprintf("format %s is not registered \u2014 install the package that provides it, or ship the format with the artifact", pyrepr(name)),
                         fix = jobj(action = "install-vocabulary", kind = "format", name = name))
  at <- where %||% sprintf("format %s", pyrepr(name))
  fmt <- tryCatch(e$factory(as_obj(options)), error = function(err) if (is_refusal(err)) stop(err) else malformed(at, sprintf("%s: format %s rejects its options: %s", at, pyrepr(name), conditionMessage(err))))
  if (!is_format(fmt)) malformed(at, sprintf("%s: format %s returned something that is not a format", at, pyrepr(name)))
  fmt$name <- name
  fmt
}

named_transport <- function(reg, name, options, where = NULL) {
  e <- if (is_str(name)) get_key(reg$transports, name) else NULL
  if (is.null(e)) refuse("unknown-transport", sprintf("transport %s is not registered \u2014 install the package that provides it, or inline the transport as data", pyrepr(name)),
                         fix = jobj(action = "install-vocabulary", kind = "transport", name = name))
  at <- where %||% sprintf("transport %s", pyrepr(name))
  built <- tryCatch(e$factory(as_obj(options)), error = function(err) if (is_refusal(err)) stop(err) else malformed(at, sprintf("%s: transport %s rejects its options: %s", at, pyrepr(name), conditionMessage(err))))
  tryCatch(if (is_transport(built)) { validate_transport(built, at); built } else transport_from_list(built, at),
           lmcc_refusal = function(r) {
             if (r$code != "entry-malformed") stop(r)
             malformed(at, sprintf("%s: transport %s built malformed data \u2014 %s", at, pyrepr(name), r$hint))
           })
}

named_reader <- function(reg, spec) {
  kind <- get_key(spec, "kind")
  e <- if (is_str(kind)) get_key(reg$readers, kind) else NULL
  if (is.null(e)) refuse("unknown-reader", sprintf("reader kind %s is neither the kernel reader 'derived' nor a registered reader \u2014 install the package that provides it", pyrepr(kind)),
                         fix = jobj(action = "install-vocabulary", kind = "reader", name = pystr(kind)))
  r <- tryCatch(e$factory(spec), error = function(err) if (is_refusal(err)) stop(err) else malformed("reader", sprintf("reader: %s rejects its spec: %s", pyrepr(kind), conditionMessage(err))))
  if (!inherits(r, "lmcc_reader")) malformed("reader", sprintf("reader: %s built something that is not a reader", pyrepr(kind)))
  r
}

versions_of <- function(m) { n <- ssort(names(m)); as_obj(structure(lapply(n, function(k) get_key(m, k)$version), names = n)) }

#' Describe a registry or a plan as plain data
#'
#' `describe_registry()`: every named format, transport and reader with its
#' version, the type bindings and the bound extensions. `describe_plan()`:
#' the whole plan (reader, anchors, formats and what resolved them, find
#' rules, puts, request settings, streaming modes, turn writers, versions).
#' @param x A registry or a plan.
#' @export
describe_registry <- function(x) {
  jobj(formats = versions_of(x$formats),
       type_bindings = lapply(members_of(x$type_bindings), function(m) { t <- m[[1]]; b <- m[[2]]; jobj(type = t, format = if (is_format(b)) b$name %||% "(inline)" else b$use) }),
       transports = versions_of(x$transports), readers = c(jobj(derived = "kernel"), versions_of(x$readers)), allow_udf = x$allow_udf,
       extensions = as_obj(lapply(x$extensions[ssort(names(x$extensions))], function(b) jobj(version = b$version, binding = b$binding))))
}

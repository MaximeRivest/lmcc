# Helpers you can autocomplete (kernel section 6): each returns the plain
# data you could write by hand, the same as Python's lmcc.find/put/when/choose,
# TypeScript's and Julia's. A wrong argument is host misuse (an R error), not
# a refusal: the kernel validates what they produce like any other data.

helper_to <- function(sub) {
  if (is.null(sub)) return("@purpose")
  if (!is_str(sub) || !nzchar(sub) || startsWith(sub, "@"))
    stop("to is a sub-purpose name like \"calls\" (NULL means the purpose itself)", call. = FALSE)
  paste0("@purpose.", sub)
}
helper_text <- function(x, what) if (!is_str(x) || !nzchar(x)) stop(what, call. = FALSE)

#' Find rules, puts, predicates and choices you can autocomplete
#'
#' Each helper returns the plain data of kernel section 6, the same as
#' Python's `lmcc.find`, `lmcc.put`, `lmcc.when` and `lmcc.choose`:
#' `find_between("<think>", "</think>", remove = TRUE)` is
#' `jobj(from = "text", between = list("<think>", "</think>"), to = "@purpose", remove = TRUE)`.
#'
#' - `find_between()`: text between two delimiters (`repair` reads
#'   misspelled ones, section 4a; `whole_reply` makes a match a complete reply).
#' - `find_lines()`: lines starting with a prefix.
#' - `find_pattern()`: a regular expression (needs a declared `pattern/*` extension).
#' - `find_part()`: reply parts of one lm15 type (`"thinking"`, `"tool_call"`).
#' - `put_system()`, `put_developer()`, `put_user()`, `put_request()`: where a
#'   field goes instead of a slot.
#' - `when_has()`, `when_lacks()`, `when_all()`, `when_any()`: predicates on
#'   the model's declared facts.
#' - `choose_transport()`: the first transport whose predicate holds (R's own
#'   `choose()` is the binomial coefficient, so the name differs from the
#'   other kernels').
#' @param open,close The delimiters.
#' @param prefix A line prefix.
#' @param regex A regular expression.
#' @param type An lm15 part type.
#' @param to A sub-purpose (`"calls"`), or `NULL` for the purpose itself.
#' @param field The same, for a put.
#' @param path A request path (`"tools"`).
#' @param remove,repair,whole_reply Rule options.
#' @param fact A capability fact.
#' @param ... Predicates (`when_all`, `when_any`) or alternatives
#'   `list(when = predicate, use = transport)` (`choose_transport`).
#' @param otherwise The transport when no predicate holds.
#' @param registry Where transport names are found.
#' @name helpers
NULL

#' @rdname helpers
#' @export
find_between <- function(open, close, to = NULL, remove = FALSE, repair = FALSE, whole_reply = FALSE) {
  if (!is_str(open) || !nzchar(open) || !is_str(close) || !nzchar(close)) stop("find_between takes two non-empty strings", call. = FALSE)
  r <- jobj(from = "text", between = list(open, close), to = helper_to(to))
  if (isTRUE(remove)) r[["remove"]] <- TRUE
  if (isTRUE(repair)) r[["repair"]] <- TRUE
  if (isTRUE(whole_reply)) r[["complete_reply"]] <- TRUE
  r
}
#' @rdname helpers
#' @export
find_lines <- function(prefix, to = NULL, remove = FALSE) {
  helper_text(prefix, "find_lines takes a non-empty prefix")
  r <- jobj(from = "text", line_prefixed = prefix, to = helper_to(to))
  if (isTRUE(remove)) r[["remove"]] <- TRUE
  r
}
#' @rdname helpers
#' @export
find_pattern <- function(regex, to = NULL, remove = FALSE) {
  helper_text(regex, "find_pattern takes a non-empty regex")
  r <- jobj(from = "text", pattern = regex, to = helper_to(to))
  if (isTRUE(remove)) r[["remove"]] <- TRUE
  r
}
#' @rdname helpers
#' @export
find_part <- function(type, to = NULL, whole_reply = FALSE) {
  helper_text(type, "find_part takes an lm15 part type such as \"thinking\"")
  r <- jobj(from = paste0("part:", type), to = helper_to(to))
  if (isTRUE(whole_reply)) r[["complete_reply"]] <- TRUE
  r
}

helper_put <- function(field, target) set_key(jobj(), helper_to(field), target)
#' @rdname helpers
#' @export
put_system <- function(field = NULL) helper_put(field, "message:system")
#' @rdname helpers
#' @export
put_developer <- function(field = NULL) helper_put(field, "message:developer")
#' @rdname helpers
#' @export
put_user <- function(field = NULL) helper_put(field, "message:user")
#' @rdname helpers
#' @export
put_request <- function(path, field = NULL) {
  helper_text(path, "put_request takes a request path such as \"tools\"")
  helper_put(field, paste0("request.", path))
}

#' @rdname helpers
#' @export
when_has <- function(fact) jobj(capability = fact)
#' @rdname helpers
#' @export
when_lacks <- function(fact) jobj(not = jobj(capability = fact))
#' @rdname helpers
#' @export
when_all <- function(...) jobj(all = list(...))
#' @rdname helpers
#' @export
when_any <- function(...) jobj(any = list(...))

#' @rdname helpers
#' @export
choose_transport <- function(..., otherwise = NULL, registry = default_registry()) {
  resolve <- function(t) {
    if (is_transport(t)) return(t)
    if (is_str(t)) return(named_transport(registry, t, jobj()))
    if (is_obj(t)) return(transport_from_list(t, "choose"))
    stop("a choice is a transport, its data or a registered transport name", call. = FALSE)
  }
  items <- lapply(list(...), function(a) {
    if (!is.list(a) || length(a) != 2L) stop("an alternative is list(when = predicate, use = transport)", call. = FALSE)
    when <- if (!is.null(names(a)) && all(c("when", "use") %in% names(a))) a[["when"]] else a[[1L]]
    use <- if (!is.null(names(a)) && all(c("when", "use") %in% names(a))) a[["use"]] else a[[2L]]
    list(when = when, use = resolve(use))
  })
  if (!is.null(otherwise)) items[[length(items) + 1L]] <- list(else_ = resolve(otherwise))
  t <- new_transport(choose = items)
  validate_transport(t, "choose")
  t
}

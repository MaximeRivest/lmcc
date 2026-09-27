# Signatures (kernel section 1). `signature_from_list()` is the plain-data
# form every implementation shares; `lmcc_signature()` with the `shape_*`
# builders is R's frontend. R has no type names at run time worth hashing,
# so the builders name no type unless given `type =` (as in TypeScript): a
# frontend spells type names (section 1); plain data never differs.

#' A signature
#'
#' Instructions and ordered fields. Constructing one validates it
#' (`signature-malformed`, naming the offender): an invalid signature cannot
#' exist.
#' @param instructions Text.
#' @param fields A list of fields, each a list with `name`, `direction`,
#'   `shape`, and optionally `type`, `purpose` (default "plain") and `desc`.
#' @export
new_signature <- function(instructions, fields) {
  if (!is_str(instructions)) refuse("signature-malformed", sprintf("instructions must be text, not %s", typename_of(instructions)), fix = jobj(action = "edit-signature"))
  if (!is.list(fields) || is_obj(fields)) refuse("signature-malformed", "a signature is an object with a fields list", fix = jobj(action = "edit-signature"))
  seen <- character(0)
  out <- list()
  for (f in fields) {
    if (!is.list(f)) refuse("signature-malformed", "each field is an object", fix = jobj(action = "edit-signature"))
    name <- get_key(f, "name")
    fix <- if (is_str(name) && nzchar(name)) jobj(action = "edit-signature", field = name) else jobj(action = "edit-signature")
    if (!is_identifier(name)) refuse("signature-malformed", sprintf("field name %s is not an ASCII identifier ([A-Za-z_][A-Za-z0-9_]*)", pyrepr(name)), fix = fix)
    if (name %in% seen) refuse("signature-malformed", sprintf("field %s is declared twice", pyrepr(name)), fix = fix)
    seen <- c(seen, name)
    d <- get_key(f, "direction")
    if (!(is_str(d) && d %in% c("input", "output"))) refuse("signature-malformed", sprintf("field %s: direction %s is not input/output", pyrepr(name), pyrepr(d)), fix = fix)
    shape <- get_key(f, "shape")
    if (!is_obj(shape)) refuse("signature-malformed", sprintf("field %s: shape must be an object", pyrepr(name)), fix = fix)
    purpose <- if (has_key(f, "purpose")) f[["purpose"]] else "plain"
    if (!(is_str(purpose) && grepl(PURPOSE_RE, purpose, perl = TRUE)))
      refuse("signature-malformed", sprintf("field %s: purpose %s is not a (dotted) identifier", pyrepr(name), pyrepr(purpose)), fix = fix)
    type <- get_key(f, "type")
    if (!is.null(type) && !is_str(type)) refuse("signature-malformed", sprintf("field %s: type must be a string", pyrepr(name)), fix = fix)
    desc <- get_key(f, "desc")
    if (!is.null(desc) && !is_str(desc)) refuse("signature-malformed", sprintf("field %s: desc must be a string", pyrepr(name)), fix = fix)
    out[[length(out) + 1L]] <- new_field(name, d, as_obj(shape), type, purpose, desc)
  }
  structure(list(instructions = instructions, fields = out), class = "lmcc_signature")
}

sig_inputs <- function(sig) Filter(function(f) f$direction == "input", sig$fields)
sig_outputs <- function(sig) Filter(function(f) f$direction == "output", sig$fields)
field_named <- function(sig, name) { for (f in sig$fields) if (identical(f$name, name)) return(f); NULL }

#' A signature from its plain-data form (the corpus form)
#' @param data A list with `instructions` and `fields`.
#' @export
signature_from_list <- function(data) {
  if (!is_obj(data) || !(is.null(get_key(data, "fields")) || is_arr(get_key(data, "fields"))))
    refuse("signature-malformed", "a signature is an object with a fields list", fix = jobj(action = "edit-signature"))
  fields <- get_key(data, "fields", list())
  for (f in fields) if (!is_obj(f)) refuse("signature-malformed", "each field is an object", fix = jobj(action = "edit-signature"))
  new_signature(if (has_key(data, "instructions")) data[["instructions"]] else "", fields)
}

#' @rdname signature_from_list
#' @param sig A signature.
#' @export
signature_to_list <- function(sig) {
  jobj(instructions = sig$instructions, fields = lapply(sig$fields, function(f) {
    d <- jobj(name = f$name, direction = f$direction, shape = f$shape)
    if (!is.null(f$type) && nzchar(f$type)) d[["type"]] <- f$type
    if (f$purpose != "plain") d[["purpose"]] <- f$purpose
    if (!is.null(f$desc)) d[["desc"]] <- f$desc
    d
  }))
}

# ------------------------------------------------------------- frontend

#' JSON-Schema shape builders
#'
#' Plain shapes for [lmcc_signature()]. Lists and objects are structured:
#' they need a format (section 5).
#' @param ... Extra JSON-Schema keywords (named), or enum members.
#' @param shape,items An inner shape.
#' @param properties A named list of shapes.
#' @param type An lm15 part type.
#' @export
shape_string <- function(...) jobj(type = "string", ...)
#' @rdname shape_string
#' @export
shape_integer <- function(...) jobj(type = "integer", ...)
#' @rdname shape_string
#' @export
shape_number <- function(...) jobj(type = "number", ...)
#' @rdname shape_string
#' @export
shape_boolean <- function(...) jobj(type = "boolean", ...)
#' @rdname shape_string
#' @export
shape_enum <- function(...) {
  members <- list(...)
  s <- jobj(enum = unname(members))
  if (all(vapply(members, is_str, TRUE))) s[["type"]] <- "string"
  else if (all(vapply(members, function(m) is_num(m) && is_int_value(m), TRUE))) s[["type"]] <- "integer"
  s
}
#' @rdname shape_string
#' @export
shape_nullable <- function(shape) jobj(anyOf = list(shape, jobj(type = "null")))
#' @rdname shape_string
#' @export
shape_list <- function(items = NULL) if (is.null(items)) jobj(type = "array") else jobj(type = "array", items = items)
#' @rdname shape_string
#' @export
shape_object <- function(properties = NULL) {
  if (is.null(properties)) return(jobj(type = "object"))
  jobj(type = "object", properties = as_obj(properties), required = as.list(names(properties)))
}
#' @rdname shape_string
#' @export
shape_media <- function(type) jobj(media = type)

#' A field spec: a shape plus purpose, description and type name
#' @param shape A JSON-Schema shape.
#' @param purpose,desc,type Optional.
#' @export
field_spec <- function(shape, purpose = "plain", desc = NULL, type = NULL) {
  structure(list(shape = shape, purpose = purpose, desc = desc, type = type), class = "lmcc_field_spec")
}

#' Build a signature
#'
#' `lmcc_signature("Answer.", inputs = list(question = shape_string()),
#' outputs = list(answer = shape_string()))`. Inputs come first, then
#' outputs, each in the order written.
#' @param instructions Text.
#' @param inputs,outputs Named lists of shapes or [field_spec()]s.
#' @export
lmcc_signature <- function(instructions, inputs = list(), outputs = list()) {
  fields <- list()
  for (direction in c("input", "output")) {
    entries <- if (direction == "input") inputs else outputs
    for (name in names(entries)) {
      spec <- entries[[name]]
      if (!inherits(spec, "lmcc_field_spec")) spec <- field_spec(spec)
      f <- list(name = name, direction = direction, shape = spec$shape, purpose = spec$purpose)
      if (!is.null(spec$type)) f$type <- spec$type
      if (!is.null(spec$desc)) f$desc <- spec$desc
      fields[[length(fields) + 1L]] <- f
    }
  }
  new_signature(instructions, fields)
}

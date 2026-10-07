# Formats (kernel section 5): how a type is written and read.

#' A format
#'
#' `write(value, field)` returns text or a list of lm15 parts,
#' `read(capture, field)` a value, `describe(field)` text or `NULL`.
#' @param write,read,describe Functions (`read` optional).
#' @param accepts Type names, structural keys, or `"*"`.
#' @param direction `"in"`, `"out"` or `"both"` (default: `both` with a read).
#' @param writes `"text"` or `"parts"`.
#' @param round_trip Whether `read(write(v)) == v`.
#' @param reads Capture kinds `read` accepts.
#' @param name The registered name, if any.
#' @export
make_format <- function(write, read = NULL, describe = NULL, accepts = "*", direction = NULL, writes = "text",
                        round_trip = TRUE, reads = "text", name = NULL) {
  structure(list(name = name, accepts = accepts, direction = direction %||% (if (is.null(read)) "in" else "both"),
                 writes = writes, round_trip = round_trip, reads = reads, write = write, read = read,
                 describe = describe %||% function(f) NULL, shipped = NULL), class = "lmcc_format")
}

is_format <- function(x) inherits(x, "lmcc_format")

SCALAR_DEFAULT <- make_format(
  write = function(v, f) spell_value(f$shape, v, sprintf("field %s", pyrepr(f$name)), f$name),
  read = function(c, f) read_value(f$shape, capture_text(c), sprintf("field %s", pyrepr(f$name))),
  describe = function(f) { s <- shape_summary(f$shape); if (nzchar(s)) s else NULL },
  accepts = c(SCALAR_TYPES, "enum"), direction = "both", reads = "*", name = "kernel-scalar")

MEDIA_MEMBERS <- c("media_type", "data", "url", "file_id", "path", "continuation")
# lm15's media parts and their members besides `type` (the pinned contract's spec/types.md);
# section 7b writes these kinds exactly as lm15 serializes them.
media_part_members <- function(kind) {
  if (identical(kind, "image")) return(c("media_type", "data", "url", "file_id", "path", "detail", "continuation"))
  if (is_str(kind) && kind %in% c("audio", "video", "document", "binary")) MEDIA_MEMBERS else NULL
}
# lm15's omission rule: null, "", [] and {} are left out.
empty_member <- function(v) is.null(v) || (is_str(v) && !nzchar(v)) || (is.list(v) && !is_num(v) && length(v) == 0L)

MEDIA_DEFAULT <- make_format(
  write = function(value, f) {
    kind <- f$shape[["media"]]
    if (!is_obj(value)) refuse("value-invalid", sprintf("field %s: a media value must be a named list of part data", pyrepr(f$name)))
    if (has_key(value, "type") && !identical(value[["type"]], kind))
      refuse("value-invalid", sprintf("field %s: a %s part given where a %s part is declared", pyrepr(f$name), pyrepr(value[["type"]]), pyrepr(kind)))
    members <- media_part_members(kind)
    if (is.null(members)) return(list(c(jobj(type = kind), drop_key(as_obj(value), "type"))))   # not one of lm15's media parts: as given
    part <- jobj(type = kind)
    for (m in members_of(value)) {        # section 7b: exactly as lm15 serializes the part
      k <- m[[1]]; v <- m[[2]]
      if (identical(k, "type")) next
      if (!k %in% members) refuse("value-invalid", sprintf("field %s: %s is not a member of lm15's %s part (%s); give the part's data, or an lm15 part through its bridge",
                                                           pyrepr(f$name), pyrepr(k), kind, paste(members, collapse = ", ")))
      if (!identical(k, "media_type") && empty_member(v)) next   # lm15's omission rule
      part <- set_key(part, k, v)
    }
    list(part)
  },
  read = function(c, f) {
    ps <- capture_parts_of(c, f$shape[["media"]])
    if (!length(ps)) refuse("parse-value", sprintf("field %s: no %s part in the capture", pyrepr(f$name), pystr(f$shape[["media"]])))
    drop_key(ps[[1]], "type")
  },
  describe = function(f) paste0("(", pystr(f$shape[["media"]]), ")"),
  accepts = "media:*", direction = "both", writes = "parts", reads = "*", name = "kernel-media")

kernel_default <- function(shape) {
  base <- nullable_base(shape)[[1]]
  if (is_media(base)) return(MEDIA_DEFAULT)
  if (has_key(base, "enum") || isTRUE(get_key(base, "type") %in% SCALAR_TYPES)) return(SCALAR_DEFAULT)
  NULL
}

format_accepts <- function(fmt, f) {
  keys <- c(structural_keys(f$shape), "*", f$type)
  any(fmt$accepts %in% keys)
}

load_udf <- function(entry, where) refuse("udf-unplaceable",
  sprintf("%s: this host places no UDF language (an R runtime does not admit %s source); bind a runtime format for the type instead", where, pyrepr(get_key(entry, "language"))),
  fix = jobj(action = "place-udf", language = pystr(get_key(entry, "language")), path = where))

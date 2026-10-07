# lmcc x lm15 (the 'lm15' package, suggested): typed convenience over a
# shared wire. The kernel already speaks lm15's canonical JSON; these use
# lm15's own serde both ways (from_dict, as_dict), so nothing here can drift
# from what lm15 says a request or a response is. Mirrors Python's lmcc_lm15.

need_lm15 <- function() if (!requireNamespace("lm15", quietly = TRUE)) stop("the lm15 package is needed for this: install it", call. = FALSE)

#' lm15 values as plain lmcc JSON
#'
#' Unclasses lm15's JSON objects, arrays and number tokens recursively.
#' @param x An lm15 dict (from `lm15::as_dict()`) or any JSON value.
#' @export
lm15_plain <- function(x) {
  if (inherits(x, "lm15_json_number") || inherits(x, "lm15_integer")) return(num_value(x))
  if (inherits(x, "lm15_value")) { need_lm15(); x <- lm15::as_dict(x) }
  if (is.list(x)) {
    obj <- is_obj(x)
    n <- names(x)
    out <- lapply(unclass_json(x), lm15_plain)
    if (obj) { names(out) <- n; if (!length(out)) names(out) <- character(0) } else out <- unname(out)
    return(out)
  }
  x
}

merge_settings <- function(base, extra, path = "", override = FALSE) {
  out <- as_obj(base)
  for (m in members_of(extra)) {
    k <- m[[1]]; v <- m[[2]]; here <- if (nzchar(path)) paste0(path, ".", k) else k
    i <- key_index(out, k)
    if (i && is_obj(out[[i]]) && is_obj(v)) out[i] <- list(merge_settings(out[[i]], v, here, override))
    else if (i && !json_equal(out[[i]], v) && !override)
      stop(structure(class = c("lmcc_config_conflict", "error", "condition"), list(call = NULL,
        message = sprintf("%s: the plan's request settings require %s (a transport or reader asked for it) but the caller's config says %s; pass override = TRUE to insist", here, json_text(out[[i]]), json_text(v)))))
    else out <- set_key(out, k, v)
  }
  out
}

#' Send a rendered plan with lm15
#'
#' `lm15_request()` makes the lm15 request: the plan's request settings are
#' the base, the caller's `lm15::config()` fills the rest, and a
#' contradiction is an `lmcc_config_conflict` error unless `override`.
#' `lm15_read()`, `lm15_parse()` and `lm15_step()` read an lm15 response or
#' message; `lm15_stream()` drives the plan's stream from `lm15::stream()`.
#' @param rendered A render result.
#' @param model The model name.
#' @param config An `lm15::config()`, or `NULL`.
#' @param override Let the caller's config win.
#' @export
lm15_request <- function(rendered, model, config = NULL, override = FALSE) {
  need_lm15()
  d <- request_of(rendered, model)
  if (!is.null(config)) d[["config"]] <- merge_settings(get_key(d, "config", jobj()), lm15_plain(lm15::as_dict(config)), "config", override)
  lm15::from_dict(d, "request")
}

#' @rdname lm15_request
#' @param p A plan.
#' @param response An lm15 response or message.
#' @export
lm15_read <- function(p, response) read_reply(p, lm15_plain(response))
#' @rdname lm15_request
#' @export
lm15_parse <- function(p, response) parse_reply(p, lm15_plain(response))
#' @rdname lm15_request
#' @export
lm15_step <- function(rendered, response) record_step(rendered, lm15_plain(response))

#' @rdname lm15_request
#' @param client An lm15 client or router.
#' @param request An lm15 request.
#' @param on_event Called with each lmcc stream event as it happens.
#' @export
lm15_stream <- function(p, client, request, on_event = NULL) {
  need_lm15()
  s <- reply_stream(p)
  env <- new.env(); env$events <- list(); env$reason <- NULL
  emit <- function(batch) for (e in batch) { env$events[[length(env$events) + 1L]] <- e; if (!is.null(on_event)) on_event(e) }
  lm15::stream(client, request, function(event) {
    ev <- lm15_plain(event)
    type <- get_key(ev, "type")
    if (identical(type, "error")) stop(sprintf("lm15 stream error: %s", json_text(get_key(ev, "error"))), call. = FALSE)
    if (identical(type, "end")) env$reason <- get_key(ev, "finish_reason")
    if (identical(type, "delta")) emit(feed(s, ev[["delta"]]))
  })
  result <- finish(s, env$reason)
  emit(result$events)
  list(events = env$events, result = result)
}

LM15_MEDIA_PARTS <- c(ImagePart = "image", AudioPart = "audio", VideoPart = "video", DocumentPart = "document", BinaryPart = "binary")

#' lm15's media parts as field types and values
#'
#' `lm15_media(kind)` is a field whose shape is `shape_media(kind)` and whose
#' type is lm15's part (`ImagePart`, `AudioPart`, `VideoPart`,
#' `DocumentPart`, `BinaryPart`): an lm15 part (`lm15::image_part()`, ...)
#' is its value, written as lm15's canonical part data, saved by
#' [dump_turn()] as that data and rebuilt into the part by [load_turn()].
#' Part data given as a named list still works. A part given by `path` keeps
#' its path: lm15 reads the file when it sends. `lm15_install()` binds the
#' five types in a registry; the default registry has them. The bindings
#' call lm15 only when they meet an lm15 value or rebuild one.
#' @param kind `"image"`, `"audio"`, `"video"`, `"document"` or `"binary"`.
#' @param purpose,desc As for [field_spec()].
#' @param reg A registry.
#' @export
lm15_media <- function(kind, purpose = "plain", desc = NULL) {
  type <- names(LM15_MEDIA_PARTS)[LM15_MEDIA_PARTS == kind]
  if (length(type) != 1L) stop(sprintf("lm15 has no %s part; use one of %s", pyrepr(kind), paste(LM15_MEDIA_PARTS, collapse = ", ")), call. = FALSE)
  field_spec(shape_media(kind), purpose = purpose, desc = desc, type = type)
}

#' @rdname lm15_media
#' @export
lm15_install <- function(reg = default_registry()) {
  for (name in names(LM15_MEDIA_PARTS)) local({
    kind <- LM15_MEDIA_PARTS[[name]]
    bind_type(reg, name,
      # lm15's canonical part data, `type` included and first, so a part of another kind refuses
      to_json = function(v) if (inherits(v, "lm15_value")) lm15_plain(v) else v,
      from_json = function(d) {
        if (!is_obj(d) || !identical(get_key(d, "type", kind), kind))
          refuse("turn-invalid", sprintf("an lm15 %s part is rebuilt from %s part data, got %s", kind, kind, json_text(d)))
        need_lm15()
        lm15::from_dict(merge_obj(jobj(type = kind), drop_key(d, "type")), "part")
      })
  })
  invisible(reg)
}

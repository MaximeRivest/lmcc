# The standard vocabulary pack (contract/spec/vocab/): it registers through
# the same sockets your own vocabulary uses; nothing here is privileged.

STD_VERSION <- "0.1.0"

#' JSON as the standard pack spells it
#'
#' Indented (ECMAScript `JSON.stringify(v, null, indent)`) or, with
#' `indent = NULL`, one line with `, ` and `: `; numbers by section 7a.
#' @param value A JSON value.
#' @param indent Spaces per level, or `NULL`.
#' @export
json_dumps <- function(value, indent = 2L) {
  w <- function(v, depth) {
    if (is.null(v)) return("null")
    if (is_bool(v)) return(if (v) "true" else "false")
    if (is_num(v)) return(format_number(v))
    if (is_str(v)) return(json_string(v))
    if (is.list(v)) {
      obj <- is_obj(v)
      if (!length(v)) return(if (obj) "{}" else "[]")
      pad <- if (is.null(indent)) "" else paste0("\n", strrep(" ", indent * (depth + 1L)))
      sep <- if (is.null(indent)) ", " else paste0(",", pad)
      end <- if (is.null(indent)) "" else paste0("\n", strrep(" ", indent * depth))
      items <- vapply(seq_along(v), function(i) paste0(if (obj) paste0(json_string(names(v)[[i]]), ": ") else "", w(v[[i]], depth + 1L)), "")
      return(paste0(if (obj) "{" else "[", pad, paste(items, collapse = sep), end, if (obj) "}" else "]"))
    }
    stop(sprintf("%s of length %d is not JSON data", class(v)[[1]], length(v)))
  }
  w(value, 0L)
}

json_loads <- function(t) parse_json(t, "reject")

json_ws <- function(s, i) { while (i < blen(s) && bchar(s, i) %in% c(" ", "\t", "\n", "\r")) i <- i + 1L; i }

json_members <- function(t) {
  s <- t
  i <- json_ws(s, 0L)
  if (!(i < blen(s) && bchar(s, i) == "{")) stop("not a JSON object")
  i <- json_ws(s, i + 1L)
  out <- list()
  finish_at <- function(at) if (json_ws(s, at) != blen(s)) stop("trailing data after the JSON object")
  if (i < blen(s) && bchar(s, i) == "}") { finish_at(i + 1L); return(out) }
  repeat {
    if (!(i < blen(s) && bchar(s, i) == '"')) stop(sprintf("expected a member name at %d", i))
    kr <- parse_json_at(s, i, "reject"); key <- kr[[1]]; i <- json_ws(s, kr[[2]])
    if (!(i < blen(s) && bchar(s, i) == ":")) stop(sprintf("expected ':' at %d", i))
    i <- json_ws(s, i + 1L)
    vr <- parse_json_at(s, i, "reject")
    out[[length(out) + 1L]] <- list(key, vr[[1]], bsl(s, i, vr[[2]]))
    i <- json_ws(s, vr[[2]])
    if (i < blen(s) && bchar(s, i) == ",") { i <- json_ws(s, i + 1L); next }
    if (i < blen(s) && bchar(s, i) == "}") { finish_at(i + 1L); return(out) }
    stop(sprintf("expected ',' or '}' at %d", i))
  }
}

errmsg <- function(e) if (is_refusal(e)) e$hint else conditionMessage(e)
FENCE_RE <- "^[ \\t\\n\\r\\f\\v]*```[a-zA-Z0-9_-]*[ \\t\\n\\r\\f\\v]*\\n([\\s\\S]*?)\\n?[ \\t\\n\\r\\f\\v]*```[ \\t\\n\\r\\f\\v]*$"

json_format <- function(options) {
  indent <- if (has_key(options, "indent")) options[["indent"]] else 2L
  make_format(write = function(v, f) json_dumps(to_json(v), indent),
              read = function(c, f) {
                t <- capture_text(c)
                m <- regmatches(t, regexec(FENCE_RE, t, perl = TRUE))[[1]]
                if (length(m)) t <- m[[2]]
                json_loads(t)
              },
              describe = function(f) paste0("JSON matching this schema: ", json_dumps(f$shape, NULL)), accepts = "*", direction = "both")
}

cell_read <- function(shape, t, where) tryCatch(read_value(shape, t, where), lmcc_refusal = function(e) stop(e$hint, call. = FALSE))
spell_cell <- function(cell, col) {
  if (is_str(cell)) return(cell)
  if (is_bool(cell)) return(if (cell) "true" else "false")
  if (is_num(cell)) return(format_number(cell))
  stop(sprintf("column %s: %s is not a cell value", pyrepr(col), typename_of(cell)), call. = FALSE)
}

table_format <- function(options) {
  if (!has_key(options, "columns")) stop("table codec requires the 'columns' option")
  columns <- unlist(options[["columns"]])
  delim <- get_key(options, "delimiter", "|"); esc <- get_key(options, "escape", "\\"); nulltext <- get_key(options, "null", "")
  split_row <- function(line) {
    inner <- bsl(line, blen(delim))
    if (endsWith(inner, delim)) inner <- bsl(inner, 0L, blen(inner) - blen(delim))
    cells <- character(0); cur <- character(0)
    cs <- chars_of(inner); k <- 1L; n <- length(cs$ch)
    while (k <= n) {
      i <- cs$start[[k]]
      if (bstarts(inner, esc, i) && k < n) { cur <- c(cur, cs$ch[[k + 1L]]); k <- k + 2L; next }
      if (bstarts(inner, delim, i)) { cells <- c(cells, paste(cur, collapse = "")); cur <- character(0); k <- k + length(chars_of(delim)$ch); next }
      cur <- c(cur, cs$ch[[k]]); k <- k + 1L
    }
    c(cells, paste(cur, collapse = ""))
  }
  make_format(
    write = function(v, f) {
      rows <- vapply(to_json(v), function(item) {
        cells <- vapply(columns, function(col) {
          cell <- get_key(item, col)
          c <- if (is.null(cell)) nulltext else spell_cell(cell, col)
          c <- gsub(esc, paste0(esc, esc), c, fixed = TRUE)
          gsub(delim, paste0(esc, delim), c, fixed = TRUE)
        }, "")
        paste0(delim, " ", paste(cells, collapse = paste0(" ", delim, " ")), " ", delim)
      }, "")
      paste(rows, collapse = "\n")
    },
    read = function(c, f) {
      items <- get_key(f$shape, "items")
      props <- if (pytruthy(items)) get_key(items, "properties", jobj()) else jobj()
      t <- capture_text(c)
      lines <- split_lines(t)
      rows <- lines[startsWith(wstrip(lines), delim)]
      if (!length(rows) && nzchar(wstrip(t))) {
        ch <- chars_of(wstrip(t))$ch; preview <- paste(ch[seq_len(min(60L, length(ch)))], collapse = "")
        stop(sprintf("no table row (a line starting with %s) in %s; an empty table is written as nothing", pyrepr(delim), pyrepr(preview)), call. = FALSE)
      }
      out <- list()
      for (line in lines) {
        line <- wstrip(line)
        if (!startsWith(line, delim)) next
        cells <- split_row(line)
        if (length(cells) == length(columns) && all(wstrip(cells) == columns)) next
        if (length(cells) != length(columns)) stop(sprintf("row has %d cells, expected %d (%s): %s", length(cells), length(columns), pyrepr(as.list(columns)), pyrepr(line)), call. = FALSE)
        item <- jobj()
        for (k in seq_along(columns)) {
          cell <- wstrip(cells[[k]])
          item <- set_key(item, columns[[k]], if (cell == nulltext) NULL else cell_read(get_key(props, columns[[k]], jobj()), cell, sprintf("column %s", pyrepr(columns[[k]]))))
        }
        out[[length(out) + 1L]] <- item
      }
      out
    },
    describe = function(f) paste0(delim, " ", paste(columns, collapse = paste0(" ", delim, " ")), " ", delim, "  (one row per item)"),
    accepts = c("list[object]", "list[*]"), direction = "both")
}

scaled_number_format <- function(options) {
  scale <- num_value(get_key(options, "scale", 1)); suffix <- get_key(options, "suffix", ""); rnd <- get_key(options, "round")
  make_format(
    write = function(v, f) {
      x <- as.double(num_value(v)) * scale
      if (!is.null(rnd)) { p <- 10^num_value(rnd); x <- round(x * p) / p }
      paste0(format_number(x), suffix)
    },
    read = function(c, f) {
      t <- wstrip(capture_text(c))
      if (nzchar(suffix) && endsWith(t, suffix)) t <- bsl(t, 0L, blen(t) - blen(suffix))
      cell_read(jobj(type = "number"), t, "scaled_number") / scale
    },
    describe = function(f) paste0("a number like ", if (isTRUE(scale == 100)) "83" else "0.83", suffix),
    accepts = c("number", "integer"), direction = "both", round_trip = is.null(rnd))
}

# ------------------------------------------------------------------ reader

json_object_reader <- function(spec) {
  extra <- ssort(setdiff(names(spec), c("kind", "probabilities")))
  policy <- get_key(spec, "probabilities")
  if (length(extra) || (!is.null(policy) && !isTRUE(policy %in% c("off", "if_available", "required"))))
    malformed("reader", paste0("reader: json_object takes 'probabilities' (off | if_available | required)", if (length(extra)) paste0(", not ", pyrepr(as.list(extra))) else paste0(", not ", pyrepr(policy))))
  document <- function(t) {
    s <- wstrip(t)
    if (startsWith(s, "```")) {
      nl <- bfind(s, "\n"); hits <- ball(s, "```"); closing <- if (length(hits)) hits[[length(hits)]] else -1L
      if (nl >= 0L && closing > nl) s <- wstrip(bsl(s, nl + 1L, closing))
    }
    tryCatch(json_members(s), error = function(first) if (is_refusal(first)) stop(first) else {
      start <- bfind(s, "{"); ends <- ball(s, "}"); stop_ <- if (length(ends)) ends[[length(ends)]] else -1L
      if (!(start >= 0L && start < stop_)) refuse("reader-error", sprintf("json_object: reply contains no JSON object (%s)", errmsg(first)))
      tryCatch(json_members(bsl(s, start, stop_ + 1L)), error = function(err) if (is_refusal(err)) stop(err) else refuse("reader-error", sprintf("json_object: reply is not a JSON object: %s", errmsg(err))))
    })
  }
  new_reader(
    spec = as_obj(spec),
    requires = function() "native_structured_output",
    request_settings = function(fields) {
      props <- jobj()
      for (f in fields) props[[f$name]] <- if (!is.null(f$desc) && nzchar(f$desc)) set_key(closed_shape(f$shape), "description", f$desc) else closed_shape(f$shape)
      config <- jobj(response_format = jobj(type = "json_schema", schema = jobj(type = "object", properties = props,
        required = lapply(fields, function(f) f$name), additionalProperties = FALSE)))
      if (!is.null(policy)) config[["probabilities"]] <- policy
      jobj(config = config)
    },
    split = function(t, names_) {
      raw <- jobj()
      for (m in document(t)) {
        key <- m[[1]]
        if (!(key %in% names_)) next
        if (has_key(raw, key)) refuse("parse-ambiguous", sprintf("json_object: member %s appears more than once in the reply \u2014 refusing to guess which one is real", pyrepr(key)))
        raw[[key]] <- if (is_str(m[[2]])) m[[2]] else wstrip(m[[3]])
      }
      missing <- names_[!vapply(names_, function(n) has_key(raw, n), TRUE)]
      if (length(missing)) refuse("parse-missing-fields", paste0("reply object is missing key(s): ", paste(vapply(missing, pyrepr, ""), collapse = ", ")), partial = raw)
      raw
    },
    join = function(spelled) {
      obj <- jobj()
      for (s in spelled) {
        r <- tryCatch(list(ok = TRUE, v = json_loads(s[[2]])), error = function(e) list(ok = FALSE, v = NULL))
        obj <- set_key(obj, s[[1]], if (r$ok && !is_str(r$v)) r$v else s[[2]])
      }
      json_dumps(obj, 2L)
    })
}

# ------------------------------------------------------------------ reasoning

prefix_cot <- function(options) new_transport(requires = list("instruct"), in_template = TRUE,
  tell = jobj(system = "Reason step by step in the '{field}' section before writing any other section."))

reasoning_tags <- function(options) {
  o <- get_key(options, "open", "<think>"); c <- get_key(options, "close", "</think>")
  new_transport(requires = list("instruct"), in_template = FALSE,
    tell = jobj(system = sprintf("After every sentence of output, add your thinking inside %s...%s tags.", o, c)),
    find = list(jobj(from = "text", between = list(o, c), to = "@purpose", remove = TRUE, repair = TRUE)),
    spelling = jobj(position = "before"))
}

native_reasoning <- function(options) {
  reasoning <- jobj(effort = get_key(options, "effort", "medium"))
  if (has_key(options, "thinking_budget")) reasoning[["thinking_budget"]] <- options[["thinking_budget"]]
  new_transport(requires = list("native_reasoning"), in_template = FALSE, request_settings = jobj(config = jobj(reasoning = reasoning)),
    find = list(jobj(from = "part:thinking", to = "@purpose")))
}

# ------------------------------------------------------------------ tools

TOOL_KEYS <- c("name", "description", "parameters")
default_parameters <- function() jobj(type = "object", properties = jobj())

tool_items <- function(value, f) {
  items <- if (is.list(value) && !is_obj(value)) value else list(value)
  lapply(seq_along(items), function(i) {
    spec <- to_json(items[[i]])
    if (!is_obj(spec)) spec <- jobj()
    if (!is_str(get_key(spec, "name")) || !nzchar(spec[["name"]])) refuse("format-write-error", sprintf("field %s: tools[%d] needs a string 'name'", pyrepr(f$name), i - 1L))
    unknown <- ssort(setdiff(names(spec), c(TOOL_KEYS, "type")))
    if (length(unknown)) refuse("format-write-error", sprintf("field %s: tools[%d] has keys %s; a tool is name, description, parameters (lm15 FunctionTool)", pyrepr(f$name), i - 1L, pyrepr(as.list(unknown))))
    spec
  })
}

TOOL_ACCEPTS <- c("list[Tool]", "Tool", "list[*]", "object", "*")

function_tool_format <- function(options) make_format(
  write = function(v, f) lapply(tool_items(v, f), function(s) {
    part <- jobj(type = "function", name = s[["name"]])
    if (pytruthy(get_key(s, "description"))) part[["description"]] <- s[["description"]]
    part[["parameters"]] <- if (pytruthy(get_key(s, "parameters"))) s[["parameters"]] else default_parameters()
    part
  }),
  read = function(c, f) lapply(capture_parts_of(c, "function"), function(p) drop_key(p, "type")),
  describe = function(f) "tools", accepts = TOOL_ACCEPTS, direction = "in", writes = "parts", reads = "function")

tool_catalog_format <- function(options) make_format(
  write = function(v, f) paste(vapply(tool_items(v, f), function(s) paste0("- ", s[["name"]], "(", json_dumps(if (pytruthy(get_key(s, "parameters"))) s[["parameters"]] else default_parameters(), NULL), ")",
                                                                        if (pytruthy(get_key(s, "description"))) paste0(": ", s[["description"]]) else ""), ""), collapse = "\n"),
  describe = function(f) "tools", accepts = TOOL_ACCEPTS, direction = "in")

tool_calls_format <- function(options) make_format(
  write = function(v, f) lapply(v %||% list(), function(c) { c <- to_json(c); jobj(type = "tool_call", id = c[["id"]], name = c[["name"]], input = get_key(c, "input", jobj())) }),
  read = function(c, f) {
    calls <- list(); n <- 0L
    for (p in c$parts) {
      if (identical(get_key(p, "type"), "tool_call")) calls[[length(calls) + 1L]] <- drop_key(drop_key(p, "type"), "continuation")
      else if (is_str(get_key(p, "text"))) {
        obj <- tryCatch(json_loads(p[["text"]]), error = function(e) refuse("format-read-error", sprintf("field %s: a fenced call is not JSON: %s", pyrepr(f$name), errmsg(e))))
        if (!is_obj(obj) || !is_str(get_key(obj, "name"))) refuse("format-read-error", sprintf("field %s: a fenced call is {name, input}", pyrepr(f$name)))
        n <- n + 1L
        calls[[length(calls) + 1L]] <- jobj(id = paste0("call_", n), name = obj[["name"]], input = if (pytruthy(get_key(obj, "input"))) obj[["input"]] else jobj())
      }
    }
    calls
  },
  describe = function(f) "tool calls", accepts = c("list[ToolCall]", "list[*]", "*"), direction = "both", writes = "parts", reads = c("tool_call", "text"))

citations_format <- function(options) make_format(
  write = function(v, f) stop("format citations does not write"),
  read = function(c, f) {
    out <- list(); seen <- character(0)
    for (p in c$parts) {
      if (identical(get_key(p, "type"), "citation")) out[[length(out) + 1L]] <- drop_key(drop_key(p, "type"), "continuation")
      else if (is_str(get_key(p, "text"))) {
        t <- wstrip(p[["text"]])
        if (grepl("\\A[0-9]+\\z", t, perl = TRUE) && !(t %in% seen)) { seen <- c(seen, t); out[[length(out) + 1L]] <- jobj(source = integer_value(t)) }
      }
    }
    out
  },
  accepts = c("list[Citation]", "list[*]", "*"), direction = "out", writes = "parts", reads = c("citation", "text"))

source_list_format <- function(options) make_format(
  write = function(v, f) {
    v <- v %||% list()
    paste(vapply(seq_along(v), function(i) {
      s <- to_json(v[[i]])
      if (!is_obj(s) || !is_str(get_key(s, "text"))) refuse("format-write-error", sprintf("field %s: sources[%d] needs 'text'", pyrepr(f$name), i - 1L))
      title <- if (pytruthy(get_key(s, "title"))) s[["title"]] else if (pytruthy(get_key(s, "url"))) s[["url"]] else paste("source", i)
      sprintf("[%d] %s: %s", i, title, s[["text"]])
    }, ""), collapse = "\n")
  },
  describe = function(f) "numbered sources", accepts = c("list[Source]", "list[*]", "*"), direction = "in")

native_tools <- function(options) new_transport(requires = list("native_function_calling"), in_template = FALSE, put = jobj(`@purpose` = "request.tools"),
  find = list(jobj(from = "part:tool_call", to = "@purpose.calls", complete_reply = TRUE)))

fenced_tools <- function(options) new_transport(requires = list("instruct"), in_template = FALSE, put = jobj(`@purpose` = "message:system"),
  written_as = jobj(`@purpose` = "tool_catalog"),
  tell = jobj(system = "You may call a tool by replying with exactly one fenced block:\n```tool\n{\"name\": \"<tool>\", \"input\": {...}}\n```\nand nothing else; you will be given the result and asked again."),
  find = list(jobj(from = "text", between = list("```tool\n", "\n```"), to = "@purpose.calls", remove = TRUE, complete_reply = TRUE)),
  spelling = jobj(call = "```tool\n{\"name\": \"{name}\", \"input\": {input}}\n```", result = "Result of {name} ({id}):\n{output}"))

native_citations <- function(options) {
  t <- new_transport(requires = list("native_citations"), in_template = FALSE, find = list(jobj(from = "part:citation", to = "@purpose")))
  if (pytruthy(if (has_key(options, "search")) options[["search"]] else TRUE)) t$request_settings <- jobj(tools = list(jobj(type = "builtin", name = "web_search")))
  t
}

inline_citations <- function(options) new_transport(requires = list("instruct"), in_template = FALSE, put = jobj(`@purpose.sources` = "message:user"),
  tell = jobj(system = "Cite the numbered sources inline as [n] after each claim they support."),
  find = list(jobj(from = "text", between = list("[", "]"), to = "@purpose", remove = FALSE)))

# ------------------------------------------------------------------ code

code_options <- function(opts, calls = FALSE) {
  allowed <- if (calls) c("marker", "tool") else "marker"
  unknown <- ssort(setdiff(names(opts), allowed))
  if (length(unknown)) stop(sprintf("unknown options: %s", pyrepr(as.list(unknown))), call. = FALSE)
  marker <- get_key(opts, "marker", "PY_END"); tool <- get_key(opts, "tool", "run_python")
  for (kv in list(list("marker", marker), list("tool", tool))) if (!is_identifier(kv[[2]])) stop(sprintf("%s must be a nonempty ASCII identifier", kv[[1]]), call. = FALSE)
  list(marker, tool)
}
code_of <- function(v) {
  if (!is_obj(v) || length(v) != 1L || !has_key(v, "code") || !is_str(v[["code"]])) stop("code arguments must be exactly {code: string}", call. = FALSE)
  v[["code"]]
}
code_write <- function(marker, v) {
  code <- code_of(v)
  if (grepl(marker, code, fixed = TRUE)) refuse("value-collides", sprintf("code contains heredoc marker %s; choose another marker", pyrepr(marker)))
  code
}
code_read <- function(marker, c) {
  if (any(vapply(c$parts, function(p) !identical(get_key(p, "type"), "text") || !is_str(get_key(p, "text")), TRUE))) stop("code arguments need text parts", call. = FALSE)
  code <- paste(vapply(c$parts, function(p) p[["text"]], ""), collapse = "")
  if (grepl(marker, code, fixed = TRUE)) stop(sprintf("code contains heredoc marker %s", pyrepr(marker)), call. = FALSE)
  jobj(code = code)
}

code_arguments_format <- function(opts) {
  marker <- code_options(opts)[[1]]
  make_format(write = function(v, f) code_write(marker, v), read = function(c, f) code_read(marker, c), describe = function(f) "raw code", accepts = "object", direction = "both")
}

code_calls_format <- function(opts) {
  o <- code_options(opts, TRUE); marker <- o[[1]]; tool <- o[[2]]
  native <- function(call, writing) {
    c <- to_json(call)
    if (!is_obj(c) || !identical(get_key(c, "name"), tool) || !is_str(get_key(c, "id")) || !nzchar(c[["id"]])) stop(sprintf("expected a %s call with a nonempty id", pyrepr(tool)), call. = FALSE)
    body <- if (writing) code_write(marker, get_key(c, "input")) else { b <- code_of(get_key(c, "input")); code_read(marker, capture_of_text(b)); b }
    jobj(id = c[["id"]], name = tool, input = jobj(code = body))
  }
  make_format(
    write = function(v, f) { if (!is.list(v) || is_obj(v)) stop("calls must be a list", call. = FALSE); lapply(v, function(c) c(jobj(type = "tool_call"), native(c, TRUE))) },
    read = function(cap, f) {
      calls <- list()
      for (p in cap$parts) calls[[length(calls) + 1L]] <- if (identical(get_key(p, "type"), "tool_call")) native(p, FALSE)
        else jobj(id = paste0("call_", length(calls) + 1L), name = tool, input = code_read(marker, new_capture(list(p))))
      calls
    },
    describe = function(f) "heredoc tool calls", accepts = c("list[*]", "*"), direction = "both", writes = "parts", reads = c("text", "tool_call"))
}

heredoc_tools <- function(opts) {
  o <- code_options(opts, TRUE); marker <- o[[1]]; tool <- o[[2]]
  opening <- sprintf("%s <<'%s'\n", tool, marker); closing <- paste0("\n", marker)
  new_transport(requires = list("instruct"), in_template = FALSE, put = jobj(`@purpose` = "message:system"), written_as = jobj(`@purpose` = "tool_catalog"),
    tell = jobj(system = sprintf("To request %s, emit this heredoc and wait for its result:\n%s<code>%s\nDo not put %s anywhere in the code. Otherwise reply normally.", tool, opening, closing, marker)),
    find = list(jobj(from = "text", between = list(opening, closing), to = "@purpose.calls", remove = TRUE, complete_reply = TRUE)),
    spelling = jobj(call = paste0("{name} <<'", marker, "'\n{input}", closing), result = "Result of {name} ({id}):\n{output}",
                    input_format = jobj(use = "code_arguments", options = jobj(marker = marker)),
                    probe = jobj(name = tool, input = jobj(code = "print(6 * 7)\n"))))
}

#' Install the standard vocabulary
#'
#' Registers the standard formats, transports and reader at the versions the
#' contract corpus pins (contract/spec/vocab/).
#' @param reg A registry.
#' @param exist_ok Replace existing entries.
#' @export
install_std <- function(reg = default_registry(), exist_ok = TRUE) {
  register_format(reg, "json", json_format, STD_VERSION, exist_ok)
  register_format(reg, "table", table_format, "0.2.0", exist_ok)
  register_format(reg, "scaled_number", scaled_number_format, "0.2.0", exist_ok)
  register_transport(reg, "prefix_cot", prefix_cot, STD_VERSION, exist_ok)
  register_transport(reg, "reasoning_tags", reasoning_tags, "0.3.0", exist_ok)
  register_transport(reg, "native_reasoning", native_reasoning, STD_VERSION, exist_ok)
  register_reader(reg, "json_object", json_object_reader, "0.2.1", exist_ok)
  for (x in list(list("function_tool", function_tool_format), list("tool_catalog", tool_catalog_format), list("tool_calls", tool_calls_format),
                 list("citations", citations_format), list("source_list", source_list_format))) register_format(reg, x[[1]], x[[2]], STD_VERSION, exist_ok)
  for (x in list(list("native_tools", native_tools), list("fenced_tools", fenced_tools), list("native_citations", native_citations),
                 list("inline_citations", inline_citations))) register_transport(reg, x[[1]], x[[2]], STD_VERSION, exist_ok)
  register_format(reg, "code_arguments", code_arguments_format, STD_VERSION, exist_ok)
  register_format(reg, "code_calls", code_calls_format, STD_VERSION, exist_ok)
  register_transport(reg, "heredoc_tools", heredoc_tools, STD_VERSION, exist_ok)
  invisible(reg)
}

# The shape as strict schema enforcement takes it (json_object 0.2.1): every
# record (an object schema with `properties`) that does not say
# `additionalProperties` gets `additionalProperties: false` and lists every
# property in `required`, in property order. A record that says
# `additionalProperties` stays open as written, and so does an object without
# `properties` (a map, any object).
closed_shape <- function(shape) {
  one <- c("additionalProperties", "items", "not", "if", "then", "else", "contains", "anyOf", "oneOf", "allOf", "prefixItems")
  maps <- c("properties", "patternProperties", "$defs", "definitions")
  if (is_arr(shape)) return(lapply(shape, closed_shape))
  if (!is_obj(shape)) return(shape)
  out <- as_obj(shape)
  # By position: a property may be named "" (kernel section 1).
  for (i in seq_along(out)) {
    key <- names(out)[[i]]
    v <- out[[i]]
    if (key %in% maps && is_obj(v)) {
      v <- as_obj(v)
      for (j in seq_along(v)) v[j] <- list(closed_shape(v[[j]]))
      out[[i]] <- v
    } else if (key %in% one) {
      out[i] <- list(closed_shape(v))
    }
  }
  properties <- get_key(out, "properties")
  if (is_obj(properties)) {
    out <- set_key(out, "required", as.list(unname(names(properties))))
    if (!has_key(out, "additionalProperties")) out <- set_key(out, "additionalProperties", FALSE)
  }
  out
}

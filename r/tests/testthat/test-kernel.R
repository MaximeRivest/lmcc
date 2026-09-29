# What the corpus and the differential check do not reach: the README runs,
# streaming refines batch under random multi-chunk splits, per-feed cost
# stays linear, the C core is exact, host differences are the stated ones.

root <- function() {
  d <- normalizePath(test_path("..", "..", ".."), mustWork = FALSE)
  if (file.exists(file.path(d, "contract"))) d else Sys.getenv("LMCC_ROOT", NA)
}

test_that("the README runs", {
  readme <- file.path(test_path("..", ".."), "README.md")
  skip_if_not(file.exists(readme))
  text <- paste(readLines(readme, encoding = "UTF-8"), collapse = "\n")
  blocks <- regmatches(text, gregexpr("(?ms)^```r\\n.*?^```$", text, perl = TRUE))[[1]]
  code <- gsub("^```r\\n|\\n```$", "", blocks)
  env <- new.env()
  eval(parse(text = paste(code, collapse = "\n"), encoding = "UTF-8"), envir = env)
  expect_true(TRUE)
})

test_that("the C core is exact", {
  expect_equal(parse_json("1.00000000000000011102230246251565404236316680908203125"), 1)
  expect_equal(vapply(list(3, 1e21, 1e-7, 0.000001, -0, 123456789012345680000), format_number, ""), c("3", "1e+21", "1e-7", "0.000001", "0", "123456789012345680000"))
  expect_equal(unclass(parse_json("9007199254740993")), "9007199254740993")
  expect_equal(sha256_hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
  expect_equal(sha256_hex(strrep("a", 1000)), "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3")
  obj <- structure(list(1.0, list(1e-7, "\u00e9\n"), 1L), names = c("b", "a", "\uffff"))
  expect_equal(json_text(obj, sort_keys = TRUE), "{\"a\":[1e-7,\"\u00e9\\n\"],\"b\":1,\"\uffff\":1}")
  expect_error(parse_json("{\"a\": 1, \"a\": 2}", "reject"))
})

test_that("host differences are the stated ones", {
  sig <- lmcc_signature("Count.", inputs = list(n = shape_integer()), outputs = list(big = shape_integer()))
  plan <- lmcc_bind(adapter(list(system_msg("<big>{big}</big>"), user_msg("{n}"))), sig)
  expect_equal(render(plan, list(n = 3))$messages[[1]]$parts[[1]]$text, "3")
  expect_equal(tryCatch(render(plan, list(n = 3.5)), lmcc_refusal = function(e) e$code), "value-invalid")
  expect_equal(unclass(parse_reply(plan, "<big>9223372036854775807</big>")$big), "9223372036854775807")
  a <- adapter(list(user_msg("{n}")), formats = list(X = make_format(function(v, f) "x")))
  expect_equal(tryCatch(dump_adapter(a), lmcc_refusal = function(e) e$code), "format-not-self-contained")
  expect_equal(tryCatch(new_signature(5, list()), lmcc_refusal = function(e) e$code), "signature-malformed")
})

mutate <- function(text, i, j, op) {
  fix <- function(s) { Encoding(s) <- "UTF-8"; s }
  b <- function(a, z = nchar(text, "bytes")) fix(substr(`Encoding<-`(text, "bytes"), a + 1, z))
  out <- switch(op,
    paste0(b(0, i), toupper(b(i, j)), b(j)), paste0(b(0, i), sample(c("**", "#", "### ", "_", "\n", " "), 1), b(i)),
    paste0(b(0, i), b(j)), paste0(b(0, j), b(i, j), b(j)), b(0, i), paste0(b(0, i), sample(c("\"", ".", "`", "None"), 1), b(i)))
  fix(out)
}

test_that("streaming refines batch under random splits", {
  r <- root(); skip_if(is.na(r))
  set.seed(7)
  runs <- 0L; successes <- 0L
  ns <- asNamespace("lmcc")
  for (f in sort(list.files(file.path(r, "contract", "corpus", "cases"), full.names = TRUE))) {
    c <- parse_json(paste(readLines(f, encoding = "UTF-8", warn = FALSE), collapse = "\n"))
    if (!is.character(c$response) || any(startsWith(as.character(unlist(c$requires)), "udf:"))) next
    reg <- lmcc_registry(extensions = as.character(unlist(c$requires)))
    if ("std" %in% unlist(c$vocab)) install_std(reg)
    plan <- tryCatch(lmcc_bind(load_adapter(c$entry, reg), signature_from_list(c$signature), c$capabilities %||% list(), reg), error = function(e) NULL)
    if (is.null(plan)) next
    for (k in 1:12) {
      t <- c$response
      if (k > 1) {
        cs <- ns$chars_of(t); n <- length(cs$ch)
        starts <- c(cs$start, nchar(t, "bytes"))
        i <- starts[[sample.int(n + 1L, 1)]]; j <- starts[[min(n + 1L, match(i, starts) + sample.int(11, 1))]]
        t <- mutate(t, i, j, sample.int(6, 1))
        if (!validUTF8(t)) next
      }
      runs <- runs + 1L
      batch <- tryCatch(list("ok", ns$parse_with_captures(plan, t)), lmcc_refusal = function(e) list("refuse", describe_refusal(e)))
      ch <- ns$chars_of(t)$ch
      cuts <- if (length(ch) > 1L) sort(unique(sample.int(length(ch) - 1L, min(6L, length(ch) - 1L)))) else integer(0)
      pieces <- mapply(function(a, z) paste(ch[seq.int(a, length.out = z - a + 1L)], collapse = ""), c(1L, cuts + 1L), c(cuts, length(ch)))
      s <- reply_stream(plan); events <- list()
      res <- tryCatch({ for (p in pieces) events <- c(events, feed(s, p)); e <- finish(s); c(events, e$events); list("ok", e, c(events, e$events)) },
                      lmcc_refusal = function(e) list("refuse", describe_refusal(e)))
      expect_equal(res[[1]], batch[[1]])
      if (batch[[1]] == "ok" && res[[1]] == "ok") {
        expect_true(ns$json_equal(res[[2]]$values, batch[[2]][[1]]) && ns$json_equal(res[[2]]$repairs, batch[[2]][[3]]))
        joined <- list()
        for (e in res[[3]]) if (e$kind == "field_delta") joined[[e$field]] <- paste0(joined[[e$field]] %||% "", e$text)
        for (n in names(batch[[2]][[2]])) expect_equal(joined[[n]] %||% "", capture_text(batch[[2]][[2]][[n]]))
        successes <- successes + 1L
      } else if (batch[[1]] == "refuse") expect_true(ns$json_equal(res[[2]], batch[[2]]))
    }
  }
  expect_gt(runs, 400L); expect_gt(successes, 150L)
})

test_that("streaming cost is linear in the reply length", {
  sig <- lmcc_signature("Think.", inputs = list(q = shape_string()), outputs = list(reasoning = shape_string(), answer = shape_string()))
  plan <- lmcc_bind(adapter(list(system_msg("{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}[[ ## completed ## ]]"), user_msg("{q}"))), sig)
  body <- strrep("lorem ipsum dolor sit amet ", 2000)
  cost <- function(n) {
    t <- paste0("[[ ## reasoning ## ]]\n", substr(body, 1, n), "\n\n[[ ## answer ## ]]\nok\n\n[[ ## completed ## ]]")
    s <- reply_stream(plan)
    start <- proc.time()[["elapsed"]]
    for (i in seq(1, nchar(t), by = 16)) feed(s, substr(t, i, i + 15))
    stopifnot(finish(s)$values$answer == "ok")
    proc.time()[["elapsed"]] - start
  }
  cost(2000)
  small <- cost(10000); large <- cost(40000)
  expect_lt(large, 12 * small + 0.5)
})

test_that("a member named \"\" is found, written once, and compared (kernel section 1, D-58)", {
  # R's x[[""]] is NULL and x[[""]] <- v appends: every lookup is by position.
  x <- parse_json("{\"\": 1, \"a\": {\"\": null}, \"\": 2}")
  expect_equal(names(x), c("", "a"))
  expect_equal(x[[1]], 2)
  expect_equal(json_text(x), "{\"\":2,\"a\":{\"\":null}}")
  expect_equal(json_text(lmcc:::to_json(x)), "{\"\":2,\"a\":{\"\":null}}")
  expect_false(lmcc:::json_equal(parse_json("{\"\": 1}"), parse_json("{\"\": 2}")))
  expect_true(lmcc:::json_equal(parse_json("{\"\": 1, \"b\": 2}"), parse_json("{\"b\": 2, \"\": 1}")))
  shape <- parse_json("{\"type\": \"object\", \"properties\": {\"b\": {\"type\": \"string\"}, \"\": {\"type\": \"object\", \"properties\": {\"\": {}}}}}")
  expect_equal(json_text(lmcc:::closed_shape(shape)),
    "{\"type\":\"object\",\"properties\":{\"b\":{\"type\":\"string\"},\"\":{\"type\":\"object\",\"properties\":{\"\":{}},\"required\":[\"\"],\"additionalProperties\":false}},\"required\":[\"b\",\"\"],\"additionalProperties\":false}")
})

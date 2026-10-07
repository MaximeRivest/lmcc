# A type's JSON form, both ways (D-61, D-62): bind_type(..., to_json, from_json),
# dump_turn(), load_turn(). The format bound to a type receives the value
# itself, live or replayed; every other format receives its JSON form.

tags <- function() adapter(list(
  system_msg("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
  turns_slot(), user_msg("{% for f in inputs %}{f.value}\n{% endfor %}")))

pages <- function(...) structure(list(...), class = "pages")
pages_to_json <- function(p) lapply(unclass(p), function(x) jobj(text = x$text, png = paste(as.character(x$png), collapse = "")))
pages_from_json <- function(d) do.call(pages, lapply(d, function(x)
  list(text = x$text, png = as.raw(strtoi(substring(x$png, seq(1, nchar(x$png), 2), seq(2, nchar(x$png), 2)), 16L)))))
doc <- pages(list(text = "page 1", png = as.raw(c(0x89, 0x50, 0x4e, 0x47))))
summary_sig <- function(shape = shape_list()) lmcc_signature("Summarize.",
  inputs = list(document = field_spec(shape, type = "Pages")), outputs = list(summary = shape_string()))

test_that("a bound type is written, saved, loaded and written again the same", {
  seen <- new.env(); seen$classes <- character()
  reg <- lmcc_registry()
  bind_type(reg, "Pages", make_format(function(v, f) { seen$classes <- c(seen$classes, class(v)[[1]]); "pages" }),
            to_json = pages_to_json, from_json = pages_from_json)
  plan <- lmcc_bind(tags(), summary_sig(), list(instruct = TRUE), reg)
  turn <- finish_turn(record_step(render(plan, list(document = doc)), "<summary>\nOne page.\n</summary>"))
  saved <- parse_json(json_text(dump_turn(plan, turn)))
  expect_equal(json_text(saved$inputs), "{\"document\":[{\"text\":\"page 1\",\"png\":\"89504e47\"}]}")
  back <- load_turn(plan, saved)
  expect_s3_class(back$inputs$document, "pages")
  expect_identical(unclass(back$inputs$document), unclass(doc))
  expect_equal(json_text(request_of(render(plan, list(document = doc), turns = list(turn)), "m")),
               json_text(request_of(render(plan, list(document = doc), turns = list(back)), "m")))
  expect_true(length(seen$classes) > 0 && all(seen$classes == "pages"))
})

test_that("every other format receives the JSON form", {
  reg <- install_std(lmcc_registry())
  bind_type(reg, "Pages", to_json = pages_to_json, from_json = pages_from_json)
  a <- adapter(tags()$template, formats = list(`list[*]` = jobj(use = "json", options = jobj(indent = NULL))))
  plan <- lmcc_bind(a, summary_sig(), list(instruct = TRUE), reg)
  text <- request_of(render(plan, list(document = doc)), "m")$messages[[1]]$parts[[1]]$text
  expect_match(text, "\"png\": \"89504e47\"", fixed = TRUE)
})

test_that("binding a type again replaces it; a binding needs something", {
  reg <- lmcc_registry()
  bind_type(reg, "Pages", make_format(function(v, f) "one"))
  bind_type(reg, "Pages", make_format(function(v, f) "two"), to_json = pages_to_json)
  expect_equal(json_text(describe_registry(reg)$type_bindings), "[{\"type\":\"Pages\",\"format\":\"(inline)\",\"json\":[\"to_json\"]}]")
  expect_equal(tryCatch(bind_type(reg, "Pages"), lmcc_refusal = function(e) e$code), "entry-malformed")
  expect_equal(tryCatch(bind_type(reg, "Pages", to_json = "no"), lmcc_refusal = function(e) e$fix$path), "to_json")
  bind_type(reg, "Pages", to_json = pages_to_json)
  expect_null(lmcc:::type_binding(reg, "Pages"))
})

test_that("failures name the value", {
  broken <- function(x) stop("boom")
  reg <- lmcc_registry()
  bind_type(reg, "Pages", to_json = broken, from_json = broken)
  plan <- lmcc_bind(tags(), summary_sig(shape_media("image")), list(instruct = TRUE), reg)
  err <- tryCatch(render(plan, list(document = doc)), lmcc_refusal = function(e) e)
  expect_equal(err$code, "format-write-error"); expect_match(err$hint, "boom")
  ex <- example_turn(plan, list(document = jobj(media_type = "image/png", data = "AA==")), list(summary = "s"))
  err <- tryCatch(load_turn(plan, turn_to_list(ex)), lmcc_refusal = function(e) e)
  expect_equal(err$code, "turn-invalid"); expect_match(err$hint, "turn.inputs.document", fixed = TRUE)
})

# The lm15 bridge (R/lm15.R) against a real lm15 for R, offline: no network
# once installed, no keys. Run by r/check with lm15 installed from its pinned
# release tag into r/.lib-lm15; fails loudly if lm15 cannot be loaded.

library(testthat)
library(lmcc)
stopifnot(requireNamespace("lm15", quietly = TRUE))

ask <- adapter(list(system_msg("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
                    turns_slot(), user_msg("{picture}")))
picture <- lm15::image_part(media_type = "image/png", data = "iVBORw0KGgo=")
colour <- function(reg = default_registry()) lmcc_bind(ask,
  lmcc_signature("The main colour.", inputs = list(picture = lm15_media("image")), outputs = list(colour = shape_string())),
  list(instruct = TRUE), reg)
part_of <- function(r) request_of(r, "m")$messages[[1]]$parts[[1]]
reply <- function(text, reason) lm15::response(model = "m", message = lm15::message_assistant(text), finish_reason = reason)

test_that("lm15 media parts are field types and values (issue #3)", {
  p <- colour()
  expect_equal(p$signature$fields[[1]]$type, "ImagePart")
  r <- render(p, list(picture = picture))
  expect_equal(json_text(part_of(r)), "{\"type\":\"image\",\"media_type\":\"image/png\",\"data\":\"iVBORw0KGgo=\"}")
  expect_s3_class(lm15_request(r, "m")$messages[[1]]$parts[[1]], "lm15_ImagePart")
  path <- lm15::image_part(media_type = "image/png", path = "cat.png")     # lm15 reads the file when it sends
  expect_equal(json_text(part_of(render(p, list(picture = path)))), "{\"type\":\"image\",\"media_type\":\"image/png\",\"path\":\"cat.png\"}")
  expect_equal(json_text(part_of(render(p, list(picture = jobj(media_type = "image/png", data = "AA=="))))),
               "{\"type\":\"image\",\"media_type\":\"image/png\",\"data\":\"AA==\"}")   # part data still works
  err <- tryCatch(render(p, list(picture = lm15::audio_part(media_type = "audio/wav", data = "AAAA"))), lmcc_refusal = function(e) e)
  expect_equal(err$code, "value-invalid"); expect_match(err$hint, "'audio'", fixed = TRUE)

  turn <- finish_turn(record_step(r, "<colour>\nred\n</colour>"))
  saved <- parse_json(json_text(dump_turn(p, turn)))
  expect_equal(json_text(saved$inputs), "{\"picture\":{\"type\":\"image\",\"media_type\":\"image/png\",\"data\":\"iVBORw0KGgo=\"}}")
  back <- load_turn(p, saved)
  expect_s3_class(back$inputs$picture, "lm15_ImagePart")
  expect_equal(json_text(lm15_plain(back$inputs$picture)), json_text(lm15_plain(picture)))
  expect_equal(json_text(request_of(render(p, list(picture = picture), turns = list(turn)), "m")),
               json_text(request_of(render(p, list(picture = picture), turns = list(back)), "m")))
  saved$inputs$picture$type <- "audio"
  expect_equal(tryCatch(load_turn(p, saved), lmcc_refusal = function(e) e$code), "turn-invalid")

  # a media field without lm15's type writes an lm15 part as lm15 does too (kernel section 7b: empty members left out)
  plain <- lmcc_bind(ask, lmcc_signature("x", inputs = list(picture = shape_media("image")), outputs = list(colour = shape_string())), list(instruct = TRUE))
  expect_equal(json_text(part_of(render(plain, list(picture = picture)))), json_text(part_of(r)))
  reg <- lm15_install(lmcc_registry())
  names <- c("ImagePart", "AudioPart", "VideoPart", "DocumentPart", "BinaryPart")
  expect_equal(vapply(describe_registry(reg)$type_bindings, function(b) b$type, ""),
               as.vector(rbind(names, sprintf("list[%s]", names), sprintf("Optional[%s]", names))))
  expect_equal(json_text(part_of(render(colour(reg), list(picture = picture)))), json_text(part_of(r)))
})

test_that("a stopped response refuses parse-filtered (issue #5)", {
  p <- lmcc_bind(ask, lmcc_signature("Answer.", inputs = list(picture = shape_string()), outputs = list(colour = shape_string())), list(instruct = TRUE))
  for (resp in list(reply("<colour>\nred\n</colour>", "content_filter"), reply("", "content_filter")))
    expect_equal(tryCatch(lm15_parse(p, resp), lmcc_refusal = function(e) e$code), "parse-filtered")
  err <- tryCatch(lm15_parse(p, lm15::message_assistant(list(lm15::refusal_part("No.")))), lmcc_refusal = function(e) e)
  expect_equal(err$code, "parse-filtered"); expect_match(err$hint, "'No.'", fixed = TRUE)
})

test_that("several lm15 parts, an optional one, a record holding one (issue #7)", {
  reg <- lm15_install(lmcc_registry()); install_std(reg)
  wildcard <- adapter(list(system_msg("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
                           turns_slot(), user_msg("{% for f in inputs %}{f.value}{% endfor %}")),
                      formats = list("*" = use_vocab("json")))     # as most artifacts carry
  sig <- lmcc_signature("Which picture is brighter?",
    inputs = list(pictures = lm15_media("image", list = TRUE), reference = lm15_media("image", nullable = TRUE)),
    outputs = list(answer = shape_string()))
  expect_equal(vapply(sig$fields[1:2], function(f) f$type, ""), c("list[ImagePart]", "Optional[ImagePart]"))
  p <- lmcc_bind(wildcard, sig, list(instruct = TRUE), reg)
  expect_equal(vapply(describe_plan(p)$inputs, function(f) f$resolved_by, ""), c("kernel", "kernel"))
  night <- lm15::image_part(media_type = "image/jpeg", url = "https://example.com/night.jpg")
  r <- render(p, list(pictures = list(picture, night), reference = NULL))
  expect_equal(json_text(request_of(r, "m")$messages[[1]]$parts),
               paste0("[{\"type\":\"image\",\"media_type\":\"image/png\",\"data\":\"iVBORw0KGgo=\"},",
                      "{\"type\":\"image\",\"media_type\":\"image/jpeg\",\"url\":\"https://example.com/night.jpg\"},",
                      "{\"type\":\"text\",\"text\":\"null\"}]"))
  expect_equal(vapply(lm15_request(r, "m")$messages[[1]]$parts, function(x) class(x)[[1]], ""),
               c("lm15_ImagePart", "lm15_ImagePart", "lm15_TextPart"))
  err <- tryCatch(render(p, list(pictures = list(picture, lm15::audio_part(media_type = "audio/wav", data = "AAAA")), reference = NULL)),
                  lmcc_refusal = function(e) e)
  expect_equal(err$code, "value-invalid"); expect_match(err$hint, "'pictures'[1]", fixed = TRUE)

  turn <- finish_turn(record_step(render(p, list(pictures = list(picture, night), reference = night)), "<answer>\nleft\n</answer>"))
  saved <- parse_json(json_text(dump_turn(p, turn)))
  expect_equal(json_text(saved$inputs$pictures[[2]]), "{\"type\":\"image\",\"media_type\":\"image/jpeg\",\"url\":\"https://example.com/night.jpg\"}")
  back <- load_turn(p, saved)
  expect_s3_class(back$inputs$pictures[[2]], "lm15_ImagePart"); expect_s3_class(back$inputs$reference, "lm15_ImagePart")
  expect_equal(json_text(request_of(render(p, list(pictures = list(), reference = NULL), turns = list(turn)), "m")),
               json_text(request_of(render(p, list(pictures = list(), reference = NULL), turns = list(back)), "m")))
  expect_error(lm15_media("image", list = TRUE, nullable = TRUE), "not both")

  shot <- lmcc_signature("Describe the shot.",
    inputs = list(shot = field_spec(shape_object(list(photo = shape_media("image"), caption = shape_string())), type = "Shot")),
    outputs = list(answer = shape_string()))
  err <- tryCatch(lmcc_bind(wildcard, shot, list(instruct = TRUE), reg), lmcc_refusal = function(e) e)
  expect_equal(err$code, "no-format"); expect_match(err$hint, "holds media", fixed = TRUE); expect_equal(err$fix$key, "Shot")
})

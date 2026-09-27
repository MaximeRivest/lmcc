# The R kernel against real models, through lm15 for R. Costs money: not part
# of ./check. From the repository root, with lm15 and lmcc installed in r/.lib-live:
#
#     set -a; source ~/Projects/lm15-dev/.env; set +a
#     Rscript r/integration/live.R        # writes r/integration/live-record.json
#     python contract/harness/replay_live.py r/integration/live-record.json

suppressPackageStartupMessages({ library(lm15, lib.loc = "r/.lib-live"); library(lmcc, lib.loc = "r/.lib-live") })

reg <- lmcc_registry(); install_std(reg)
# lm15 for R 1.0.0: new_router() with its default env = Sys.getenv() refuses every key, because the
# values keep the "Dlist" class its key check rejects; a plain named character vector works.
router <- new_router(env = unclass(Sys.getenv()))
record <- list(); results <- list()

TAGS <- "Reply with exactly this pattern and nothing else:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"
sections <- adapter(list(system_msg(paste0("{instruction}\n\n", TAGS)), turns_slot(), user_msg("{question}")), name = "sections")
quiz <- lmcc_signature("Answer the question. The score is how sure you are, from 1 to 10.",
                       inputs = list(question = shape_string()), outputs = list(answer = shape_string(), score = shape_integer()))
cfg <- function(n) lm15::config(max_tokens = n)

exchange <- function(r, model, response, turn) jobj(current = turn_to_list(r$turn), request = request_of(r, model),
  response = lm15_plain(response), turn = if (is.null(turn)) NULL else turn_to_list(turn))
save <- function(name, a, sig, caps, exchanges) record[[length(record) + 1L]] <<- jobj(name = name, entry = dump_adapter(a, reg),
  signature = signature_to_list(sig), capabilities = caps, vocab = list("std"), exchanges = exchanges)

attempt <- function(name, model, f) {
  line <- tryCatch(paste("ok ", f()), error = function(e) paste("FAIL", substr(conditionMessage(e), 1, 200)))
  results[[length(results) + 1L]] <<- line
  cat(sprintf("%-14s %-30s %s\n", name, model, line))
}

for (mc in list(list("gpt-4.1-mini", jobj(instruct = TRUE, stop_sequences = TRUE)), list("claude-haiku-4-5", jobj(instruct = TRUE, stop_sequences = TRUE)),
                list("gemini:gemini-2.5-flash", jobj(instruct = TRUE)), list("groq:openai/gpt-oss-20b", jobj(instruct = TRUE)),
                list("deepseek:deepseek-chat", jobj(instruct = TRUE)))) {
  model <- mc[[1]]; caps <- mc[[2]]
  attempt("sections", model, function() {
    plan <- lmcc_bind(sections, quiz, caps, reg)
    r <- render(plan, list(question = "What is the capital of Australia?"))
    response <- complete(router, lm15_request(r, model, cfg(300)))
    reading <- lm15_read(plan, response)
    turn <- lm15_step(r, response)
    st <- lm15_stream(plan, router, lm15_request(r, model, cfg(300)))
    if (!is.numeric(reading$values$score)) stop("score is not a number")
    save(paste0("sections/", model), sections, quiz, caps, list(exchange(r, model, response, turn)))
    sprintf("answer=%s score=%s repairs=%d | stream answer=%s (%d deltas)", deparse(reading$values$answer), reading$values$score, length(reading$repairs),
            deparse(st$result$values$answer), sum(vapply(st$events, function(e) e$kind == "field_delta", TRUE)))
  })
}

ask <- lmcc_signature("Answer the question. Use a tool when you need facts you do not have.",
  inputs = list(question = shape_string(), tools = field_spec(shape_list(shape_object()), purpose = "tools", type = "list[Tool]")),
  outputs = list(calls = field_spec(shape_list(shape_object()), purpose = "tools.calls", type = "list[ToolCall]"), answer = shape_string()))
WEATHER <- jobj(name = "get_weather", description = "Current weather for a city.",
                parameters = jobj(type = "object", properties = jobj(city = jobj(type = "string")), required = list("city")))

tool_loop <- function(transport, model, caps) {
  a <- adapter(list(system_msg("{instruction}\n\nReply with exactly this pattern and nothing else, also after a tool result:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
                    turns_slot(), user_msg("{question}")), name = paste0("tools_", transport),
               transports = list(tools = transport), formats = list(`list[Tool]` = use_vocab("function_tool"), `list[ToolCall]` = use_vocab("tool_calls")))
  plan <- lmcc_bind(a, ask, caps, reg)
  turn <- new_turn(plan, list(question = "What is the weather in Montreal right now?", tools = list(WEATHER)))
  exchanges <- list()
  for (round in 1:4) {
    r <- render(plan, turn)
    response <- complete(router, lm15_request(r, model, cfg(400)))
    turn <- lm15_step(r, response)
    exchanges[[length(exchanges) + 1L]] <- exchange(r, model, response, turn)
    calls <- turn$steps[[length(turn$steps)]]$outputs$calls
    if (!length(calls)) {
      turn <- finish_turn(turn)
      save(sprintf("tools/%s/%s", transport, model), a, ask, caps, exchanges)
      return(sprintf("%d model calls, answer=%s", round, deparse(substr(turn$outputs$answer, 1, 60))))
    }
    for (c in calls) turn <- tool_result(turn, c$id, sprintf("Sunny and 22°C in %s.", c$input$city))
  }
  stop("no answer after 4 rounds")
}

attempt("tools/native", "gpt-4.1-mini", function() tool_loop("native_tools", "gpt-4.1-mini", jobj(instruct = TRUE, native_function_calling = TRUE)))
attempt("tools/native", "claude-haiku-4-5", function() tool_loop("native_tools", "claude-haiku-4-5", jobj(instruct = TRUE, native_function_calling = TRUE)))
attempt("tools/fenced", "deepseek:deepseek-chat", function() tool_loop("fenced_tools", "deepseek:deepseek-chat", jobj(instruct = TRUE)))
attempt("tools/fenced", "claude-haiku-4-5", function() tool_loop("fenced_tools", "claude-haiku-4-5", jobj(instruct = TRUE)))

solve <- lmcc_signature("Solve the problem.", inputs = list(problem = shape_string()),
                        outputs = list(reasoning = field_spec(shape_string(), purpose = "reasoning"), answer = shape_integer()))
thinking <- adapter(list(system_msg(paste0("{instruction}\n\n", TAGS)), user_msg("{problem}")), name = "thinking",
  transports = list(reasoning = jobj(choose = list(jobj(when = jobj(capability = "native_reasoning"), use = jobj(requires = list("native_reasoning"), in_template = FALSE,
      request_settings = jobj(config = jobj(reasoning = jobj(effort = "low"))), find = list(jobj(from = "part:thinking", to = "@purpose")))),
    jobj(`else` = jobj(requires = list("instruct"), in_template = FALSE, tell = jobj(system = "After every sentence of output, add your thinking inside <think>...</think> tags."),
      find = list(jobj(from = "text", between = list("<think>", "</think>"), to = "@purpose", remove = TRUE, repair = TRUE)), spelling = jobj(position = "before")))))))
for (mc in list(list("claude-haiku-4-5", jobj(instruct = TRUE, native_reasoning = TRUE)), list("gemini:gemini-2.5-flash", jobj(instruct = TRUE, native_reasoning = TRUE)),
                list("gpt-4.1-mini", jobj(instruct = TRUE)))) {
  model <- mc[[1]]; caps <- mc[[2]]
  attempt("reasoning", model, function() {
    plan <- lmcc_bind(thinking, solve, caps, reg)
    r <- render(plan, list(problem = "A train leaves at 9:40 and arrives at 13:05. How many minutes is the trip?"))
    response <- complete(router, lm15_request(r, model, cfg(4000)))
    v <- lm15_parse(plan, response)
    save(paste0("reasoning/", model), thinking, solve, caps, list(exchange(r, model, response, lm15_step(r, response))))
    if (!identical(as.integer(v$answer), 205L)) stop(sprintf("answer %s", v$answer))
    sprintf("answer=205 via %s, reasoning %d chars", paste(vapply(plan$find_rules, function(fr) fr[[2]]$from, ""), collapse = ","), nchar(v$reasoning %||% ""))
  })
}

sentiment <- lmcc_signature("Classify the review.", inputs = list(review = shape_string()),
  outputs = list(label = field_spec(shape_enum("positive", "negative", "mixed"), desc = "the review's overall sentiment"), stars = shape_integer()))
json_adapter <- adapter(list(system_msg("{instruction}"), user_msg("{review}")), name = "json", reader = jobj(kind = "json_object"))
attempt("json_object", "gpt-4.1-mini", function() {
  caps <- jobj(instruct = TRUE, native_structured_output = TRUE)
  plan <- lmcc_bind(json_adapter, sentiment, caps, reg)
  r <- render(plan, list(review = "Great battery, awful screen. Three stars."))
  response <- complete(router, lm15_request(r, "gpt-4.1-mini", cfg(200)))
  v <- lm15_parse(plan, response)
  save("json_object/gpt-4.1-mini", json_adapter, sentiment, caps, list(exchange(r, "gpt-4.1-mini", response, lm15_step(r, response))))
  sprintf("label=%s stars=%s", v$label, v$stars)
})

prefilled <- adapter(list(system_msg(paste0("{instruction}\n\n", TAGS)), user_msg("{question}"), assistant_msg("<answer>\n")), name = "prefilled")
attempt("prefill", "claude-haiku-4-5", function() {
  caps <- jobj(instruct = TRUE, assistant_prefill = TRUE, stop_sequences = TRUE)
  plan <- lmcc_bind(prefilled, quiz, caps, reg)
  r <- render(plan, list(question = "What is 17 times 3?"))
  response <- complete(router, lm15_request(r, "claude-haiku-4-5", cfg(200)))
  v <- lm15_parse(plan, response)
  save("prefill/claude-haiku-4-5", prefilled, quiz, caps, list(exchange(r, "claude-haiku-4-5", response, lm15_step(r, response))))
  sprintf("answer=%s score=%s", deparse(v$answer), v$score)
})

attempt("truncated", "gpt-4.1-mini", function() {
  caps <- jobj(instruct = TRUE)
  plan <- lmcc_bind(sections, quiz, caps, reg)
  r <- render(plan, list(question = "Explain photosynthesis in detail."))
  response <- complete(router, lm15_request(r, "gpt-4.1-mini", cfg(16)))
  save("truncated/gpt-4.1-mini", sections, quiz, caps, list(exchange(r, "gpt-4.1-mini", response, NULL)))
  res <- tryCatch({ lm15_parse(plan, response); NULL }, lmcc_refusal = function(e) e$code)
  if (!identical(res, "parse-truncated")) stop("a cut reply was read as finished")
  "refused parse-truncated (finish_reason=length)"
})

writeLines(enc2utf8(json_text(record, spaced = TRUE)), "r/integration/live-record.json", useBytes = TRUE)
failed <- sum(startsWith(unlist(results), "FAIL"))
cat(sprintf("\n%d of %d live scenarios ok; %d recorded for the Python replay\n", length(results) - failed, length(results), length(record)))

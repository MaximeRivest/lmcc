# The helpers (kernel section 6, plan 13) return the same data as Python's
# lmcc.find/put/when/choose; the expected JSON below is what Python's write.

j <- function(x) json_text(x)

test_that("find rules, puts and predicates are Python's data", {
  expect_equal(j(find_between("<think>", "</think>", remove = TRUE, repair = TRUE)),
               "{\"from\":\"text\",\"between\":[\"<think>\",\"</think>\"],\"to\":\"@purpose\",\"remove\":true,\"repair\":true}")
  expect_equal(j(find_between("<a>", "</a>", to = "calls", whole_reply = TRUE)),
               "{\"from\":\"text\",\"between\":[\"<a>\",\"</a>\"],\"to\":\"@purpose.calls\",\"complete_reply\":true}")
  expect_equal(j(find_lines("Answer:", remove = TRUE)), "{\"from\":\"text\",\"line_prefixed\":\"Answer:\",\"to\":\"@purpose\",\"remove\":true}")
  expect_equal(j(find_pattern("x+")), "{\"from\":\"text\",\"pattern\":\"x+\",\"to\":\"@purpose\"}")
  expect_equal(j(find_part("tool_call", to = "calls")), "{\"from\":\"part:tool_call\",\"to\":\"@purpose.calls\"}")
  expect_equal(c(j(put_system()), j(put_developer("x")), j(put_user()), j(put_request("tools", "calls"))),
               c("{\"@purpose\":\"message:system\"}", "{\"@purpose.x\":\"message:developer\"}", "{\"@purpose\":\"message:user\"}",
                 "{\"@purpose.calls\":\"request.tools\"}"))
  expect_equal(c(j(when_has("a")), j(when_lacks("a")), j(when_all(when_has("a"), when_lacks("b"))), j(when_any(when_has("a")))),
               c("{\"capability\":\"a\"}", "{\"not\":{\"capability\":\"a\"}}", "{\"all\":[{\"capability\":\"a\"},{\"not\":{\"capability\":\"b\"}}]}",
                 "{\"any\":[{\"capability\":\"a\"}]}"))
  expect_error(find_between("", "x")); expect_error(find_part("thinking", to = "@x")); expect_error(put_request(""))
})

test_that("choose_transport resolves names and dumps as Python's choose", {
  reg <- install_std(lmcc_registry())
  chosen <- choose_transport(list(when = when_has("native_reasoning"), use = "native_reasoning"), otherwise = "reasoning_tags", registry = reg)
  a <- adapter(list(system_msg("{instruction}\n<answer>{answer}</answer>"), user_msg("{q}")), transports = list(reasoning = chosen))
  expect_equal(j(dump_adapter(a, registry = reg)$transports),
    paste0("{\"reasoning\":{\"choose\":[{\"when\":{\"capability\":\"native_reasoning\"},\"use\":{\"requires\":[\"native_reasoning\"],",
           "\"in_template\":false,\"request_settings\":{\"config\":{\"reasoning\":{\"effort\":\"medium\"}}},\"find\":[{\"from\":\"part:thinking\",\"to\":\"@purpose\"}]}},",
           "{\"else\":{\"requires\":[\"instruct\"],\"in_template\":false,\"tell\":{\"system\":\"After every sentence of output, add your thinking inside <think>...</think> tags.\"},",
           "\"find\":[{\"from\":\"text\",\"between\":[\"<think>\",\"</think>\"],\"to\":\"@purpose\",\"remove\":true,\"repair\":true}],\"spelling\":{\"position\":\"before\"}}}]}}"))
  same <- choose_transport(list(when_has("native_reasoning"), "native_reasoning"), otherwise = "reasoning_tags", registry = reg)
  expect_equal(j(lmcc:::transport_to_list(same)), j(lmcc:::transport_to_list(chosen)))
  expect_error(choose_transport(list(when_has("x")), registry = reg))
})

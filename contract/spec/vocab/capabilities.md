# The capability vocabulary — version 0.3.0

Capability facts are **declared, never sniffed**: the caller hands `bake`
a plain dict of booleans describing the model. Transports predicate on
them; readers may require them. Refusals fire at bake, by name, before any
money is spent.

The vocabulary is deliberately closed and small — predicates stay
portable because they can only mention these words. You cannot predicate
on context length, model name, or version. Adding a fact is a minor
version of this file; changing one's meaning is breaking.

| fact | true means |
|---|---|
| `instruct` | post-trained to follow instructions in a chat shape |
| `completion` | raw continuation model (base); no chat shape |
| `native_reasoning` | an API-level thinking channel exists |
| `native_function_calling` | provider-native tool calling |
| `native_citations` | a provider citations channel |
| `native_structured_output` | the server enforces a JSON schema on the reply (`response_format`) — the gate for `reader/json_object` |
| `image_input` | accepts image parts |
| `assistant_prefill` | the provider continues a request's last `assistant` message as the start of its reply; the plan then sends the template's prefill (kernel §3). Anthropic does for models without extended thinking; OpenAI's Responses API does not |
| `stop_sequences` | the request honors `config.stop` (lm15 `Config.stop`); the plan then asks to stop at the reader's tail (kernel §3) |

An absent key means **false**. A predicate or `requires` naming a fact
not in this table refuses `entry-malformed` at load, at its path (D-29
R2, D-44): a typo in a transport must not silently read as "false". The
caller's own dict may hold extra keys; nothing can name them, so they
are harmless and convey nothing portable.

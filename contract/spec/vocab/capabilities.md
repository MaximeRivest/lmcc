# The capability vocabulary — version 0.1.0

Capability facts are **declared, never sniffed**: the caller hands `bake`
a plain dict of booleans describing the model. Strategies predicate on
them; lenses may require them. Refusals fire at bake, by name, before any
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
| `native_structured_output` | the server enforces a JSON schema on the reply (`response_format`) — the gate for `lens/json_object` |
| `image_input` | accepts image parts |

An absent key means **false**. Unknown keys are ignored by predicates
(they can only be named by the vocabulary above), so declaring extra
private facts is harmless but conveys nothing portable.

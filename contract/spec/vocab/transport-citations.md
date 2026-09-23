# The citations transports and formats — 0.1.0

The `citations` purpose (`purposes.md`): claims grounded in sources. Output
field `citations`, a `list`. Two transports; the program never changes.

## format/citations

`accepts: list[*], *` · `direction: out` · `writes: parts` · `reads:
citation, text`. From `citation` parts (lm15 `CitationPart`): each part
minus `type` and `continuation` — `url`, `title`, `text` as the
provider gave them. From text parts (inline markers): each part's text
is a decimal integer `n` (else skipped — prose in brackets is not a
citation), read as `{"source": n}`; duplicates collapse, first
occurrence wins, order kept. Empty capture reads `[]`.

## transport/native_citations

Requires `native_citations`. **Hidden.** The only citations lm15 returns
today come from provider search tools, so the transport asks for one:
request_settings `{"tools": [{"type": "builtin", "name": "web_search"}]}`
(option `search: false` omits it — for providers that cite without
being asked). FindRule `{from: part:citation, to: @purpose}`. Not a
call turn: the reply still carries its outputs.

## transport/inline_citations

Requires `instruct`. **Hidden.** Serves `citations` together with the
`citations.sources` input (a `list` of sources, `{"title", "text", "url"?}`),
which is placed `{"@purpose.sources": "message:user"}` through
`format/source_list` (`writes: text`; one source per line:
`[n] <title>: <text>`, `n` from 1). `tell` (system):

> Cite the numbered sources inline as [n] after each claim they support.

FindRule `{from: text, between: ["[", "]"], to: @purpose, remove: false}`:
markers stay in the prose the reader reads; `citations` reads them.
Cost, stated: any bracketed integer in the reply counts; bracketed prose
is skipped by the format.

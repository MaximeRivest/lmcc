# LMCC TypeScript clean-room audit

**Provenance.** This implementation (`ts/`) and this audit were written
from `contract/` alone: `spec/kernel.md`, `spec/errors.md`,
`spec/decisions.md`, `spec/vocab/*`, `schema/*`, `corpus/README.md`,
`corpus/cases/*.json`, `corpus/tools/bootstrap.py`, `harness/runner.py`.
No other implementation was read, searched, or opened. The contract was
not modified.

**Result as measured** (`ts/check`): tsc clean; 20/20 unit tests;
harness `74 passed, 0 failed, 6 unclaimed (udf:python)` over the 80 case
files. Section K lists every case.

**How to read an entry.** Each entry has: **Where** (file, section, or
case), **Ambiguity** (quoted), **Chosen** (what this implementation does
and why), **Pinned by** (a case number, or *nothing*), **Proposed case**
(kind, minimal scenario, exact expectation), **Spec sentence** (the one
sentence that would remove the guess). Entries were written while
implementing, in the order the guesses were met, then grouped.

Entry counts: A 6 · B 5 · C 3 · D 6 · E 10 · F 26 · G 26 · H 9 · I 7 · J 9 — 107 entries.

---

## A. Contradictions between spec and corpus

**A1 · `*` and kernel scalars.**
Where: `kernel.md` §5 resolution steps 2 and 4; `schema/entry.schema.json`
`formats.description`; case 48.
Ambiguity: §5 orders "2. the artifact's most specific structural key: …
before `*`" *above* "4. the kernel default: scalars, enums and nullables";
the schema lists `*` as a structural key. Read literally, `formats: {"*":
json}` binds `json` to every field, including strings. Case 48 binds `*`
→ `json` yet renders `doc` (string) as `d`, `who` (nullable string) as
`me`/`null`, and `count` (nullable integer) as `(integer)`/`null` — the
kernel defaults.
Chosen: `*` matches structured shapes only (D-20's `@structured`
ancestry); scalars, enums, nullables and media never resolve through `*`.
Pinned by: 48/49.
Proposed case: `render`, formats `{"*": {"use": "json"}}`, one boolean
input `flag: true` and one string input `s: "hi"` rendered by bare slots →
user text `true hi` (not `true "hi"`).
Spec sentence: "The key `*` matches structured shapes only; a shape the
kernel defaults (scalar, enum, nullable, media) never resolves through `*`."

**A2 · Scope of `visible: false`.**
Where: `kernel.md` §6 "`visible: false` hides the field from loops and the
pattern"; cases 71, 72.
Ambiguity: "the field" is the field bearing the strategy's role. In 71/72
the strategy `work` routes `@role.notes` to field `notes` (role
`work.notes`); the expected prefix shows only `<answer>`, so `notes` must
be hidden too — otherwise it is visible-and-routed (`field-double-covered`,
case 75).
Chosen: `visible: false` hides every field the strategy targets (its role's
field and every `@role.<sub>` routing or placement target).
Pinned by: 72 (prefix bytes), 71.
Proposed case: `refuse`, the 71 entry with `visible` removed → expect
`field-double-covered` naming `work`… (`strategies['work'].visible`); and a
`render` twin of 71 asserting the system text omits `<notes>`.
Spec sentence: "`visible: false` hides the role's field and every field
the strategy's routings and placements target."

**A3 · Kernel scalar reading a `thinking` span.**
Where: `kernel.md` §6 "a routing's span kind must be one the format's
`read` accepts (`format-span-mismatch`)"; §7b; case 64; case 68.
Ambiguity: the kernel default string format declares no span kinds. Case
64 routes `channel:thinking` into a plain string field and expects
`reasoning: "four"`, so the kernel default must accept `thinking` spans;
case 68 (a UDF with `reads: ["text"]`) expects `format-span-mismatch` for
the same routing.
Chosen: kernel scalar defaults and the std text formats read `span.text`
and therefore accept every span kind (`reads: ["*"]`); shipped UDFs use
their declared `reads`.
Pinned by: 64 (accept), 68 (UDF refuse; unclaimed here).
Proposed case: `refuse` or `parse`: `channel:image` routed to an integer
field with a response `{content: [{kind: "image", data: "AA"}]}` → either
`format-span-mismatch` at bind or `parse-value` at parse; the corpus must
pick one.
Spec sentence: "A kernel default format reads any span kind; its value is
`span.text`, the text-bearing parts stripped and joined by newlines."

**A4 · Part coalescing in batch vs span join.**
Where: `kernel.md` §8 "Adjacent part deltas with the same `kind` and string
`text` coalesce into one logical part"; §6 "`span.text` is the stripped
text parts joined by `\n`"; §8 refinement law.
Ambiguity: for a batch response `{content: [{thinking: "a"}, {thinking:
"b"}, …]}` the §6 rule gives `a\nb`; feeding the same parts whole through
`stream.feed` coalesces them to one part and gives `ab`. The law "final
values equal `parse()` of the concatenated response" cannot hold unless
batch coalesces too.
Chosen: `parse()` coalesces adjacent same-kind text-bearing parts before
routing, exactly as the reducer does.
Pinned by: nothing.
Proposed case: `parse`, the 64 entry, response `{content: [{kind:
"thinking", text: "fo"}, {kind: "thinking", text: "ur"}, {kind: "text",
text: "<answer>\n4\n</answer>"}]}` → `reasoning: "four"` (coalesced) — or
`"fo\nur"` if the contract prefers; either way the streaming replay pins
the batch rule.
Spec sentence: "Batch parse coalesces adjacent text-bearing parts of one
kind exactly as `feed` does, so a response and its part-wise replay read
alike."

**A5 · `skeleton().stops` when both a last close and a tail exist.**
Where: `kernel.md` §3 "`stops`: [the last close or tail]"; case 72.
Ambiguity: "or" does not say which wins when the pattern has both (xml
closes plus a `</done>` tail).
Chosen: the tail when non-empty, else the last field's close, else `[]`.
Pinned by: 72 (no tail → last close); 01-style templates (empty closes →
tail) would agree; the both-present case is unpinned.
Proposed case: `plan`, template `{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}</done>` → `stops: ["</done>"]`.
Spec sentence: "`stops` holds the tail when the pattern has one, else the
last visible field's close; a pattern with neither has no stop."

**A6 · Predicates naming facts outside the vocabulary.**
Where: `vocab/capabilities.md` "predicates … can only mention these words";
`errors.md` `entry-malformed` "a bad predicate"; case 78.
Ambiguity: case 78 predicates on `prefill`, which is not in the
vocabulary, and expects `capability-missing`, not `entry-malformed`.
Chosen: any string is a legal fact name; an undeclared fact is false.
Pinned by: 78.
Proposed case: none needed beyond 78; add a sentence.
Spec sentence: "A predicate may name any fact; a fact the caller did not
declare true is false, never a malformed entry."

## B. Contradictions between schema and corpus

**B1 · Structural key `list[string]`.**
Where: `entry.schema.json` `formats.description` lists `object, list[*],
list[object], string, integer, number, boolean, enum, media:<kind>,
media:*, *`; `kernel.md` §5 step 2 names only `list[object]`, `list[*]`;
case 16 keys a format by `list[string]`.
Chosen: arrays whose `items` is a kernel scalar have the key `list[<scalar>]`
before `list[*]`; the `bind-format.key` for such a field is `list[string]`.
Pinned by: 16 (resolution). The fix key is unpinned.
Proposed case: `refuse`, no formats, output `{"type": "array", "items":
{"type": "string"}}` → `no-format`, fix `{"action": "bind-format",
"field": "items", "key": "list[string]"}`.
Spec sentence: "Structural keys are `object`, `list[object]`,
`list[<scalar>]`, `list[*]`, the scalar names, `enum`, `media:<kind>`,
`media:*`, `*`, most specific first."

**B2 · Case kind `plan`.**
Where: `case.schema.json` `kind` enum has `plan`; `kernel.md` §9 "Case
kinds: `render`, `parse`, `roundtrip`, `refuse`"; case 72.
Chosen: implemented `plan` (skeleton + prefix) as the harness does.
Pinned by: 72.
Spec sentence: add `plan` to §9's list: "`plan` compares `skeleton()` and
`prefix(demos, history)`."

**B3 · Shipped UDF keys `accepts`, `emits`, `round_trip`, `reads`.**
Where: `entry.schema.json` `$defs.shipped`; `kernel.md` §5 shipped example
lacks them; case 68 relies on `reads`.
Chosen: honored as the UDF's declared facts (`reads` default `["text"]`,
`emits` default `text`, `round_trip` default `true`, `accepts` default
`[the key]`) — moot here since UDFs are never placed.
Pinned by: nothing (68 is unclaimed for non-placing runtimes).
Proposed case: a runtime-neutral one — a shipped UDF with `emits: "text"`
placed at `controls.x` → `format-placement-mismatch` at bind, without
`requires` (bind facts need no placement). This conflicts with C1: today
`format-untrusted` fires first at load.
Spec sentence: "A shipped format declares `accepts`, `emits`, `reads`
(span kinds), and `round_trip`; absent, they default to `[key]`, `text`,
`["text"]`, `true`."

**B4 · Strategy keys with dots.**
Where: `entry.schema.json` `strategies.propertyNames` pattern allows dots
(`work.notes`); `kernel.md` §6 "`@role` binds to the field bearing the
role".
Ambiguity: for a strategy keyed `work.notes`, `@role` binds to the field
bearing `work.notes` and `@role.x` to `work.notes.x` — presumably; nothing
says.
Chosen: exactly that (the key is the role, dots included).
Pinned by: nothing.
Proposed case: `parse`, strategy keyed `work.notes` routing `@role` from
`between [<n>, </n>]`, field `notes` with role `work.notes` → routed.
Spec sentence: "A strategy's key is its role, dots included; `@role` is
that key."

**B5 · `response` schema vs part validation.**
Where: `case.schema.json` `response.content` is `array` of anything;
`errors.md` `response-malformed` "neither text nor a part list".
Chosen: every part must be an object with a string `kind`; a `text` member,
if present, must be a string; else `response-malformed`.
Pinned by: nothing.
Proposed case: `refuse` at parse, response `{"content": [{"text": "x"}]}`
→ `response-malformed`.
Spec sentence: "A part is an object with a string `kind`; `text`, when
present, is a string."

## C. Contradictions between two cases

**C1 · Cases 60/61 require a placement their refusal does not need.**
Where: 59 (`format-untrusted`, no `requires`), 60 (`udf-tampered`,
`requires: ["udf:python"]`), 61 (`format-not-self-contained`, requires).
Ambiguity: hash verification (60) needs no interpreter, yet the case is
unclaimable by a non-placing runtime, so this implementation's hash check
is exercised by unit tests only. It also hides the load-order question:
does a non-placing runtime say `format-untrusted` or `udf-tampered` for a
tampered UDF?
Chosen: verify the hash first (`udf-tampered`), then refuse placement
(`format-untrusted`).
Pinned by: nothing (60 is unclaimed here).
Proposed case: 60 without `requires` → `udf-tampered`, fix
`{"action": "reship-udf", "path": "formats['Person']"}`.
Spec sentence: "Loaders verify `sha256` before deciding placement; a
tampered UDF refuses `udf-tampered` on every runtime."

**C2 · Case 26 reorders `versions.vocab`.**
Where: 26 input has `lens/json_object` before `format/json`; `expect.entry`
has them reversed.
Ambiguity: harmless under unordered object comparison, but it suggests
`dump` sorts or regenerates `versions.vocab` from references.
Chosen: `dump` echoes the loaded entry unchanged.
Pinned by: 08, 26 (both pass either way).
Proposed case: `roundtrip`, entry with `versions: {"kernel": "0.2.0"}`
(no `vocab`) and a `{"use": "json"}` format → does `dump` add
`"vocab": {"format/json": "0.1.0"}`? Pin one.
Spec sentence: "`dump` writes `versions.vocab` as the versions of every
vocabulary entry the artifact references, from the registry."

**C3 · Case 34 vs 63 fragment placement with a trailing newline.**
Where: 34 (`…<answer>\n...\n` + `\n\n` + fragment → three newlines), 63
(same).
Not a contradiction — recorded because the bytes surprised: the fragment
separator is a fixed `\n\n` with no stripping of the message text.
Pinned by: 34, 63.
Spec sentence: "A fragment appends `\n\n` and its text to the named
message's text, without stripping."

## D. Contradictions between spec and harness

**D1 · Section pointer.** `kernel.md` §9 says "(`spec/kernel.md` §9)" is
the driver protocol; `runner.py` docstring and `corpus/README.md` say §10.
Spec sentence: fix the pointer to §9.

**D2 · `expect.at` is never asserted.**
Where: `case.schema.json` requires `at`; `runner.py` compares only `code`
and `fix`.
Ambiguity: the stage a refusal fires at (`load` vs `bind`, `signature` vs
`bind`) is declared by every refuse case but not checked, so a driver may
refuse at the wrong stage unnoticed.
Chosen: each `Refusal` carries a `stage`; the driver does not report it
(the protocol has no field for it).
Proposed change: the driver answer gains `"at"`, and the harness compares
it when the case declares one.
Spec sentence: "The driver answer may carry `at`; when the case declares
`expect.at`, the harness asserts it."

**D3 · The harness never compares deltas against batch raw text.**
Where: `kernel.md` §8 "the concatenation of emitted deltas equals the
batch raw text"; `runner.py` `_check_stream_success` compares deltas only
across chunkings.
Ambiguity: a driver that emits no `field_delta` at all passes.
Chosen: this driver additionally requires the concatenated deltas to equal
the batch raw per field (from `parseWithRaws`).
Spec sentence: "The harness compares the concatenated deltas of every
chunking with the batch raw text per field."

**D4 · Whole-part chunking equals batch only if batch coalesces (see A4).**
The harness's first chunking feeds every part as one delta; if a case
ever carries two adjacent same-kind parts, the harness itself forces A4.

**D5 · `capabilities` typing.** `capabilities.md`: "a plain dict of
booleans"; the harness passes the case object as-is. Chosen: non-`true`
values are false. Proposed case: `capabilities: {"instruct": 1}` with
`prefix_cot` → `capability-missing`. Spec sentence: "Only the boolean
`true` declares a fact."

**D6 · Refuse cases without `inputs`/`response` cannot reach render/parse.**
`runner.py` renders only when `"inputs" in case`; a render refusal that
needs demos but no inputs (e.g. `demo-not-renderable`) must still carry
`inputs`. Documentary; no code choice. Spec sentence: "A refuse case at
`render` carries `inputs` (possibly `{}`)."

## E. Underdetermined text rules

**E1 · Rounding formula vs decimal intuition.**
Where: `kernel.md` §7a "half-to-even in binary64: `roundeven(x·10ⁿ)/10ⁿ`".
Ambiguity: `2.675·100` is exactly `267.5` in binary64, so the formula gives
`2.68`, while Python's `round(2.675, 2)` gives `2.67`. A reference that
calls its host `round` diverges.
Chosen: the formula, literally.
Pinned by: nothing (19 and 45 have no half case).
Proposed case: `render`, `scaled_number {scale: 100, round: 2, suffix: "%"}`
demo value `0.02675` → `2.68%`; and `0.025 × 100 = 2.5` with `round: 0` →
`2%`.
Spec sentence: "Rounding multiplies in binary64 first; `2.675` at two
places is `2.68`."

**E2 · Integer enum spelling.**
Where: §7a "the stripped text equals a member's spelling".
Ambiguity: does `02` read as member `2`?
Chosen: no — the text must equal the member's decimal spelling.
Proposed case: `refuse` at parse, enum `[1, 2]`, reply `02` → `parse-value`.
Spec sentence: "An integer member's spelling is its decimal form; `02` is
not `2`."

**E3 · Number text that overflows binary64.**
Where: §7a number grammar; "non-finite refuses `value-invalid`" (write side).
Chosen: `1e400` (grammar-valid, value +∞) refuses `parse-value`.
Proposed case: `refuse` at parse, number field, reply `1e400` → `parse-value`.
Spec sentence: "Number text whose binary64 value is not finite refuses
`parse-value`."

**E4 · Non-integral value on an integer field at write.**
Chosen: `3.5` on `{"type": "integer"}` → `value-invalid`; `3.0` writes `3`.
Proposed case: `refuse` at render, integer input `3.5` → `value-invalid`.
Spec sentence: "An integer field writes only integral values."

**E5 · Integer write beyond exponent threshold.**
Where: §7a "Written in decimal".
Chosen: integers never use exponent form (`1e21` as an integer writes
`1000000000000000000000`); numbers use ECMAScript spelling (`1e+21`).
Proposed case: `render`, integer input `1e21` (JSON `1000000000000000000000`)
→ `1000000000000000000000`.
Spec sentence: "Integer text is always digits; the exponent form belongs
to numbers."

**E6 · Regex dialect enforcement (trade-off).**
Where: §7a, D-14 "RE2 syntax minus named groups"; case 42.
Ambiguity: JavaScript's engine is not RE2. Constructs RE2 accepts and JS
does not (`(?i)` inline flags, `\A`, `\z`, `\C`, `\Q…\E`, POSIX classes)
have no JS translation without a full parser.
Chosen: a syntactic lint refuses the D-14 list (`entry-malformed`) *and*
refuses those RE2-only constructs (`entry-malformed`). A conformant RE2
pattern like `(?i)thought: (.*)` is therefore refused here and accepted by
an RE2 host — a stated dialect narrowing, not silence.
Pinned by: 42 (lookahead only).
Proposed cases: `refuse` `(?i)thought: (.*)` → is it in the subset?;
`parse` `[[:alpha:]]+` → in or out?; `refuse` `a*+` → `entry-malformed`;
`refuse` `(a)\1` → `entry-malformed`.
Spec sentence: "The subset is RE2 without named groups, inline flags,
POSIX classes, `\A`, `\z`, `\C`, and `\Q…\E`."

**E7 · `.` semantics.**
Where: RE2 `.` excludes only `\n`; JS `.` also excludes `\r`, U+2028, U+2029.
Chosen: `.` outside classes is translated to `[^\n]`; the `u` flag makes it
consume one scalar.
Proposed case: `parse`, pattern `Thought: (.+)`, reply `Thought: a\r\n<answer>…`
→ `reasoning: "a"` (the `\r` is captured, then stripped by `span.text`) —
and a reply `Thought: a\u2028b\n` → capture `a\u2028b`.
Spec sentence: "`.` matches any scalar except U+000A."

**E8 · Pattern without a capture group.**
Where: §6 "`pattern` (RE2, group 1, empty matches discarded)".
Chosen: no group → the whole match is the capture.
Proposed case: `parse`, pattern `Thought: [^\n]+` → `reasoning: "Thought: first"`.
Spec sentence: "A pattern without a group captures the whole match."

**E9 · Empty captures and consumption.**
Chosen: a match whose capture is empty is discarded and not consumed;
zero-length matches are skipped.
Proposed case: `parse`, pattern `Thought:( ?)` with consume → text unchanged.
Spec sentence: "A match with an empty capture is discarded and never
consumed."

**E10 · Strings are UTF-16 in this host (trade-off).**
Where: §7a "Unicode scalar values, never normalized".
Chosen: all scanning is by UTF-16 code unit with markers that are whole
scalars, so results equal scalar-wise scanning; `Array.from` splits
scalars for the harness replay; lone surrogates in JSON `\uD800` are
accepted and written raw.
Proposed case: `parse`, reply containing an astral scalar `𝄞` inside a
value and a `between` marker adjacent to it → captured intact.
Spec sentence: "A lone surrogate is not a scalar value; a reply carrying
one is `response-malformed`" — or the opposite; pin one.

## F. Underdetermined template, lens, and render rules

**F1 · The demo turn is stripped.**
Where: §3 "one assistant turn written by the lens"; §4 "`join`"; cases 02,
21, 30, 53.
Ambiguity: `join` concatenates anchors, values, closes and the tail; the
xml template's last close ends in `\n` yet case 30 expects
`…</score>` with no trailing newline. Nothing says the turn is stripped.
Chosen: `strip(join)` (both ends; only the trailing side is pinned).
Pinned by: 30 (trailing).
Proposed case: `render`, template whose loop body starts with a newline
(`{% for f in outputs %}\n<{f.name}>…`) and a demo → assistant text starts
at `<`.
Spec sentence: "The demo assistant text is the joined pattern with outer
whitespace stripped."

**F2 · Which template messages a demo renders.**
Where: §3 "the user templates over the demo's inputs".
Ambiguity: with a template `[system, demos, user, user2 (no slots)]`,
does a demo render `user2`?
Chosen: a demo renders every template message that references an input
(input slot or inputs loop), in template order, then the assistant join.
Pinned by: 02, 22, 72 (single user message only).
Proposed case: `render`, template `[system, demos, user "{q}", user
"Go."]` with one demo → does the demo include `Go.`?
Spec sentence: "A demo renders the template messages that reference
inputs, then the lens's assistant turn."

**F3 · Demos or history given without a directive.**
Chosen: ignored.
Proposed case: `render`, template without `{"directive": "demos"}`, one
demo → messages unchanged (or refuse `value-invalid`).
Spec sentence: "Demos and history render only at their directive; without
one they are ignored."

**F4 · Fragment target creation for non-system roles.**
Where: §6 "fragments append to the named message (created if absent,
system first)".
Chosen: a missing `system` message is created at index 0; a missing `user`
or `assistant` message is created at the end.
Pinned by: nothing (34/63 append to an existing system).
Proposed case: `render`, template `[user "{q}"]`, strategy fragment
`{"system": "S"}` → messages `[system "S", user …]`; fragment `{"assistant":
"A"}` → `[user …, assistant "A"]`.
Spec sentence: "A created system message is first; any other created
message is last."

**F5 · Order of fragments vs placements on one message.**
Chosen: strategies in signature order; within one strategy fragments first,
then placements; a `message:` placement appends parts with no separator
(66).
Proposed case: `render`, one strategy with `fragments.system` and a
`message:system` placement → text `…\n\nFRAGMENT` + `VALUE`.
Spec sentence: "Per strategy, fragments append before placements."

**F6 · Bare-slot join with an omitted value.**
Where: §3 "absent outputs are omitted".
Chosen: for a loop pattern, the absent field's whole iteration is omitted
(53); for bare slots, the line literals stay and the hole is empty
(`{"answer": "", "score": 9}`).
Pinned by: 53 (loop). Bare slots: nothing.
Proposed case: `render`, the 69 entry, demo `{q, score: 9}` (no answer) →
assistant `{"answer": "", "score": 9}`.
Spec sentence: "In a bare-slot pattern an absent output leaves its hole
empty; in a loop pattern its iteration is omitted."

**F7 · The tail's line.**
Where: §4 "the literal after an outputs loop, up to the next slot and to
the end of its line, is the pattern's tail".
Ambiguity: `{% endfor %}\n</done>` — is the tail `</done>` (next line) or
empty (the loop's line ends immediately)?
Chosen: the literal is cut at its first newline, so this tail is empty and
`</done>` is prose.
Pinned by: nothing (01/21/45 put the tail on the loop's line; 34/72 have
none).
Proposed case: `parse`, template `…{% endfor %}\n</done>` with reply
`<answer>\nA</done>\n<score>\n1\n</done>` → is `</done>` a marker (then
`parse-ambiguous`) or not (then `answer: "A</done>"`)?
Spec sentence: "The tail is the literal on the line where the loop ends,
up to the next slot; a newline ends it."

**F8 · Regions for `parse-ambiguous`.**
Where: §4 "an anchor, close, or tail occurring twice in its region".
Chosen: anchor region = the whole lens text (32); close region = from its
anchor's end to the next boundary (next anchor start, tail, or end) (39);
tail region = the whole text.
Pinned by: 32 (anchor), 39 (close). Tail: nothing.
Proposed case: `refuse` at parse, 01 entry, reply `I end with </done>.\n<answer>\nA\n<score>\n1\n</done>` → `parse-ambiguous` (whole-text tail
region) or values (region after the last anchor)?
Spec sentence: "An anchor's region and the tail's region are the whole
text; a close's region runs from its anchor to the next boundary."

**F9 · Capture end without a close.**
Chosen: the earliest of the close (first occurrence in region), the next
anchor by position, the tail, end of text.
Pinned by: 12, 20 (indirectly).
Proposed case: `parse`, xml template, reply `<answer>\nA\n<score>\n9\n</score>`
(no `</answer>`) → `answer: "A"`.
Spec sentence: "A capture ends at the first of: its close, the next anchor
by position, the tail, the end of text."

**F10 · Anchors in reply order, not signature order.**
Where: §4 "first occurrence, any order".
Chosen: "next anchor" is positional.
Proposed case: `parse`, reply `<score>\n9\n<answer>\nA\n</done>` (01 entry) →
`{answer: "A", score: 9}`.
Spec sentence: "Boundaries are positions in the reply, whatever the
signature order."

**F11 · `partial` payload.**
Where: `errors.md` "`partial` carries what was read"; lens-json_object.md
"the recovered raw strings".
Chosen: raw strings per recovered field (derived lens too).
Pinned by: nothing (the harness never compares `partial` to a fixture).
Proposed case: 12 with `expect.partial: {"answer": "only this"}`.
Spec sentence: "`partial` maps each recovered field to its raw text."

**F12 · Hidden output with no routing or placement.**
Chosen: not expected at parse (never `parse-missing-fields`), absent from
`values`.
Proposed case: `parse`, strategy `{visible: false}` alone on `reasoning`,
reply with only `answer` → `{answer: …}`.
Spec sentence: "A hidden field that no routing or placement carries is
absent from the parse."

**F13 · Bare slot naming a hidden output.**
Chosen: renders empty and is not a hole.
Proposed case: `render`, template `**R:**{reasoning}**A:**{answer}` with
`native_reasoning` → system text `**R:****A:**...`.
Spec sentence: "A slot of a hidden field renders nothing and is no hole."

**F14 · Placed inputs and inputs loops.**
Chosen: a placed input is hidden from inputs loops and bare slots.
Pinned by: nothing (66 has no inputs loop).
Proposed case: `render`, 66 entry with user text
`{% for f in inputs %}{f.name}={f.value}\n{% endfor %}` → only `q=…`.
Spec sentence: "Placement hides the field from loops and slots."

**F15 · Strategy for a role no field bears.**
Chosen: skipped entirely (fragments, controls, routings).
Proposed case: `render`, 07 entry with the QA signature (no reasoning
field) → no fragment, `patch: {}`.
Spec sentence: "A strategy whose role no field bears is inert."

**F16 · Empty messages.**
Where: §3 "empty messages drop".
Chosen: a message whose parts are all empty text is dropped; a message
with a non-text part is kept.
Proposed case: `render`, template `[user "", user "{q}"]` → one message.
Spec sentence: "A message with no parts, or only empty text, is dropped."

**F17 · `describe` default and the type name.**
Where: §5 "`describe(field)` … default: the type's name, else the
mechanical hint"; §2 "`schema` (the format's `describe`, else the
mechanical hint)".
Ambiguity: for a kernel-default scalar with `type: "int"`, is the
placeholder `int` or `(integer)`?
Chosen: kernel defaults describe with the mechanical hint (ignoring
`type`); registered or shipped formats without `describe` fall back to the
type name, else the hint.
Proposed case: `render`, integer output with `type: "int"` and no desc →
`(integer)` or `int`.
Spec sentence: "Kernel defaults describe by the mechanical hint; a format
without `describe` is described by the field's type name, else the hint."

**F18 · Mechanical hints for boolean, media, structured.**
Pinned: `(integer)`, `(number)`, `one of: low, high`, empty for string
(01, 35, 47), `...` fallback (04).
Chosen: `(boolean)`, `(<media kind>)`, and the single-line JSON of the
shape for structured.
Proposed case: `render`, boolean output without desc → `(boolean)`;
nullable enum → `one of: a, b`.
Spec sentence: "Mechanical hints: `(integer)`, `(number)`, `(boolean)`,
`one of: m1, m2`, `(<kind>)` for media, nothing for string."

**F19 · Skeleton and prefix for a vocabulary lens / placements.**
Chosen: `json_object` skeleton is `{prefill: "", stops: []}`; `prefix`
stops at the first message that references inputs *or* is the target of a
`message:` placement.
Proposed case: `plan`, 22 entry → `skeleton`, `prefix`; `plan`, 66 entry →
`prefix: []` (system carries a placed input) or the system message.
Spec sentence: "A message that a `message:` placement writes depends on
inputs and ends the prefix."

**F20 · `{format}` under the derived lens.**
Where: §4 "`format` (placeholders) are the lens writing forward".
Chosen: the joined pattern over placeholders, stripped; no collision check.
Pinned by: 28 (json_object only).
Proposed case: `render`, `{instruction}\n{format}` with the 01 pattern in
another message… (a template with both `{format}` and the loop) → system
`…<answer>\nshort answer\n<score>\n(integer)\n</done>`.
Spec sentence: "`{format}` is `join` over the placeholders of the visible
outputs."

**F21 · Loop pattern and bare holes in one message.**
Chosen: `not-lensable` ("two patterns").
Proposed case: `refuse`, `{% for f in outputs %}<{f.name}>{f.value}{% endfor %}\nAlso: {answer}` → `not-lensable`.
Spec sentence: "A message with both an outputs loop hole and a bare
output hole has two patterns."

**F22 · Non-literal constructs inside the pattern body.**
Chosen: `{instruction}` is static and allowed; any other bare slot in the
loop body refuses `not-lensable` naming the field.
Proposed case: `refuse`, `{% for f in outputs %}{q}: {f.value}\n{% endfor %}` → `not-lensable`.
Spec sentence: "An anchor or close may contain only literals, loop
attributes, and `{instruction}`."

**F23 · Demo supplying no outputs.**
Chosen: the assistant turn is the tail alone (stripped); an empty result
drops the message.
Proposed case: `render`, 01 entry, demo `{question: "x"}` → assistant
`</done>`.
Spec sentence: "A demo without outputs still writes the tail."

**F24 · `not-lensable` fix locator.**
Where: `errors.md` `edit-template` "`template` when no single message is
the offender"; case 33.
Chosen: `template[i]` + `field` for an empty anchor or shared anchor
(33); `template` for "no pattern"; `template[j]` for the second pattern.
Proposed case: `refuse`, template with no output hole → `not-lensable`,
fix `{"action": "edit-template", "path": "template"}`.
Spec sentence: "A missing pattern names `template`; a defective hole
names its message and field."

**F25 · History message `content` as a part list is verbatim (47) — but
not validated beyond `kind`.** Chosen: each part needs a string `kind`;
else `value-invalid`. Proposed case: history `{"role": "user", "content":
[{"text": "x"}]}` → `value-invalid`. Spec sentence: "History parts are
validated like response parts."

**F26 · Unknown loop attribute.**
Chosen: `{f.bogus}` refuses `unknown-slot` at bind with `slot: "f.bogus"`.
Proposed case: `refuse` at bind → `unknown-slot`, fix `{"action":
"edit-template", "path": "template[0]", "slot": "f.bogus"}`.
Spec sentence: "A loop attribute outside name, desc, type, schema, role,
value is an unknown slot."

## G. Underdetermined format and strategy rules

**G1 · Nullable shapes have no structural key.**
Where: §5 step 2; §1 nullable forms; case 48 (`count` nullable integer
under `*` → kernel).
Ambiguity: does `formats: {"number": scaled_number}` catch a nullable
number?
Chosen: no — nullables resolve by type name or kernel default only.
Proposed case: `render`, `{"number": scaled_number}` and a nullable number
demo output `0.5` → `0.5` (kernel) or `50%`.
Spec sentence: "A nullable shape has no structural key."

**G2 · Enum structural key.**
Chosen: `enum` only (not also `string`/`integer`).
Proposed case: `render`, `{"string": json}` and `{"type": "string", "enum":
["a"]}` input `a` → `a` (kernel) or `"a"` (json).
Spec sentence: "An enum's structural key is `enum`."

**G3 · `accepts` matching.**
Chosen: `*`, the field's type name, or any of the field's structural keys
(plus `media:*` for media); kernel defaults are never checked (they are
chosen by shape).
Pinned by: 56 (table under `string`).
Proposed case: `refuse`, `{"list[*]": scaled_number}` on an array field →
`format-shape-mismatch`.
Spec sentence: "A format accepts a field when `accepts` names `*`, the
field's type, or one of its structural keys."

**G4 · `round_trip` of `scaled_number` with `round`.**
Chosen: `false` when `round` is set (lossy), so demos refuse
`demo-not-renderable`; `true` otherwise.
Proposed case: `render` with `{scale: 100, round: 0}` and a demo → refuse
or `78%`; pin one.
Spec sentence (format-scaled_number.md): "`round_trip` is true only when
`round` is null."

**G5 · Table row without a trailing delimiter.**
Chosen: a trailing empty cell is dropped only when the line ends with the
delimiter; `| a | 9` yields two cells.
Proposed case: `parse`, reply `<rows>\n| a | 9\n</done>` → one row or
`format-read-error`.
Spec sentence: "A row's trailing delimiter is optional."

**G6 · Table write of a missing column.**
Chosen: a missing key writes the `null` string.
Proposed case: `render`, demo row `{name: "a"}` (no score) → `| a |  |`.
Spec sentence: "A missing property writes as null."

**G7 · Table header detection.** Chosen: exact, case-sensitive cell
equality with `columns`. Proposed case: header `| Name | Score |` → read as
a data row → `format-read-error` (integer `Score`). Spec sentence: "A
header row equals `columns` exactly."

**G8 · Table cells of structured/unknown columns.** Chosen: string.
Proposed case: column absent from `items.properties` → string.

**G9 · Fence unwrapping differs between `format/json` and `lens/json_object`.**
format-json.md: "the whole text … is a single fenced code block";
lens-json_object.md: "If it starts with a markdown fence … the document is
the fence body".
Chosen: the format requires both fences; the lens takes the body up to the
last closing fence, or to the end when none.
Proposed case: `parse`, json_object reply "```json\n{…}" (no closing fence)
→ values; `refuse`, json format span "```json\n[1]" → `format-read-error`.
Spec sentence: "The lens tolerates a missing closing fence; the format
does not."

**G10 · Duplicate non-field members under `json_object`.**
Where: lens-json_object.md "parse … as strict JSON" vs "Unknown members are
ignored".
Chosen: only a *field's* duplicated key refuses `parse-ambiguous`;
duplicated chatter keys are ignored.
Proposed case: `parse`, reply `{"answer": "A", "x": 1, "x": 2}` → values
(or `lens-parse-error`).
Spec sentence: "Duplicate members that are not fields are ignored."

**G11 · `json_object` fallback substring.** Chosen: first `{` to last `}`
of the (fence-stripped) text. Pinned by nothing (25 has no braces).
Proposed case: `parse`, reply `Sure: {"answer": "A"} ok` → `answer: "A"`.

**G12 · Placement kinds.**
Chosen: `controls.<key>` requires `emits: parts` (67); `message:<role>`
accepts text or parts (66).
Proposed case: `render`, media input placed at `message:user` → the part
appended to the user message.
Spec sentence: "`message:` placements accept text and parts; `controls.`
placements need parts."

**G13 · Dotted control paths.** Chosen: `controls.a.b` sets `patch.a.b`.
Proposed case: `render`, placement `controls.tools.list` → `{"tools":
{"list": [part]}}`.

**G14 · Equal controls from two strategies.** Chosen: no conflict when the
values are deep-equal. Proposed case: two strategies with `temperature: 0`
→ `patch: {"temperature": 0}`. Spec sentence: "Controls conflict only
when their values differ."

**G15 · Placement key vs control key.** Chosen: a `controls.<key>`
placement whose top key a strategy control also writes refuses
`control-conflict` at bind (fix `strategies['role'].placement`).
Proposed case: as described → `control-conflict`.

**G16 · Lens patch vs strategy control.** Chosen: `control-conflict`, fix
`strategies['role'].controls['key']` (the strategy is the editable side).
Proposed case: `json_object` with a strategy `controls.response_format` →
`control-conflict`.

**G17 · Routed field with no capture.**
Chosen: `parse-missing-fields` (the field is not recovered), `partial`
carries the others.
Pinned by: nothing.
Proposed case: `refuse` at parse, 15 entry, reply `<answer>\nParis\n</done>`
(no think tags) → `parse-missing-fields` — or `reasoning: ""`.
Spec sentence: "A routed field with an empty span is missing."

**G18 · `between` with an open and no close.** Chosen: no capture; the
text is left untouched from that open on. Proposed case: reply
`<answer>\nA<think>x\n</answer>` → `answer: "A<think>x"` and reasoning
missing.

**G19 · `line_prefixed` and the removed newline.** Chosen: lines split on
`\n`, matching lines dropped, the rest joined by `\n`. Proposed case: reply
`<ans\n> note\nwer>\nX\n</answer>` → does the lens see `<ans\nwer>`? Spec
sentence: "Consuming a prefixed line removes the line and its newline."

**G20 · Fix for a failing plain-strategy `when`.**
Where: `errors.md` `capability-missing` fixes `declare-capability`,
`satisfy-predicate`.
Chosen: `requires` → `declare-capability` (first missing fact, 10);
`when` on a plain strategy → `satisfy-predicate {role, predicate}`; a
`choose` with no branch → `satisfy-predicate` with `{"any": [whens]}` (78).
Proposed case: `refuse`, plain strategy `when: {"capability": "instruct"}`,
`capabilities: {}` → which fix?
Spec sentence: "`requires` refuses with `declare-capability`; `when`
refuses with `satisfy-predicate`."

**G21 · Several missing `requires` facts.** Chosen: the first in list
order. Proposed case: `requires: ["a", "b"]` → fix fact `a`.

**G22 · Version compatibility rule.**
Where: §9 "semver; while major = 0, minor is breaking".
Chosen: same major; when major is 0, same minor; otherwise `needs.minor ≤
provides.minor`; patch ignored.
Proposed case: `roundtrip`, `versions.kernel: "0.2.7"` → loads; `refuse`,
`"0.1.0"` → `version-incompatible`.
Spec sentence: "An artifact is compatible when majors match and, for
major 0, minors match; patch never matters."

**G23 · `versions.vocab` for unregistered or unreferenced names.**
Chosen: checked only for registered entries; unregistered names are
ignored (a referenced one already refused by name, 77).
Proposed case: `refuse`, `versions.vocab: {"format/json": "0.9.0"}` with
std → `version-incompatible`, fix `{"entry": "format/json", "needs":
"0.9.0", "provides": "0.1.0"}`.
Spec sentence: "Each `versions.vocab` entry is checked against the
registry; an unregistered name refuses by reference, not by version."

**G24 · Format factory option errors.** Chosen: a bad option (table
without `columns`) refuses `entry-malformed` at `formats['key']`.
Proposed case: `refuse` at load, `{"use": "table"}` → `entry-malformed`.

**G25 · Media value carrying `kind`.** Chosen: must equal the shape's kind
else `value-invalid`; the written part is `{"kind": kind, …value}` (66).
Proposed case: `refuse` at render, `{"media": "image"}` input `{"kind":
"audio"}` → `value-invalid`.

**G26 · Media read without a matching part.** Chosen: `parse-value`.
Proposed case: `refuse` at parse, media output routed from
`channel:image`, response without image parts → `parse-missing-fields`
(empty span, G17) — the two rules meet; pin one.

## H. Underdetermined streaming rules

**H1 · Batch coalescing** — see A4.

**H2 · When `field_started` fires.** Chosen: immediately before a field's
first `field_delta`, or at `finish` for a recovered field with no delta
(empty raw). Proposed test: the harness could assert `field_started`
precedes every `field_delta`/`field_done` of its field (this driver does).
Spec sentence: "`field_started` precedes the field's first delta or, when
the raw is empty, its `field_done`."

**H3 · Event order at `finish`.** Chosen: remaining deltas (signature
order), then `field_done` for every value (signature order).
Spec sentence: "At EOF, held deltas are emitted before any `field_done`."

**H4 · The text channel of a parts response.** Chosen: the concatenation
of every `kind: "text"` part's text, in order (thinking parts do not
break it). Proposed case: `parse`, `{content: [{text: "<ans"}, {thinking:
"…"}, {text: "wer>\nA\n</answer>"}]}` → `answer: "A"`.
Spec sentence: "The reply text is the concatenation of its text parts."

**H5 · Text deltas and part deltas mix.** Chosen: a string delta is a
`kind: "text"` part delta and coalesces with an adjacent text part.
Pinned by §8 wording; proposed case: mixed feed.

**H6 · Empty-text part delta.** Chosen: coalesces (adds nothing); a part
delta with no `text` is one complete part. Proposed case: `{content:
[{kind: "thinking", text: ""}, {kind: "thinking", text: "x"}]}` →
`reasoning: "x"` (batch coalesces, A4).

**H7 · `finish` after no `feed`.** Chosen: batch parse of `""` →
`parse-missing-fields`. Spec sentence: "An empty stream is an empty reply."

**H8 · What `finish` re-parses.** Chosen: the accumulated parts; when only
text deltas were fed, the concatenated string. Both normalize identically.

**H9 · Refusal equality includes `hint`.** `errors.md`: hints "may improve
without a version bump", yet the streaming refusal law compares whole
`describe()` including hint. Fine within one implementation; the spec
should say hints are compared only within an implementation.

## I. Refusal ordering

**I1 · Load order.** Chosen: structural `entry-malformed` →
`versions.kernel` → template syntax → `parse.kind` → strategies
(`unknown-strategy`, regex `entry-malformed`) → formats (`unknown-format`,
`udf-tampered`, `format-untrusted`) → `versions.vocab`.
Pinned by: 13, 77 (each alone). Proposed case: kernel `9.0.0` plus an
unknown format → `version-incompatible` (this order) — pin it.
Spec sentence: "Load checks the kernel version first, then the template,
the parse kind, strategies, formats, and vocabulary versions."

**I2 · Bind order.** Chosen: `role-ambiguous` → template `unknown-slot` →
strategies in signature order (`capability-missing`, routing/placement
`unknown-slot`, `control-conflict`) → `field-double-covered` → per-field
formats in signature order (`no-format`, `format-shape-mismatch`,
`format-direction`, `format-span-mismatch`, `format-placement-mismatch`) →
lens (`not-lensable` or lens `capability-missing`) → `field-uncovered`.
Pinned by: each case alone. Proposed cases: (a) an uncovered input plus a
template with no output hole → `not-lensable` here; (b) `no-format` plus
a missing capability → `capability-missing` here.
Spec sentence: "Bind refuses in this order: roles, slots, strategies,
coverage, formats, lens, uncovered inputs."

**I3 · Parse order.** Chosen: `response-malformed` → routings → lens
structure (anchor ambiguity for every field, tail ambiguity, close
ambiguity per field, then missing fields) → routed-field emptiness →
typed reads in signature order (`parse-value`, `format-read-error`).
Proposed case: reply with a duplicated anchor *and* a missing field →
`parse-ambiguous`.
Spec sentence: "Structural refusals precede typed reads; ambiguity
precedes absence."

**I4 · `when` before `requires`.** Proposed case: plain strategy with both
failing → `satisfy-predicate`.

**I5 · Signature after load.** The harness loads the entry before
validating the signature, so an invalid signature with an invalid entry
refuses at load. Documentary.

**I6 · `json_object`: ambiguity before absence.** Proposed case: reply
`{"answer": "A", "answer": "B"}` with a second required field absent →
`parse-ambiguous`.

**I7 · `field-double-covered` before formats.** A visible routed field
whose format also mismatches refuses `field-double-covered` here.
Proposed case: 75's entry with a `string → table` format → which code?

## J. Resolved only by reverse-engineering expected bytes

**J1 · The UDF `sha256`.** Where: §5 "a tampered hash `udf-tampered`";
`errors.md` "does not match its source"; cases 57–62, 68 carry hashes.
Nothing says what is hashed. Brute-forcing serializations against case
61 (one function) found: SHA-256 over the UTF-8 bytes of
`"write\0" + write + "\0"`, and for 57/68 the concatenation for the present
functions in the order write, read, describe, each as `name\0source\0`.
Verified against all three distinct hashes in the corpus.
Spec sentence: "`sha256` is the hex SHA-256 of `name\0source\0` for each
of write, read, describe that is present, in that order."
Proposed case: C1's (60 without `requires`).

**J2 · `*` skipping kernel scalars** — from case 48 (A1).

**J3 · Stripping the demo turn** — from 02/30 (F1).

**J4 · Fragment separator `\n\n`** — from 34/63 (C3).

**J5 · Structural key `list[string]`** — from 16 (B1).

**J6 · `visible: false` covering sub-role targets** — from 72 (A2).

**J7 · Kernel scalars reading `thinking` spans** — from 64 (A3).

**J8 · Mechanical hint spellings** (`(integer)`, `(number)`, `one of: low,
high`, empty for string, `...` fallback) — from 01, 04, 35, 47 (F18).

**J9 · Media part key order** `{"kind": …, …value}` — from 66; harmless
under unordered comparison but the placeholder rule "a value that is
already a part passes through" did not say `kind` is added.
Spec sentence: "The kernel media default writes `{"kind": <kind>}`
merged over the value's own members."

## K. Case results

Command: `python3 ../contract/harness/runner.py --driver 'node --experimental-strip-types conform/main.ts' --cwd ts`
→ `74 passed, 0 failed, 6 unclaimed (udf:python)`.

Passed (74): 01–56, 59, 63–67, 69–80.

Failed (0): none.

Unclaimed (6), each `{"ok": true, "unclaimed": "udf:python"}` because the
case declares `requires: ["udf:python"]` and this runtime places no code:
57 render-shipped-udf · 58 parse-shipped-udf · 60 refuse-load-udf-tampered ·
61 refuse-load-format-not-self-contained · 62 roundtrip-shipped-udf ·
68 refuse-bind-format-span-mismatch. (60 and 68 would be answerable by a
non-placing runtime if the corpus dropped `requires`; see C1 and B3.)

Bytes that surprised while implementing, then matched: F1 (stripped demo
turn), C3 (`\n\n` fragment separator), A1 (`*` not catching scalars), A2
(`visible: false` scope), A3 (thinking span into a string field), 45's
`78%` (0.78 × 100 is exactly 78 in binary64 — no rounding needed), 35's
`9007199254740993` (forced a BigInt-preserving JSON reader).

## Trade-offs taken by this runtime (stated, not absorbed)

1. **Regex**: JavaScript is not RE2. Admission is a syntactic lint
   (D-14 list plus RE2-only constructs JS cannot run), `.` is translated to
   `[^\n]`, the `u` flag is used. Some valid RE2 patterns are refused here
   (E6).
2. **Integers beyond 2^53** are `bigint` (reader, kernel integer rule,
   writer); comparisons treat `9007199254740993n` and a number by value.
3. **Object member order**: JavaScript reorders integer-like keys; a
   JSON value with such keys would be re-spelled in a different order by
   `format/json` (no corpus case has one).
4. **UDFs are never placed** (no Python, no `eval`): every shipped
   format refuses `format-untrusted` after its hash is verified.
5. **`reads: ["*"]`** for kernel scalars and std text formats (A3).
6. **`json_object` streams buffered** (no `stream` face); routings around
   it still stream.
7. **No `@types/node` offline**: a hand-written ambient shim
   (`types/node-shim.d.ts`) declares the Node APIs used.
8. **`readNumber` refuses non-finite** (E3).

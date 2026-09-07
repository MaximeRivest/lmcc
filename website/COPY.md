# lmcc website — copy

Every sentence of site copy, grouped by page, in reading order. The
bracketed marker after a sentence or group names the repository file
that supports it. Code blocks are not repeated here; they are copied
verbatim from the file named on their `data-src` attribute and checked
by `tools/verbatim.py`.

Markers:

- `[README §n]` — `README.md`, section n. `[README intro]` is the text
  before §1.
- `[GUIDE §n]` — `GUIDE.md`, section n.
- `[AGENTS]` — `AGENTS.md` (the tower, the three rules).
- `[kernel §n]` — `contract/spec/kernel.md`.
- `[errors]` — `contract/spec/errors.md`.
- `[corpus]` — `contract/corpus/README.md`.
- `[plans]` — `plans/README.md` and the named plan file.
- `[vocab/x]` — `contract/spec/vocab/x.md`.
- `[check]` — the `check` script at the repository root.
- `[run]` — bytes produced by running README §1–§3 with the reference
  kernel; recomputed by `tools/verbatim.py check`.
- `[site]` — navigation or structural text with no factual claim.
- `[maintainer]` — stated in the delegation brief; **not in the
  repository**. Flagged on the page.
- `[git]` — `git remote` of this worktree.

## Shared: header and footer

- lmcc · kernel 0.2 `[kernel §0: "Version 0.2.0"; tag kernel-0.2]`
- Start · Why · Docs · Status · Repository `[site]`
- lmcc · kernel 0.2 · github.com/MaximeRivest/lmcc · MIT license. `[git; python/pyproject.toml: license = MIT]`
- Every sentence on this site traces to a file in the repository. `[this file]`

## index.html — Home

### Hero

- The calling convention for calling a model. `[README title]`
- When your program calls a function in another language, a calling convention says where each argument goes, how the result comes back, and how each type crosses the boundary. A model is another language. lmcc is its calling convention. `[README intro, verbatim]`
- lmcc never touches the network. It lays out the call and reads the return. You send. `[README intro, verbatim]`
- Start in three steps `[site]`
- Read why `[site]`
- Every Python block on this site is copied from README.md or GUIDE.md. `[tools/verbatim.py]`
- The test suite runs each one. `[check step 4; python/tests/test_guide.py]`
- Two implementations, Python and Go, pass every corpus case they claim, byte for byte. `[plans 05; corpus]`

### One description, both directions

- An adapter is a template. `[README §2 heading]`
- It never knows your field names. That is what lets one adapter serve every signature. `[README §2]`
- The template has three constructs and nothing else: a slot, a loop, and an escape. `[README §2 table]`
- Read it top to bottom and you know the prompt. If a byte is not in the template or in a format you registered, it is not in the prompt. `[README §2]`
- You wrote no parser. lmcc read the output pattern backwards: the literal before each output hole is its anchor, the literal after it its close. Rename `<answer>` to `<reply>` and the prompt and the parser change in the same edit. `[README §4]`
- README.md §2, §4 `[source line]`

### The wire is plain messages

- This is the request that `plan.render(question="Why is the sky blue?")` lays out for the signature and adapter above. `[README §3; run]`
- The instruction comes from the docstring. The pattern comes from the outputs loop. The user turn comes from the inputs loop. `[README §1, §2; kernel §2]`
- The rendered form is plain messages with parts plus a request patch. Hand it to any client. `[README §3]`
- `render` is pure, so you can look at a million prompts for free. `[README §3]`
- `plan.skeleton()` gives a client the assistant prefill and the stop sequence: `{"prefill": "<answer>\n", "stops": ["</answer>"]}`. `[README §8, asserted on p1; run confirms the same skeleton for `answer`]`
- Bytes produced by running README.md §1–§3 with the reference kernel at tag kernel-0.2. `website/tools/verbatim.py check` recomputes them. `[run]`
- SYSTEM · USER · patch: {} `[run; README §3: assert request.patch == {}]`
- Two messages, no patch. `[run]`
- The reply `<answer>\nRayleigh scattering.\n</answer>` parses to `{"answer": "Rayleigh scattering."}`. `[README §3, asserted]`

### Refuse before you pay

- `bind` joins a signature, an adapter, and what the model declares it can do. Every refusal fires here, before any call. `[README §3]`
- Capabilities are a closed, versioned vocabulary of facts, declared by whoever knows the model. Nothing is sniffed. `[README §7; vocab/capabilities]`
- Every refusal that fires before render carries a `fix`: the one next action, as data from a closed vocabulary, naming the exact field, role, fact, name, or artifact path to act on. A program can repair without reading English. `[README §7; errors]`
- README.md §7; contract/spec/errors.md `[source line]`

### The artifact is data

- One JSON file: template, parse rule, strategies by role, formats by type. No signature, no field names, no hidden code. A shipped format says so on its entry: language, deps, hash, author. `[README §10]`
- `lmcc.load(entry)` needs nothing ambient. Another implementation that loads it lays out the same bytes. `[README §10]`
- README.md §10; contract/schema/entry.schema.json `[source line]`

### Proof, not claims

- 82 corpus cases — Byte-exact cases are the authority. If an implementation disagrees with a case, the implementation is wrong. `[corpus; README §11: "82 byte-exact cases"]`
- Python: 82 of 82 — The reference kernel passes every case. `[contract/harness/runner.py, run in this worktree: 82 passed]`
- Go: 76 of 82 — An independent implementation passes every case it claims. It declares 6 cases unclaimed: they ship Python code. `[plans 05; harness run in this worktree: 76 passed, 6 unclaimed (udf:python)]`
- The README runs — Every code block in README.md and GUIDE.md is executed by the test suite. If a document drifts from the code, the check goes red. `[check step 4; GUIDE intro; python/tests/test_guide.py]`
- Same refusals — Both kernels raise the same set of refusal codes, minus one code that only a runtime that places code can raise, and emit the same `fix` for the same refusal. `[python/tests/test_coherence.py: PYTHON_ONLY = {"format-not-self-contained"}; errors: "Both kernels emit the same fix"]`
- Read the full status, including what is not done. `[site]`

### What lmcc refuses to be

- Not a client. It lays out and reads. You send. `[README §12]`
- Not an orchestrator. One plan, one call. `[README §12]`
- Not a runtime for other people's code. A format travels whole with its language declared; where it runs is the host's rule. `[README §12]`
- Not a guesser. Ambiguity, missing capabilities, non-invertible templates, unknown names: refuse, loudly, with a stable code. `[README §12]`
- Not batteries. The kernel ships scalar defaults and nothing else. `[README §12]`

### Where next

- Start — a signature, an adapter, bind, render, parse. `[README §1–§3 headings]`
- Why — the calling-convention argument and the three rules every design answer derives from. `[AGENTS]`
- Docs — the guide, the reference, the contract. `[site]`
- Status — what works, what is planned, what portable means here. `[site]`

## start.html — Start

- Start `[site]`
- A signature, an adapter, then bind, render, parse. This page is the first three sections of README.md. The test suite runs every code block on it. `[README §1–§3; check step 4]`
- Install. The repository has no published package. `[no package index or release in the repository; python/pyproject.toml exists with no publish step]`
- Run from a checkout: `cd python && PYTHONPATH=. python`. `[check: run_py]`
- Python 3.10 or later. `[python/pyproject.toml: requires-python]`
- The kernel imports the standard library only. `[README §11; python/tests/test_agent_surface.py]`
- 1. A signature `[README §1]`
- Inputs from the parameters, outputs from the return type, instructions from the docstring. Nothing else is inferred. Several outputs: return a dataclass. One structured value: `-> lmcc.One[Person]`. `[README §1, verbatim]`
- 2. An adapter is a template `[README §2]`
- An adapter never knows your field names — that is what lets one adapter serve every signature. The template has three constructs and nothing else: `[README §2, verbatim]`
- (table) slot · loop · escape rows `[README §2 table, verbatim]`
- `lmcc.demos()` marks where worked examples go. Read the template top to bottom and you know the prompt. If a byte is not in the template or in a format you registered, it is not in the prompt. `[README §2, verbatim]`
- 3. Bind, render, parse `[README §3]`
- (five bullets) `[README §3, verbatim]`
- What the wire holds `[site]`
- The request from step 3, as bytes. lmcc does not send it; you do. `[run; README intro]`
- Produced by running README.md §1–§3 with the reference kernel at tag kernel-0.2. `[run]`
- Next `[site]`
- Sections 4 to 12 of the README: the template is the parser, formats, strategies, capabilities, the plan, the artifact. `[README §4–§12 headings]`
- The longer walkthrough, kernel only, every block executed: the guide. `[GUIDE intro]`
- Why the design is shaped this way: Why. `[site]`

## why.html — Why

### A model is another language

- When a program calls a function in another language, a calling convention says where each argument goes, how the result comes back, and how each type crosses the boundary. `[README intro; kernel §0]`
- Nobody writes that agreement twice. The compiler on each side reads one description. `[analogy; supports rule 1 in AGENTS — not a claim about lmcc]`
- A call to a model has the same three questions. Where does each input go: the system message, the user turn, a request control? How does the result come back: text between markers, a JSON object, a native channel? How does each type cross: what does an integer look like on the way out, and how is it read on the way back? `[README intro; kernel §2, §4, §5, §6 name these three places]`
- Today the answers live in prompt strings and parsers. The prompt says "reply with `<answer>`". The parser looks for `<answer>`. They are two objects. When they are two objects, they can disagree, and nothing tells you when they do. `[GUIDE §1: "the parts that could disagree are derived from each other, so they cannot"; AGENTS rule 1: "drift unrepresentable"]`
- README.md (intro); contract/spec/kernel.md (one sentence); GUIDE.md §1 `[source line]`

### Where lmcc puts each answer

- where each argument goes — the template decides where visible things sit; a strategy, by role, decides where a meaning travels — data in the artifact `[AGENTS rule 2; README §6, §10]`
- how the result comes back — the lens, derived from the template's output pattern; routings for native channels — derived; never a second copy `[README §4; kernel §4, §6]`
- how each type crosses — a format, by type: `write` and `read` — kernel defaults for scalars; yours for the rest `[README §5; kernel §5, §7b]`
- Type → format decides how a value is spelled. Role → strategy decides where it travels. The template decides where visible things sit. `[AGENTS rule 2, near-verbatim]`
- README.md §2, §4, §5, §6; AGENTS.md (rule 2) `[source line]`

### The three rules

- Every design answer in the repository derives from three rules. When a question comes up, the maintainer derives from these before inventing anything. `[AGENTS: "Every design answer in this repo derives from three rules"]`
- 1. One description, many directions `[AGENTS rule 1]`
- The template's output pattern renders the prompt, writes the demos and history turns, and derives the parser. One object. Drift is not representable. Any feature that would create a second copy of a contract is wrong by construction. `[AGENTS rule 1, near-verbatim]`
- The guide states the law in one line: what the lens wrote as a demo, the lens reads back identically. `[GUIDE §4]`
- AGENTS.md (rule 1); GUIDE.md §4; contract/spec/kernel.md §4 `[source line]`
- 2. Data over code at every seam `[AGENTS rule 2]`
- Artifacts, plans, strategies, predicates, anchors: plain data. The one place an artifact carries code is a shipped format, and it says so on the entry: language, deps, hash, author. Loading never runs it. A runtime that will not place code refuses. `[AGENTS rule 2; README §5, §10; kernel §5]`
- AGENTS.md (rule 2); README.md §5, §10; contract/spec/kernel.md §5 `[source line]`
- 3. Refuse loudly, before money `[AGENTS rule 3]`
- Bind is the gate. Every failure has a stable code, names its exact offender, and says what to do next: before render, as data, a `fix` from a closed action vocabulary. Ambiguity refuses. Guessing is the one forbidden behavior. `[AGENTS rule 3, near-verbatim; errors]`
- AGENTS.md (rule 3); GUIDE.md §5; contract/spec/errors.md `[source line]`

### The tower

- Authority flows up from the contract. If code and corpus disagree, the code is wrong. `[AGENTS: "L0 outranks everything. If code and corpus disagree, the code is wrong."]`
- AGENTS.md (the tower) `[source line]`

### Who this is for

- Programs — You write prompts by hand, or through a framework, and you keep a parser next to each one. With lmcc you keep the template. The parser is derived. Any DSPy signature lowers to an lmcc signature. `[README §4; plans 07; python/lmcc_dspy. The first sentence describes the reader's situation, not lmcc; it is the brief's audience statement.]`
- Frameworks and clients — The artifact is one JSON file with a schema. A frontend lowers any syntax to the signature form; none is the contract. A client receives plain messages, a patch, a prefill and stop sequences, and the cache-stable prefix. `[README §10; contract/schema/entry.schema.json; kernel §1 "Frontends"; README §8; kernel §3]`
- Model providers and trainers — Capabilities are a closed vocabulary of facts, declared by whoever knows the model, never sniffed. Strategies choose by those facts. Roles are aligned with wire part kinds, and every role must be servable with no native part at all. `[vocab/capabilities; README §6; vocab/roles "The governing rule"]`

### What the design costs

- These are trade-offs the repository takes on purpose. Each one is stated, not hidden. `[README §12; AGENTS "state every trade-off"]`
- You must spell the pattern. "Reply with a JSON object" names a format, not a pattern, so it cannot be read backwards. Spell it, or use a document-form lens gated on a capability. `[README §4 "The JSON rule"]`
- Structured types need a format. Scalars, enums and `Optional[...]` have kernel defaults. Anything with structure refuses `no-format`. Never a silent `str()`. `[README §5; GUIDE §9]`
- Refusals instead of guesses. A reply that reads two ways refuses `parse-ambiguous`. A reply that omits its close and contains it inside the value is the one undetectable double fault. `[README §4; kernel §4]`
- Retrying is not lmcc's job. A plan is one call. Refusals about model text carry no `fix`. `[README §9]`
- The kernel ships nothing. Scalar defaults only. Formats, strategies and lenses come from packs with zero privilege. `[README §12; AGENTS L4 "zero privilege"]`
- Start in three steps · See what is done `[site]`

## status.html — Status

- Kernel 0.2.0, tag kernel-0.2. `[kernel §0; git tag]`
- This page says what works, what is planned, and what portable means. Each row names the file that supports it. `[site]`

### What works

- Corpus — 82 byte-exact cases: 23 render, 20 parse, 3 roundtrip, 35 refuse, 1 plan. The corpus is the authority. `[contract/corpus/cases, counted by kind; corpus]`
- Python reference — Passes 82 of 82 cases. Imports the standard library only. `[harness run; README §11]`
- Go implementation — Passes 76 of 82 cases byte-exactly. Declares 6 cases unclaimed: they require `udf:python`, and the Go runtime places no code. Both kernels raise the same refusal codes, minus one code only a runtime that places code can raise. `[plans 05; harness run; python/tests/test_coherence.py]`
- Streaming — Done. A sans-I/O reducer. Every parse case is replayed at every scalar and part split through both kernels. `[plans 01; kernel §8]`
- Fix hints — Done. Every refusal before render carries a `fix` from a closed action vocabulary. 36 refusal codes, 11 fix actions. `[plans 06; errors, rows counted]`
- DSPy frontend — Any `dspy.Signature` lowers, bakes, renders and parses. A 16-row catalog runs against a real DSPy. `[AGENTS invariants; plans 07; check step 6]`
- Go frontend — Struct tags lower to a signature. `[kernel §1 "Frontends"; decisions D-18]`
- Standard vocabulary — 7 entries, all 0.1.0: formats json, table, scaled_number; strategies prefix_cot, reasoning_tags, native_reasoning; lens json_object. Provided by `lmcc_std` and, byte-identically, by `lmccstd`. `[vocab/README]`
- Capabilities — Vocabulary 0.1.0, 7 facts: … `[vocab/capabilities]`
- Roles — `plain` and `reasoning` are live. `tools`, `citations`, `citable` are reserved: named, no strategies shipped. `[vocab/roles]`
- One check — `./check` runs the Python tests, the corpus through both kernels, the schemas, the README verbatim, and the DSPy catalog. `[README §11; check]`

### In progress

- TypeScript implementation — In progress. Not yet conformant. Not in the repository at tag kernel-0.2. — stated by the maintainer (placeholder: link when public) `[maintainer]`

### Planned, not done

- Each item is a plan with acceptance criteria. Each lands as a versioned addition. None of them exists in code today. `[plans/README; kernel "Deliberate gaps (0.2)"]`
- Parse combinators — Declared recovery for messy replies: fenced blocks, tolerant labels, truncation policy. Refusal stays the default; recovery is opt-in, visible data. `[plans/02-parse-combinators.md]`
- Tool-call turns — Tool calls and results spelled into the next prompt, probe-checked: `parse(render(call)) == call` or the rule is refused. `[plans/03-turns-face.md]`
- Tools and citations strategies — Strategy vocabularies for the reserved roles `tools` and `citations`. `[plans/04-tools-citations-strategies.md]`
- Grammar face — A `grammar` face of `skeleton()`. A stated gap. `[kernel §3, "Deliberate gaps (0.2)"]`

### What portable means here

- Exactly this: the artifact is data and travels anywhere; the layout is byte-exact across implementations; a named format is byte-exact where both runtimes ship the name; a shipped UDF runs where its language can be placed and is declared unclaimed where it cannot. `[README §11, verbatim]`
- That boundary is the contract's, not an accident. `[README §11]`
- A type with no artifact entry uses the runtime binding or the kernel default, and `plan.describe()` says which. This is the stated place where two runtimes may legitimately spell the same type differently. `[kernel §5]`

### Versions

- Kernel and every vocabulary entry version independently. Semver. While major = 0, minor is breaking. `[kernel §9]`
- Artifacts pin what they need. Loaders refuse `version-incompatible`, naming both sides. `[kernel §9]`
- Adding a refusal code or a fix action is a minor change. Changing when a code fires, or renaming an action, is breaking. `[errors]`

### Not claimed

- This site does not say "production-ready". It does not give adoption numbers. It does not name a published package. The repository does not contain those facts, so the site does not either. `[absence in repository; delegation rules]`

## docs.html — Docs

- Guide · kernel only · every code block is executed by python/tests/test_guide.py `[GUIDE intro]`
- Using lmcc — the kernel guide `[GUIDE title]`
- Prototype note. This page shows how the docs are navigated. Only guide sections 1 to 3 are rendered here, verbatim from GUIDE.md. Every item marked "placeholder" in the sidebar has no page yet. The Contract links go to the repository. `[site]`
- (guide intro, §1, §2, §3 prose) `[GUIDE intro, §1, §2, §3, verbatim]`
- Sections 4 to 12 are placeholders in this prototype. Read them in GUIDE.md. `[site]`
- Sidebar: Guide items 1–11 `[GUIDE headings]`; How-to items `[derived from GUIDE §4, §7, §9 and corpus/README "Running another implementation"; pages do not exist]`; Reference items `[README §8, §10; GUIDE §11; kernel §3; pages do not exist]`; Contract items `[contract/ tree; links to the repository]`

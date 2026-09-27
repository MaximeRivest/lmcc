# lmcc for TypeScript

The TypeScript kernel of **lmcc**, the calling convention for calling a
model: where each argument goes, how the result comes back, how each type
crosses. It passes the same contract corpus as the Python reference, byte for
byte, and serializes the same data (artifacts, turns, plans, readings).

- **No runtime dependencies.** The kernel imports nothing, not even `node:`
  modules: it runs in Node 22.6+, Deno, Bun, browsers and workers.
- **lmcc never touches the network.** It lays out the call and reads the
  return. `lmcc/lm15` hands the call to [lm15](https://lm15.dev) (`@lm15/lm15`,
  an optional peer dependency), which sends it to any provider.
- **Same meaning as Python.** A signature, an adapter artifact or a recorded
  turn written by one kernel is read identically by the other.

Every block below runs in the test suite (`npm test`).

## 1. A signature

```ts
import * as lmcc from "lmcc";

const answer = lmcc.signature("Answer the question in one sentence.", {
  inputs: { question: lmcc.t.string() },
  outputs: { answer: lmcc.t.string() },
});
```

Shapes are JSON Schema; the `t` builders also carry a static type, so what
`parse` returns is typed (`{ answer: string }` here). A signature can also
be loaded from its plain-data form with `lmcc.signatureFromDict(...)`, the
form every implementation shares.

## 2. An adapter is a template

```ts
const xml = lmcc.adapter({ messages: [
  lmcc.system(
    "{instruction}\n\n" +
    "Reply with exactly this pattern:\n" +
    "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
  lmcc.turns(),
  lmcc.user("{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
] });
```

An adapter never knows your field names, which is what lets one adapter serve
every signature. Four constructs: slots `{question}`, loops
`{% for f in inputs %}`, guards `{% if examples %}`, escapes `{{ }}`.

## 3. Bind, render, parse, stream

```ts
import assert from "node:assert/strict";

const plan = xml.bind(answer, { instruct: true });

const request = plan.render({ question: "Why is the sky blue?" });
assert.equal(request.messages[0].parts[0].text, "<question>\nWhy is the sky blue?\n</question>\n");

const values = plan.parse("<answer>\nRayleigh scattering.\n</answer>");
assert.equal(values.answer, "Rayleigh scattering.");

const stream = plan.stream();
const events = stream.feed("<answer>\nRayleigh");
assert.deepEqual(events, [
  { kind: "field_started", field: "answer" },
  { kind: "field_delta", field: "answer", text: "Rayleigh" },
]);
stream.feed(" scattering.\n</answer>");
const end = stream.finish();
assert.deepEqual(end.values, { answer: "Rayleigh scattering." });
```

`bind` joins a signature, an adapter and what the model declares it can do;
every refusal fires there, before any call. `render`, `parse` and `stream`
are pure. Streaming refines batch: any chunking gives the same values.

## 4. The template is the parser

```ts
assert.deepEqual(plan.describe().reader, {
  kind: "derived", anchors: [["answer", "<answer>\n", "\n</answer>\n"]],
});

const reading = plan.read("<Answer>\nRayleigh scattering.\n</Answer>");
assert.equal(reading.values.answer, "Rayleigh scattering.");
assert.deepEqual(reading.repairs.map((r) => r.saw), ["<Answer>", "</Answer>"]);

assert.throws(() => plan.parse("<answer>\none\n</answer>\n<answer>\ntwo\n</answer>"),
  (err) => err instanceof lmcc.Refusal && err.code === "parse-ambiguous");
```

Misspelled markers are repaired by one rule, out loud; a reply that reads two
ways refuses. lmcc never guesses.

## 5. Turns: examples and conversations

```ts
const example = plan.example({ question: "Is water wet?" }, { answer: "Yes, to the touch." });
const withExample = plan.render({ question: "Why is grass green?" }, { turns: [example] });
assert.equal(withExample.messages[1].parts[0].text, "<answer>\nYes, to the touch.\n</answer>");

const turn = request.step("<answer>\nRayleigh scattering.\n</answer>");
const [step] = turn.toJSON().steps;
assert.ok(step.kind === "model" && step.outputs.answer === "Rayleigh scattering.");
```

A turn is one call of one signature: inputs, steps (replies and tool
results), outputs. `turn.toJSON()` is the same record Python writes
(`schema/turn.schema.json`), so a conversation recorded in one language
continues in the other.

## 6. Tools, with the standard pack

```ts
import { install } from "lmcc/std";

const registry = new lmcc.Registry();
install(registry);

const ask = lmcc.signature("Answer, using tools when needed.", {
  inputs: {
    question: lmcc.t.string(),
    tools: lmcc.field(lmcc.t.list(lmcc.t.json({ type: "object" })), { purpose: "tools", type: "list[Tool]" }),
  },
  outputs: {
    calls: lmcc.field(lmcc.t.list(lmcc.t.json({ type: "object" })), { purpose: "tools.calls", type: "list[ToolCall]" }),
    answer: lmcc.t.string(),
  },
});
const tooled = lmcc.adapter({
  messages: [lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
             lmcc.turns(), lmcc.user("{question}")],
  transports: { tools: "fenced_tools" },
  formats: { "list[Tool]": { use: "function_tool" }, "list[ToolCall]": { use: "tool_calls" } },
});
const agent = tooled.bind(ask, { instruct: true }, { registry });

let t = agent.turn({ question: "Weather in Paris?", tools: [{ name: "get_weather", parameters: { type: "object" } }] });
t = agent.render(t).step('```tool\n{"name": "get_weather", "input": {"city": "Paris"}}\n```');
t = t.tool("call_1", "Sunny, 22C");
const next = agent.render(t);
assert.equal(next.messages[2].parts[0].text, "Result of get_weather (call_1):\nSunny, 22C");
```

The same program runs with native tool calling by changing one word:
`transports: { tools: "native_tools" }` and a model that declares
`native_function_calling`.

## 7. Artifacts travel

```ts
const artifact = lmcc.dump(tooled, registry);
const again = lmcc.load(JSON.parse(JSON.stringify(artifact)), { registry });
assert.deepEqual(lmcc.dump(again, registry), artifact);
```

An adapter is data: dump it here, load it in Python (or the reverse).

## 8. Sending it with lm15

```ts
import * as bridge from "lmcc/lm15";

const lm15Request = bridge.request(request, { model: "claude-haiku-4-5", config: { maxTokens: 300 } });
assert.equal(lm15Request.model, "claude-haiku-4-5");
// const response = await new LMRouter().complete(lm15Request);   // @lm15/lm15
// bridge.parse(plan, response); bridge.step(request, response); await bridge.stream(plan, router.stream(lm15Request));
```

## Building on lmcc (a library such as functai)

A frontend builds its own fields and signatures; `new Signature` validates
them (an invalid signature cannot exist) and freezes them, so a
fingerprint never changes after the fact. Turns are immutable records:
`withMeta` and `withScore` return new ones. `sha256` and `canonicalJson`
are the exact hashing both languages use.

```ts
const direct = new lmcc.Signature("Route the message.", [
  { name: "message", direction: "input", shape: { type: "string" } },
  { name: "team", direction: "output", shape: { type: "string", enum: ["billing", "shipping"] } },
]);
assert.equal(lmcc.signatureFingerprint(direct), lmcc.signatureFingerprint(lmcc.signatureFromDict(lmcc.signatureToDict(direct))));

const routed = xml.bind(direct, { instruct: true });
let answered = routed.turn({ message: "Where is my parcel?" });
try {
  answered = routed.render(answered).step("<team>\nlogistics\n</team>");
} catch (err) {
  if (!lmcc.isRefusal(err)) throw err;              // a Refusal from any copy of lmcc
  answered = answered.withMeta({ ...answered.meta, refusal: err.describe() });
}
assert.equal((answered.meta.refusal as { code: string }).code, "parse-value");
```

**Two copies of lmcc in one program** (npm installs it twice easily) work:
`instanceof` and `isRefusal` recognize objects from another copy of the same
kernel version, and a pack (`lmcc/std`) installed from one copy plugs into
another's registry. Across kernel versions, turns and transports cross
through their JSON; a reader or format of another version is refused with a
hint that says so. `isRefusal` recognizes a refusal from any version.

**Developing against a local checkout.** `npm install ../lmcc/ts` links the
folder and builds `dist/` once (the `prepare` script; npm 11 warns that it
ran an install script, and a future npm may ask you to approve it with
`npm approve-scripts lmcc`). A linked `dist/` does not rebuild when lmcc's
source changes. To always run the current source, with no build, start
Node with the source condition (Node 22.6–23.5 also needs
`--experimental-strip-types`):

```text
node --conditions=lmcc-source app.js
```

Bundlers take the same condition (`conditions: ["lmcc-source"]` in esbuild
and Vite). npm cannot install a package from a subdirectory of a git
repository, so until lmcc is published, use a local path or a packed
tarball (`npm pack` in `ts/`).

## Where TypeScript and Python differ, stated

The contract names the places two hosts may legitimately differ; this kernel
takes these, and nothing else (the differential check,
`python contract/harness/differential.py --probe 'node ts/tools/probe.ts'`, compares everything else on every corpus
case and 2,600 fuzzed replies):

- **Shipped code (UDF formats)**: this runtime places no UDF language, so an
  artifact that ships Python code refuses `format-untrusted`/`udf-unplaceable`
  and the six corpus cases that need `udf:python` are unclaimed. A
  code-built TypeScript format is a closure, not portable source: bind it at
  runtime with `registry.format(typeName, ...)`; `dump` refuses to ship it.
- **Integers**: one number type. An integral `3.0` given to an integer field
  writes `3` (Python refuses a float there); integers beyond ±(2^53−1) are
  read as `bigint` (the contract requires at least int64), though the static
  type of `t.integer()` says `number`.
- **Type names**: TypeScript types do not exist at run time, so the builders
  name no type unless you pass `type:` (Python writes `str`, `int`,
  `list[Person]`). Runtime format bindings match the field's type *name*.
- **Regex (`pattern/legacy-re2`)**: bound to ECMAScript `RegExp` with the
  `s` and `u` flags (label `ecmascript:RegExp`); identity escapes of
  non-syntax characters (`\:`) refuse and `\d`/`\w` are ASCII. The contract
  leaves these unspecified.
- **Hints** (the prose of a refusal) name TypeScript APIs; codes, fixes and
  partials are identical.

## Development

```text
npm install
npm run check      # tsc
npm test           # unit tests and this README
npm run conform    # the contract corpus through the harness (needs the repo's Python)
```

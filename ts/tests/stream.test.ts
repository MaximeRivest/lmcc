// §8 refinement law under random chunkings, including adversarial texts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { Refusal } from "../lmcc/refusal.ts";
import { Registry } from "../lmcc/registry.ts";
import { load } from "../lmcc/serde.ts";
import { signatureFromData } from "../lmcc/signature.ts";
import { bind, type Plan } from "../lmcc/plan.ts";
import type { StreamEvent } from "../lmcc/stream.ts";
import { jsonEqual } from "../lmcc/json.ts";
import { install } from "../lmccstd/index.ts";

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function randomChunks(text: string, r: () => number): string[] {
  const chars = Array.from(text);
  const out: string[] = [];
  let i = 0;
  while (i < chars.length) {
    const n = 1 + Math.floor(r() * 4);
    out.push(chars.slice(i, i + n).join(""));
    i += n;
  }
  return out;
}

function deltas(events: StreamEvent[]): { [f: string]: string } {
  const out: { [f: string]: string } = {};
  for (const e of events) if (e.kind === "field_delta") out[e.field] = (out[e.field] ?? "") + e.text;
  return out;
}

function checkLaw(plan: Plan, response: unknown, chunkings: unknown[][]): void {
  let batch: { values: unknown; raws: { [f: string]: string } } | null = null;
  let batchRefusal: Refusal | null = null;
  try {
    batch = plan.parseWithRaws(response);
  } catch (e) {
    if (!(e instanceof Refusal)) throw e;
    batchRefusal = e;
  }
  for (const chunks of chunkings) {
    const s = plan.stream();
    const events: StreamEvent[] = [];
    let refused: Refusal | null = null;
    let values: unknown = null;
    try {
      for (const c of chunks) events.push(...s.feed(c));
      const r = s.finish();
      events.push(...r.events);
      values = r.values;
    } catch (e) {
      if (!(e instanceof Refusal)) throw e;
      refused = e;
    }
    if (batchRefusal) {
      assert.ok(refused, `expected refusal ${batchRefusal.code} for chunks ${JSON.stringify(chunks)}`);
      assert.deepEqual(refused!.describe(), batchRefusal.describe());
      continue;
    }
    assert.ok(!refused, `unexpected refusal ${refused?.code} for chunks ${JSON.stringify(chunks)}`);
    assert.ok(jsonEqual(values, batch!.values), `values differ for chunks ${JSON.stringify(chunks)}`);
    const d = deltas(events);
    const expected: { [f: string]: string } = {};
    for (const [f, raw] of Object.entries(batch!.raws)) if (raw) expected[f] = raw;
    assert.deepEqual(d, expected, `deltas differ for chunks ${JSON.stringify(chunks)}`);
  }
}

function textChunkings(text: string, seed: number): string[][] {
  const r = rng(seed);
  const chars = Array.from(text);
  const out: string[][] = [[text], chars];
  for (let i = 0; i <= chars.length; i++) out.push([chars.slice(0, i).join(""), chars.slice(i).join("")]);
  for (let k = 0; k < 20; k++) out.push(randomChunks(text, r));
  return out;
}

const REG = new Registry();
install(REG);

const XML_ENTRY = {
  versions: { kernel: "0.2.0", vocab: {} },
  template: [
    { role: "system", text: "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}" },
    { role: "user", text: "{q}" },
  ],
  parse: { kind: "derived" },
  strategies: {
    reasoning: { visible: false, routings: [{ from: "text", between: ["<think>", "</think>"], to: "@role", consume: true }] },
    notes: { visible: false, routings: [{ from: "text", line_prefixed: "> ", to: "@role", consume: true }] },
    native: { visible: false, routings: [{ from: "channel:thinking", to: "@role" }] },
  },
};
const SIG = signatureFromData({
  instructions: "Answer.",
  fields: [
    { name: "q", direction: "input", shape: { type: "string" } },
    { name: "reasoning", direction: "output", shape: { type: "string" }, role: "reasoning" },
    { name: "notes", direction: "output", shape: { type: "string" }, role: "notes" },
    { name: "native", direction: "output", shape: { type: "string" }, role: "native" },
    { name: "answer", direction: "output", shape: { type: "string" } },
    { name: "score", direction: "output", shape: { type: ["integer", "null"] } },
  ],
});

test("derived lens + between + line_prefixed + channel: deltas join to batch raws under every chunking", () => {
  const plan = bind(load(XML_ENTRY, { registry: REG }), SIG, {});
  const texts = [
    "<think>a<think>b</think>\n> n1\r\n<answer>\n  Paris  \u00a0 \n</answer>\n> n2\n<score>\n null \n</score>",
    "<answer>\n<thi\nnk>\n</answer><think>x</think><score>\n7\n</score>>  not a note",
    "> only\n<answer>\n</answer><score>\nnull</score>",
  ];
  for (const t of texts) {
    const response = { content: [{ kind: "thinking", text: "  hm " }, { kind: "text", text: t }, { kind: "thinking", text: " more\n" }] };
    const r = rng(7);
    const chunkings: unknown[][] = [[...response.content]];
    for (let k = 0; k < 15; k++) {
      const chunks: unknown[] = [];
      for (const part of response.content) for (const c of randomChunks(part.text, r)) chunks.push({ kind: part.kind, text: c });
      chunkings.push(chunks);
    }
    checkLaw(plan, response, chunkings);
  }
});

test("refusal law: every chunking finishes with the batch refusal", () => {
  const plan = bind(load(XML_ENTRY, { registry: REG }), SIG, {});
  const response = { content: [{ kind: "thinking", text: "t" }, { kind: "text", text: "<think>a</think>> n\n<answer>\nA </answer> B\n</answer>\n<score>\n9\n</score>" }] };
  const chunkings: unknown[][] = [[...response.content]];
  const r = rng(3);
  for (let k = 0; k < 10; k++) {
    const chunks: unknown[] = [];
    for (const part of response.content) for (const c of randomChunks(part.text, r)) chunks.push({ kind: part.kind, text: c });
    chunkings.push(chunks);
  }
  checkLaw(plan, response, chunkings);
});

test("bare pattern and overlapping anchors stream correctly", () => {
  const entry = {
    versions: { kernel: "0.2.0", vocab: {} },
    template: [{ role: "system", text: "{instruction}\n**Reasoning:**{reasoning}**Answer:**{answer}" }, { role: "user", text: "{q}" }],
    parse: { kind: "derived" },
  };
  const sig = signatureFromData({
    instructions: "x",
    fields: [
      { name: "q", direction: "input", shape: { type: "string" } },
      { name: "reasoning", direction: "output", shape: { type: "string" } },
      { name: "answer", direction: "output", shape: { type: "string" } },
    ],
  });
  const plan = bind(load(entry), sig, {});
  for (const t of ["**Reasoning:**Answer:** Paris", "**Reasoning:** because **Answer:**\n Paris \n", "**Answer:** P **Reasoning:** r"]) {
    checkLaw(plan, t, textChunkings(t, 11));
  }
});

test("json_object lens buffers; routings still stream", () => {
  const entry = {
    versions: { kernel: "0.2.0", vocab: { "lens/json_object": "0.1.0" } },
    template: [{ role: "user", text: "{q}" }],
    parse: { kind: "json_object" },
    strategies: { reasoning: { visible: false, routings: [{ from: "text", between: ["<think>", "</think>"], to: "@role", consume: true }] } },
  };
  const sig = signatureFromData({
    instructions: "x",
    fields: [
      { name: "q", direction: "input", shape: { type: "string" } },
      { name: "reasoning", direction: "output", shape: { type: "string" }, role: "reasoning" },
      { name: "answer", direction: "output", shape: { type: "string" } },
      { name: "n", direction: "output", shape: { type: "integer" } },
    ],
  });
  const plan = bind(load(entry, { registry: REG }), sig, { native_structured_output: true });
  assert.equal(plan.streamingDescription().mode, "hybrid");
  const t = '<think>why</think>```json\n{"answer": "A", "n":  42, "extra": [1]}\n```';
  checkLaw(plan, t, textChunkings(t, 5));
});

test("feed after finish and malformed deltas", () => {
  const plan = bind(load(XML_ENTRY, { registry: REG }), SIG, {});
  const s = plan.stream();
  assert.throws(() => s.feed({ nokind: true }), (e: unknown) => e instanceof Refusal && e.code === "response-malformed");
  s.feed("<answer>\nA\n</answer>");
  assert.throws(() => s.finish(), (e: unknown) => e instanceof Refusal && e.code === "parse-missing-fields");
  assert.throws(() => s.feed("x"), /host API misuse/);
});

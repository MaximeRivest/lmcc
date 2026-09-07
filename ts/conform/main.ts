// The JSON Lines conformance driver (kernel §9, harness/runner.py
// SubprocessDriver): one case per stdin line, one {"ok", "detail"} (or
// {"ok": true, "unclaimed": "udf:python"}) per stdout line, in order.
//
// Every parse and parse-refusal case is replayed through the streaming
// reducer at every chunking the corpus README names: whole, one Unicode
// scalar at a time, every scalar split, and every split inside each
// text-bearing part.

import * as readline from "node:readline";
import { Refusal } from "../lmcc/refusal.ts";
import { parseJson, dumpJson, jsonEqual, isJsonObject, type Json } from "../lmcc/json.ts";
import { Registry } from "../lmcc/registry.ts";
import { load, dump } from "../lmcc/serde.ts";
import { signatureFromData } from "../lmcc/signature.ts";
import { bind, type Plan, type Values } from "../lmcc/plan.ts";
import type { StreamEvent } from "../lmcc/stream.ts";
import { install as installStd } from "../lmccstd/index.ts";

/** placements this driver can honor: none (this runtime places no code) */
const PLACEMENTS: ReadonlySet<string> = new Set();

type Answer = { ok: boolean; detail: string; unclaimed?: string };

function compare(expected: unknown, got: unknown, what: string): Answer {
  if (jsonEqual(expected, got)) return { ok: true, detail: "" };
  return { ok: false, detail: `${what} mismatch\n--- expected\n${dumpJson(expected, 1)}\n--- got\n${dumpJson(got, 1)}` };
}

function chunkings(response: unknown): unknown[][] {
  if (typeof response === "string") {
    const chars = Array.from(response);
    const out: unknown[][] = [[response], chars.slice()];
    for (let i = 0; i <= chars.length; i++) out.push([chars.slice(0, i).join(""), chars.slice(i).join("")]);
    return out;
  }
  const parts = (isJsonObject(response) && Array.isArray(response.content) ? response.content : []) as { [k: string]: Json }[];
  const copy = (p: { [k: string]: Json }): { [k: string]: Json } => ({ ...p });
  const out: unknown[][] = [parts.map(copy)];
  parts.forEach((part, pi) => {
    const text = part.text;
    if (typeof text !== "string") return;
    const chars = Array.from(text);
    let characters: { [k: string]: Json }[] = chars.map((c) => ({ ...part, text: c }));
    if (characters.length === 0) characters = [copy(part)];
    out.push([...parts.slice(0, pi).map(copy), ...characters, ...parts.slice(pi + 1).map(copy)]);
    for (let i = 0; i <= chars.length; i++) {
      const left = { ...part, text: chars.slice(0, i).join("") };
      const right = { ...part, text: chars.slice(i).join("") };
      out.push([...parts.slice(0, pi).map(copy), left, right, ...parts.slice(pi + 1).map(copy)]);
    }
  });
  return out;
}

function deltaText(events: StreamEvent[]): { [field: string]: string } {
  const out: { [field: string]: string } = {};
  for (const e of events) if (e.kind === "field_delta") out[e.field] = (out[e.field] ?? "") + e.text;
  return out;
}

function checkStreamSuccess(plan: Plan, response: unknown, batchValues: Values, batchRaws: { [field: string]: string }): Answer {
  let baseline: { [field: string]: string } | null = null;
  const all = chunkings(response);
  for (let n = 0; n < all.length; n++) {
    const stream = plan.stream();
    const events: StreamEvent[] = [];
    let values: Values;
    try {
      for (const chunk of all[n]) events.push(...stream.feed(chunk));
      const result = stream.finish();
      events.push(...result.events);
      values = result.values;
    } catch (e) {
      return { ok: false, detail: `stream split ${n} refused/failed: ${(e as Error).message}` };
    }
    const cmp = compare(batchValues, values, `stream split ${n} values`);
    if (!cmp.ok) return cmp;
    const deltas = deltaText(events);
    if (baseline === null) {
      baseline = deltas;
      // §8: per field, the concatenation of emitted deltas equals the batch raw text
      const expectedDeltas: { [field: string]: string } = {};
      for (const [f, raw] of Object.entries(batchRaws)) if (raw.length) expectedDeltas[f] = raw;
      const raw = compare(expectedDeltas, deltas, `stream split ${n} field deltas vs batch raw text`);
      if (!raw.ok) return raw;
    } else {
      const d = compare(baseline, deltas, `stream split ${n} field deltas`);
      if (!d.ok) return d;
    }
    // structural event checks
    const started = new Set<string>();
    const done = new Set<string>();
    for (const e of events) {
      if (e.kind === "field_started") {
        if (started.has(e.field)) return { ok: false, detail: `stream split ${n}: field_started twice for ${e.field}` };
        started.add(e.field);
      } else if (e.kind === "field_done") {
        if (done.has(e.field)) return { ok: false, detail: `stream split ${n}: field_done twice for ${e.field}` };
        if (!started.has(e.field)) return { ok: false, detail: `stream split ${n}: field_done before field_started for ${e.field}` };
        done.add(e.field);
      } else if (e.text.length === 0) return { ok: false, detail: `stream split ${n}: empty field_delta for ${e.field}` };
    }
    for (const f of Object.keys(values)) if (!done.has(f)) return { ok: false, detail: `stream split ${n}: no field_done for ${f}` };
  }
  return { ok: true, detail: "" };
}

function checkStreamRefusal(plan: Plan, response: unknown, batch: Refusal): Answer {
  const expected = batch.describe();
  const all = chunkings(response);
  for (let n = 0; n < all.length; n++) {
    const stream = plan.stream();
    try {
      for (const chunk of all[n]) stream.feed(chunk);
      stream.finish();
    } catch (e) {
      if (e instanceof Refusal) {
        if (jsonEqual(expected, e.describe())) continue;
        return compare(expected, e.describe(), `stream split ${n} refusal`);
      }
      return { ok: false, detail: `stream split ${n} failed outside Refusal: ${(e as Error).message}` };
    }
    return { ok: false, detail: `stream split ${n}: expected refusal [${batch.code}]` };
  }
  return { ok: true, detail: "" };
}

export function runCase(kase: { [k: string]: Json }): Answer {
  const requires = Array.isArray(kase.requires) ? (kase.requires as string[]) : [];
  for (const r of requires) if (!PLACEMENTS.has(r)) return { ok: true, detail: "", unclaimed: r };
  const expect = kase.expect as { [k: string]: Json };
  const kind = kase.kind as string;
  const registry = new Registry();
  const vocab = Array.isArray(kase.vocab) ? (kase.vocab as string[]) : [];
  for (const v of vocab) {
    if (v === "std") installStd(registry);
    else return { ok: false, detail: `vocabulary pack ${JSON.stringify(v)} is not available in this driver` };
  }
  let plan: Plan | null = null;
  try {
    const adapter = load(kase.entry, { registry });
    if (kind === "roundtrip") return compare(expect.entry, dump(adapter, registry), "entry");
    const sig = signatureFromData(kase.signature);
    plan = bind(adapter, sig, (kase.capabilities as { [k: string]: boolean }) ?? {});
    if (kind === "plan") {
      const got = { skeleton: plan.skeleton(), prefix: plan.prefix(kase.demos as unknown[] | undefined, kase.history as unknown[] | undefined) };
      return compare({ skeleton: expect.skeleton, prefix: expect.prefix }, got, "plan");
    }
    if (kind === "render") {
      const result = plan.render((kase.inputs as Values) ?? {}, kase.demos as unknown[] | undefined, kase.history as unknown[] | undefined);
      return compare(expect, { messages: result.messages, patch: result.patch }, "render result");
    }
    if (kind === "parse") {
      const { values, raws } = plan.parseWithRaws(kase.response);
      const cmp = compare(expect.values, values, "values");
      if (!cmp.ok) return cmp;
      return checkStreamSuccess(plan, kase.response, values, raws);
    }
    if (kind === "refuse") {
      if ("inputs" in kase) plan.render(kase.inputs as Values, kase.demos as unknown[] | undefined, kase.history as unknown[] | undefined);
      if ("response" in kase) plan.parse(kase.response);
      return { ok: false, detail: `expected refusal ${JSON.stringify(expect.code)}, but nothing refused` };
    }
    return { ok: false, detail: `unknown case kind ${JSON.stringify(kind)}` };
  } catch (e) {
    if (e instanceof Refusal) {
      if (kind === "refuse" && e.code === expect.code) {
        if ("fix" in expect) {
          const cmp = compare(expect.fix, e.fix ?? null, `fix of [${e.code}]`);
          if (!cmp.ok) return cmp;
        }
        if (expect.at === "parse" && "response" in kase && plan) return checkStreamRefusal(plan, kase.response, e);
        return { ok: true, detail: "" };
      }
      return { ok: false, detail: `unexpected refusal [${e.code}]: ${e.hint}` };
    }
    return { ok: false, detail: `driver error outside Refusal: ${(e as Error).stack ?? String(e)}` };
  }
}

function main(): void {
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => {
    if (line.trim() === "") return;
    let answer: Answer;
    try {
      const kase = parseJson(line);
      if (!isJsonObject(kase)) throw new Error("case is not an object");
      answer = runCase(kase);
    } catch (e) {
      answer = { ok: false, detail: `driver could not run the case: ${(e as Error).message}` };
    }
    const out: { [k: string]: Json } = { ok: answer.ok, detail: answer.detail };
    if (answer.unclaimed) out.unclaimed = answer.unclaimed;
    process.stdout.write(dumpJson(out, null) + "\n");
  });
}

if (process.argv[1] && /conform[\\/]main\.ts$/.test(process.argv[1])) main();

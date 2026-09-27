/**
 * The TypeScript kernel behind the harness's driver protocol (kernel §9).
 *
 *     cd python && python ../contract/harness/runner.py --driver 'node ../ts/conform/driver.ts'
 *
 * One case per line on stdin, one `{ok, detail?, unclaimed?, stream_trace?}`
 * per line on stdout. Mirrors contract/harness/runner.py's reference driver:
 * the same stages, the same stream replays (whole, one scalar at a time, and
 * every split of text and of each text-bearing part), and the one-scalar
 * event trace the harness compares with the reference kernel's.
 *
 * Case JSON is read with lmcc's own parser, so integers beyond 2^53 stay
 * exact (case 35 writes 9007199254740993).
 */

import { createInterface } from "node:readline";
import * as lmcc from "../src/index.ts";
import { install as installStd } from "../src/std/index.ts";
import { jsonEqual, parseJson, pretty } from "../src/json.ts";
import { nativeExtensions } from "../src/extensions.ts";
import { sha256Hex } from "../src/sha256.ts";
import { jsonText } from "../src/json.ts";

type Case = Record<string, any>;
type Result = { ok: boolean; detail: string; unclaimed?: string; stream_trace?: unknown };

/** Kernel §3a, computed here as the harness does, for case turns that omit `signature`. */
function signatureFingerprint(signature: Case): string {
  const fields = (signature["fields"] as Case[]).map((f) => ({
    direction: f["direction"], name: f["name"], purpose: f["purpose"] ?? "plain", shape: f["shape"], type: f["type"] ?? "",
  }));
  return "sha256:" + sha256Hex(jsonText(fields, { sortKeys: true }));
}

function caseTurns(c: Case): [Case, Record<string, Case[]>] {
  const fp = signatureFingerprint(c["signature"]);
  const current = { signature: fp, inputs: c["inputs"] ?? {}, steps: c["steps"] ?? [] };
  const slots: Record<string, Case[]> = {};
  for (const [name, ts] of Object.entries((c["turns"] ?? {}) as Record<string, Case[]>)) slots[name] = ts.map((t) => ({ signature: fp, ...t }));
  return [current, slots];
}

function registryFor(c: Case): lmcc.Registry {
  const requires: string[] = c["requires"] ?? [];
  const registry = new lmcc.Registry({ allowUdf: requires.includes("udf:python"), extensions: requires.filter((r) => !r.startsWith("udf:")) });
  if ((c["vocab"] ?? []).includes("std")) installStd(registry);
  return registry;
}

function unclaimedOf(c: Case): string | null {
  const native = new Set(nativeExtensions().map((b) => b.extension));
  for (const r of (c["requires"] ?? []) as string[]) {
    if (r.startsWith("udf:")) return r; // this runtime places no UDF language
    if (!native.has(r)) return r;
  }
  return null;
}

function compare(expected: unknown, got: unknown, what: string): Result {
  if (jsonEqual(expected, got)) return { ok: true, detail: "" };
  return { ok: false, detail: `${what} mismatch\n--- expected\n${pretty(expected)}\n--- got\n${pretty(got)}` };
}

function messageParts(response: unknown): Case[] {
  let r = response as Case;
  if (r && typeof r === "object" && r["message"] && typeof r["message"] === "object") r = r["message"];
  return r && typeof r === "object" && Array.isArray(r["parts"]) ? r["parts"] : [];
}

/** One whole feed, then every scalar split of text and of each text-bearing part. */
function streamChunkings(response: unknown): unknown[][] {
  if (typeof response === "string") {
    const scalars = Array.from(response);
    const out: unknown[][] = [[response], scalars];
    let offset = 0;
    for (let i = 0; i <= scalars.length; i++) {
      out.push([response.slice(0, offset), response.slice(offset)]);
      if (i < scalars.length) offset += scalars[i].length;
    }
    return out;
  }
  const parts = messageParts(response);
  const out: unknown[][] = [[...parts]];
  parts.forEach((part, pi) => {
    const text = part && typeof part === "object" ? part["text"] : undefined;
    if (typeof text !== "string") return;
    const scalars = Array.from(text);
    let characters: Case[] = scalars.map((ch) => ({ ...part, text: ch }));
    if (!characters.length) characters = [{ ...part }];
    out.push([...parts.slice(0, pi), ...characters, ...parts.slice(pi + 1)]);
    let offset = 0;
    for (let i = 0; i <= scalars.length; i++) {
      out.push([...parts.slice(0, pi), { ...part, text: text.slice(0, offset) }, { ...part, text: text.slice(offset) }, ...parts.slice(pi + 1)]);
      if (i < scalars.length) offset += scalars[i].length;
    }
  });
  return out;
}

function feedChunk(plan: lmcc.Plan, stream: lmcc.Stream, response: unknown, chunk: unknown): lmcc.StreamEvent[] {
  // A string in a part list is not a text delta: check its list boundary first.
  if (typeof response !== "string" && typeof chunk === "string") plan.parse({ role: "assistant", parts: [chunk] });
  return stream.feed(chunk as string);
}

function deltaText(events: lmcc.StreamEvent[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of events) if (e.kind === "field_delta") out[e.field] = (out[e.field] ?? "") + e.text;
  return out;
}

function finishReasonOf(response: unknown): string | null {
  const r = response as Case;
  if (r && typeof r === "object" && r["message"] && typeof r["message"] === "object") return r["finish_reason"] ?? null;
  return null;
}

function checkStreamSuccess(plan: lmcc.Plan, response: unknown, reading: lmcc.Reading, raw: Record<string, string>): Result {
  let baseline: Record<string, string> | null = null;
  const chunkings = streamChunkings(response);
  for (let n = 0; n < chunkings.length; n++) {
    const stream = plan.stream();
    const events: lmcc.StreamEvent[] = [];
    let result: lmcc.StreamResult;
    try {
      for (const chunk of chunkings[n]) events.push(...feedChunk(plan, stream, response, chunk));
      result = stream.finish(finishReasonOf(response));
      events.push(...result.events);
    } catch (err) {
      return { ok: false, detail: `stream split ${n} refused/failed: ${(err as Error).message}` };
    }
    if (!jsonEqual(result.values, reading.values)) return compare(reading.values, result.values, `stream split ${n} values`);
    if (!jsonEqual(result.repairs, reading.repairs)) return compare(reading.repairs, result.repairs, `stream split ${n} repairs`);
    if (!jsonEqual(result.probabilities, reading.probabilities)) return compare(reading.probabilities, result.probabilities, `stream split ${n} probabilities`);
    if (!jsonEqual(result.measuredBy, reading.measuredBy)) return compare(reading.measuredBy, result.measuredBy, `stream split ${n} measured_by`);
    const deltas = deltaText(events);
    if (!jsonEqual(deltas, raw)) return compare(raw, deltas, `stream split ${n} deltas against batch raw text`);
    if (baseline === null) baseline = deltas;
    else if (!jsonEqual(deltas, baseline)) return compare(baseline, deltas, `stream split ${n} field deltas`);
  }
  return { ok: true, detail: "" };
}

function checkStreamRefusal(plan: lmcc.Plan, response: unknown, batch: lmcc.Refusal): Result {
  const expected = batch.describe();
  const chunkings = streamChunkings(response);
  for (let n = 0; n < chunkings.length; n++) {
    const stream = plan.stream();
    try {
      for (const chunk of chunkings[n]) feedChunk(plan, stream, response, chunk);
      stream.finish(finishReasonOf(response));
    } catch (err) {
      if (err instanceof lmcc.Refusal) {
        if (jsonEqual(err.describe(), expected)) continue;
        return compare(expected, err.describe(), `stream split ${n} refusal`);
      }
      return { ok: false, detail: `stream split ${n} failed outside Refusal: ${(err as Error).message}` };
    }
    return { ok: false, detail: `stream split ${n}: expected refusal [${batch.code}]` };
  }
  return { ok: true, detail: "" };
}

/** One scalar per feed; a part without text is one feed. */
function traceChunking(response: unknown): unknown[] {
  if (typeof response === "string") return Array.from(response);
  const out: unknown[] = [];
  for (const part of messageParts(response)) {
    const text = part && typeof part === "object" ? part["text"] : undefined;
    if (typeof text === "string" && text) for (const ch of text) out.push({ ...part, text: ch });
    else out.push(part);
  }
  return out;
}

function digest(e: lmcc.StreamEvent): unknown[] {
  return e.kind === "field_delta" ? [e.kind, e.field, e.text] : [e.kind, e.field];
}

function streamTrace(plan: lmcc.Plan, response: unknown): unknown[] {
  const stream = plan.stream();
  const trace: unknown[] = [];
  try {
    for (const chunk of traceChunking(response)) trace.push(feedChunk(plan, stream, response, chunk).map(digest));
    trace.push(stream.finish(finishReasonOf(response)).events.map(digest));
  } catch (err) {
    if (!(err instanceof lmcc.Refusal)) throw err;
    trace.push({ refusal: err.code });
  }
  return trace;
}

export function runCase(c: Case): Result {
  const expect = c["expect"];
  const kind = c["kind"];
  const unclaimed = unclaimedOf(c);
  if (unclaimed) return { ok: true, detail: "", unclaimed };
  const registry = registryFor(c);
  let stage = "load";
  let plan: lmcc.Plan | null = null;
  try {
    const adapter = lmcc.load(c["entry"], { registry });
    if (kind === "roundtrip") return compare(expect["entry"], lmcc.dump(adapter, registry), "entry");
    stage = "signature";
    const sig = lmcc.signatureFromDict(c["signature"]);
    stage = "bind";
    plan = adapter.bind(sig, c["capabilities"] ?? {}, { registry });
    if (kind === "plan") {
      const [, slots] = caseTurns(c);
      return compare({ skeleton: expect["skeleton"], prefix: expect["prefix"] }, { skeleton: plan.skeleton(), prefix: plan.prefix({ turns: slots }) }, "plan");
    }
    if (kind === "render") {
      const [current, slots] = caseTurns(c);
      return compare(expect["request"], plan.render(lmcc.Turn.fromJSON(current), { turns: slots }).request(), "request");
    }
    if (kind === "parse") {
      const reading = plan.read(c["response"]);
      let r = compare(expect["values"], reading.values, "values");
      if (!r.ok) return r;
      if ("repairs" in expect) {
        r = compare(expect["repairs"], reading.repairs, "repairs");
        if (!r.ok) return r;
      }
      for (const [key, got] of [["probabilities", reading.probabilities], ["measured_by", reading.measuredBy]] as const) {
        if (key in expect) {
          r = compare(expect[key], got, key);
          if (!r.ok) return r;
        }
      }
      const [, captures] = plan.parseWithCaptures(c["response"]);
      const raw: Record<string, string> = {};
      for (const [name, capture] of captures) if (capture.text) raw[name] = capture.text;
      const result = checkStreamSuccess(plan, c["response"], reading, raw);
      if (result.ok) result.stream_trace = streamTrace(plan, c["response"]);
      return result;
    }
    if (kind === "refuse") {
      if ("inputs" in c) {
        stage = "render";
        const [current, slots] = caseTurns(c);
        plan.render(lmcc.Turn.fromJSON(current), { turns: slots });
      }
      if ("response" in c) {
        stage = "parse";
        plan.parse(c["response"]);
      }
      return { ok: false, detail: `expected refusal '${expect["code"]}', but nothing refused` };
    }
    return { ok: false, detail: `unknown case kind '${kind}'` };
  } catch (err) {
    if (!(err instanceof lmcc.Refusal)) {
      return { ok: false, detail: `host error at ${stage}: ${(err as Error).stack ?? String(err)}` };
    }
    if (kind === "refuse" && err.code === expect["code"] && "at" in expect && stage !== expect["at"]) {
      return { ok: false, detail: `refusal [${err.code}] fired at ${stage}, the case says ${expect["at"]}` };
    }
    if (kind === "refuse" && err.code === expect["code"]) {
      if ("fix" in expect) {
        const r = compare(expect["fix"], err.fix, `fix of [${err.code}]`);
        if (!r.ok) return r;
      }
      if (expect["at"] === "parse" && "response" in c && plan !== null) {
        const r = checkStreamRefusal(plan, c["response"], err);
        if (r.ok) r.stream_trace = streamTrace(plan, c["response"]);
        return r;
      }
      return { ok: true, detail: "" };
    }
    return { ok: false, detail: `unexpected refusal [${err.code}]: ${err.hint}` };
  }
}

function main(): void {
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => {
    if (!line.trim()) return;
    let answer: Result;
    try {
      answer = runCase(parseJson(line) as Case);
    } catch (err) {
      answer = { ok: false, detail: `driver error: ${(err as Error).stack ?? String(err)}` };
    }
    process.stdout.write(JSON.stringify(answer, (_k, v) => (typeof v === "bigint" ? Number(v) : v)) + "\n");
  });
}

if (import.meta.main ?? process.argv[1]?.endsWith("driver.ts")) main();

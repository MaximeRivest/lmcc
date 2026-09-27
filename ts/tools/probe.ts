/**
 * Observations of the TypeScript kernel on one corpus case, as JSON, for the
 * differential check against the Python reference (tools/differential.py).
 * The corpus pins requests, values and refusals; this pins everything else
 * two implementations serialize: `plan.describe()`, `dump()`, fingerprints,
 * request hashes, readings, recorded turns, prefixes, refusal data.
 *
 *     node tools/probe.ts < cases.jsonl > observations.jsonl
 */

import { createInterface } from "node:readline";
import * as lmcc from "../src/index.ts";
import { install as installStd } from "../src/std/index.ts";
import { parseJson } from "../src/json.ts";
import { asMessage, ModelStep, sha256, Turn } from "../src/turn.ts";

type Case = Record<string, any>;

function refusal(err: unknown): unknown {
  if (err instanceof lmcc.Refusal) return { code: err.code, fix: err.fix, partial: err.partial, hint: err.hint };
  throw err;
}

function attempt(fn: () => unknown): unknown {
  try {
    return { ok: fn() };
  } catch (err) {
    return { refused: refusal(err) };
  }
}

function fill(sig: lmcc.Signature, turn: Case): Case {
  return { signature: lmcc.signatureFingerprint(sig), ...turn };
}

export function observe(c: Case): Record<string, unknown> {
  const requires: string[] = c["requires"] ?? [];
  if (requires.some((r) => r.startsWith("udf:"))) return { skipped: "udf" };
  const registry = new lmcc.Registry({ extensions: requires });
  if ((c["vocab"] ?? []).includes("std")) installStd(registry);
  const out: Record<string, unknown> = {};
  let adapter: lmcc.Adapter;
  try {
    adapter = lmcc.load(c["entry"], { registry });
  } catch (err) {
    return { load: { refused: refusal(err) } };
  }
  out["dump"] = attempt(() => lmcc.dump(adapter, registry));
  if (!c["signature"]) return out;
  let sig: lmcc.Signature;
  try {
    sig = lmcc.signatureFromDict(c["signature"]);
  } catch (err) {
    out["signature"] = { refused: refusal(err) };
    return out;
  }
  out["fingerprint"] = lmcc.signatureFingerprint(sig);
  out["signature_dict"] = lmcc.signatureToDict(sig);
  let plan: lmcc.Plan;
  try {
    plan = adapter.bind(sig, c["capabilities"] ?? {}, { registry });
  } catch (err) {
    out["bind"] = { refused: refusal(err) };
    return out;
  }
  out["describe"] = plan.describe();
  const slots: Record<string, Case[]> = {};
  for (const [name, ts] of Object.entries((c["turns"] ?? {}) as Record<string, Case[]>)) slots[name] = ts.map((t) => fill(sig, t));
  out["prefix"] = attempt(() => plan.prefix({ turns: slots }));
  out["skeleton"] = plan.skeleton();
  if ("inputs" in c) {
    const current = fill(sig, { inputs: c["inputs"], steps: c["steps"] ?? [] });
    out["turn_json"] = attempt(() => Turn.fromJSON(current).toJSON());
    out["slot_json"] = attempt(() => Object.fromEntries(Object.entries(slots).map(([k, ts]) => [k, ts.map((t) => Turn.fromJSON(t).toJSON())])));
    out["render"] = attempt(() => {
      const rendered = plan.render(Turn.fromJSON(current), { turns: slots });
      return { request: rendered.request("m"), hash: sha256(rendered.request()) };
    });
  }
  if ("response" in c) {
    out["read"] = attempt(() => plan.read(c["response"]).toJSON());
    out["step"] = attempt(() => {
      const values = plan.parse(c["response"]);
      return new ModelStep(values, asMessage(c["response"]), sha256({ messages: [] }), plan.callsField).toJSON();
    });
    out["stream"] = attempt(() => {
      const stream = plan.stream();
      const events: unknown[] = [];
      const response = c["response"];
      const parts = typeof response === "string" ? [response] : ((response["message"] ?? response)["parts"] as unknown[]);
      for (const p of parts) events.push(...stream.feed(p as string));
      const end = stream.finish(typeof response === "object" && response["message"] ? response["finish_reason"] ?? null : null);
      return { events: [...events, ...end.events], result: end.toJSON() };
    });
  }
  return out;
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  if (!line.trim()) return;
  let answer: unknown;
  try {
    answer = observe(parseJson(line) as Case);
  } catch (err) {
    answer = { crash: (err as Error).stack ?? String(err) };
  }
  process.stdout.write(JSON.stringify(answer, (_k, v) => (typeof v === "bigint" ? v.toString() + "n" : v)) + "\n");
});

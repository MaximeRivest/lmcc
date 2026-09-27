/**
 * Two copies of lmcc in one process (npm installs it twice easily: an app
 * and a pack each with their own). Objects must cross between copies of one
 * kernel version, and between versions only through their versioned JSON, or
 * be refused by name. Each copy here is a real second load of the source.
 */

import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

type Lmcc = typeof import("../src/index.ts");
type Std = typeof import("../src/std/index.ts");

const SRC = fileURLToPath(new URL("../src", import.meta.url));
const dirs: string[] = [];

async function copy(version?: string): Promise<{ lmcc: Lmcc; std: Std }> {
  const dir = mkdtempSync(join(tmpdir(), "lmcc-copy-"));
  dirs.push(dir);
  cpSync(SRC, dir, { recursive: true });
  if (version) {
    const file = join(dir, "version.ts");
    writeFileSync(file, readFileSync(file, "utf8").replace(/"\d+\.\d+\.\d+"/, JSON.stringify(version)));
  }
  const lmcc = (await import(pathToFileURL(join(dir, "index.ts")).href)) as Lmcc;
  const std = (await import(pathToFileURL(join(dir, "std", "index.ts")).href)) as Std;
  return { lmcc, std };
}

after(() => {
  for (const d of dirs) rmSync(d, { recursive: true, force: true });
});

const A = await copy();
const B = await copy();
const NEXT = await copy("0.9.0");

const quiz = (l: Lmcc) => l.signatureFromDict({
  instructions: "Classify.",
  fields: [
    { name: "text", direction: "input", shape: { type: "string" } },
    { name: "label", direction: "output", shape: { type: "string", enum: ["a", "b"] } },
  ],
});
const tags = (l: Lmcc) => l.adapter({ messages: [l.system("{% for f in outputs %}<{f.name}>{f.value}</{f.name}>{% endfor %}"), l.turns(), l.user("{text}")] });

test("the copies really are distinct classes", () => {
  assert.notEqual(A.lmcc.Refusal, B.lmcc.Refusal);
  assert.notEqual(A.lmcc.Turn, B.lmcc.Turn);
});

test("a refusal from any copy or version is a Refusal; nothing else is", () => {
  for (const from of [A, NEXT]) {
    const err = new from.lmcc.Refusal("parse-value", "x");
    assert.ok(err instanceof B.lmcc.Refusal && B.lmcc.isRefusal(err));
  }
  assert.ok(!B.lmcc.isRefusal({ code: "parse-value", hint: "x", fix: null, partial: null }));
  assert.ok(!B.lmcc.isRefusal(new Error("x")));
});

test("a pack from one copy plugs into another copy's registry, refusals intact", () => {
  const registry = new B.lmcc.Registry();
  A.std.install(registry as never); // lmcc/std resolved against another copy
  const sig = B.lmcc.signatureFromDict({ instructions: "Rate.", fields: [
    { name: "text", direction: "input", shape: { type: "string" } },
    { name: "stars", direction: "output", shape: { type: "integer" } },
  ] });
  const json = B.lmcc.adapter({ messages: [B.lmcc.system("{instruction}"), B.lmcc.user("{text}")], reader: { kind: "json_object" } });
  const plan = json.bind(sig, { native_structured_output: true }, { registry });
  assert.deepEqual(plan.parse('{"stars": 4}'), { stars: 4 });
  // A's reader throws A's Refusal; B must pass it on, not wrap it as reader-error
  assert.throws(() => plan.parse('{"stars": 4, "stars": 5}'), (e) => B.lmcc.isRefusal(e) && e.code === "parse-ambiguous");
  // A's transports cross too, checked as data by B
  const reasoned = B.lmcc.adapter({ messages: [B.lmcc.system("{% for f in outputs %}<{f.name}>{f.value}</{f.name}>{% endfor %}"), B.lmcc.user("{text}")],
    transports: { reasoning: "reasoning_tags" } });
  const sig2 = B.lmcc.signatureFromDict({ instructions: "", fields: [
    { name: "text", direction: "input", shape: { type: "string" } },
    { name: "reasoning", direction: "output", shape: { type: "string" }, purpose: "reasoning" },
    { name: "stars", direction: "output", shape: { type: "integer" } },
  ] });
  assert.deepEqual(reasoned.bind(sig2, { instruct: true }, { registry }).parse("<think>ok</think><stars>3</stars>"), { stars: 3, reasoning: "ok" });
});

test("turns and signatures cross between copies of one version", () => {
  const planA = tags(A.lmcc).bind(quiz(A.lmcc), { instruct: true });
  const planB = tags(B.lmcc).bind(quiz(B.lmcc), { instruct: true });
  const example = planA.example({ text: "x" }, { label: "a" });
  const current = planA.render({ text: "y" }).step("<label>b</label>");
  const request = planB.render(current, { turns: [example] }).request();
  assert.deepEqual(request, planA.render(current, { turns: [example] }).request());
  assert.equal(B.lmcc.signatureFingerprint(quiz(A.lmcc)), A.lmcc.signatureFingerprint(quiz(B.lmcc)));
});

test("across versions, records cross through their JSON and behavior is refused by name", () => {
  const planNext = tags(NEXT.lmcc).bind(quiz(NEXT.lmcc), { instruct: true });
  const planB = tags(B.lmcc).bind(quiz(B.lmcc), { instruct: true });
  const turnNext = planNext.render({ text: "y" }).step("<label>b</label>");
  assert.ok(!(turnNext instanceof B.lmcc.Turn), "a 0.9 Turn is not a 0.8 Turn");
  assert.deepEqual(planB.render(turnNext).request(), planNext.render(turnNext).request());

  const registry = new B.lmcc.Registry();
  NEXT.std.install(registry as never);
  // transports are data: a 0.9 transport crosses as its artifact form
  assert.ok(registry.transport("reasoning_tags", {}) instanceof B.lmcc.Transport);
  // a reader is behavior: refused, and the hint says why
  assert.throws(() => registry.reader({ kind: "json_object" }),
    (e) => B.lmcc.isRefusal(e) && e.code === "entry-malformed" && /another lmcc version/.test(e.hint));
});

test("instanceof keeps JavaScript's rule for subclasses", () => {
  const derived = new A.lmcc.DerivedReader([["x", "<x>", "</x>"]]);
  assert.ok(derived instanceof B.lmcc.Reader && derived instanceof B.lmcc.DerivedReader);
  const registry = new B.lmcc.Registry();
  B.std.install(registry);
  const json = registry.reader({ kind: "json_object" });
  assert.ok(json instanceof B.lmcc.Reader);
  assert.ok(!(json instanceof B.lmcc.DerivedReader), "a JSON reader is not the derived reader");
  assert.ok(json instanceof B.std.readers.JsonObjectReader, "a subclass still matches itself");
});

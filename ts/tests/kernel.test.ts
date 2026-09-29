/**
 * Unit tests for what the corpus and the differential check do not reach:
 * the README runs verbatim (and type-checks), streaming refines batch under
 * random multi-chunk splits, per-feed cost stays linear, the kernel stays
 * dependency-free and browser-safe, and the host differences are the ones
 * README.md states.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import * as lmcc from "../src/index.ts";
import { install } from "../src/std/index.ts";
import { formatNumber, jsonEqual, jsonText, parseJson } from "../src/json.ts";
import { sha256Hex } from "../src/sha256.ts";
import { pyRepr } from "../src/text.ts";
import { dumps } from "../src/std/jsontext.ts";
import { lower } from "../src/std/formats.ts";

const TS = dirname(dirname(fileURLToPath(import.meta.url)));
const CASES = join(TS, "..", "contract", "corpus", "cases");

test("the README runs verbatim and type-checks", () => {
  const text = readFileSync(join(TS, "README.md"), "utf8");
  const code = [...text.matchAll(/^```ts\n([\s\S]*?)^```$/gm)].map((m) => m[1]).join("\n");
  const file = join(TS, ".readme-verbatim.ts");
  writeFileSync(file, code);
  try {
    execFileSync(process.execPath, ["--conditions=lmcc-source", file], { cwd: TS, stdio: "pipe" });
    execFileSync(process.execPath, [join(TS, "node_modules", "typescript", "bin", "tsc"), "--noEmit", "--strict", "--target", "es2022",
      "--module", "nodenext", "--moduleResolution", "nodenext", "--allowImportingTsExtensions", "--skipLibCheck", "--types", "node", "--customConditions", "lmcc-source", file],
      { cwd: TS, stdio: "pipe" });
  } finally {
    rmSync(file, { force: true });
  }
});

test("the kernel imports nothing outside itself and nothing host-specific", () => {
  const walk = (dir: string): string[] => readdirSync(dir, { withFileTypes: true })
    .flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]));
  for (const file of walk(join(TS, "src"))) {
    const text = readFileSync(file, "utf8");
    const imports = [...text.matchAll(/^import[^;]*?from\s+"([^"]+)"/gm)].map((m) => m[1]);
    for (const spec of imports) {
      const allowed = spec.startsWith(".") || (file.endsWith("lm15.ts") && spec === "@lm15/lm15");
      assert.ok(allowed, `${file} imports ${spec}`);
    }
    assert.doesNotMatch(text, /\bprocess\.|\brequire\(|\bBuffer\b/, `${file} reaches for a Node global`);
  }
  const pkg = JSON.parse(readFileSync(join(TS, "package.json"), "utf8"));
  assert.equal(pkg.dependencies, undefined, "the package has no runtime dependencies");
});

test("the package version is the kernel version, in both languages", () => {
  const pkg = JSON.parse(readFileSync(join(TS, "package.json"), "utf8"));
  const pyproject = readFileSync(join(TS, "..", "python", "pyproject.toml"), "utf8");
  assert.equal(pkg.version, lmcc.KERNEL_VERSION);
  assert.equal(lmcc.VERSION, lmcc.KERNEL_VERSION);
  assert.equal(/^version = "([^"]+)"/m.exec(pyproject)?.[1], lmcc.KERNEL_VERSION);
});

test("text rules: ECMAScript numbers, exact int64, strict JSON, code-point order", () => {
  assert.deepEqual([3, 1e21, 1e-7, 0.000001, -0, 123456789012345680000].map((n) => formatNumber(n)), ["3", "1e+21", "1e-7", "0.000001", "0", "123456789012345680000"]);
  assert.equal(parseJson("9007199254740993"), 9007199254740993n);
  assert.equal(parseJson("-0"), 0);
  assert.equal(Object.is(parseJson("-0"), -0), false);
  assert.throws(() => parseJson('{"a": 1, "a": 2}', { duplicates: "reject" }));
  assert.throws(() => parseJson("NaN"));
  assert.throws(() => parseJson('"a\u0001"'));
  const proto = parseJson('{"__proto__": {"polluted": true}}') as Record<string, unknown>;
  assert.equal(({} as Record<string, unknown>)["polluted"], undefined);
  assert.ok(Object.keys(proto).includes("__proto__"));
  assert.equal(jsonText({ "\uffff": 1, "\u{1f600}": 2, b: 1.0, a: [1e-7, "é\n"] }, { sortKeys: true }), '{"a":[1e-7,"é\\n"],"b":1,"\uffff":1,"\u{1f600}":2}');
  assert.ok(jsonEqual(9007199254740993n, 9007199254740993n) && !jsonEqual(9007199254740993n, 9007199254740992));
  assert.equal(pyRepr("it's"), '"it\'s"');
  assert.equal(pyRepr(["a", null, true, 1.5, 1e-7]), "['a', None, True, 1.5, 1e-07]");
});

test("sha256 matches the standard vectors", () => {
  assert.equal(sha256Hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  assert.equal(sha256Hex("a".repeat(1000)), "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3");
  assert.equal(sha256Hex("日本 😀"), "3d55913885fee5c317f716b93f695df3fae14628b64d8f25ebc3a8afde76c72d");
});

test("host differences are the stated ones", () => {
  const sig = lmcc.signature("Count.", { inputs: { n: lmcc.t.integer() }, outputs: { big: lmcc.t.integer() } });
  const adapter = lmcc.adapter({ messages: [lmcc.system("{% for f in outputs %}<{f.name}>{f.value}</{f.name}>{% endfor %}"), lmcc.user("{n}")] });
  const plan = adapter.bind(sig, { instruct: true });
  assert.equal(plan.render({ n: 3.0 }).messages[0].parts[0].text, "3"); // Python refuses a float here
  assert.throws(() => plan.render({ n: 3.5 }), (e) => e instanceof lmcc.Refusal && e.code === "value-invalid");
  assert.equal(plan.parse("<big>9223372036854775807</big>").big, 9223372036854775807n as unknown as number);
  assert.throws(() => lmcc.dump(lmcc.adapter({ messages: [lmcc.user("{n}")], formats: { X: lmcc.makeFormat({ write: String }) } })),
    (e) => e instanceof lmcc.Refusal && e.code === "format-not-self-contained");
});

// ------------------------------------------------ streaming refines batch

function mulberry32(seed: number): () => number {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function mutate(text: string, rnd: () => number): string {
  const i = Math.floor(rnd() * (text.length + 1));
  const j = Math.min(text.length, i + 1 + Math.floor(rnd() * 11));
  const pick = <T>(xs: T[]) => xs[Math.floor(rnd() * xs.length)];
  switch (Math.floor(rnd() * 6)) {
    case 0: return text.slice(0, i) + text.slice(i, j).toUpperCase() + text.slice(j);
    case 1: return text.slice(0, i) + pick(["**", "#", "### ", "_", "\n", " "]) + text.slice(i);
    case 2: return text.slice(0, i) + text.slice(j);
    case 3: return text.slice(0, j) + text.slice(i, j) + text.slice(j);
    case 4: return text.slice(0, i);
    default: return text.slice(0, i) + pick(['"', ".", "`", "None"]) + text.slice(i);
  }
}

function chunks(text: string, rnd: () => number): string[] {
  const scalars = Array.from(text);
  const cuts = new Set<number>();
  const n = Math.floor(rnd() * 7);
  for (let k = 0; k < n && scalars.length > 1; k++) cuts.add(1 + Math.floor(rnd() * (scalars.length - 1)));
  const out: string[] = [];
  let prev = 0;
  for (const c of [...cuts].sort((a, b) => a - b)) {
    out.push(scalars.slice(prev, c).join(""));
    prev = c;
  }
  out.push(scalars.slice(prev).join(""));
  return out;
}

test("streaming refines batch under random multi-chunk splits of corpus and mutated replies", () => {
  const rnd = mulberry32(7);
  let runs = 0;
  let successes = 0;
  for (const name of readdirSync(CASES).sort()) {
    const c = parseJson(readFileSync(join(CASES, name), "utf8")) as Record<string, any>;
    if (typeof c["response"] !== "string" || (c["requires"] ?? []).some((r: string) => r.startsWith("udf:"))) continue;
    const registry = new lmcc.Registry({ extensions: c["requires"] ?? [] });
    if ((c["vocab"] ?? []).includes("std")) install(registry);
    let plan: lmcc.Plan;
    try {
      plan = lmcc.load(c["entry"], { registry }).bind(lmcc.signatureFromDict(c["signature"]), c["capabilities"] ?? {}, { registry });
    } catch {
      continue;
    }
    for (let k = 0; k < 40; k++) {
      const text: string = k === 0 ? c["response"] : mutate(c["response"], rnd);
      runs++;
      let batch: ["ok", Record<string, unknown>, unknown[], Map<string, lmcc.Capture>] | ["refuse", unknown];
      try {
        const [values, captures, repairs] = plan.parseWithCaptures(text);
        batch = ["ok", values, repairs, captures];
      } catch (err) {
        if (!(err instanceof lmcc.Refusal)) throw err;
        batch = ["refuse", err.describe()];
      }
      const stream = plan.stream();
      const events: lmcc.StreamEvent[] = [];
      const where: string = `${name} ${JSON.stringify(text)}`;
      try {
        for (const piece of chunks(text, rnd)) events.push(...stream.feed(piece));
        const end = stream.finish();
        events.push(...end.events);
        assert.equal(batch[0], "ok", where);
        const [, values, repairs, captures] = batch as ["ok", Record<string, unknown>, unknown[], Map<string, lmcc.Capture>];
        assert.ok(jsonEqual(end.values, values), where);
        assert.ok(jsonEqual(end.repairs, repairs), where);
        const joined = new Map<string, string>(); // field names are data: __proto__ is one (case 216)
        for (const e of events) {
          if (e.kind === "field_delta") {
            assert.ok(e.text, where);
            joined.set(e.field, (joined.get(e.field) ?? "") + e.text);
          }
        }
        for (const [field, capture] of captures) assert.equal(joined.get(field) ?? "", capture.text, where);
        successes++;
      } catch (err) {
        if (!(err instanceof lmcc.Refusal)) throw err;
        assert.equal(batch[0], "refuse", where);
        assert.ok(jsonEqual(err.describe(), batch[1]), where);
      }
    }
  }
  assert.ok(runs > 1500 && successes > 500, `coverage: ${runs} runs, ${successes} successes`);
});

test("streaming cost is linear in the reply length", () => {
  const sig = lmcc.signature("Think.", { inputs: { q: lmcc.t.string() }, outputs: { reasoning: lmcc.t.string(), answer: lmcc.t.string() } });
  const plan = lmcc.adapter({ messages: [lmcc.system("{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}[[ ## completed ## ]]"), lmcc.user("{q}")] })
    .bind(sig, { instruct: true });
  const body = "lorem ipsum dolor sit amet ".repeat(8000);
  const cost = (n: number) => {
    const text = `[[ ## reasoning ## ]]\n${body.slice(0, n)}\n\n[[ ## answer ## ]]\nok\n\n[[ ## completed ## ]]`;
    const stream = plan.stream();
    const start = performance.now();
    for (let i = 0; i < text.length; i += 4) stream.feed(text.slice(i, i + 4));
    assert.equal(stream.finish().values.answer, "ok");
    return performance.now() - start;
  };
  cost(10_000);
  const small = cost(40_000);
  const large = cost(160_000);
  assert.ok(large < 12 * small + 50, `4x the reply cost ${large.toFixed(1)}ms vs ${small.toFixed(1)}ms`);
});

test("new Signature validates, fills defaults, and cannot change after it is made", () => {
  const sig = new lmcc.Signature("Answer.", [
    { name: "q", direction: "input", shape: { type: "string" } },
    { name: "a", direction: "output", shape: { type: "object", properties: { x: { type: "number" } } }, type: "Answer" },
  ]);
  assert.deepEqual(sig.fields[0], { name: "q", direction: "input", shape: { type: "string" }, type: null, purpose: "plain", desc: null });
  const before = lmcc.signatureFingerprint(sig);
  assert.equal(before, lmcc.signatureFingerprint(lmcc.signatureFromDict(lmcc.signatureToDict(sig))));
  assert.throws(() => { (sig.fields[1].shape["properties"] as Record<string, unknown>)["y"] = {}; });
  assert.equal(lmcc.signatureFingerprint(sig), before);
  const refused = (fn: () => unknown, field?: string) => assert.throws(fn, (e) => lmcc.isRefusal(e) && e.code === "signature-malformed"
    && JSON.stringify(e.fix) === JSON.stringify(field ? { action: "edit-signature", field } : { action: "edit-signature" }));
  refused(() => new lmcc.Signature(5 as unknown as string, []));
  refused(() => new lmcc.Signature("x", [{ name: "a b", direction: "input", shape: {} }]), "a b");
  refused(() => new lmcc.Signature("x", [{ name: "a", direction: "sideways" as "input", shape: {} }]), "a");
  refused(() => new lmcc.Signature("x", [{ name: "a", direction: "input", shape: {} }, { name: "a", direction: "output", shape: {} }]), "a");
});

test("withMeta and withScore return new turns and refuse what has no JSON form", () => {
  const sig = lmcc.signature("A.", { inputs: { q: lmcc.t.string() }, outputs: { a: lmcc.t.string() } });
  const plan = lmcc.adapter({ messages: [lmcc.system("<a>{a}</a>"), lmcc.user("{q}")] }).bind(sig);
  const turn = plan.example({ q: "x" }, { a: "y" });
  const noted = turn.withMeta({ ...turn.meta, source: "rating" }).withScore(0.5);
  assert.deepEqual(turn.meta, {});
  assert.equal(turn.score, null);
  assert.deepEqual(noted.toJSON().meta, { source: "rating" });
  assert.equal(noted.toJSON().score, 0.5);
  assert.equal(noted.withScore(null).toJSON().score, undefined);
  const invalid = (fn: () => unknown) => assert.throws(fn, (e) => lmcc.isRefusal(e) && e.code === "turn-invalid");
  invalid(() => turn.withMeta({ when: () => 1 }));
  invalid(() => turn.withMeta([] as unknown as Record<string, unknown>));
  invalid(() => turn.withScore(Number.NaN));
});

test("the hashing and value helpers are the ones fingerprints use", () => {
  assert.equal(lmcc.sha256({ b: 1.0, a: "é" }), "sha256:" + lmcc.sha256Hex('{"a":"é","b":1}'));
  const own = { a: [1, { toJSON: () => "x" }], b: undefined };
  assert.deepEqual(lmcc.toJson(own), { a: [1, "x"] });
  assert.equal(jsonText(own), '{"a":[1,"x"]}');
  assert.equal(dumps(own, null), '{"a": [1, "x"]}');
  assert.deepEqual(lower(own), { a: [1, "x"], b: undefined });
  assert.deepEqual(lmcc.nullableBase({ anyOf: [{ type: "integer" }, { type: "null" }] }), [{ type: "integer" }, true]);
});

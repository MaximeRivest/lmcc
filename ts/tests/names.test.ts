/**
 * Names are data (corpus 214–222): field names, JSON members, slot names and
 * artifact keys that `Object.prototype` has (`__proto__`, `toString`,
 * `constructor`, `valueOf`, …) are ordinary names. The corpus drives turns
 * through their JSON; these tests hold the paths it does not reach: values
 * given as objects (`plan.render`, `plan.turn`, `plan.example`), the JSON
 * helpers, a refusal's partial, a table format, and the lm15 bridge.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { Config, Request } from "@lm15/lm15";
import * as lmcc from "../src/index.ts";
import { install } from "../src/std/index.ts";
import { request as lm15Request } from "../src/lm15.ts";
import { lower } from "../src/std/formats.ts";

/** An object with exactly these own members, as `JSON.parse` makes it (a literal `__proto__:` would set the prototype). */
const own = (json: string): Record<string, unknown> => JSON.parse(json) as Record<string, unknown>;

const SECTIONS = [
  { role: "system", text: "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}" },
  { directive: "turns" },
  { role: "user", text: "{% for f in inputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}" },
];

function registry(): lmcc.Registry {
  const reg = new lmcc.Registry();
  install(reg);
  return reg;
}

function planOf(fields: string, entry: Record<string, unknown> = {}, reg = registry()): lmcc.Plan {
  const adapter = lmcc.load({ name: "names", versions: { kernel: "0.8.0", vocab: {} }, template: SECTIONS, reader: { kind: "derived" }, ...entry }, { registry: reg });
  return adapter.bind(lmcc.signatureFromDict(own(`{"instructions": "Do it.", "fields": ${fields}}`)), { native_structured_output: true }, { registry: reg });
}

const texts = (request: Record<string, unknown>): string[] =>
  (request["messages"] as { parts: { text?: string }[] }[]).map((m) => m.parts.map((p) => p.text ?? "").join(""));

const S = '{"type": "string"}';

test("an input named __proto__, given as an object, is sent (render, turn, example)", () => {
  const plan = planOf(`[{"name": "__proto__", "direction": "input", "shape": ${S}}, {"name": "json", "direction": "input", "shape": {}},
    {"name": "r", "direction": "output", "shape": ${S}}]`, { formats: { "*": { use: "json" } } });
  const inputs = own('{"__proto__": "P", "json": 5}');
  assert.deepEqual(texts(plan.render(inputs).request()), ["<__proto__>\nP\n</__proto__>\n<json>\n5\n</json>\n"]);
  const turn = plan.turn(inputs);
  assert.ok(Object.hasOwn(turn.inputs, "__proto__"));
  assert.equal(Object.getPrototypeOf(turn.inputs), Object.prototype);
  assert.deepEqual(turn.toJSON().inputs, inputs);
  const example = plan.example(own('{"__proto__": "p", "json": 1}'), { r: "x" });
  assert.deepEqual(texts(plan.render(inputs, { turns: [example] }).request()),
    ["<__proto__>\np\n</__proto__>\n<json>\n1\n</json>\n", "<r>\nx\n</r>", "<__proto__>\nP\n</__proto__>\n<json>\n5\n</json>\n"]);
});

test("a partial example lacks what it lacks, even a toString input or a valueOf output", () => {
  const plan = planOf(`[{"name": "toString", "direction": "input", "shape": ${S}}, {"name": "q", "direction": "input", "shape": ${S}},
    {"name": "valueOf", "direction": "output", "shape": ${S}}, {"name": "r", "direction": "output", "shape": ${S}}]`);
  const example = plan.example({ q: "x" }, { r: "EXAMPLE" });
  assert.deepEqual(texts(plan.render({ toString: "T", q: "Q" }, { turns: [example] }).request()),
    ["<q>\nx\n</q>\n", "<r>\nEXAMPLE\n</r>", "<toString>\nT\n</toString>\n<q>\nQ\n</q>\n"]);
  assert.throws(() => plan.render({ q: "Q" }), (e: lmcc.Refusal) => e.code === "missing-input" && e.hint.includes("'toString'"));
});

test("JSON members named __proto__ are data in every writer, and never reach a prototype", () => {
  const value = own('{"__proto__": {"admin": true}, "constructor": {"toString": 1}}');
  assert.deepEqual(lmcc.toJson(value), value);
  assert.ok(Object.hasOwn(lmcc.toJson(value) as object, "__proto__"));
  assert.deepEqual(lower(value), value);
  assert.equal(lmcc.jsonText(value), '{"__proto__":{"admin":true},"constructor":{"toString":1}}');
  const plan = planOf(`[{"name": "q", "direction": "input", "shape": ${S}}, {"name": "__proto__", "direction": "output", "shape": {"type": "object"}}]`,
    { formats: { object: { use: "json" } } });
  const values = plan.parse('<__proto__>\n{"__proto__": {"admin": true}}\n</__proto__>');
  assert.equal(Object.getPrototypeOf(values), Object.prototype);
  assert.deepEqual(values, own('{"__proto__": {"__proto__": {"admin": true}}}'));
  assert.equal(({} as Record<string, unknown>)["admin"], undefined);
  const step = plan.render({ q: "x" }).step('<__proto__>\n{"__proto__": 1}\n</__proto__>');
  assert.deepEqual(step.toJSON().steps[0], { kind: "model", outputs: own('{"__proto__": {"__proto__": 1}}'),
    message: { role: "assistant", parts: [{ type: "text", text: '<__proto__>\n{"__proto__": 1}\n</__proto__>' }] },
    request: step.steps[0].kind === "model" ? step.steps[0].request! : "" });
});

test("a refusal's partial keeps outputs named like Object members", () => {
  const plan = planOf(`[{"name": "q", "direction": "input", "shape": ${S}}, {"name": "__proto__", "direction": "output", "shape": ${S}},
    {"name": "toString", "direction": "output", "shape": ${S}}]`);
  assert.throws(() => plan.parse("<__proto__>\nA\n</__proto__>"), (e: lmcc.Refusal) =>
    e.code === "parse-missing-fields" && Object.hasOwn(e.partial!, "__proto__") && !Object.hasOwn(e.partial!, "toString")
    && lmcc.jsonEqual(e.describe().partial, own('{"__proto__": "A"}')));
});

test("a hidden output named __proto__ is described by name", () => {
  const plan = planOf(`[{"name": "q", "direction": "input", "shape": ${S}}, {"name": "__proto__", "direction": "output", "shape": ${S}, "purpose": "reasoning"},
    {"name": "r", "direction": "output", "shape": ${S}}]`,
  { transports: { reasoning: { in_template: false, find: [{ from: "text", between: ["<think>", "</think>"], to: "@purpose", remove: true }] } } });
  const writers = (plan.describe()["turns"] as Record<string, Record<string, unknown>>)["writers"];
  assert.deepEqual(writers, own('{"__proto__": {"by": "derived:between", "between": ["<think>", "</think>"], "position": "after"}}'));
  assert.deepEqual(plan.parse("<think>hm</think><r>\nA\n</r>"), own('{"r": "A", "__proto__": "hm"}'));
});

test("a table's columns may be named like Object members", () => {
  const reg = registry();
  const fmt = reg.namedFormat("table", { columns: ["__proto__", "toString"] });
  const field = { name: "rows", direction: "output" as const, shape: { type: "array", items: { type: "object" } }, type: null, purpose: "plain", desc: null };
  assert.equal(fmt.write([own('{"__proto__": "a"}')], field), "| a |  |");
  const rows = fmt.read!(lmcc.Capture.ofText("| a | b |"), field) as Record<string, unknown>[];
  assert.deepEqual(rows, [own('{"__proto__": "a", "toString": "b"}')]);
});

test("the lm15 bridge merges a caller's schema holding __proto__ without losing it", () => {
  const reg = registry();
  const adapter = lmcc.load({ name: "j", versions: { kernel: "0.8.0", vocab: {} }, template: [{ role: "system", text: "{instruction}" }, { role: "user", text: "{q}" }],
    reader: { kind: "json_object" } }, { registry: reg });
  const sig = lmcc.signatureFromDict(own(`{"instructions": "x", "fields": [{"name": "q", "direction": "input", "shape": ${S}},
    {"name": "__proto__", "direction": "output", "shape": ${S}}, {"name": "toString", "direction": "output", "shape": ${S}}]}`));
  const rendered = adapter.bind(sig, { native_structured_output: true }, { registry: reg }).render({ q: "hi" });
  const settings = rendered.request()["config"] as Record<string, unknown>;
  const config = Config.fromJSON(JSON.parse(JSON.stringify({ temperature: 0.5, response_format: settings["response_format"] })));
  const sent = Request.toJSON(lm15Request(rendered, { model: "m", config })) as { config: { response_format: unknown } };
  assert.deepEqual(sent.config.response_format, settings["response_format"]);
  assert.deepEqual(Object.keys((sent.config.response_format as { schema: { properties: object } }).schema.properties), ["__proto__", "toString"]);
});

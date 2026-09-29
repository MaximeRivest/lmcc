/**
 * Members keep their order (kernel §1, corpus 226–230, 234, 235). A JavaScript object
 * enumerates integer-like names ("1", "10") first; lmcc carries the order a
 * value holds on the objects it builds and writes by it. The corpus drives
 * values through the driver's parse; these tests hold the paths it does not
 * reach: a value read from a reply and written back, `orderedObject`,
 * copies, a member added later, and what the recorded order is not (it is
 * invisible to JavaScript's own operations and never copied by them).
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import * as lmcc from "../src/index.ts";
import { install } from "../src/std/index.ts";
import { closed } from "../src/std/readers.ts";

function registry(): lmcc.Registry {
  const reg = new lmcc.Registry();
  install(reg);
  return reg;
}

const OBJECT = { type: "object" };

function jsonPlan(): lmcc.Plan {
  const reg = registry();
  const adapter = lmcc.load({
    name: "order", versions: { kernel: "0.8.4", vocab: {} },
    template: [{ role: "system", text: "{instruction}\n<o>{o}</o>" }, { directive: "turns" }, { role: "user", text: "{q}" }],
    reader: { kind: "derived" }, formats: { object: { use: "json", options: { indent: null } } },
  }, { registry: reg });
  return adapter.bind(lmcc.signatureFromDict({ instructions: "Do.", fields: [
    { name: "q", direction: "input", shape: { type: "string" } },
    { name: "o", direction: "output", shape: OBJECT }] }), {}, { registry: reg });
}

const assistantText = (request: Record<string, unknown>): string =>
  ((request["messages"] as { role: string; parts: { text: string }[] }[]).find((m) => m.role === "assistant")!).parts[0].text;

test("a value read from a reply is written back in the order it was read", () => {
  const plan = jsonPlan();
  const reading = plan.read('<o>{"b": 1, "10": 2, "a": {"z": 0, "1": 1}, "2": 4}</o>');
  const o = reading.values["o"] as Record<string, unknown>;
  assert.deepEqual(Object.keys(o), ["2", "10", "b", "a"]); // JavaScript's own order, unchanged
  assert.deepEqual(lmcc.memberNames(o), ["b", "10", "a", "2"]);
  const example = plan.example({ q: "x" }, reading.values);
  assert.equal(assistantText(plan.render({ q: "y" }, { turns: [example] }).request()),
    '<o>{"b": 1, "10": 2, "a": {"z": 0, "1": 1}, "2": 4}</o>');
  // Through a turn's JSON, read back with lmcc's parser (JSON.parse would reorder).
  const again = lmcc.Turn.fromJSON(lmcc.parseJson(lmcc.jsonText(example.toJSON())) as unknown as lmcc.TurnJSON);
  assert.equal(assistantText(plan.render({ q: "y" }, { turns: [again] }).request()),
    '<o>{"b": 1, "10": 2, "a": {"z": 0, "1": 1}, "2": 4}</o>');
});

test("orderedObject builds a value in a given order; a literal keeps JavaScript's", () => {
  const plan = jsonPlan();
  const ordered = lmcc.orderedObject([["b", 1], ["10", 2], ["", 3], ["b", 4]]);
  assert.deepEqual(lmcc.memberNames(ordered), ["b", "10", ""]);
  assert.equal(ordered["b"], 4); // a name twice: first place, last value
  assert.equal(assistantText(plan.render({ q: "y" }, { turns: [plan.example({ q: "x" }, { o: ordered })] }).request()),
    '<o>{"b": 4, "10": 2, "": 3}</o>');
  assert.equal(assistantText(plan.render({ q: "y" }, { turns: [plan.example({ q: "x" }, { o: { b: 1, 10: 2 } })] }).request()),
    '<o>{"10": 2, "b": 1}</o>');
  assert.equal(lmcc.jsonText(lmcc.orderedObject([["__proto__", 1], ["0", 2]])), '{"__proto__":1,"0":2}');
});

test("the order is invisible to JavaScript and never copied by it; lmcc's copies keep it", () => {
  const value = lmcc.parseJson('{"b": 1, "10": {"y": 0, "3": 3}}') as Record<string, unknown>;
  assert.deepEqual(Object.keys(value), ["10", "b"]);
  assert.deepEqual(Reflect.ownKeys(value).filter((k) => typeof k === "string"), ["10", "b"]);
  assert.equal(JSON.stringify(value), '{"10":{"3":3,"y":0},"b":1}');
  assert.deepStrictEqual(value, { b: 1, 10: { y: 0, 3: 3 } });
  assert.deepEqual(lmcc.memberNames({ ...value }), ["10", "b"]);
  assert.deepEqual(lmcc.memberNames(structuredClone(value)), ["10", "b"]);
  assert.equal(lmcc.jsonText(lmcc.toJson(value)), '{"b":1,"10":{"y":0,"3":3}}');
  assert.equal(lmcc.canonicalJson(value), '{"10":{"3":3,"y":0},"b":1}'); // canonical JSON orders by code point
  // Nothing is recorded where JavaScript's order is the value's.
  const plain = lmcc.parseJson('{"a": 1, "b": {"c": 2}}') as object;
  assert.deepEqual(Object.getOwnPropertySymbols(plain), []);
});

test("setMember adds a name last, keeps a replaced one in place, and puts one set again last", () => {
  const v = lmcc.parseJson('{"b": 1, "10": 2}') as Record<string, unknown>;
  lmcc.setMember(v, "5", 5);
  lmcc.setMember(v, "2", 2);
  assert.equal(lmcc.jsonText(v), '{"b":1,"10":2,"5":5,"2":2}');
  // The first integer-like name added to an object that recorded nothing.
  const plain = lmcc.parseJson('{"b": 1}') as Record<string, unknown>;
  lmcc.setMember(plain, "10", 2);
  assert.equal(lmcc.jsonText(plain), '{"b":1,"10":2}');
  // A literal holds JavaScript's order; setMember keeps it and appends.
  const literal: Record<string, unknown> = { 3: "c", 1: "a" };
  lmcc.setMember(literal, "x", 0);
  lmcc.setMember(literal, "0", 0);
  assert.deepEqual(lmcc.memberNames(literal), ["1", "3", "x", "0"]);
  // Replacing keeps the place; removing and setting again puts it last (a Python dict does both).
  lmcc.setMember(v, "10", 20);
  delete v["b"];
  lmcc.setMember(v, "b", 1);
  assert.equal(lmcc.jsonText(v), '{"10":20,"5":5,"2":2,"b":1}');
  // Plain assignment is JavaScript's: its names follow the recorded ones, in JavaScript's order.
  v["7"] = 7;
  v["6"] = 6;
  assert.deepEqual(lmcc.memberNames(v), ["10", "5", "2", "b", "6", "7"]);
  // copyObject is a spread that keeps the order, with later members set in turn.
  assert.equal(lmcc.jsonText(lmcc.copyObject(lmcc.parseJson('{"b": 1, "10": 2}') as object, { "3": 3, b: 0 })), '{"b":0,"10":2,"3":3}');
});

function tablePlan(format: Record<string, unknown>): [lmcc.Plan, lmcc.Registry] {
  const reg = registry();
  const columns = ["b", "10", "", "2"];
  const adapter = lmcc.load({
    name: "rows", versions: { kernel: "0.8.4", vocab: {} },
    template: [{ role: "system", text: "{instruction}\n<o>{o}</o>" }, { directive: "turns" }, { role: "user", text: "{q}" }],
    reader: { kind: "derived" }, formats: { "list[object]": format },
  }, { registry: reg });
  const sig = lmcc.signatureFromDict({ instructions: "Do.", fields: [
    { name: "q", direction: "input", shape: { type: "string" } },
    { name: "o", direction: "output", shape: { type: "array", items: { type: "object", properties: lmcc.orderedObject(columns.map((k) => [k, { type: "string" }])) } } }] });
  return [adapter.bind(sig, {}, { registry: reg }), reg];
}

test("a table row is read in column order, and written in it again by another format", () => {
  const [table] = tablePlan({ use: "table", options: { columns: ["b", "10", "", "2"] } });
  const values = table.parse("<o>| B | TEN | EMPTY | TWO |</o>");
  const row = (values["o"] as Record<string, unknown>[])[0];
  assert.deepEqual(lmcc.memberNames(row), ["b", "10", "", "2"]);
  const [json] = tablePlan({ use: "json", options: { indent: null } });
  assert.equal(assistantText(json.render({ q: "x" }, { turns: [json.example({ q: "prev" }, values)] }).request()),
    '<o>[{"b": "B", "10": "TEN", "": "EMPTY", "2": "TWO"}]</o>');
});

test("probabilities and measured_by keep the reply's order, under any name", () => {
  const plan = jsonPlan();
  const reply = lmcc.parseJson('{"role": "assistant", "parts": [{"type": "text", "text": "<o>{}</o>"}, {"type": "data", "value": 1, "probabilities": {"o": {"b": 0.2, "10": 0.7, "": 0.1}, "": {"x": 1}}, "method": "m"}]}');
  const reading = plan.read(reply);
  assert.equal(lmcc.jsonText(reading.probabilities), '{"o":{"b":0.2,"10":0.7,"":0.1},"":{"x":1}}');
  assert.equal(lmcc.jsonText(reading.measuredBy), '{"o":"m","":"m"}');
});

test("an artifact is dumped with its format keys and options in the order it was loaded", () => {
  const reg = registry();
  const entry = lmcc.parseJson(`{"name": "keys", "versions": {"kernel": "0.8.4", "vocab": {}},
    "template": [{"role": "system", "text": "{instruction}"}], "reader": {"kind": "derived"},
    "formats": {"": {"use": "json"}, "10": {"use": "json", "options": {"indent": null}}, "b": {"describe": "B"}, "2": {"use": "table", "options": {"columns": ["z", "1"]}}}}`) as Record<string, unknown>;
  const dumped = lmcc.dump(lmcc.load(entry, { registry: reg }), reg);
  assert.deepEqual(lmcc.memberNames(dumped["formats"] as object), ["", "10", "b", "2"]);
  assert.equal(lmcc.jsonText(lmcc.dump(lmcc.adapter({ template: [{ role: "system", text: "{instruction}" }], formats: lmcc.orderedObject([["b", "json"], ["1", "json"]]) }), reg)["formats"]),
    '{"b":{"use":"json"},"1":{"use":"json"}}');
});

test("a shape's properties keep their order: signature, schema, required, description", () => {
  const shape = lmcc.parseJson('{"type": "object", "properties": {"b": {"type": "string"}, "1": {"type": "string"}, "": {"type": "integer"}}}') as Record<string, unknown>;
  const sig = new lmcc.Signature("Do.", [{ name: "o", direction: "output", shape: shape as lmcc.Shape }]);
  const kept = sig.fields[0].shape;
  assert.ok(Object.isFrozen(kept) && Object.isFrozen(kept["properties"]));
  assert.deepEqual(lmcc.memberNames(kept["properties"] as object), ["b", "1", ""]);
  assert.deepEqual((closed(kept) as { required: string[] }).required, ["b", "1", ""]);
  assert.equal(lmcc.jsonText(lmcc.signatureToDict(lmcc.signatureFromDict(lmcc.signatureToDict(sig)))),
    '{"instructions":"Do.","fields":[{"name":"o","direction":"output","shape":{"type":"object","properties":{"b":{"type":"string"},"1":{"type":"string"},"":{"type":"integer"}}}}]}');
  const object = lmcc.t.object(lmcc.orderedObject([["b", lmcc.t.string()], ["1", lmcc.t.string()]]));
  assert.deepEqual(object["required"], ["b", "1"]);
});

test("a nullable shape's base puts its type last, as every kernel does", () => {
  const [base, nullable] = lmcc.nullableBase({ type: ["string", "null"], description: "d" } as lmcc.Shape);
  assert.equal(nullable, true);
  assert.equal(lmcc.jsonText(base), '{"description":"d","type":"string"}');
});

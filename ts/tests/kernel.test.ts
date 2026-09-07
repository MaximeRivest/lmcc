import { test } from "node:test";
import assert from "node:assert/strict";
import { Refusal } from "../lmcc/refusal.ts";
import { parseTemplateText } from "../lmcc/template.ts";
import { Registry } from "../lmcc/registry.ts";
import { load, dump, udfHash, versionCompatible } from "../lmcc/serde.ts";
import { signatureFromData } from "../lmcc/signature.ts";
import { bind } from "../lmcc/plan.ts";
import { install } from "../lmccstd/index.ts";

const XML = {
  name: "t",
  versions: { kernel: "0.2.0", vocab: {} },
  template: [
    { role: "system", text: "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}" },
    { directive: "demos" },
    { role: "user", text: "{q}" },
  ],
  parse: { kind: "derived" },
};

const SIG = {
  instructions: "Answer.",
  fields: [
    { name: "q", direction: "input", shape: { type: "string" } },
    { name: "answer", direction: "output", shape: { type: "string" } },
    { name: "score", direction: "output", shape: { type: "integer" } },
  ],
};

function refusal(fn: () => unknown): Refusal {
  try {
    fn();
  } catch (e) {
    if (e instanceof Refusal) return e;
    throw e;
  }
  throw new Error("expected a refusal");
}

test("template: three constructs, escapes, syntax refusals", () => {
  const nodes = parseTemplateText("a {{b}} {c} {% for f in inputs %}{f.name}{% endfor %}", "template[0]");
  assert.deepEqual(nodes[0], { kind: "text", text: "a {b} " });
  assert.deepEqual(nodes[1], { kind: "slot", name: "c" });
  assert.equal(nodes[3].kind, "loop");
  assert.equal(refusal(() => parseTemplateText("{q", "template[1]")).code, "template-syntax");
  assert.equal(refusal(() => parseTemplateText("a } b", "template[1]")).code, "template-syntax");
  assert.equal(refusal(() => parseTemplateText("{% for f in things %}{% endfor %}", "template[1]")).code, "template-syntax");
  assert.equal(refusal(() => parseTemplateText("{% for f in inputs %}", "template[1]")).code, "template-syntax");
});

test("versions: minor is breaking while major is 0", () => {
  assert.ok(versionCompatible("0.2.0", "0.2.5"));
  assert.ok(!versionCompatible("0.1.0", "0.2.0"));
  assert.ok(!versionCompatible("9.0.0", "0.2.0"));
  assert.ok(versionCompatible("1.1.0", "1.3.0"));
  assert.ok(!versionCompatible("1.4.0", "1.3.0"));
});

test("udf hash covers write, read, describe as name\\0source\\0", () => {
  assert.equal(udfHash({ write: "def write(p, f):\n    return HELPER(p)" }), "8d68ac2f639deb671d61c8762f0111d381188bcf713b369a092a01744e475018");
});

test("dump echoes the loaded artifact", () => {
  const reg = new Registry();
  const adapter = load(XML, { registry: reg });
  assert.deepEqual(dump(adapter, reg), XML);
});

test("render: bare pattern join keeps the line literals; loop join omits absent fields", () => {
  const bare = {
    ...XML,
    template: [{ role: "system", text: '{instruction}\n{{"answer": "{answer}", "score": {score}}}' }, { directive: "demos" }, { role: "user", text: "{q}" }],
  };
  const plan = bind(load(bare), signatureFromData(SIG), {});
  const r = plan.render({ q: "x" }, [{ q: "d", answer: "A", score: 3 }]);
  assert.equal(r.messages[2].content[0].text, '{"answer": "A", "score": 3}');
  assert.deepEqual(plan.skeleton(), { prefill: '{"answer": "', stops: ["}"] });
  const loop = bind(load(XML), signatureFromData(SIG), {});
  const r2 = loop.render({ q: "x" }, [{ q: "d", score: 3 }]);
  assert.equal(r2.messages[2].content[0].text, "<score>\n3\n</score>");
});

test("refusals: unknown slot, not lensable, value collides, missing input", () => {
  const bad = { ...XML, template: [{ role: "system", text: "{nope}" }, { role: "user", text: "{q}" }] };
  const r = refusal(() => bind(load(bad), signatureFromData(SIG), {}));
  assert.equal(r.code, "unknown-slot");
  assert.deepEqual(r.fix, { action: "edit-template", path: "template[0]", slot: "nope" });
  const plan = bind(load(XML), signatureFromData(SIG), {});
  assert.equal(refusal(() => plan.render({ q: "x" }, [{ q: "d", answer: "</answer>", score: 1 }])).code, "value-collides");
  assert.equal(refusal(() => plan.render({})).code, "missing-input");
  assert.equal(refusal(() => plan.parse("<answer>\nA\n</answer>\n<answer>\nB\n</answer>")).code, "parse-ambiguous");
  const missing = refusal(() => plan.parse("<answer>\nA\n</answer>"));
  assert.equal(missing.code, "parse-missing-fields");
  assert.deepEqual(missing.partial, { answer: "A" });
});

test("std: json format fence unwrapping and strictness, table escaping, scaled_number rounding", () => {
  const reg = new Registry();
  install(reg);
  const json = reg.format("json", {});
  const field = { name: "x", direction: "output" as const, shape: { type: "array" }, role: "plain" };
  const ctx = { formatFor: () => json };
  assert.deepEqual(json.read({ parts: [], text: '```json\n["a", "b"]\n```' }, field, ctx), ["a", "b"]);
  assert.throws(() => json.read({ parts: [], text: "[1,]" }, field, ctx));
  const table = reg.format("table", { columns: ["name", "score"] });
  assert.equal(table.write([{ name: "a|b\\c", score: 3 }], field, ctx), "| a\\|b\\\\c | 3 |");
  const rows = table.read({ parts: [], text: "| name | score |\n| a\\|b | 9 |\n|  | 1 |" }, { ...field, shape: { type: "array", items: { type: "object", properties: { score: { type: "integer" } } } } }, ctx);
  assert.deepEqual(rows, [{ name: "a|b", score: 9 }, { name: null, score: 1 }]);
  assert.throws(() => table.read({ parts: [], text: "| a | x |" }, { ...field, shape: { type: "array", items: { type: "object", properties: { score: { type: "integer" } } } } }, ctx));
  const scaled = reg.format("scaled_number", { scale: 100, suffix: "%", round: 0 });
  assert.equal(scaled.write(0.835, field, ctx), "84%");
  assert.equal(scaled.write(0.825, field, ctx), "82%");
  assert.equal(scaled.read({ parts: [], text: " 83% " }, field, ctx), 0.83);
});

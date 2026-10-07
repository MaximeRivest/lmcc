/**
 * A type's JSON form, both ways (kernel §3a: a turn holds JSON; a host lifts
 * it back to its own types): `registry.format(type, {toJson, fromJson})`,
 * `plan.dumpTurn`, `plan.loadTurn`. The rule under test, the same in every
 * kernel (D-61, D-62): the format bound to a type receives the value itself,
 * live or replayed; every other format receives its JSON form. And lm15's
 * media parts through `lmcc/lm15` (issue #3).
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import * as lm15 from "@lm15/lm15";
import * as lmcc from "../src/index.ts";
import { install as installStd } from "../src/std/index.ts";
import { install as installLm15, media, request as lm15Request } from "../src/lm15.ts";

const TAGS = lmcc.adapter({
  messages: [
    lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.turns(),
    lmcc.user("{% for f in inputs %}{f.value}\n{% endfor %}"),
  ],
});

/** A converter's result: pages of text and raw bytes, which have no JSON form. */
class Pages {
  readonly pages: { text: string; png: Uint8Array }[];
  constructor(pages: { text: string; png: Uint8Array }[]) {
    this.pages = pages;
  }
}
const hex = (b: Uint8Array) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
const unhex = (s: string) => new Uint8Array(s.match(/../g)!.map((x) => parseInt(x, 16)));
const pagesToJson = (p: Pages) => p.pages.map((x) => ({ text: x.text, png: hex(x.png) }));
const pagesFromJson = (d: { text: string; png: string }[]) => new Pages(d.map((x) => ({ text: x.text, png: unhex(x.png) })));
const DOC = new Pages([{ text: "page 1", png: new Uint8Array([0x89, 0x50, 0x4e, 0x47]) }]);

function summary() {
  return lmcc.signature("Summarize.", { inputs: { document: lmcc.field(lmcc.t.json(), { type: "Pages" }) }, outputs: { summary: lmcc.t.string() } });
}

test("a bound type is written, saved, loaded and written again the same", () => {
  const seen: unknown[] = [];
  const reg = new lmcc.Registry();
  reg.format("Pages", {
    write: (v: Pages) => { seen.push(v); return v.pages.map((p) => p.text).join("\n"); },
    toJson: pagesToJson, fromJson: pagesFromJson,
  });
  const plan = lmcc.bind(TAGS, summary(), { instruct: true }, reg);
  const live = plan.render({ document: DOC });
  const turn = live.step("<summary>\nOne page.\n</summary>").finish();
  const saved = JSON.parse(JSON.stringify(plan.dumpTurn(turn)));
  assert.deepEqual(saved.inputs, { document: [{ text: "page 1", png: "89504e47" }] });
  const back = plan.loadTurn(saved);
  assert.ok(back.inputs["document"] instanceof Pages);
  assert.deepEqual(plan.render({ document: DOC } as never, { turns: [turn] }).request("m"),
    plan.render({ document: DOC } as never, { turns: [back] }).request("m"));
  assert.ok(seen.length > 0 && seen.every((v) => v instanceof Pages));
});

test("every other format receives the JSON form", () => {
  const reg = new lmcc.Registry();
  installStd(reg);
  reg.format("Pages", { shape: { type: "array" }, toJson: pagesToJson, fromJson: pagesFromJson });
  const a = lmcc.adapter({ messages: TAGS.template, formats: { "list[*]": { use: "json", options: { indent: null } } } } as never);
  const sig = lmcc.signature("Summarize.", { inputs: { document: lmcc.field(lmcc.t.json({ type: "array" }), { type: "Pages" }) }, outputs: { summary: lmcc.t.string() } });
  const plan = lmcc.bind(a, sig, { instruct: true }, reg);
  assert.equal(plan.describe()["inputs"] instanceof Array && (plan.describe()["inputs"] as any)[0]["resolved_by"], "artifact:list[*]");
  const text = (plan.render({ document: DOC }).request("m") as any).messages[0].parts[0].text;
  assert.match(text, /"png": "89504e47"/);
});

test("binding a type again replaces it; a binding needs something", () => {
  const reg = new lmcc.Registry();
  reg.format("Pages", { write: () => "one" });
  reg.format("Pages", { write: () => "two", toJson: pagesToJson });
  assert.equal(reg.typeBindings.length, 1);
  assert.deepEqual(reg.describe()["type_bindings"], [{ type: "Pages", format: "(inline)", shape: {}, json: ["to_json"] }]);
  assert.throws(() => reg.format("Pages", {} as never), (e: lmcc.Refusal) => e.code === "entry-malformed");
  assert.throws(() => reg.format("Pages", { read: () => 1, shape: {} } as never), (e: lmcc.Refusal) => e.code === "entry-malformed");
  assert.throws(() => reg.format("Pages", { write: () => "", toJson: "no" } as never),
    (e: lmcc.Refusal) => e.code === "entry-malformed" && JSON.stringify(e.fix) === JSON.stringify({ action: "edit-entry", path: "toJson" }));
  assert.equal(reg.format("Pages", { shape: { media: "image" } }), null);
});

test("failures name the value", () => {
  const broken = () => { throw new Error("boom"); };
  const reg = new lmcc.Registry();
  reg.format("Pages", { shape: { media: "image" }, toJson: broken, fromJson: broken });
  const sig = lmcc.signature("Summarize.", { inputs: { document: lmcc.field(lmcc.t.media("image"), { type: "Pages" }) }, outputs: { summary: lmcc.t.string() } });
  const plan = lmcc.bind(TAGS, sig, { instruct: true }, reg);
  assert.throws(() => plan.render({ document: DOC } as never), (e: lmcc.Refusal) => e.code === "format-write-error" && e.hint.includes("boom"));
  const turn = plan.example({ document: { media_type: "image/png", data: "AA==" } } as never, { summary: "s" } as never);
  assert.throws(() => plan.dumpTurn(turn), (e: lmcc.Refusal) => e.code === "turn-invalid" && e.hint.includes("Pages's toJson failed"));
  assert.throws(() => plan.loadTurn(turn.toJSON()), (e: lmcc.Refusal) => e.code === "turn-invalid" && e.hint.includes("turn.inputs.document"));
});

// ------------------------------------------------------------ lm15 media parts

const PICTURE = lm15.image({ data: "iVBORw0KGgo=", mediaType: "image/png" });

function colour(reg = lmcc.defaultRegistry) {
  const sig = lmcc.signature("The main colour.", { inputs: { picture: media.image() }, outputs: { colour: lmcc.t.string() } });
  return lmcc.bind(TAGS, sig, { instruct: true }, reg);
}

test("an lm15 part is written as lm15's canonical part data, never mediaType", () => {
  const plan = colour();
  assert.equal((plan.describe()["inputs"] as any)[0]["resolved_by"], "kernel");
  const rendered = plan.render({ picture: PICTURE });
  assert.deepEqual((rendered.request("m") as any).messages[0].parts[0], { type: "image", media_type: "image/png", data: "iVBORw0KGgo=" });
  assert.equal(lm15Request(rendered, { model: "m" }).messages[0]!.parts[0]!.type, "image");
  assert.deepEqual((plan.render({ picture: { media_type: "image/png", data: "AA==" } as never }).request("m") as any).messages[0].parts[0],
    { type: "image", media_type: "image/png", data: "AA==" }); // part data still works
  assert.deepEqual((plan.render({ picture: lm15.image({ path: "cat.png" }) }).request("m") as any).messages[0].parts[0],
    { type: "image", media_type: "image/png", path: "cat.png" }); // lm15 reads the file, lmcc never does
  assert.throws(() => plan.render({ picture: lm15.audio({ data: "AAAA", mediaType: "audio/wav" }) as never }),
    (e: lmcc.Refusal) => e.code === "value-invalid" && e.hint.includes("'audio'"));
});

test("a media field without lm15's type refuses an lm15-ts part before the wire, naming mediaType (kernel §7b)", () => {
  const sig = lmcc.signature("The main colour.", { inputs: { picture: lmcc.t.media("image") }, outputs: { colour: lmcc.t.string() } });
  const plan = lmcc.bind(TAGS, sig, { instruct: true }, new lmcc.Registry());
  assert.throws(() => plan.render({ picture: PICTURE as never }), (e: lmcc.Refusal) => e.code === "value-invalid" && e.hint.includes("'mediaType'"));
});

test("an lm15 part is saved as its part data and rebuilt by loadTurn", () => {
  const plan = colour();
  const turn = plan.render({ picture: PICTURE }).step("<colour>\nred\n</colour>").finish();
  const saved = JSON.parse(JSON.stringify(plan.dumpTurn(turn)));
  assert.deepEqual(saved.inputs, { picture: { type: "image", media_type: "image/png", data: "iVBORw0KGgo=" } });
  const back = plan.loadTurn(saved);
  assert.deepEqual(back.inputs["picture"], PICTURE);
  assert.deepEqual(plan.render({ picture: PICTURE } as never, { turns: [turn] }).request("m"),
    plan.render({ picture: PICTURE } as never, { turns: [back] }).request("m"));
  saved.inputs.picture.type = "audio";
  assert.throws(() => plan.loadTurn(saved), (e: lmcc.Refusal) => e.code === "turn-invalid");
});

test("install binds the five part types in another registry", () => {
  const reg = installLm15(new lmcc.Registry());
  assert.deepEqual(reg.typeBindings.map((b) => [b.type, b.shape]),
    [["ImagePart", { media: "image" }], ["AudioPart", { media: "audio" }], ["VideoPart", { media: "video" }],
      ["DocumentPart", { media: "document" }], ["BinaryPart", { media: "binary" }]]);
  assert.deepEqual((colour(reg).render({ picture: PICTURE }).request("m") as any).messages[0].parts[0]["media_type"], "image/png");
});

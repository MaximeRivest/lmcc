import { test } from "node:test";
import assert from "node:assert/strict";
import { strip, readInteger, readNumber, readBoolean, spellNumber, spellInteger, roundHalfEven, lintRe2, compileRe2 } from "../lmcc/text.ts";
import { parseJson, dumpJson, jsonEqual, parseJsonDocument, quoteJsonString } from "../lmcc/json.ts";

test("strip removes exactly the six ASCII whitespace characters", () => {
  assert.equal(strip("\t\n\v\f\r x \r\n"), "x");
  assert.equal(strip("\u00a0Paris\u3000"), "\u00a0Paris\u3000");
  assert.equal(strip(""), "");
  assert.equal(strip("   "), "");
});

test("integer grammar -?[0-9]+", () => {
  assert.equal(readInteger("-007"), -7);
  assert.equal(readInteger("+5"), null);
  assert.equal(readInteger("1_000"), null);
  assert.equal(readInteger("9007199254740993"), 9007199254740993n);
  assert.equal(spellInteger(9007199254740993n), "9007199254740993");
  assert.equal(spellInteger(1e21), "1000000000000000000000");
  assert.equal(spellInteger(-0), "0");
});

test("number grammar and ECMAScript spelling", () => {
  assert.equal(readNumber("1e3"), 1000);
  assert.equal(readNumber("1."), null);
  assert.equal(readNumber(".5"), null);
  assert.equal(readNumber("Infinity"), null);
  assert.equal(spellNumber(3.0), "3");
  assert.equal(spellNumber(1e21), "1e+21");
  assert.equal(spellNumber(1e-7), "1e-7");
  assert.equal(spellNumber(1e-6), "0.000001");
  assert.equal(spellNumber(-0), "0");
  assert.equal(spellNumber(123456789012345680000), "123456789012345680000");
  assert.throws(() => spellNumber(Number.NaN));
});

test("booleans fold ASCII case only", () => {
  assert.equal(readBoolean("Yes"), true);
  assert.equal(readBoolean("NO"), false);
  assert.equal(readBoolean("maybe"), null);
});

test("half-to-even rounding", () => {
  assert.equal(roundHalfEven(0.5, 0), 0);
  assert.equal(roundHalfEven(1.5, 0), 2);
  assert.equal(roundHalfEven(2.5, 0), 2);
  assert.equal(roundHalfEven(2.675, 2), 2.68); // binary64: 2.675 * 100 is exactly 267.5, so the half rounds to even (268); Python round() gives 2.67
  assert.equal(roundHalfEven(83.4, 0), 83);
});

test("RE2 subset lint refuses the D-14 constructs", () => {
  assert.equal(lintRe2("Thought: ([^\\n]+)"), null);
  assert.ok(lintRe2("(?=Thought)(.*)"));
  assert.ok(lintRe2("(a)\\1"));
  assert.ok(lintRe2("(?P<n>a)"));
  assert.ok(lintRe2("(?<n>a)"));
  assert.ok(lintRe2("(?>a)"));
  assert.ok(lintRe2("a*+"));
  assert.ok(lintRe2("(?i)a"));
  assert.equal(lintRe2("(?:a|b)+"), null);
  assert.equal(lintRe2("[[]"), null);
});

test("compiled RE2 dot excludes only \\n", () => {
  const re = compileRe2("a(.)b");
  assert.deepEqual(Array.from("a\rb a\nb".matchAll(re)).map((m) => m[1]), ["\r"]);
});

test("JSON reader keeps big integers and member order; writer follows format-json.md", () => {
  const v = parseJson('{"z": 9007199254740993, "a": 1.0, "s": "é\\n\\"q\\""}') as { [k: string]: unknown };
  assert.deepEqual(Object.keys(v), ["z", "a", "s"]);
  assert.equal(v.z, 9007199254740993n);
  assert.equal(v.a, 1);
  assert.equal(dumpJson(v, null), '{"z": 9007199254740993, "a": 1, "s": "é\\n\\"q\\""}');
  assert.equal(dumpJson({ e: {}, l: [], n: null }, 2), '{\n  "e": {},\n  "l": [],\n  "n": null\n}');
  assert.equal(quoteJsonString("\u0001\u007f"), '"\\u0001\u007f"');
  assert.throws(() => parseJson('{"a": 1, "a": 2}'));
  assert.throws(() => parseJson("[1,]"));
  assert.throws(() => parseJson("NaN"));
  const doc = parseJsonDocument('{"a": 1, "a": {"x":  [1, 2]}}');
  assert.equal(doc.members?.length, 2);
  assert.equal(doc.members?.[1].source, '{"x":  [1, 2]}');
  assert.ok(jsonEqual(1000, 1000.0));
  assert.ok(jsonEqual(9007199254740993n, 9007199254740993n));
  assert.ok(!jsonEqual(1, 2n));
});

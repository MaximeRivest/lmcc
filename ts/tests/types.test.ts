/**
 * The typed surface: `tsc` checks these lines (npm run check); the test run
 * executes them. A line marked @ts-expect-error must fail to compile.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import * as lmcc from "../src/index.ts";

test("signatures carry static types through bind, render and parse", () => {
  const classify = lmcc.signature("Classify.", {
    inputs: { text: lmcc.t.string(), hint: lmcc.t.nullable(lmcc.t.string()) },
    outputs: {
      label: lmcc.t.enum("positive", "negative"),
      confidence: lmcc.t.number(),
      reasoning: lmcc.field(lmcc.t.string(), { purpose: "reasoning" }),
    },
  });
  const plan = lmcc.adapter({
    messages: [lmcc.system("{% for f in outputs %}<{f.name}>{f.value}</{f.name}>{% endfor %}"), lmcc.user("{text}{% if hint %} ({hint}){% endif %}")],
  }).bind(classify, { instruct: true });

  plan.render({ text: "great", hint: null });
  // @ts-expect-error: 'txt' is not an input of this signature
  assert.throws(() => plan.render({ txt: "great" }));

  const values = plan.parse("<label>positive</label><confidence>0.9</confidence><reasoning>clear</reasoning>");
  const label: "positive" | "negative" = values.label;
  const confidence: number = values.confidence;
  assert.equal(label, "positive");
  assert.equal(confidence, 0.9);
  // @ts-expect-error: a label is not any string
  const wrong: "neutral" = values.label;
  void wrong;
});

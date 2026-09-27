/**
 * The TypeScript kernel against real models, through lm15-ts. Costs money:
 * not part of ./check. Run by hand:
 *
 *     set -a; source ~/Projects/lm15-dev/.env; set +a
 *     node ts/integration/live.ts            # writes ts/integration/live-record.json
 *     python contract/harness/replay_live.py
 *
 * Every exchange is recorded (the adapter's artifact, the signature, the
 * capabilities, the turns, the requests TypeScript rendered and the replies
 * as lm15 returned them) so the Python kernel can re-render and re-read each
 * one and prove both kernels agree on real traffic, not only on the corpus.
 */

import { writeFileSync } from "node:fs";
import { LMRouter, Response } from "@lm15/lm15";
import * as lmcc from "../src/index.ts";
import * as bridge from "../src/lm15.ts";
import { install as installStd } from "../src/std/index.ts";
import { nativeReasoning, reasoningTags } from "../src/std/reasoning.ts";

const registry = new lmcc.Registry();
installStd(registry);
const router = new LMRouter();
const record: Record<string, unknown>[] = [];
const results: [string, string, string][] = [];

const TAGS = "Reply with exactly this pattern and nothing else:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}";
const sections = lmcc.adapter({ name: "sections", messages: [lmcc.system("{instruction}\n\n" + TAGS), lmcc.turns(), lmcc.user("{question}")] });

const quiz = lmcc.signature("Answer the question. The score is how sure you are, from 1 to 10.", {
  inputs: { question: lmcc.t.string() },
  outputs: { answer: lmcc.t.string({}), score: lmcc.t.integer() },
});

function save(name: string, adapter: lmcc.Adapter, sig: lmcc.Signature<any, any>, capabilities: Record<string, unknown>,
  exchanges: { current: unknown; request: unknown; response: unknown; turn: unknown }[]): void {
  record.push({ name, entry: adapter.dump({ registry }), signature: lmcc.signatureToDict(sig), capabilities, vocab: ["std"], exchanges });
}

async function attempt(name: string, model: string, fn: () => Promise<string>): Promise<void> {
  try {
    const note = await fn();
    results.push([name, model, `ok  ${note}`]);
  } catch (err) {
    const e = err as Error & { code?: string };
    results.push([name, model, `FAIL ${e.name}${e.code ? " [" + e.code + "]" : ""}: ${e.message.slice(0, 160)}`]);
  }
  console.log(results[results.length - 1].join("  "));
}

// 1. The same program, several providers; batch and stream must agree.
const MODELS: [string, Record<string, unknown>][] = [
  ["gpt-4.1-mini", { instruct: true, stop_sequences: true }],
  ["claude-haiku-4-5", { instruct: true, stop_sequences: true }],
  ["gemini:gemini-2.5-flash", { instruct: true }],
  ["groq:openai/gpt-oss-20b", { instruct: true }],
  ["deepseek:deepseek-chat", { instruct: true }],
];
for (const [model, caps] of MODELS) {
  await attempt("sections", model, async () => {
    const plan = sections.bind(quiz, caps, { registry });
    const rendered = plan.render({ question: "What is the capital of Australia?" });
    const req = bridge.request(rendered, { model, config: { maxTokens: 300 } });
    const response = await router.complete(req);
    const reading = bridge.read(plan, response);
    const turn = bridge.step(rendered, response);
    const [events, streamed] = await bridge.stream(plan, router.stream(bridge.request(rendered, { model, config: { maxTokens: 300 } })));
    if (typeof reading.values.score !== "number") throw new Error(`score is ${typeof reading.values.score}`);
    const deltas = events.filter((e) => e.kind === "field_delta").length;
    save(`sections/${model}`, sections, quiz, caps, [{ current: rendered.turn.toJSON(), request: rendered.request(model), response: Response.toJSON(response), turn: turn.toJSON() }]);
    return `answer=${JSON.stringify(reading.values.answer)} score=${reading.values.score} repairs=${reading.repairs.length} | stream answer=${JSON.stringify(streamed.values.answer)} (${deltas} deltas)`;
  });
}

// 2. One tool program, native and text tiers: the caller runs the loop (§6).
const ask = lmcc.signature("Answer the question. Use a tool when you need facts you do not have.", {
  inputs: {
    question: lmcc.t.string(),
    tools: lmcc.field(lmcc.t.list(lmcc.t.json({ type: "object" })), { purpose: "tools", type: "list[Tool]" }),
  },
  outputs: {
    calls: lmcc.field(lmcc.t.list(lmcc.t.json<{ id: string; name: string; input: { city: string } }>({ type: "object" })), { purpose: "tools.calls", type: "list[ToolCall]" }),
    answer: lmcc.t.string(),
  },
});
const WEATHER = { name: "get_weather", description: "Current weather for a city.", parameters: { type: "object", properties: { city: { type: "string" } }, required: ["city"] } };

async function toolLoop(transport: string, model: string, caps: Record<string, unknown>): Promise<string> {
  const adapter = lmcc.adapter({
    name: `tools_${transport}`,
    messages: [lmcc.system("{instruction}\n\nReply with exactly this pattern and nothing else, also after a tool result:\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"), lmcc.turns(), lmcc.user("{question}")],
    transports: { tools: transport },
    formats: { "list[Tool]": { use: "function_tool" }, "list[ToolCall]": { use: "tool_calls" } },
  });
  const plan = adapter.bind(ask, caps, { registry });
  let turn = plan.turn({ question: "What is the weather in Montreal right now?", tools: [WEATHER] });
  const exchanges: { current: unknown; request: unknown; response: unknown; turn: unknown }[] = [];
  for (let round = 0; round < 4; round++) {
    const rendered = plan.render(turn);
    const response = await router.complete(bridge.request(rendered, { model, config: { maxTokens: 400 } }));
    turn = bridge.step(rendered, response);
    exchanges.push({ current: rendered.turn.toJSON(), request: rendered.request(model), response: Response.toJSON(response), turn: turn.toJSON() });
    const last = turn.steps[turn.steps.length - 1] as lmcc.ModelStep;
    const calls = (last.outputs["calls"] ?? []) as { id: string; input: { city: string } }[];
    if (!calls.length) {
      turn = turn.finish();
      save(`tools/${transport}/${model}`, adapter, ask, caps, exchanges);
      return `${round + 1} model calls, answer=${JSON.stringify(String(last.outputs["answer"]).slice(0, 60))}`;
    }
    for (const call of calls) turn = turn.tool(call.id, `Sunny and 22°C in ${call.input.city}.`);
  }
  throw new Error("no answer after 4 rounds");
}

await attempt("tools/native", "gpt-4.1-mini", () => toolLoop("native_tools", "gpt-4.1-mini", { instruct: true, native_function_calling: true }));
await attempt("tools/native", "claude-haiku-4-5", () => toolLoop("native_tools", "claude-haiku-4-5", { instruct: true, native_function_calling: true }));
await attempt("tools/fenced", "deepseek:deepseek-chat", () => toolLoop("fenced_tools", "deepseek:deepseek-chat", { instruct: true }));
await attempt("tools/fenced", "claude-haiku-4-5", () => toolLoop("fenced_tools", "claude-haiku-4-5", { instruct: true }));

// 3. Reasoning: one program, the transport chosen by the model's declared facts.
const solve = lmcc.signature("Solve the problem.", {
  inputs: { problem: lmcc.t.string() },
  outputs: { reasoning: lmcc.field(lmcc.t.string(), { purpose: "reasoning" }), answer: lmcc.t.integer() },
});
const thinking = lmcc.adapter({
  name: "thinking",
  messages: [lmcc.system("{instruction}\n\n" + TAGS), lmcc.user("{problem}")],
  transports: { reasoning: lmcc.choose([[lmcc.when.has("native_reasoning"), nativeReasoning({ effort: "low" })]], { otherwise: reasoningTags({}), registry }) },
});
for (const [model, caps] of [
  ["claude-haiku-4-5", { instruct: true, native_reasoning: true }],
  ["gemini:gemini-2.5-flash", { instruct: true, native_reasoning: true }],
  ["gpt-4.1-mini", { instruct: true }],
] as [string, Record<string, unknown>][]) {
  await attempt("reasoning", model, async () => {
    const plan = thinking.bind(solve, caps, { registry });
    const rendered = plan.render({ problem: "A train leaves at 9:40 and arrives at 13:05. How many minutes is the trip?" });
    const response = await router.complete(bridge.request(rendered, { model, config: { maxTokens: 4000 } }));
    const values = bridge.parse(plan, response);
    save(`reasoning/${model}`, thinking, solve, caps, [{ current: rendered.turn.toJSON(), request: rendered.request(model), response: Response.toJSON(response), turn: bridge.step(rendered, response).toJSON() }]);
    if (values.answer !== 205) throw new Error(`answer ${values.answer}`);
    const via = plan.findRules.map(([, r]) => r.from).join(",") || "sections";
    return `answer=${values.answer} via ${via}, reasoning ${String(values.reasoning).length} chars`;
  });
}

// 4. The JSON reader: a provider that enforces the schema.
const sentiment = lmcc.signature("Classify the review.", {
  inputs: { review: lmcc.t.string() },
  outputs: { label: lmcc.field(lmcc.t.enum("positive", "negative", "mixed"), { desc: "the review's overall sentiment" }), stars: lmcc.t.integer() },
});
const jsonAdapter = lmcc.adapter({ name: "json", messages: [lmcc.system("{instruction}"), lmcc.user("{review}")], reader: { kind: "json_object" } });
await attempt("json_object", "gpt-4.1-mini", async () => {
  const caps = { instruct: true, native_structured_output: true };
  const plan = jsonAdapter.bind(sentiment, caps, { registry });
  const rendered = plan.render({ review: "Great battery, awful screen. Three stars." });
  const response = await router.complete(bridge.request(rendered, { model: "gpt-4.1-mini", config: { maxTokens: 200 } }));
  const reading = bridge.read(plan, response);
  save("json_object/gpt-4.1-mini", jsonAdapter, sentiment, caps, [{ current: rendered.turn.toJSON(), request: rendered.request("gpt-4.1-mini"), response: Response.toJSON(response), turn: bridge.step(rendered, response).toJSON() }]);
  return `label=${reading.values.label} stars=${reading.values.stars}`;
});

// 5. The prefill (§3): sent only to a model that continues one.
const prefilled = lmcc.adapter({
  name: "prefilled",
  messages: [lmcc.system("{instruction}\n\n" + TAGS), lmcc.user("{question}"), lmcc.assistant("<answer>\n")],
});
await attempt("prefill", "claude-haiku-4-5", async () => {
  const caps = { instruct: true, assistant_prefill: true, stop_sequences: true };
  const plan = prefilled.bind(quiz, caps, { registry });
  const rendered = plan.render({ question: "What is 17 times 3?" });
  const response = await router.complete(bridge.request(rendered, { model: "claude-haiku-4-5", config: { maxTokens: 200 } }));
  const values = bridge.parse(plan, response);
  save("prefill/claude-haiku-4-5", prefilled, quiz, caps, [{ current: rendered.turn.toJSON(), request: rendered.request("claude-haiku-4-5"), response: Response.toJSON(response), turn: bridge.step(rendered, response).toJSON() }]);
  return `answer=${JSON.stringify(values.answer)} score=${values.score}`;
});

// 6. Truncation (§4a): a reply cut at its length limit never reads as finished.
await attempt("truncated", "gpt-4.1-mini", async () => {
  const plan = sections.bind(quiz, { instruct: true }, { registry });
  const rendered = plan.render({ question: "Explain photosynthesis in detail." });
  const response = await router.complete(bridge.request(rendered, { model: "gpt-4.1-mini", config: { maxTokens: 16 } }));
  save("truncated/gpt-4.1-mini", sections, quiz, { instruct: true }, [{ current: rendered.turn.toJSON(), request: rendered.request("gpt-4.1-mini"), response: Response.toJSON(response), turn: null }]);
  try {
    bridge.parse(plan, response);
  } catch (err) {
    if (err instanceof lmcc.Refusal && err.code === "parse-truncated") return `refused parse-truncated (finish_reason=${response.finishReason})`;
    throw err;
  }
  throw new Error(`a cut reply was read as finished (finish_reason=${response.finishReason})`);
});

writeFileSync(new URL("./live-record.json", import.meta.url), JSON.stringify(record, null, 1) + "\n");
const failed = results.filter(([, , r]) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed} of ${results.length} live scenarios ok; ${record.length} recorded for the Python replay`);

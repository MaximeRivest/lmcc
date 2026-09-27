/**
 * Standard reasoning transports: three ways to serve one purpose
 * (spec/vocab/transport-reasoning.md). The same signature, the same program,
 * three inference behaviors — chosen at bind by the model's declared facts.
 *
 * - `prefix_cot`: the reasoning field stays a visible section written first.
 * - `reasoning_tags`: `<think>` captures, found and removed from the text.
 * - `native_reasoning`: read from the provider's thinking parts.
 */

import type { Registry } from "../registry.ts";
import { Transport } from "../transport.ts";

export const VERSION = "0.1.0";
export const REASONING_TAGS_VERSION = "0.3.0";

export function prefixCot(): Transport {
  return new Transport({
    requires: ["instruct"],
    tell: { system: "Reason step by step in the '{field}' section before writing any other section." },
    in_template: true,
  });
}

export function reasoningTags(options: Record<string, unknown>): Transport {
  const open = (options["open"] as string | undefined) ?? "<think>";
  const close = (options["close"] as string | undefined) ?? "</think>";
  return new Transport({
    requires: ["instruct"],
    tell: { system: `After every sentence of output, add your thinking inside ${open}...${close} tags.` },
    find: [{ from: "text", between: [open, close], to: "@purpose", remove: true, repair: true }],
    spelling: { position: "before" },
    in_template: false,
  });
}

/** Options: `effort` (lm15 `Reasoning.effort`, default `medium`), `thinking_budget`. */
export function nativeReasoning(options: Record<string, unknown>): Transport {
  const reasoning: Record<string, unknown> = { effort: options["effort"] ?? "medium" };
  if ("thinking_budget" in options) reasoning["thinking_budget"] = options["thinking_budget"];
  return new Transport({
    requires: ["native_reasoning"],
    request_settings: { config: { reasoning } },
    find: [{ from: "part:thinking", to: "@purpose" }],
    in_template: false,
  });
}

export function install(registry: Registry, opts: { existOk?: boolean } = {}): void {
  const existOk = opts.existOk ?? true;
  registry.registerTransport("prefix_cot", prefixCot, { version: VERSION, existOk });
  registry.registerTransport("reasoning_tags", reasoningTags, { version: REASONING_TAGS_VERSION, existOk });
  registry.registerTransport("native_reasoning", nativeReasoning, { version: VERSION, existOk });
}

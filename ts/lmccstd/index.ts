// lmccstd: the std vocabulary pack. Registers through the socket; the
// kernel never imports this module.

import type { Registry, Options } from "../lmcc/registry.ts";
import type { StrategyData } from "../lmcc/strategy.ts";
import { jsonFormat, tableFormat, scaledNumberFormat } from "./formats.ts";
import { jsonObjectLens } from "./json_object.ts";

export const STD_VERSION = "0.1.0";

export function prefixCot(_options: Options): StrategyData {
  return {
    requires: ["instruct"],
    visible: true,
    fragments: { system: "Reason step by step in the '{field}' section before writing any other section." },
  };
}

export function reasoningTags(options: Options): StrategyData {
  const open = typeof options.open === "string" ? options.open : "<think>";
  const close = typeof options.close === "string" ? options.close : "</think>";
  return {
    requires: ["instruct"],
    visible: false,
    fragments: { system: `After every sentence of output, add your thinking inside ${open}...${close} tags.` },
    routings: [{ from: "text", between: [open, close], to: "@role", consume: true }],
  };
}

export function nativeReasoning(_options: Options): StrategyData {
  return {
    requires: ["native_reasoning"],
    visible: false,
    routings: [{ from: "channel:thinking", to: "@role" }],
  };
}

export function install(registry: Registry): void {
  registry.registerFormat("json", STD_VERSION, jsonFormat, true);
  registry.registerFormat("table", STD_VERSION, tableFormat, true);
  registry.registerFormat("scaled_number", STD_VERSION, scaledNumberFormat, true);
  registry.registerStrategy("prefix_cot", STD_VERSION, prefixCot, true);
  registry.registerStrategy("reasoning_tags", STD_VERSION, reasoningTags, true);
  registry.registerStrategy("native_reasoning", STD_VERSION, nativeReasoning, true);
  registry.registerLens("json_object", STD_VERSION, () => jsonObjectLens, true);
}

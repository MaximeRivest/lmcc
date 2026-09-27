/**
 * lmcc/std — the standard vocabulary pack.
 *
 * Deliberately outside the kernel: it registers through the same sockets
 * your own formats and transports use, and earns its standing the same way,
 * by passing the contract corpus. Nothing here is privileged.
 *
 * ```ts
 * import { Registry } from "lmcc";
 * import { install } from "lmcc/std";
 * const registry = new Registry();
 * install(registry);
 * ```
 */

import type { Registry } from "../registry.ts";
import * as code from "./code.ts";
import * as formats from "./formats.ts";
import * as readers from "./readers.ts";
import * as reasoning from "./reasoning.ts";
import * as tools from "./tools.ts";

export const VERSION = "0.1.0";

export function install(registry: Registry, opts: { existOk?: boolean } = {}): void {
  formats.install(registry, opts);
  reasoning.install(registry, opts);
  readers.install(registry, opts);
  tools.install(registry, opts);
  code.install(registry, opts);
}

export { code, formats, readers, reasoning, tools };
export { bindTypeNames, type Tool, type ToolCall, type Citation, type Source } from "./tools.ts";

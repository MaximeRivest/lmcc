/**
 * Tools and citations: formats and transports (spec/vocab/transport-tools.md,
 * transport-citations.md). Every value shape is lm15's; the program never
 * changes between the native and the text tier.
 *
 * Formats resolve by type, never by purpose (§5): an artifact names them
 * under `formats` (`"list[Tool]": {"use": "function_tool"}`). The Python
 * pack also binds its host classes at runtime; TypeScript types are erased,
 * so this pack binds nothing implicitly (call `bindTypeNames` to bind the
 * conventional names `list[Tool]`, `list[ToolCall]`, `list[Citation]`,
 * `list[Source]` in a registry of your own).
 */

import { refuse } from "../errors.ts";
import { isObj, type Capture, type Field, type Part } from "../core.ts";
import type { Format } from "../formats.ts";
import { integerValue, setMember } from "../json.ts";
import type { Registry } from "../registry.ts";
import { pyRepr, pyTruthy, strip } from "../text.ts";
import { Transport } from "../transport.ts";
import { dumps, loads } from "./jsontext.ts";

export const VERSION = "0.1.0";

export interface Tool { name: string; description?: string | null; parameters?: Record<string, unknown> | null }
export interface ToolCall { id: string; name: string; input: Record<string, unknown> }
export interface Citation { url?: string | null; title?: string | null; text?: string | null; source?: number | null }
export interface Source { text: string; title?: string | null; url?: string | null }

const TOOL_KEYS = ["name", "description", "parameters"];
const DEFAULT_PARAMETERS = () => ({ type: "object", properties: {} });

function toolItems(value: unknown, field: Field): Record<string, unknown>[] {
  const items = Array.isArray(value) ? value : [value];
  return items.map((item, i) => {
    let spec: Record<string, unknown>;
    if (isObj(item)) spec = item;
    else spec = {};
    if (typeof spec["name"] !== "string" || !spec["name"]) refuse("format-write-error", `field ${pyRepr(field.name)}: tools[${i}] needs a string 'name'`);
    const unknown = Object.keys(spec).filter((k) => !TOOL_KEYS.includes(k) && k !== "type" && spec[k] !== undefined).sort();
    if (unknown.length) {
      refuse("format-write-error", `field ${pyRepr(field.name)}: tools[${i}] has keys ${pyRepr(unknown)}; a tool is name, description, parameters (lm15 FunctionTool)`);
    }
    return spec;
  });
}

abstract class Base implements Format {
  name: string | null = null;
  abstract readonly accepts: readonly string[];
  abstract readonly direction: "in" | "out" | "both";
  abstract readonly writes: "text" | "parts";
  roundTrip = true;
  reads: readonly string[] = ["text"];
  describe(_field: Field): string | null {
    return null;
  }
  write(_value: unknown, _field: Field): string | Part[] {
    throw new Error(`format ${this.name ?? "(inline)"} does not write`);
  }
}

/** lm15 `FunctionTool` parts, for `Request.tools`. */
export class FunctionToolFormat extends Base {
  readonly accepts = ["list[Tool]", "Tool", "list[*]", "object", "*"];
  readonly direction = "in" as const;
  readonly writes = "parts" as const;
  override reads = ["function"];
  override describe(): string {
    return "tools";
  }
  override write(value: unknown, field: Field): Part[] {
    return toolItems(value, field).map((spec) => {
      const part: Record<string, unknown> = { type: "function", name: spec["name"] };
      if (pyTruthy(spec["description"])) part["description"] = spec["description"];
      part["parameters"] = pyTruthy(spec["parameters"]) ? spec["parameters"] : DEFAULT_PARAMETERS();
      return part as Part;
    });
  }
  read(capture: Capture): unknown {
    return capture.of("function").map((p) => {
      const out: Record<string, unknown> = {};
      for (const k of Object.keys(p)) if (k !== "type") setMember(out, k, p[k]);
      return out;
    });
  }
}

/** The same tools as text, for a model without native calling. */
export class ToolCatalogFormat extends Base {
  readonly accepts = ["list[Tool]", "Tool", "list[*]", "object", "*"];
  readonly direction = "in" as const;
  readonly writes = "text" as const;
  override describe(): string {
    return "tools";
  }
  override write(value: unknown, field: Field): string {
    return toolItems(value, field).map((spec) => {
      const params = dumps(pyTruthy(spec["parameters"]) ? spec["parameters"] : DEFAULT_PARAMETERS(), null);
      const desc = pyTruthy(spec["description"]) ? `: ${spec["description"]}` : "";
      return `- ${spec["name"]}(${params})${desc}`;
    }).join("\n");
  }
}

/** Calls from `tool_call` parts (verbatim) or from text (fenced JSON; ids `call_1`… in reply order). */
export class ToolCallsFormat extends Base {
  readonly accepts = ["list[ToolCall]", "list[*]", "*"];
  readonly direction = "both" as const;
  readonly writes = "parts" as const;
  override reads = ["tool_call", "text"];
  override describe(): string {
    return "tool calls";
  }
  override write(value: unknown): Part[] {
    return ((value || []) as Record<string, unknown>[]).map((c) => {
      const call = lowerObject(c);
      return { type: "tool_call", id: call["id"], name: call["name"], input: "input" in call ? call["input"] : {} } as Part;
    });
  }
  read(capture: Capture, field: Field): unknown {
    const calls: Record<string, unknown>[] = [];
    let n = 0;
    for (const p of capture.parts) {
      if (p.type === "tool_call") {
        const out: Record<string, unknown> = {};
        for (const k of Object.keys(p)) if (k !== "type" && k !== "continuation") setMember(out, k, p[k]);
        calls.push(out);
      } else if (typeof p["text"] === "string") {
        let obj: unknown;
        try {
          obj = loads(p["text"] as string);
        } catch (err) {
          refuse("format-read-error", `field ${pyRepr(field.name)}: a fenced call is not JSON: ${(err as Error).message}`);
        }
        if (!isObj(obj) || typeof obj["name"] !== "string") refuse("format-read-error", `field ${pyRepr(field.name)}: a fenced call is {name, input}`);
        n++;
        calls.push({ id: `call_${n}`, name: obj["name"], input: pyTruthy(obj["input"]) ? obj["input"] : {} });
      }
    }
    return calls;
  }
}

/** From `citation` parts verbatim; from text markers `{"source": n}` per distinct decimal integer, order kept. */
export class CitationsFormat extends Base {
  readonly accepts = ["list[Citation]", "list[*]", "*"];
  readonly direction = "out" as const;
  readonly writes = "parts" as const;
  override reads = ["citation", "text"];
  read(capture: Capture): unknown {
    const out: Record<string, unknown>[] = [];
    const seen = new Set<string>();
    for (const p of capture.parts) {
      if (p.type === "citation") {
        const c: Record<string, unknown> = {};
        for (const k of Object.keys(p)) if (k !== "type" && k !== "continuation") setMember(c, k, p[k]);
        out.push(c);
      } else if (typeof p["text"] === "string") {
        const t = strip(p["text"] as string);
        if (/^[0-9]+$/.test(t) && !seen.has(t)) {
          seen.add(t);
          out.push({ source: integerValue(t) });
        }
      }
    }
    return out;
  }
}

/** Numbered sources as text: `[n] title: text`. */
export class SourceListFormat extends Base {
  readonly accepts = ["list[Source]", "list[*]", "*"];
  readonly direction = "in" as const;
  readonly writes = "text" as const;
  override describe(): string {
    return "numbered sources";
  }
  override write(value: unknown, field: Field): string {
    return ((value || []) as unknown[]).map((raw, i) => {
      const s = lowerObject(raw);
      if (!isObj(s) || typeof s["text"] !== "string") refuse("format-write-error", `field ${pyRepr(field.name)}: sources[${i}] needs 'text'`);
      const title = s["title"] || s["url"] || `source ${i + 1}`;
      return `[${i + 1}] ${title}: ${s["text"]}`;
    }).join("\n");
  }
}

function lowerObject(value: unknown): Record<string, unknown> {
  if (isObj(value) && typeof (value as { toJSON?: unknown }).toJSON === "function") return (value as { toJSON: () => Record<string, unknown> }).toJSON();
  return value as Record<string, unknown>;
}

// ------------------------------------------------------------ transports

export function nativeTools(): Transport {
  return new Transport({
    requires: ["native_function_calling"], in_template: false,
    put: { "@purpose": "request.tools" },
    find: [{ from: "part:tool_call", to: "@purpose.calls", complete_reply: true }],
  });
}

export const FENCE_OPEN = "```tool\n";
export const FENCE_CLOSE = "\n```";

export function fencedTools(): Transport {
  return new Transport({
    requires: ["instruct"], in_template: false,
    put: { "@purpose": "message:system" }, written_as: { "@purpose": "tool_catalog" },
    tell: {
      system: "You may call a tool by replying with exactly one fenced block:\n```tool\n{\"name\": \"<tool>\", \"input\": {...}}\n```\nand nothing else; you will be given the result and asked again.",
    },
    find: [{ from: "text", between: [FENCE_OPEN, FENCE_CLOSE], to: "@purpose.calls", remove: true, complete_reply: true }],
    spelling: { call: "```tool\n{\"name\": \"{name}\", \"input\": {input}}\n```", result: "Result of {name} ({id}):\n{output}" },
  });
}

export function nativeCitations(options: Record<string, unknown>): Transport {
  const s = new Transport({ requires: ["native_citations"], in_template: false, find: [{ from: "part:citation", to: "@purpose" }] });
  if (pyTruthy(options["search"] ?? true)) s.request_settings = { tools: [{ type: "builtin", name: "web_search" }] };
  return s;
}

export function inlineCitations(): Transport {
  return new Transport({
    requires: ["instruct"], in_template: false,
    put: { "@purpose.sources": "message:user" },
    tell: { system: "Cite the numbered sources inline as [n] after each claim they support." },
    find: [{ from: "text", between: ["[", "]"], to: "@purpose", remove: false }],
  });
}

export function install(registry: Registry, opts: { existOk?: boolean } = {}): void {
  const existOk = opts.existOk ?? true;
  const formats: [string, () => Format][] = [
    ["function_tool", () => new FunctionToolFormat()], ["tool_catalog", () => new ToolCatalogFormat()],
    ["tool_calls", () => new ToolCallsFormat()], ["citations", () => new CitationsFormat()], ["source_list", () => new SourceListFormat()],
  ];
  for (const [name, factory] of formats) registry.registerFormat(name, factory, { version: VERSION, existOk });
  const transports: [string, (o: Record<string, unknown>) => Transport][] = [
    ["native_tools", nativeTools], ["fenced_tools", fencedTools], ["native_citations", nativeCitations], ["inline_citations", inlineCitations],
  ];
  for (const [name, factory] of transports) registry.registerTransport(name, factory, { version: VERSION, existOk });
}

/** Bind the conventional type names to these formats (runtime, never serialized). */
export function bindTypeNames(registry: Registry): void {
  registry.format("list[Tool]", { use: "function_tool" });
  registry.format("list[ToolCall]", { use: "tool_calls" });
  registry.format("list[Citation]", { use: "citations" });
  registry.format("list[Source]", { use: "source_list" });
}

/**
 * Raw-code argument spelling and heredoc calls (spec/vocab/format-code.md).
 * No execution. Arguments and capture bodies stay exact, including
 * indentation and trailing newlines; the envelope is the transport's.
 */

import { refuse } from "../errors.ts";
import { Capture, isObj, type Field, type Part } from "../core.ts";
import type { Format } from "../formats.ts";
import type { Registry } from "../registry.ts";
import { pyRepr } from "../text.ts";
import { Transport } from "../transport.ts";

export const VERSION = "0.1.0";
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

function options(opts: Record<string, unknown>, calls = false): [string, string] {
  const allowed = calls ? ["marker", "tool"] : ["marker"];
  const unknown = Object.keys(opts).filter((k) => !allowed.includes(k)).sort();
  if (unknown.length) throw new Error(`unknown options: ${pyRepr(unknown)}`);
  const marker = opts["marker"] ?? "PY_END";
  const tool = opts["tool"] ?? "run_python";
  for (const [key, value] of [["marker", marker], ["tool", tool]] as const) {
    if (typeof value !== "string" || !IDENT.test(value)) throw new Error(`${key} must be a nonempty ASCII identifier`);
  }
  return [marker as string, tool as string];
}

export class CodeArguments implements Format {
  name: string | null = null;
  readonly accepts = ["object"];
  readonly direction = "both" as const;
  readonly writes = "text" as const;
  readonly roundTrip = true;
  readonly reads = ["text"];
  readonly marker: string;

  constructor(opts: Record<string, unknown>) {
    [this.marker] = options(opts);
  }

  describe(): string {
    return "raw code";
  }

  code(value: unknown): string {
    if (!isObj(value) || Object.keys(value).length !== 1 || !("code" in value) || typeof value["code"] !== "string") {
      throw new Error("code arguments must be exactly {code: string}");
    }
    return value["code"];
  }

  write(value: unknown): string {
    const code = this.code(value);
    if (code.includes(this.marker)) refuse("value-collides", `code contains heredoc marker ${pyRepr(this.marker)}; choose another marker`);
    return code;
  }

  read(capture: Capture): unknown {
    if (capture.parts.some((p) => p.type !== "text" || typeof p["text"] !== "string")) throw new Error("code arguments need text parts");
    const code = capture.parts.map((p) => p["text"] as string).join(""); // not capture.text: code whitespace is data
    if (code.includes(this.marker)) throw new Error(`code contains heredoc marker ${pyRepr(this.marker)}`);
    return { code };
  }
}

export class CodeCalls implements Format {
  name: string | null = null;
  readonly accepts = ["list[*]", "*"];
  readonly direction = "both" as const;
  readonly writes = "parts" as const;
  readonly roundTrip = true;
  readonly reads = ["text", "tool_call"];
  readonly tool: string;
  readonly arguments: CodeArguments;

  constructor(opts: Record<string, unknown>) {
    const [marker, tool] = options(opts, true);
    this.tool = tool;
    this.arguments = new CodeArguments({ marker });
  }

  describe(): string {
    return "heredoc tool calls";
  }

  private native(call: unknown, field: Field, writing: boolean): Record<string, unknown> {
    const c = call as Record<string, unknown>;
    if (!isObj(c) || c["name"] !== this.tool || typeof c["id"] !== "string" || !c["id"]) {
      throw new Error(`expected a ${pyRepr(this.tool)} call with a nonempty id`);
    }
    let body: string;
    if (writing) {
      body = this.arguments.write(c["input"]); // the same writer as spelling.input_format
    } else {
      body = this.arguments.code(c["input"]);
      this.arguments.read(Capture.ofText(body));
    }
    void field;
    return { id: c["id"], name: this.tool, input: { code: body } };
  }

  write(value: unknown, field: Field): Part[] {
    if (!Array.isArray(value)) throw new Error("calls must be a list");
    return value.map((c) => ({ type: "tool_call", ...this.native(c, field, true) }) as Part);
  }

  read(capture: Capture, field: Field): unknown {
    const calls: Record<string, unknown>[] = [];
    for (const part of capture.parts) {
      if (part.type === "tool_call") calls.push(this.native(part, field, false));
      else calls.push({ id: `call_${calls.length + 1}`, name: this.tool, input: this.arguments.read(new Capture([part])) });
    }
    return calls;
  }
}

export function heredocTools(opts: Record<string, unknown>): Transport {
  const [marker, tool] = options(opts, true);
  const opening = `${tool} <<'${marker}'\n`;
  const closing = `\n${marker}`;
  return new Transport({
    requires: ["instruct"], in_template: false,
    put: { "@purpose": "message:system" }, written_as: { "@purpose": "tool_catalog" },
    tell: { system: `To request ${tool}, emit this heredoc and wait for its result:\n${opening}<code>${closing}\nDo not put ${marker} anywhere in the code. Otherwise reply normally.` },
    find: [{ from: "text", between: [opening, closing], to: "@purpose.calls", remove: true, complete_reply: true }],
    spelling: {
      call: "{name} <<'" + marker + "'\n{input}" + closing,
      result: "Result of {name} ({id}):\n{output}",
      input_format: { use: "code_arguments", options: { marker } },
      probe: { name: tool, input: { code: "print(6 * 7)\n" } },
    },
  });
}

export function install(registry: Registry, opts: { existOk?: boolean } = {}): void {
  const existOk = opts.existOk ?? true;
  registry.registerFormat("code_arguments", (o) => new CodeArguments(o), { version: VERSION, existOk });
  registry.registerFormat("code_calls", (o) => new CodeCalls(o), { version: VERSION, existOk });
  registry.registerTransport("heredoc_tools", heredocTools, { version: VERSION, existOk });
}

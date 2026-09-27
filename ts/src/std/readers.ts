/**
 * Standard readers: json_object (spec/vocab/reader-json_object.md).
 *
 * The reply is one JSON object keyed by field name. A mode, not a template
 * style: bind refuses without `native_structured_output`, and the reader asks
 * for `response_format` with a schema of the visible outputs (a field's
 * `desc` is its property's `description`, 0.2.0). A string member is the
 * field's raw text verbatim; any other member hands its source text to the
 * field's format. A key twice refuses `parse-ambiguous`.
 */

import { refuse } from "../errors.ts";
import type { Field } from "../core.ts";
import { Reader } from "../reader.ts";
import type { Registry } from "../registry.ts";
import { pyRepr, strip } from "../text.ts";
import { dumps, loads, members } from "./jsontext.ts";
import type { Json } from "../json.ts";

export const VERSION = "0.2.0";
export const PROBABILITY_POLICIES = ["off", "if_available", "required"];

export class JsonObjectReader extends Reader {
  override spec: Record<string, unknown>;

  constructor(spec: Record<string, unknown>) {
    super();
    const extra = Object.keys(spec).filter((k) => k !== "kind" && k !== "probabilities").sort();
    const policy = spec["probabilities"];
    if (extra.length || (policy !== undefined && policy !== null && !PROBABILITY_POLICIES.includes(policy as string))) {
      refuse("entry-malformed",
        `reader: json_object takes 'probabilities' (${PROBABILITY_POLICIES.join(" | ")})` + (extra.length ? `, not ${pyRepr(extra)}` : `, not ${pyRepr(policy)}`),
        { fix: { action: "edit-entry", path: "reader" } });
    }
    this.spec = { ...spec };
  }

  override requires(): string[] {
    return ["native_structured_output"];
  }

  override requestSettings(fields: Field[]): Record<string, unknown> {
    const policy = this.spec["probabilities"];
    const extra = policy !== undefined && policy !== null ? { probabilities: policy } : {};
    const properties: Record<string, unknown> = {};
    for (const f of fields) properties[f.name] = f.desc ? { ...f.shape, description: f.desc } : { ...f.shape };
    return {
      config: {
        response_format: {
          type: "json_schema",
          schema: { type: "object", properties, required: fields.map((f) => f.name), additionalProperties: false },
        },
        ...extra,
      },
    };
  }

  split(text: string, fieldNames: string[]): Record<string, string> {
    const found = this.document(text);
    const wanted = new Set(fieldNames);
    const raw: Record<string, string> = {};
    for (const [key, value, source] of found) {
      if (!wanted.has(key)) continue;
      if (key in raw) refuse("parse-ambiguous", `json_object: member ${pyRepr(key)} appears more than once in the reply — refusing to guess which one is real`);
      raw[key] = typeof value === "string" ? value : strip(source);
    }
    const missing = fieldNames.filter((n) => !(n in raw));
    if (missing.length) refuse("parse-missing-fields", "reply object is missing key(s): " + missing.map(pyRepr).join(", "), { partial: raw });
    return raw;
  }

  private document(text: string): [string, Json, string][] {
    let t = strip(text);
    if (t.startsWith("```")) {
      const firstNl = t.indexOf("\n");
      const closing = t.lastIndexOf("```");
      if (firstNl >= 0 && closing > firstNl) t = strip(t.slice(firstNl + 1, closing));
    }
    try {
      return members(t);
    } catch (first) {
      const start = t.indexOf("{");
      const end = t.lastIndexOf("}");
      if (!(start >= 0 && start < end)) refuse("reader-error", `json_object: reply contains no JSON object (${(first as Error).message})`);
      try {
        return members(t.slice(start, end + 1));
      } catch (err) {
        refuse("reader-error", `json_object: reply is not a JSON object: ${(err as Error).message}`);
      }
    }
  }

  join(spelled: [string, string][]): string {
    const obj: Record<string, unknown> = {};
    for (const [name, text] of spelled) {
      let value: unknown = text;
      try {
        const parsed = loads(text);
        if (typeof parsed !== "string") value = parsed;
      } catch {
        // not JSON: embeds as a string
      }
      obj[name] = value;
    }
    return dumps(obj, 2);
  }
}

export function install(registry: Registry, opts: { existOk?: boolean } = {}): void {
  registry.registerReader("json_object", (spec) => new JsonObjectReader(spec), { version: VERSION, existOk: opts.existOk ?? true });
}

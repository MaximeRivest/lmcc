/**
 * Standard readers: json_object (spec/vocab/reader-json_object.md).
 *
 * The reply is one JSON object keyed by field name. A mode, not a template
 * style: bind refuses without `native_structured_output`, and the reader asks
 * for `response_format` with a schema of the visible outputs (a field's
 * `desc` is its property's `description`, 0.2.0; every record closed, 0.2.1). A string member is the
 * field's raw text verbatim; any other member hands its source text to the
 * field's format. A key twice refuses `parse-ambiguous`.
 */

import { refuse } from "../errors.ts";
import type { Field } from "../core.ts";
import { Reader } from "../reader.ts";
import type { Registry } from "../registry.ts";
import { pyRepr, strip } from "../text.ts";
import { dumps, loads, members } from "./jsontext.ts";
import { hasOwn, setMember, type Json } from "../json.ts";

export const VERSION = "0.2.1";
export const PROBABILITY_POLICIES = ["off", "if_available", "required"];

const ONE = new Set(["additionalProperties", "items", "not", "if", "then", "else", "contains"]);
const LIST = new Set(["anyOf", "oneOf", "allOf", "prefixItems", "items"]);
const MAP = new Set(["properties", "patternProperties", "$defs", "definitions"]);
const isPlain = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * The shape as strict schema enforcement takes it (0.2.1): every record (an
 * object schema with `properties`) that does not say `additionalProperties`
 * gets `additionalProperties: false` and lists every property in `required`,
 * in property order. OpenAI's strict mode and Anthropic refuse a nested
 * record without them; lm15 sends a schema verbatim, so this reader writes
 * one they accept. A record that says `additionalProperties` is left open as
 * written, and so is an object without `properties` (a map, any object).
 * Returns a new value: `shape` is not changed.
 */
export function closed(shape: unknown): unknown {
  if (Array.isArray(shape)) return shape.map(closed);
  if (!isPlain(shape)) return shape;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(shape)) {
    if (MAP.has(key) && isPlain(value)) setMember(out, key, Object.fromEntries(Object.entries(value).map(([k, v]) => [k, closed(v)])));
    else if (ONE.has(key) || LIST.has(key)) setMember(out, key, closed(value));
    else setMember(out, key, value);
  }
  if (hasOwn(out, "properties") && isPlain(out["properties"])) {
    out["required"] = Object.keys(out["properties"]);
    if (!hasOwn(out, "additionalProperties")) out["additionalProperties"] = false;
  }
  return out;
}

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
    for (const f of fields) {
      const shape = closed(f.shape) as Record<string, unknown>;
      setMember(properties, f.name, f.desc ? { ...shape, description: f.desc } : shape);
    }
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
      if (hasOwn(raw, key)) refuse("parse-ambiguous", `json_object: member ${pyRepr(key)} appears more than once in the reply — refusing to guess which one is real`);
      setMember(raw, key, typeof value === "string" ? value : strip(source));
    }
    const missing = fieldNames.filter((n) => !hasOwn(raw, n));
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
      setMember(obj, name, value);
    }
    return dumps(obj, 2);
  }
}

export function install(registry: Registry, opts: { existOk?: boolean } = {}): void {
  registry.registerReader("json_object", (spec) => new JsonObjectReader(spec), { version: VERSION, existOk: opts.existOk ?? true });
}

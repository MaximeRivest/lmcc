/**
 * The neutral core: shapes, values, parts, captures, responses.
 *
 * Shapes are JSON-Schema objects (kernel §1). The kernel spells scalars as
 * §7a says and passes strings through verbatim; anything structured needs a
 * format. Messages and parts are plain lm15 canonical JSON:
 * `{"role", "parts": [{"type": "text", "text"}, ...]}`.
 *
 * Imports nothing outside this package. That is a rule, not an accident.
 */

import { refuse, Refusal } from "./errors.ts";
import { formatNumber, isPlainObject, jsonEqual, jsonText, type JsonObject } from "./json.ts";
import { asciiLower, pyRepr, pyStr, readBoolean, readInteger, readNumber, strip, WHITESPACE } from "./text.ts";

/** An lm15 part as canonical JSON: `{"type": ..., ...}`. */
export type Part = { readonly type: string; readonly [key: string]: unknown };
/** An lm15 message as canonical JSON. */
export interface Message {
  readonly role: string;
  readonly parts: Part[];
}

export type Shape = JsonObject;

export interface Field {
  readonly name: string;
  readonly direction: "input" | "output";
  readonly shape: Shape;
  /** The type's name as the frontend spells it; formats resolve by it first (§5). */
  readonly type: string | null;
  readonly purpose: string;
  readonly desc: string | null;
}

export const SCALAR_TYPES = ["string", "integer", "number", "boolean"] as const;
const SCALARS = new Set<string>(SCALAR_TYPES);

/** The capability facts a predicate or `requires` may name (spec/vocab/capabilities.md). */
export const CAPABILITY_FACTS: ReadonlySet<string> = new Set([
  "instruct", "completion", "native_reasoning", "native_function_calling",
  "native_citations", "native_structured_output", "image_input", "stop_sequences",
  "assistant_prefill",
]);

export function isObj(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Kernel §1: a nullable form of a scalar/enum shape is that shape plus null.
 * Returns `[base, nullable]`; only the two spellings the spec names count.
 */
export function nullableBase(shape: Shape): [Shape, boolean] {
  const t = shape["type"];
  if (Array.isArray(t)) {
    const others = t.filter((x) => x !== "null");
    if (t.includes("null") && others.length === 1 && t.length === 2) {
      const base: Record<string, unknown> = {};
      for (const k of Object.keys(shape)) if (k !== "type") base[k] = shape[k];
      base["type"] = others[0];
      return [base as Shape, true];
    }
    return [shape, false];
  }
  const alts = shape["anyOf"];
  if (Array.isArray(alts) && alts.length === 2 && Object.keys(shape).length === 1) {
    const isNull = (a: unknown) => isObj(a) && jsonEqual(a, { type: "null" });
    const nulls = alts.filter(isNull);
    const others = alts.filter((a) => !isNull(a));
    if (nulls.length === 1 && others.length === 1 && isObj(others[0])) {
      const base = others[0] as Shape;
      if ("enum" in base || SCALARS.has(base["type"] as string)) return [base, true];
    }
  }
  return [shape, false];
}

/** A short human hint for a field's shape (`{f.schema}` when no format describes it). */
export function shapeSummary(shape: Shape): string {
  const [base] = nullableBase(shape);
  if ("enum" in base) return "one of: " + (base["enum"] as unknown[]).map(pyStr).join(", ");
  if ("media" in base) return `(${pyStr(base["media"])})`;
  const t = base["type"];
  if (t === "integer" || t === "number" || t === "boolean") return `(${t})`;
  return "";
}

export function isMedia(shape: Shape): boolean {
  return "media" in shape;
}

/** Kernel §1: object/array and every uninterpreted shape need a format. */
export function isStructured(shape: Shape): boolean {
  const [base] = nullableBase(shape);
  if (isMedia(base) || "enum" in base) return false;
  return !SCALARS.has(base["type"] as string);
}

function inEnum(members: unknown[], value: unknown): boolean {
  return members.some((m) => jsonEqual(m, value));
}

/**
 * Kernel §7a, writing: strings verbatim, integers in decimal, numbers by the
 * ECMAScript spelling, booleans `true`/`false`, enums by member spelling,
 * `null` for nullable shapes. Refuses anything structured (`no-format`).
 *
 * Host difference, stated: JavaScript has one number type, so an integral
 * `3.0` given to an integer field writes `3`; the reference refuses it.
 */
export function spellValue(shape: Shape, value: unknown, where: string, field?: string): string {
  const [base, nullable] = nullableBase(shape);
  if (value === null || value === undefined) {
    if (nullable) return "null";
    refuse("value-invalid", `${where}: null is not allowed by the shape`);
  }
  if ("enum" in base) {
    const members = base["enum"] as unknown[];
    if (typeof value === "boolean" || !inEnum(members, value)) {
      refuse("value-invalid", `${where}: value ${pyRepr(value)} is not one of ${pyRepr(members)}`);
    }
    return pyStr(value);
  }
  const t = base["type"];
  if (t === "string") {
    if (typeof value === "string") return value;
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "bigint" || typeof value === "number") return formatNumber(value);
    refuse("value-invalid", `${where}: ${pyRepr(value)} is not text`);
  }
  if (t === "integer") {
    if (typeof value === "bigint") return value.toString();
    if (typeof value !== "number" || !Number.isInteger(value)) {
      refuse("value-invalid", `${where}: ${pyRepr(value)} is not an integer`);
    }
    return BigInt(value).toString();
  }
  if (t === "number") {
    if (typeof value !== "number" && typeof value !== "bigint") {
      refuse("value-invalid", `${where}: ${pyRepr(value)} is not a number`);
    }
    return formatNumber(value);
  }
  if (t === "boolean") {
    if (typeof value !== "boolean") refuse("value-invalid", `${where}: ${pyRepr(value)} is not a boolean`);
    return value ? "true" : "false";
  }
  if (typeof value === "string") return value;
  refuse("no-format",
    `${where}: value of type ${Array.isArray(value) ? "list" : typeof value} has no format bound and is not a scalar — bind a format for this field`,
    { fix: { action: "bind-format", field: field ?? where, key: formatKey(null, shape) } });
}

/** Kernel §7a, reading. Vocabulary reuses this so one grammar rules everywhere. */
export function readValue(shape: Shape, text: string, where: string): unknown {
  const [base, nullable] = nullableBase(shape);
  if (nullable && strip(text) === "null") return null;
  if ("enum" in base) {
    const stripped = strip(text);
    for (const v of base["enum"] as unknown[]) if (pyStr(v) === stripped) return v;
    refuse("parse-value", `${where}: ${pyRepr(stripped)} is not one of ${pyRepr(base["enum"])}`);
  }
  const t = base["type"];
  if (t === "integer") return readInteger(text, where);
  if (t === "number") return readNumber(text, where);
  if (t === "boolean") return readBoolean(text, where);
  return text;
}

const QUOTES = ['"', "'", "`"];

/**
 * Kernel §7a, forgiving reads: called only after the exact read refused.
 * Tries the text without one pair of matching quotes, then also without one
 * trailing period; then without the period and then the quotes (the period
 * outside them); then a nullable's `null`/`none` and an enum member in any
 * ASCII case when exactly one member matches. Else the exact refusal stands.
 */
export function forgiveValue(shape: Shape, text: string, where: string): unknown {
  const [base, nullable] = nullableBase(shape);
  const unquote = (s: string) => (s.length >= 2 && s[0] === s[s.length - 1] && QUOTES.includes(s[0]) ? strip(s.slice(1, -1)) : s);
  const unperiod = (s: string) => (s.endsWith(".") && !s.endsWith("..") ? strip(s.slice(0, -1)) : s);
  const t = strip(text);
  const t1 = unquote(t);
  const t2 = unperiod(t1);
  const t3 = unquote(unperiod(t));
  const texts = [...new Set([t1, t2, t3])];
  for (const c of texts) {
    if (c === t || !c) continue;
    try {
      return readValue(shape, c, where);
    } catch (err) {
      if (!(err instanceof Refusal)) throw err;
    }
  }
  for (const c of texts) {
    const low = asciiLower(c);
    if (nullable && (low === "null" || low === "none")) return null;
    if ("enum" in base) {
      const hits = (base["enum"] as unknown[]).filter((v) => typeof v === "string" && asciiLower(v) === low);
      if (hits.length === 1) return hits[0];
    }
  }
  return readValue(shape, text, where); // the exact refusal
}

/** The structural keys a shape answers to, most specific first, never `*` (§5). */
export function structuralKeys(shape: Shape): string[] {
  const [base] = nullableBase(shape);
  if (isMedia(base)) return [`media:${pyStr(base["media"])}`, "media:*"];
  if ("enum" in base) return ["enum"];
  const t = base["type"];
  if (SCALARS.has(t as string)) return [t as string];
  if (t === "array") {
    const items = (base["items"] as unknown) || {};
    const inner = isObj(items) ? structuralKeys(items as Shape) : [];
    return [...inner.filter((k) => !k.startsWith("media")).map((k) => `list[${k}]`), "list[*]"];
  }
  if (t === "object") return ["object"];
  return [];
}

/** The artifact key a format for this field binds under (errors.md `bind-format`). */
export function formatKey(typeName: string | null, shape: Shape): string {
  if (typeName) return typeName;
  const keys = structuralKeys(shape);
  return keys.length ? keys[0] : "*";
}

// ------------------------------------------------------------ captures

export function textPart(text: string): Part {
  return { type: "text", text };
}

/**
 * What a find rule or the reader captured for one field: a list of parts.
 * `text` is the parts that carry text, each stripped, joined by newlines
 * (§6); for a reader capture holding non-text parts, the section's text
 * exactly as without them (§4b).
 */
export class Capture {
  readonly parts: Part[];
  private readonly _text: string | null;

  constructor(parts: Part[], text: string | null = null) {
    this.parts = [...parts];
    this._text = text;
  }

  static ofText(text: string): Capture {
    return new Capture([textPart(text)]);
  }

  get text(): string {
    if (this._text !== null) return this._text;
    return this.parts.filter((p) => typeof p["text"] === "string").map((p) => strip(p["text"] as string)).join("\n");
  }

  of(type: string): Part[] {
    return this.parts.filter((p) => p.type === type);
  }

  get kinds(): Set<string> {
    return new Set(this.parts.map((p) => p.type));
  }
}

/** A format's `write` returns text (one text part) or a part list. */
export function asParts(written: unknown, where: string): Part[] {
  if (typeof written === "string") return [textPart(written)];
  if (Array.isArray(written) && written.every((p) => isObj(p) && "type" in p)) return [...written] as Part[];
  refuse("format-write-error",
    `${where}: write must return text or a list of parts, got ${Array.isArray(written) ? "list" : written === null ? "None" : typeof written}`);
}

export function makeMessage(role: string, parts: Part[]): Message {
  return { role, parts };
}

/** Adjacent text parts merge; empty text parts vanish. */
export function mergeTextParts(parts: Part[]): Part[] {
  const out: Part[] = [];
  for (const p of parts) {
    if (p.type === "text") {
      if (!p["text"]) continue;
      const last = out[out.length - 1];
      if (last && last.type === "text") {
        out[out.length - 1] = textPart((last["text"] as string) + (p["text"] as string));
        continue;
      }
    }
    out.push(p);
  }
  return out;
}

/** The shared batch and part-delta boundary; no text coercion. */
export function validateResponsePart(part: unknown): asserts part is Part {
  if (!isObj(part) || typeof part["type"] !== "string") {
    refuse("response-malformed", "response part must be an object with a string 'type' (an lm15 part)");
  }
  if ("text" in part && typeof part["text"] !== "string") {
    refuse("response-malformed", "a response part's 'text' must be text");
  }
  if (part["type"] === "data" && !("value" in part)) {
    refuse("response-malformed", "a data part carries a 'value' (lm15 DataPart), even when it is null");
  }
}

/** Kernel §3: a data part's value as the reply text in its place (§7a numbers). */
export function dataText(value: unknown): string {
  return jsonText(value, { code: "response-malformed" });
}

/** The text a reply part contributes to the reply text (§3). */
export function partText(part: Part): string {
  if (part.type === "text") return (part["text"] as string | undefined) ?? "";
  if (part.type === "data") return dataText(part["value"]);
  return "";
}

function responseMessage(response: unknown): unknown {
  if (isObj(response) && isObj(response["message"])) return response["message"];
  return response;
}

/** Kernel §3: `[probabilities, measuredBy]` from the reply's data parts, checked on intake. */
export function replyProbabilities(response: unknown): [Record<string, Record<string, number>>, Record<string, string>] {
  const message = responseMessage(response);
  const parts = isObj(message) ? message["parts"] : undefined;
  const probabilities: Record<string, Record<string, number>> = {};
  const measuredBy: Record<string, string> = {};
  for (const part of Array.isArray(parts) ? parts : []) {
    if (!isObj(part) || part["type"] !== "data") continue;
    const dist = part["probabilities"];
    const method = part["method"];
    if ((dist === undefined || dist === null) && (method === undefined || method === null)) continue;
    if (dist === undefined || dist === null || method === undefined || method === null) {
      refuse("response-malformed", "a data part's 'probabilities' and 'method' come together (lm15 INV-052)");
    }
    if (typeof method !== "string" || !isObj(dist)) {
      refuse("response-malformed", "a data part's 'method' is text and its 'probabilities' an object {field: {key: p}}");
    }
    for (const field of Object.keys(dist)) {
      const keys = dist[field];
      const valid = isObj(keys) && Object.values(keys).every((p) => {
        const n = typeof p === "bigint" ? Number(p) : p;
        return typeof n === "number" && n >= 0 && n <= 1;
      });
      if (!valid) {
        refuse("response-malformed", `probabilities for ${pyRepr(field)} must map each answer key to a number in [0, 1]`);
      }
      if (Object.prototype.hasOwnProperty.call(probabilities, field)) {
        refuse("parse-ambiguous", `two data parts carry probabilities for ${pyRepr(field)} — refusing to guess which measured the answer`);
      }
      probabilities[field] = { ...(keys as Record<string, number>) };
      measuredBy[field] = method;
    }
  }
  return [probabilities, measuredBy];
}

/** Coalesce text runs as §8 does. The caller's parts are not changed. */
export function normalizeResponseParts(parts: unknown[]): Part[] {
  const out: Record<string, unknown>[] = [];
  let texts: string[] = [];
  for (const part of parts) {
    validateResponsePart(part);
    const hasText = typeof part["text"] === "string";
    const last = out[out.length - 1];
    if (hasText && texts.length && last["type"] === part.type) {
      texts.push(part["text"] as string);
      for (const k of Object.keys(part)) if (k !== "type" && k !== "text") last[k] = part[k];
      continue;
    }
    if (texts.length) last["text"] = texts.join("");
    out.push({ ...part });
    texts = hasText ? [part["text"] as string] : [];
  }
  if (texts.length) out[out.length - 1]["text"] = texts.join("");
  return out as Part[];
}

/** The lm15 `finish_reason` of a response; `null` for a text or a message. */
export function finishReason(response: unknown): string | null {
  if (isObj(response) && isObj(response["message"])) {
    const reason = response["finish_reason"];
    return typeof reason === "string" ? reason : null;
  }
  return null;
}

/** The reply text, an lm15 message, or an lm15 response → `[text, parts]` (§3). */
export function responseTextAndParts(response: unknown): [string, Part[]] {
  if (typeof response === "string") return [response, []];
  const message = responseMessage(response);
  if (isObj(message) && Array.isArray(message["parts"])) {
    const parts = normalizeResponseParts(message["parts"]);
    return [parts.map(partText).join(""), parts];
  }
  refuse("response-malformed", "response must be text, an lm15 message {role, parts}, or an lm15 response {message: ...}");
}

export { isPlainObject, WHITESPACE };

/**
 * JSON as lmcc reads and writes it.
 *
 * Reading (`parseJson`): strict RFC 8259 — no NaN/Infinity, no comments, no
 * trailing commas, no raw control characters in strings. Integers outside
 * ±(2^53 − 1) come back as `bigint`, so the kernel carries at least int64
 * exactly (kernel §7a); every other number is a binary64 `number`.
 *
 * Writing (`jsonText`): the kernel's one JSON spelling (§3, §3a, §6):
 * strings minimally escaped (non-ASCII verbatim), integers in decimal, every
 * other number by §7a (ECMAScript `Number::toString`) — the same bytes as
 * the Python reference, never a host's own float spelling (D-54).
 */

import { refuse } from "./errors.ts";

export type JsonPrimitive = null | boolean | number | bigint | string;
export type Json = JsonPrimitive | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export class JsonSyntaxError extends Error {
  readonly position: number;
  constructor(message: string, position: number) {
    super(`${message} at ${position}`);
    this.name = "JsonSyntaxError";
    this.position = position;
  }
}

export interface ParseOptions {
  /** `"reject"` (lmcc's strict reads) or `"last"` (RFC 8259's common reading, Python's `json.loads`). */
  readonly duplicates?: "reject" | "last";
}

const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);

/** Set a member without letting `__proto__` reach the prototype. */
export function setMember(obj: Record<string, unknown>, key: string, value: unknown): void {
  if (key === "__proto__") {
    Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
  } else {
    obj[key] = value;
  }
}

class Parser {
  readonly s: string;
  readonly duplicates: "reject" | "last";
  i = 0;

  constructor(s: string, options: ParseOptions) {
    this.s = s;
    this.duplicates = options.duplicates ?? "last";
  }

  ws(): void {
    const s = this.s;
    while (this.i < s.length) {
      const c = s.charCodeAt(this.i);
      if (c === 0x20 || c === 0x09 || c === 0x0a || c === 0x0d) this.i++;
      else break;
    }
  }

  fail(message: string): never {
    throw new JsonSyntaxError(message, this.i);
  }

  value(): Json {
    const s = this.s;
    if (this.i >= s.length) this.fail("expected a value");
    const c = s[this.i];
    if (c === "{") return this.object();
    if (c === "[") return this.array();
    if (c === '"') return this.string();
    if (c === "t") return this.literal("true", true);
    if (c === "f") return this.literal("false", false);
    if (c === "n") return this.literal("null", null);
    if (c === "-" || (c >= "0" && c <= "9")) return this.number();
    this.fail(`unexpected character ${JSON.stringify(c)}`);
  }

  literal<T extends Json>(word: string, value: T): T {
    if (this.s.startsWith(word, this.i)) {
      this.i += word.length;
      return value;
    }
    this.fail("invalid literal");
  }

  number(): number | bigint {
    const s = this.s;
    const start = this.i;
    if (s[this.i] === "-") this.i++;
    if (s[this.i] === "0") {
      this.i++;
    } else if (s[this.i] >= "1" && s[this.i] <= "9") {
      while (s[this.i] >= "0" && s[this.i] <= "9") this.i++;
    } else {
      this.fail("invalid number");
    }
    let integral = true;
    if (s[this.i] === ".") {
      integral = false;
      this.i++;
      if (!(s[this.i] >= "0" && s[this.i] <= "9")) this.fail("invalid number");
      while (s[this.i] >= "0" && s[this.i] <= "9") this.i++;
    }
    if (s[this.i] === "e" || s[this.i] === "E") {
      integral = false;
      this.i++;
      if (s[this.i] === "+" || s[this.i] === "-") this.i++;
      if (!(s[this.i] >= "0" && s[this.i] <= "9")) this.fail("invalid number");
      while (s[this.i] >= "0" && s[this.i] <= "9") this.i++;
    }
    const text = s.slice(start, this.i);
    if (integral) return integerValue(text);
    return Number(text);
  }

  string(): string {
    const s = this.s;
    this.i++; // opening quote
    let out = "";
    let run = this.i;
    for (;;) {
      if (this.i >= s.length) this.fail("unterminated string");
      const c = s.charCodeAt(this.i);
      if (c === 0x22) {
        out += s.slice(run, this.i);
        this.i++;
        return out;
      }
      if (c < 0x20) this.fail("control character in string");
      if (c !== 0x5c) {
        this.i++;
        continue;
      }
      out += s.slice(run, this.i);
      const e = s[this.i + 1];
      switch (e) {
        case '"': out += '"'; break;
        case "\\": out += "\\"; break;
        case "/": out += "/"; break;
        case "b": out += "\b"; break;
        case "f": out += "\f"; break;
        case "n": out += "\n"; break;
        case "r": out += "\r"; break;
        case "t": out += "\t"; break;
        case "u": {
          const hex = s.slice(this.i + 2, this.i + 6);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) this.fail("invalid \\u escape");
          out += String.fromCharCode(parseInt(hex, 16));
          this.i += 4;
          break;
        }
        default:
          this.fail("invalid escape");
      }
      this.i += 2;
      run = this.i;
    }
  }

  array(): Json[] {
    this.i++;
    const out: Json[] = [];
    this.ws();
    if (this.s[this.i] === "]") {
      this.i++;
      return out;
    }
    for (;;) {
      this.ws();
      out.push(this.value());
      this.ws();
      if (this.s[this.i] === ",") {
        this.i++;
        continue;
      }
      if (this.s[this.i] === "]") {
        this.i++;
        return out;
      }
      this.fail("expected ',' or ']'");
    }
  }

  object(): JsonObject {
    this.i++;
    const out: JsonObject = {};
    this.ws();
    if (this.s[this.i] === "}") {
      this.i++;
      return out;
    }
    for (;;) {
      this.ws();
      if (this.s[this.i] !== '"') this.fail("expected a member name");
      const key = this.string();
      this.ws();
      if (this.s[this.i] !== ":") this.fail("expected ':'");
      this.i++;
      this.ws();
      const value = this.value();
      if (Object.prototype.hasOwnProperty.call(out, key) && this.duplicates === "reject") {
        throw new JsonSyntaxError(`duplicate member ${JSON.stringify(key)}`, this.i);
      }
      setMember(out, key, value);
      this.ws();
      if (this.s[this.i] === ",") {
        this.i++;
        continue;
      }
      if (this.s[this.i] === "}") {
        this.i++;
        return out;
      }
      this.fail("expected ',' or '}'");
    }
  }
}

/** An integer's decimal text as a value: a `number` when exact, else a `bigint`. Never `-0`. */
export function integerValue(text: string): number | bigint {
  const big = BigInt(text);
  if (big <= MAX_SAFE && big >= -MAX_SAFE) return Number(big);
  return big;
}

/** Strict RFC 8259 JSON text → value. Throws {@link JsonSyntaxError}. */
export function parseJson(text: string, options: ParseOptions = {}): Json {
  const p = new Parser(text, options);
  p.ws();
  const value = p.value();
  p.ws();
  if (p.i !== text.length) p.fail("trailing data");
  return value;
}

/** One value starting exactly at `start` (no leading whitespace skipped): `[value, end]`. */
export function parseJsonAt(text: string, start: number, options: ParseOptions = {}): [Json, number] {
  const p = new Parser(text, options);
  p.i = start;
  const value = p.value();
  return [value, p.i];
}

// ------------------------------------------------------------------ write

/** Kernel §7a: ECMAScript `Number::toString`; non-finite refuses `value-invalid`. */
export function formatNumber(value: number | bigint): string {
  const n = typeof value === "bigint" ? Number(value) : value;
  if (typeof n !== "number" || !Number.isFinite(n)) {
    refuse("value-invalid", `${String(value)} has no portable number spelling`);
  }
  return String(n); // String(-0) is "0"
}

const SHORT_ESCAPES: Record<string, string> = {
  '"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t",
};

/** A JSON string: `"`, `\` and U+0000–U+001F escaped, everything else verbatim. */
export function jsonString(text: string): string {
  let out = '"';
  let run = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c >= 0x20 && c !== 0x22 && c !== 0x5c) continue;
    out += text.slice(run, i);
    const ch = text[i];
    out += SHORT_ESCAPES[ch] ?? "\\u" + c.toString(16).padStart(4, "0");
    run = i + 1;
  }
  return out + text.slice(run) + '"';
}

/** Code point order (Python's string order), not UTF-16 code unit order. */
export function compareCodePoints(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const x = a.charCodeAt(i);
    const y = b.charCodeAt(i);
    if (x === y) continue;
    // A surrogate (D800–DFFF) belongs to a code point above every BMP character.
    const xs = x >= 0xd800 && x <= 0xdfff;
    const ys = y >= 0xd800 && y <= 0xdfff;
    if (xs !== ys) return xs ? 1 : -1;
    return x - y;
  }
  return a.length - b.length;
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

export interface JsonTextOptions {
  /** Order members by code point (canonical JSON, §3a). */
  readonly sortKeys?: boolean;
  /** Separate with `, ` and `: ` (a call's `{input}`, §6). */
  readonly spaced?: boolean;
  /** The refusal code for a value that is not JSON. */
  readonly code?: string;
}

/** JSON as the kernel writes it (§3, §3a, §6; D-54). */
export function jsonText(value: unknown, options: JsonTextOptions = {}): string {
  const item = options.spaced ? ", " : ",";
  const key = options.spaced ? ": " : ":";
  const code = options.code ?? "value-invalid";
  const write = (v: unknown): string => {
    if (v === null) return "null";
    if (v === true) return "true";
    if (v === false) return "false";
    if (typeof v === "bigint") return v.toString();
    if (typeof v === "number") {
      if (!Number.isFinite(v)) refuse(code, `${v} has no JSON spelling`);
      return String(v);
    }
    if (typeof v === "string") return jsonString(v);
    if (Array.isArray(v)) return "[" + v.map(write).join(item) + "]";
    if (typeof v === "object" && typeof (v as { toJSON?: unknown }).toJSON === "function" && !isPlainObject(v)) {
      return write((v as { toJSON: () => unknown }).toJSON());
    }
    if (isPlainObject(v)) {
      let keys = Object.keys(v).filter((k) => v[k] !== undefined);
      if (options.sortKeys) keys = [...keys].sort(compareCodePoints);
      return "{" + keys.map((k) => jsonString(k) + key + write(v[k])).join(item) + "}";
    }
    refuse(code, `a ${v === undefined ? "missing value" : typeof v} is not JSON data`);
  };
  return write(value);
}

/**
 * JSON equality as the reference compares values (Python `==`): objects
 * unordered, arrays ordered, numbers by value (an integer equals the same
 * float, and a `bigint` the same `number`; `true == 1` as in Python).
 */
export function jsonEqual(a: unknown, b: unknown): boolean {
  const num = (x: unknown): number | bigint | undefined =>
    typeof x === "number" || typeof x === "bigint" ? x : typeof x === "boolean" ? (x ? 1 : 0) : undefined;
  const na = num(a);
  const nb = num(b);
  if (na !== undefined || nb !== undefined) {
    if (na === undefined || nb === undefined) return false;
    if (typeof na === "bigint" || typeof nb === "bigint") {
      try {
        return BigInt(na) === BigInt(nb);
      } catch {
        return false; // a non-integral number never equals an integer beyond 2^53
      }
    }
    return na === nb;
  }
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return a === b;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => jsonEqual(x, b[i]));
  }
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  const rb = b as Record<string, unknown>;
  const ra = a as Record<string, unknown>;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(rb, k) && jsonEqual(ra[k], rb[k]));
}

/** A readable dump for messages and tools (bigint-safe, two-space indent). */
export function pretty(value: unknown): string {
  return JSON.stringify(value, (_k, v) => (typeof v === "bigint" ? v.toString() : v), 1) ?? "undefined";
}

/** A deep copy of JSON-like data (plain objects and arrays; other values shared). */
export function deepCopy<T>(value: T): T {
  if (Array.isArray(value)) return value.map(deepCopy) as T;
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value)) setMember(out, k, deepCopy(value[k]));
    return out as T;
  }
  return value;
}

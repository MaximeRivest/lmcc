// Strict RFC 8259 JSON reader and writer (stdlib only).
//
// Why not JSON.parse/JSON.stringify: the corpus carries integers beyond
// 2^53 (case 35: 9007199254740993), the json_object lens needs member
// source spans (D-17), duplicate members must be detectable (case 46),
// and the writer must follow format-json.md (minimal escapes, kernel
// number spelling, single-line layout with spaces).
//
// Integers outside the IEEE-754 safe range are read as BigInt; every
// other number is a binary64 `number`. Object member order is the
// document's own order, with one stated trade-off: JavaScript objects
// reorder integer-like keys ("1" before "a"); the corpus never relies on
// such keys.

import { spellNumber } from "./text.ts";

export type Json = null | boolean | number | bigint | string | Json[] | { [k: string]: Json };

export interface Member {
  key: string;
  value: Json;
  /** source text of the value, exactly as written (outer whitespace trimmed) */
  source: string;
  isString: boolean;
}

export interface ParsedDocument {
  value: Json;
  /** top-level members when the root is an object, in document order (duplicates kept) */
  members: Member[] | null;
}

export class JsonError extends Error {
  position: number;
  constructor(message: string, position: number) {
    super(`${message} at offset ${position}`);
    this.name = "JsonError";
    this.position = position;
  }
}

const WS = new Set([0x20, 0x09, 0x0a, 0x0d]);

class Reader {
  text: string;
  pos = 0;
  duplicates: "error" | "keep";
  members: Member[] | null = null;
  constructor(text: string, duplicates: "error" | "keep") {
    this.text = text;
    this.duplicates = duplicates;
  }
  fail(msg: string): never {
    throw new JsonError(msg, this.pos);
  }
  skipWs(): void {
    while (this.pos < this.text.length && WS.has(this.text.charCodeAt(this.pos))) this.pos++;
  }
  parseDocument(): ParsedDocument {
    this.skipWs();
    const isRootObject = this.text[this.pos] === "{";
    const value = this.parseValue(isRootObject);
    this.skipWs();
    if (this.pos !== this.text.length) this.fail("trailing characters");
    return { value, members: isRootObject ? this.members : null };
  }
  parseValue(recordMembers = false): Json {
    this.skipWs();
    const c = this.text[this.pos];
    if (c === undefined) this.fail("unexpected end of input");
    if (c === "{") return this.parseObject(recordMembers);
    if (c === "[") return this.parseArray();
    if (c === '"') return this.parseString();
    if (c === "t") return this.literal("true", true);
    if (c === "f") return this.literal("false", false);
    if (c === "n") return this.literal("null", null);
    if (c === "-" || (c >= "0" && c <= "9")) return this.parseNumber();
    this.fail(`unexpected character ${JSON.stringify(c)}`);
  }
  literal<T extends Json>(word: string, value: T): T {
    if (this.text.startsWith(word, this.pos)) {
      this.pos += word.length;
      return value;
    }
    this.fail(`invalid literal`);
  }
  parseNumber(): number | bigint {
    const start = this.pos;
    const t = this.text;
    if (t[this.pos] === "-") this.pos++;
    if (t[this.pos] === "0") this.pos++;
    else if (t[this.pos] >= "1" && t[this.pos] <= "9") {
      while (t[this.pos] >= "0" && t[this.pos] <= "9") this.pos++;
    } else this.fail("invalid number");
    let isInt = true;
    if (t[this.pos] === ".") {
      isInt = false;
      this.pos++;
      if (!(t[this.pos] >= "0" && t[this.pos] <= "9")) this.fail("invalid number");
      while (t[this.pos] >= "0" && t[this.pos] <= "9") this.pos++;
    }
    if (t[this.pos] === "e" || t[this.pos] === "E") {
      isInt = false;
      this.pos++;
      if (t[this.pos] === "+" || t[this.pos] === "-") this.pos++;
      if (!(t[this.pos] >= "0" && t[this.pos] <= "9")) this.fail("invalid number");
      while (t[this.pos] >= "0" && t[this.pos] <= "9") this.pos++;
    }
    const src = t.slice(start, this.pos);
    if (isInt) {
      const big = BigInt(src);
      if (big >= BigInt(Number.MIN_SAFE_INTEGER) && big <= BigInt(Number.MAX_SAFE_INTEGER)) return Number(big);
      return big;
    }
    return Number(src);
  }
  parseString(): string {
    // assumes text[pos] === '"'
    this.pos++;
    let out = "";
    const t = this.text;
    for (;;) {
      if (this.pos >= t.length) this.fail("unterminated string");
      const code = t.charCodeAt(this.pos);
      const c = t[this.pos];
      if (c === '"') {
        this.pos++;
        return out;
      }
      if (c === "\\") {
        const e = t[this.pos + 1];
        this.pos += 2;
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
            const hex = t.slice(this.pos, this.pos + 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) this.fail("invalid \\u escape");
            out += String.fromCharCode(parseInt(hex, 16));
            this.pos += 4;
            break;
          }
          default:
            this.fail("invalid escape");
        }
        continue;
      }
      if (code < 0x20) this.fail("control character in string");
      out += c;
      this.pos++;
    }
  }
  parseArray(): Json[] {
    this.pos++;
    const out: Json[] = [];
    this.skipWs();
    if (this.text[this.pos] === "]") {
      this.pos++;
      return out;
    }
    for (;;) {
      out.push(this.parseValue());
      this.skipWs();
      const c = this.text[this.pos];
      if (c === ",") {
        this.pos++;
        continue;
      }
      if (c === "]") {
        this.pos++;
        return out;
      }
      this.fail("expected , or ]");
    }
  }
  parseObject(record: boolean): { [k: string]: Json } {
    this.pos++;
    const out: { [k: string]: Json } = {};
    const seen = new Set<string>();
    const members: Member[] = [];
    this.skipWs();
    if (this.text[this.pos] === "}") {
      this.pos++;
      if (record) this.members = members;
      return out;
    }
    for (;;) {
      this.skipWs();
      if (this.text[this.pos] !== '"') this.fail("expected string key");
      const key = this.parseString();
      this.skipWs();
      if (this.text[this.pos] !== ":") this.fail("expected :");
      this.pos++;
      this.skipWs();
      const start = this.pos;
      const value = this.parseValue();
      const end = this.pos;
      if (seen.has(key)) {
        if (this.duplicates === "error") this.fail(`duplicate member ${JSON.stringify(key)}`);
      } else {
        seen.add(key);
        out[key] = value;
      }
      if (record) members.push({ key, value, source: this.text.slice(start, end), isString: typeof value === "string" });
      this.skipWs();
      const c = this.text[this.pos];
      if (c === ",") {
        this.pos++;
        continue;
      }
      if (c === "}") {
        this.pos++;
        if (record) this.members = members;
        return out;
      }
      this.fail("expected , or }");
    }
  }
}

/** Strict parse; duplicate object members are an error (format-json.md). */
export function parseJson(text: string): Json {
  return new Reader(text, "error").parseDocument().value;
}

/** Strict parse that keeps duplicate top-level members visible (lens-json_object.md). */
export function parseJsonDocument(text: string): ParsedDocument {
  return new Reader(text, "keep").parseDocument();
}

export function isJsonObject(v: unknown): v is { [k: string]: Json } {
  return typeof v === "object" && v !== null && !Array.isArray(v) && typeof v !== "bigint";
}

/** Minimal escaping per format-json.md. */
export function quoteJsonString(s: string): string {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    const code = s.charCodeAt(i);
    if (c === '"') out += '\\"';
    else if (c === "\\") out += "\\\\";
    else if (code < 0x20) {
      if (c === "\n") out += "\\n";
      else if (c === "\r") out += "\\r";
      else if (c === "\t") out += "\\t";
      else if (c === "\b") out += "\\b";
      else if (c === "\f") out += "\\f";
      else out += "\\u" + code.toString(16).padStart(4, "0");
    } else out += c;
  }
  return out + '"';
}

export class JsonWriteError extends Error {}

/**
 * Serialize per format-json.md. `indent` = n gives the indented layout;
 * `null` gives the single-line layout with `, ` and `: `.
 */
export function dumpJson(value: unknown, indent: number | null = 2): string {
  const pad = (depth: number): string => (indent === null ? "" : " ".repeat(indent * depth));
  const go = (v: unknown, depth: number): string => {
    if (v === null || v === undefined) return "null";
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") {
      if (!Number.isFinite(v)) throw new JsonWriteError("non-finite number");
      return spellNumber(v);
    }
    if (typeof v === "bigint") return v.toString();
    if (typeof v === "string") return quoteJsonString(v);
    if (Array.isArray(v)) {
      if (v.length === 0) return "[]";
      const items = v.map((x) => go(x, depth + 1));
      if (indent === null) return "[" + items.join(", ") + "]";
      return "[\n" + items.map((s) => pad(depth + 1) + s).join(",\n") + "\n" + pad(depth) + "]";
    }
    if (typeof v === "object") {
      const keys = Object.keys(v as object);
      if (keys.length === 0) return "{}";
      const items = keys.map((k) => quoteJsonString(k) + ": " + go((v as { [k: string]: unknown })[k], depth + 1));
      if (indent === null) return "{" + items.join(", ") + "}";
      return "{\n" + items.map((s) => pad(depth + 1) + s).join(",\n") + "\n" + pad(depth) + "}";
    }
    throw new JsonWriteError(`cannot serialize ${typeof v}`);
  };
  return go(value, 0);
}

/** Deep JSON equality: objects unordered, arrays ordered, numbers by value. */
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a === "number" && typeof b === "number") return a === b || (Number.isNaN(a) && Number.isNaN(b));
  if ((typeof a === "number" || typeof a === "bigint") && (typeof b === "number" || typeof b === "bigint")) {
    if (typeof a === "number" && !Number.isInteger(a)) return false;
    if (typeof b === "number" && !Number.isInteger(b)) return false;
    return BigInt(a) === BigInt(b);
  }
  if (a === null || b === null || a === undefined || b === undefined) return a === b;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => jsonEqual(x, b[i]));
  }
  if (typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a as object);
    const kb = Object.keys(b as object);
    if (ka.length !== kb.length) return false;
    for (const k of ka) {
      if (!Object.prototype.hasOwnProperty.call(b, k)) return false;
      if (!jsonEqual((a as { [k: string]: unknown })[k], (b as { [k: string]: unknown })[k])) return false;
    }
    return true;
  }
  return false;
}

export function cloneJson<T>(v: T): T {
  if (v === null || typeof v !== "object") return v;
  if (Array.isArray(v)) return v.map(cloneJson) as unknown as T;
  const out: { [k: string]: unknown } = {};
  for (const k of Object.keys(v as object)) out[k] = cloneJson((v as { [k: string]: unknown })[k]);
  return out as T;
}

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

/*
 * Records keyed by names (field names, JSON members, artifact keys) are
 * ordinary objects, read and written as data: any name is an own member or
 * absent, never one `Object.prototype` has (`toString`, `constructor`,
 * `__proto__`, ...), and their members keep the order the value holds
 * (kernel §1). Four helpers are the only way lmcc touches such a record's
 * names, and `tests/names.test.ts` keeps it so (no `Object.keys`, object
 * spread or `for ... in` anywhere else in `src/`):
 *
 *   memberNames(obj)            its names, in the value's order (read)
 *   setMember(obj, name, value) set one; a new name comes last (write)
 *   orderedObject(entries)      a record built from (name, value) pairs
 *   copyObject(obj, ...more)    a shallow copy, then `more`'s members set
 *
 * plus `hasOwn`/`ownValue` for a single name.
 *
 * Member order. A JavaScript object enumerates integer-like names ("0",
 * "10") first, in numeric order, however it was built; every other host
 * keeps the order a value holds. So an object whose order JavaScript would
 * change carries its own: the list of its names under a registered symbol,
 * not enumerable, so `Object.keys`, spread, `JSON.stringify`,
 * `structuredClone` and deep equality neither see nor copy it. `setMember`
 * keeps the list as it adds names; nothing is recorded while JavaScript's
 * order is the value's (no integer-like name yet).
 *
 * The record is lm15's (D-59): the symbol `lm15.memberOrder` and the
 * protocol lm15-ts defines with it (`MEMBER_ORDER` in its `src/json.ts`):
 * an own data property holding an array of strings; the object's order is
 * each listed name it holds, at its last place in the list, then its other
 * own members in JavaScript's order; a writer appends the name it adds. So
 * an object lmcc builds reaches the wire through lm15 in its order, and one
 * lm15 read (a reply's tool call input) reaches lmcc in the order it was
 * read. lmcc never imports lm15 for it: the symbol is registered.
 */

export const MEMBER_ORDER: unique symbol = Symbol.for("lm15.memberOrder");
const ORDER = MEMBER_ORDER;

type Recorded = { [ORDER]?: string[] };

/** An object's order record, or null; a record that breaks the protocol is refused loudly. */
function recordOf(obj: object): string[] | null {
  if (!Object.prototype.hasOwnProperty.call(obj, ORDER)) return null;
  const d = Object.getOwnPropertyDescriptor(obj, ORDER)!;
  if (!("value" in d) || !Array.isArray(d.value) || d.value.some((n: unknown) => typeof n !== "string")) {
    throw new TypeError("a member order record (Symbol.for('lm15.memberOrder')) must be an array of strings held as a value");
  }
  return (obj as Recorded)[ORDER]!;
}

/** Drop an object's order record: its members are then in JavaScript's order. */
export function forgetOrder(obj: object): void {
  if (Object.prototype.hasOwnProperty.call(obj, ORDER)) delete (obj as Recorded)[ORDER];
}

/** An array index name ("0", "10", not "01" or "4294967295"): JavaScript enumerates these first. */
function isIndexName(key: string): boolean {
  return /^(0|[1-9][0-9]{0,9})$/.test(key) && Number(key) < 4294967295;
}

function record(obj: object, names: string[]): void {
  Object.defineProperty(obj, ORDER, { value: names, configurable: true, enumerable: false, writable: false });
}

/**
 * Set a member as data: `__proto__` is an own member like any other, never
 * the prototype; a name the object does not hold yet comes after every
 * member it holds (as a Python dict or a Julia OrderedDict adds it), even an
 * integer-like name JavaScript would move first. Replacing a member keeps
 * its place. A member added by plain assignment instead (`obj[k] = v`) is
 * listed after the recorded ones, in JavaScript's order.
 */
export function setMember(obj: Record<string, unknown>, key: string, value: unknown): void {
  const added = !Object.prototype.hasOwnProperty.call(obj, key);
  const recorded = recordOf(obj);
  const before = added && !recorded && isIndexName(key) ? Object.keys(obj) : null;
  if (key === "__proto__") {
    Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
  } else {
    obj[key] = value;
  }
  if (!added) return;
  if (recorded) recorded.push(key);
  else if (before && before.length) record(obj, [...before, key]);
}

/** Whether `key` is `obj`'s own member (an inherited `toString` is not). */
export function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/** `obj[key]` when `key` is `obj`'s own member, else `undefined`. */
export function ownValue(obj: object, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(obj, key) ? (obj as Record<string, unknown>)[key] : undefined;
}

/**
 * An object's own enumerable member names in the value's order: the order
 * lmcc read, built or added them in (a name removed and set again comes
 * last); names added by plain assignment follow, in JavaScript's order.
 * Without a record this is `Object.keys`.
 */
export function memberNames(obj: object): string[] {
  const own = Object.keys(obj);
  const recorded = recordOf(obj);
  if (recorded === null) return own;
  const present = new Set(own);
  const seen = new Set<string>();
  const out: string[] = [];
  for (let i = recorded.length - 1; i >= 0; i--) {
    const k = recorded[i];
    if (present.has(k) && !seen.has(k)) {
      seen.add(k);
      out.push(k);
    }
  }
  out.reverse();
  if (out.length === own.length) return out;
  for (const k of own) if (!seen.has(k)) out.push(k);
  return out;
}

/**
 * A plain object whose members are in the order given, even integer-like
 * names JavaScript would move first: `orderedObject([["b", 1], ["10", 2]])`
 * is written `{"b": 1, "10": 2}` by every lmcc writer. A name given twice
 * keeps its first place and its last value (as a JSON parse does).
 */
export function orderedObject<V = unknown>(entries: Iterable<readonly [string, V]>): Record<string, V> {
  const out: Record<string, V> = {};
  for (const [k, v] of entries) setMember(out, k, v);
  return out;
}

/**
 * A shallow copy of `obj` (its own members, in its order), then each of
 * `more`'s members set in turn: `copyObject(a, b)` is `{...a, ...b}` with
 * the order kept and `__proto__` a member. Values are shared, not copied.
 */
export function copyObject<V = unknown>(obj: object | null | undefined, ...more: (object | null | undefined)[]): Record<string, V> {
  const out: Record<string, V> = {};
  for (const src of [obj, ...more]) {
    if (src === null || src === undefined) continue;
    for (const k of memberNames(src)) setMember(out, k, (src as Record<string, V>)[k]);
  }
  return out;
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
      if (this.duplicates === "reject" && Object.prototype.hasOwnProperty.call(out, key)) {
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

/**
 * Whether `value` converts itself to JSON (a `toJSON` method, the convention
 * `JSON.stringify` follows): class instances, dates, and plain objects that
 * carry one. Every JSON writer in lmcc asks this first, so all of them agree.
 */
export function hasToJSON(value: unknown): value is { toJSON: () => unknown } {
  return typeof value === "object" && value !== null && typeof (value as { toJSON?: unknown }).toJSON === "function";
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
    if (hasToJSON(v)) return write(v.toJSON());
    if (Array.isArray(v)) return "[" + v.map(write).join(item) + "]";
    if (isPlainObject(v)) {
      let keys = memberNames(v).filter((k) => v[k] !== undefined);
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

/** A deep copy of JSON-like data (plain objects and arrays; other values shared), members in order. */
export function deepCopy<T>(value: T): T {
  if (Array.isArray(value)) return value.map(deepCopy) as T;
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const k of memberNames(value)) setMember(out, k, deepCopy(value[k]));
    return out as T;
  }
  return value;
}

/**
 * Text rules (kernel §7a) and the spellings the contract borrowed from the
 * reference host.
 *
 * Portable by construction: every strip and grammar here is defined on
 * ASCII so that every implementation agrees byte for byte. Never use
 * `String.prototype.trim`, `parseInt` or `parseFloat` on model text anywhere
 * in the kernel or a pack: `trim` strips Unicode spaces, `parseInt` accepts
 * `"12abc"`.
 *
 * `pyRepr`/`pyStr`: fix locators are spelled `transports['tools']`,
 * `formats['list[Tool]']` (errors.md, Locators) — the reference's string
 * `repr`. Those bytes are contract data (the corpus pins fixes), so this
 * kernel spells them the same way.
 */

import { refuse } from "./errors.ts";
import { formatNumber, integerValue, isPlainObject } from "./json.ts";

export const WHITESPACE = " \t\n\r\f\v";
const WS = new Set(WHITESPACE);

export function isWhitespace(ch: string): boolean {
  return WS.has(ch);
}

/** Trim the six ASCII whitespace characters, nothing else. */
export function strip(text: string, chars: string = WHITESPACE): string {
  return rstrip(lstrip(text, chars), chars);
}

export function lstrip(text: string, chars: string = WHITESPACE): string {
  let i = 0;
  while (i < text.length && chars.includes(text[i])) i++;
  return i === 0 ? text : text.slice(i);
}

export function rstrip(text: string, chars: string = WHITESPACE): string {
  let j = text.length;
  while (j > 0 && chars.includes(text[j - 1])) j--;
  return j === text.length ? text : text.slice(0, j);
}

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const PURPOSE_RE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;
const INTEGER = /^-?[0-9]+$/;
const NUMBER = /^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$/;

export function isIdentifier(name: unknown): name is string {
  return typeof name === "string" && IDENTIFIER.test(name);
}

export { formatNumber };

export function readInteger(text: string, where: string): number | bigint {
  const t = strip(text);
  if (!INTEGER.test(t)) refuse("parse-value", `${where}: ${pyRepr(t)} is not an integer`);
  return integerValue(t);
}

export function readNumber(text: string, where: string): number {
  const t = strip(text);
  if (!NUMBER.test(t)) refuse("parse-value", `${where}: ${pyRepr(t)} is not a number`);
  const value = Number(t);
  if (!Number.isFinite(value)) refuse("parse-value", `${where}: ${pyRepr(t)} is not a finite number`);
  return value;
}

export function asciiLower(text: string): string {
  return text.replace(/[A-Z]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 32));
}

export function readBoolean(text: string, where: string): boolean {
  const t = strip(text);
  const low = asciiLower(t);
  if (low === "true" || low === "yes") return true;
  if (low === "false" || low === "no") return false;
  refuse("parse-value", `${where}: ${pyRepr(t)} is not a boolean`);
}

/** Truthiness as the reference host tests it: empty containers and `""` are false. */
export function pyTruthy(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (isPlainObject(value)) return Object.keys(value).length > 0;
  if (typeof value === "bigint") return value !== 0n;
  return Boolean(value);
}

/** Non-overlapping occurrences of `sub` in `text` (an empty `sub` counts `len + 1`). */
export function countOf(text: string, sub: string): number {
  if (!sub) return text.length + 1;
  let n = 0;
  let i = text.indexOf(sub);
  while (i >= 0) {
    n++;
    i = text.indexOf(sub, i + sub.length);
  }
  return n;
}

/** The first occurrence of each value, in order. */
export function unique<T>(values: Iterable<T>): T[] {
  return [...new Set(values)];
}

// ------------------------------------------------------ reference spellings

const PRINTABLE_EXCLUDED = /[\p{C}\p{Z}]/u;

function reprString(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if (ch === quote || ch === "\\") out += "\\" + ch;
    else if (ch === "\t") out += "\\t";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (cp < 0x20 || cp === 0x7f) out += "\\x" + cp.toString(16).padStart(2, "0");
    else if (cp < 0x7f || ch === " ") out += ch;
    else if (!PRINTABLE_EXCLUDED.test(ch)) out += ch;
    else if (cp <= 0xff) out += "\\x" + cp.toString(16).padStart(2, "0");
    else if (cp <= 0xffff) out += "\\u" + cp.toString(16).padStart(4, "0");
    else out += "\\U" + cp.toString(16).padStart(8, "0");
  }
  return out + quote;
}

function reprFloat(x: number): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const sign = x < 0 ? "-" : "";
  const [mantissa, expText] = Math.abs(x).toExponential().split("e");
  const digits = mantissa.replace(".", "");
  const exp = Number(expText);
  if (exp >= -4 && exp < 16) {
    if (exp >= 0) {
      const whole = digits.slice(0, exp + 1).padEnd(exp + 1, "0");
      const frac = digits.slice(exp + 1) || "0";
      return `${sign}${whole}.${frac}`;
    }
    return `${sign}0.${"0".repeat(-exp - 1)}${digits}`;
  }
  const rest = digits.slice(1);
  const e = Math.abs(exp).toString().padStart(2, "0");
  return `${sign}${digits[0]}${rest ? "." + rest : ""}e${exp < 0 ? "-" : "+"}${e}`;
}

/** The reference host's `repr` of JSON-like data (`'a'`, `None`, `[1, 'b']`, `{'k': True}`). */
export function pyRepr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "string") return reprString(value);
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number") {
    return Number.isInteger(value) && Math.abs(value) < 1e16 ? String(value) : reprFloat(value);
  }
  if (Array.isArray(value)) return "[" + value.map(pyRepr).join(", ") + "]";
  if (isPlainObject(value)) {
    return "{" + Object.keys(value).map((k) => `${reprString(k)}: ${pyRepr(value[k])}`).join(", ") + "}";
  }
  return String(value);
}

/** The reference host's `str`: text as itself, everything else as {@link pyRepr}. */
export function pyStr(value: unknown): string {
  return typeof value === "string" ? value : pyRepr(value);
}

/**
 * JSON text, spelled the way the vocabulary specs legislate: numbers per
 * kernel §7a, two layouts (ECMAScript `JSON.stringify(v, null, n)` indented,
 * or one line with `, ` / `: `), strict reading (no NaN, no duplicate
 * members). Both the json format and the json_object reader go through it,
 * so they cannot disagree — and neither can the two implementations.
 */

import { formatNumber, hasToJSON, isPlainObject, jsonString, memberNames, parseJson, parseJsonAt, type Json } from "../json.ts";

export function dumps(value: unknown, indent: number | null = 2): string {
  const out: string[] = [];
  write(value, out, indent, 0);
  return out.join("");
}

function write(value: unknown, out: string[], indent: number | null, depth: number): void {
  if (value === null) out.push("null");
  else if (value === true) out.push("true");
  else if (value === false) out.push("false");
  else if (typeof value === "bigint") out.push(value.toString());
  else if (typeof value === "number") out.push(formatNumber(value));
  else if (typeof value === "string") out.push(jsonString(value));
  else if (hasToJSON(value)) write(value.toJSON(), out, indent, depth);
  else if (Array.isArray(value)) {
    if (!value.length) {
      out.push("[]");
      return;
    }
    out.push("[");
    members(value.map((v) => [null, v] as [string | null, unknown]), out, indent, depth, false);
    out.push("]");
  } else if (isPlainObject(value)) {
    const keys = memberNames(value).filter((k) => value[k] !== undefined);
    if (!keys.length) {
      out.push("{}");
      return;
    }
    out.push("{");
    members(keys.map((k) => [k, value[k]] as [string | null, unknown]), out, indent, depth, true);
    out.push("}");
  } else {
    throw new TypeError(`${value === undefined ? "undefined" : typeof value} is not JSON data`);
  }
}

function members(items: [string | null, unknown][], out: string[], indent: number | null, depth: number, keyed: boolean): void {
  let sep: string;
  let pad: string;
  let end: string;
  if (indent === null) {
    sep = ", ";
    pad = "";
    end = "";
  } else {
    pad = "\n" + " ".repeat(indent * (depth + 1));
    sep = "," + pad;
    end = "\n" + " ".repeat(indent * depth);
  }
  items.forEach(([k, v], i) => {
    out.push(i === 0 ? pad : sep);
    if (keyed) out.push(jsonString(k!) + ": ");
    write(v, out, indent, depth + 1);
  });
  out.push(end);
}

/** Strict RFC 8259: no NaN/Infinity, no duplicate members. Throws on failure. */
export function loads(text: string): Json {
  return parseJson(text, { duplicates: "reject" });
}

function ws(s: string, i: number): number {
  while (i < s.length && " \t\n\r".includes(s[i])) i++;
  return i;
}

/**
 * One JSON object's top-level members as `[key, value, sourceText]`, in
 * document order, duplicates kept (the reader decides what a duplicate
 * means). Throws when the text is not a JSON object.
 */
export function members_(text: string): [string, Json, string][] {
  const s = text;
  let i = ws(s, 0);
  if (i >= s.length || s[i] !== "{") throw new Error("not a JSON object");
  i = ws(s, i + 1);
  const out: [string, Json, string][] = [];
  const end = (at: number) => {
    if (ws(s, at) !== s.length) throw new Error("trailing data after the JSON object");
  };
  if (i < s.length && s[i] === "}") {
    end(i + 1);
    return out;
  }
  for (;;) {
    if (i >= s.length || s[i] !== '"') throw new Error(`expected a member name at ${i}`);
    const [key, afterKey] = parseJsonAt(s, i, { duplicates: "reject" });
    i = ws(s, afterKey);
    if (i >= s.length || s[i] !== ":") throw new Error(`expected ':' at ${i}`);
    i = ws(s, i + 1);
    const [value, j] = parseJsonAt(s, i, { duplicates: "reject" });
    out.push([key as string, value, s.slice(i, j)]);
    i = ws(s, j);
    if (i < s.length && s[i] === ",") {
      i = ws(s, i + 1);
      continue;
    }
    if (i < s.length && s[i] === "}") {
      end(i + 1);
      return out;
    }
    throw new Error(`expected ',' or '}' at ${i}`);
  }
}

export { members_ as members };

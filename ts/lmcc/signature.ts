// Kernel §1: the signature (validated data) and the closed shape set.

import { refuse } from "./refusal.ts";
import { dumpJson, isJsonObject, type Json } from "./json.ts";
import { spellInteger } from "./text.ts";

export type Direction = "input" | "output";

export interface Field {
  name: string;
  direction: Direction;
  shape: { [k: string]: Json };
  type?: string;
  role: string;
  desc?: string;
}

export interface Signature {
  instructions: string;
  fields: Field[];
}

export type ScalarType = "string" | "integer" | "number" | "boolean";

export type ShapeInfo =
  | { kind: "scalar"; scalar: ScalarType; nullable: boolean }
  | { kind: "enum"; members: (string | number | bigint)[]; nullable: boolean }
  | { kind: "media"; media: string }
  | { kind: "structured"; structural: string };

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ROLE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;
const SCALARS: ReadonlySet<string> = new Set(["string", "integer", "number", "boolean"]);

/** Plain-data form → Signature; refuses `signature-malformed` naming the offender. */
export function signatureFromData(data: unknown): Signature {
  const bad = (hint: string, field?: string): never =>
    refuse("signature-malformed", hint, { fix: field === undefined ? { action: "edit-signature" } : { action: "edit-signature", field }, stage: "signature" });
  if (!isJsonObject(data)) return bad("signature must be an object");
  if (typeof data.instructions !== "string") return bad("signature.instructions must be a string");
  if (!Array.isArray(data.fields)) return bad("signature.fields must be an array");
  const fields: Field[] = [];
  const seen = new Set<string>();
  for (const raw of data.fields) {
    if (!isJsonObject(raw)) return bad("each field must be an object");
    const name = raw.name;
    if (typeof name !== "string" || !IDENT.test(name)) return bad(`field name ${JSON.stringify(name)} is not an ASCII identifier`, typeof name === "string" ? name : undefined);
    if (seen.has(name)) return bad(`field name ${JSON.stringify(name)} is duplicated`, name);
    seen.add(name);
    if (raw.direction !== "input" && raw.direction !== "output") return bad(`field ${name}: direction must be "input" or "output"`, name);
    if (!isJsonObject(raw.shape)) return bad(`field ${name}: shape must be an object`, name);
    const field: Field = { name, direction: raw.direction, shape: raw.shape, role: "plain" };
    if (raw.role !== undefined) {
      if (typeof raw.role !== "string" || !ROLE.test(raw.role)) return bad(`field ${name}: role must be a dotted identifier`, name);
      field.role = raw.role;
    }
    if (raw.desc !== undefined) {
      if (typeof raw.desc !== "string") return bad(`field ${name}: desc must be a string`, name);
      field.desc = raw.desc;
    }
    if (raw.type !== undefined) {
      if (typeof raw.type !== "string" || raw.type.length === 0) return bad(`field ${name}: type must be a non-empty string`, name);
      field.type = raw.type;
    }
    for (const k of Object.keys(raw)) {
      if (!["name", "direction", "shape", "role", "desc", "type"].includes(k)) return bad(`field ${name}: unknown key ${JSON.stringify(k)}`, name);
    }
    fields.push(field);
  }
  return { instructions: data.instructions, fields };
}

function isNullType(s: unknown): boolean {
  return isJsonObject(s) && s.type === "null" && Object.keys(s).length === 1;
}

function classifyBase(shape: { [k: string]: Json }): ShapeInfo | null {
  // enum wins over type (corpus 06, 35: {"type": "string", "enum": [...]})
  if (Array.isArray(shape.enum)) {
    const members: (string | number | bigint)[] = [];
    for (const m of shape.enum) {
      if (typeof m === "string" || typeof m === "number" || typeof m === "bigint") members.push(m);
      else return null;
    }
    return { kind: "enum", members, nullable: false };
  }
  if (typeof shape.type === "string" && SCALARS.has(shape.type)) {
    return { kind: "scalar", scalar: shape.type as ScalarType, nullable: false };
  }
  return null;
}

export function classifyShape(shape: { [k: string]: Json }): ShapeInfo {
  if (typeof shape.media === "string") return { kind: "media", media: shape.media };
  const base = classifyBase(shape);
  if (base) return base;
  // nullable forms
  if (Array.isArray(shape.type) && shape.type.length === 2 && shape.type.includes("null")) {
    const other = shape.type.find((t) => t !== "null");
    if (typeof other === "string" && SCALARS.has(other)) {
      return { kind: "scalar", scalar: other as ScalarType, nullable: true };
    }
  }
  if (Array.isArray(shape.anyOf) && shape.anyOf.length === 2 && Object.keys(shape).length === 1) {
    const [a, b] = shape.anyOf;
    const nullIdx = isNullType(a) ? 0 : isNullType(b) ? 1 : -1;
    if (nullIdx >= 0) {
      const other = nullIdx === 0 ? b : a;
      if (isJsonObject(other)) {
        const inner = classifyBase(other);
        if (inner && inner.kind !== "media" && inner.kind !== "structured") return { ...inner, nullable: true };
      }
    }
  }
  return { kind: "structured", structural: structuralKeys(shape)[0] };
}

/** Structural keys, most specific first (kernel §5 step 2). */
export function structuralKeys(shape: { [k: string]: Json }): string[] {
  if (typeof shape.media === "string") return [`media:${shape.media}`, "media:*"];
  const base = classifyBase(shape);
  if (base?.kind === "scalar") return [base.scalar];
  if (base?.kind === "enum") return ["enum"];
  if (shape.type === "object") return ["object", "*"];
  if (shape.type === "array") {
    const items = shape.items;
    if (isJsonObject(items)) {
      if (items.type === "object") return ["list[object]", "list[*]", "*"];
      const ib = classifyBase(items);
      if (ib?.kind === "scalar") return [`list[${ib.scalar}]`, "list[*]", "*"];
    }
    return ["list[*]", "*"];
  }
  if (isNullableShape(shape)) return []; // nullable: no structural key (stated guess, AUDIT G)
  return ["*"];
}

function isNullableShape(shape: { [k: string]: Json }): boolean {
  if (Array.isArray(shape.type) && shape.type.length === 2 && shape.type.includes("null")) {
    const other = shape.type.find((t) => t !== "null");
    return typeof other === "string" && SCALARS.has(other);
  }
  if (Array.isArray(shape.anyOf) && shape.anyOf.length === 2 && Object.keys(shape).length === 1) {
    const [a, b] = shape.anyOf;
    const nullIdx = isNullType(a) ? 0 : isNullType(b) ? 1 : -1;
    if (nullIdx < 0) return false;
    const other = nullIdx === 0 ? b : a;
    return isJsonObject(other) && classifyBase(other) !== null;
  }
  return false;
}

/** The mechanical hint: what the model is told about a kernel shape. */
export function mechanicalHint(field: Field): string {
  const info = classifyShape(field.shape);
  switch (info.kind) {
    case "scalar":
      return info.scalar === "string" ? "" : `(${info.scalar})`;
    case "enum":
      return "one of: " + info.members.map((m) => (typeof m === "string" ? m : spellInteger(m))).join(", ");
    case "media":
      return `(${info.media})`;
    case "structured":
      return dumpJson(field.shape, null);
  }
}

export function isStructured(field: Field): boolean {
  return classifyShape(field.shape).kind === "structured";
}

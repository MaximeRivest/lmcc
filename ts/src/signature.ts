/**
 * Signatures (kernel §1): the frontend-neutral typed contract.
 *
 * Two surfaces lower to the same data:
 *
 * - `signatureFromDict` / `signatureToDict`: the plain-data form
 *   (schema/signature.schema.json), byte-compatible with every
 *   implementation — use it when a signature must mean exactly the same
 *   thing in two languages (turn fingerprints hash it, §3a).
 * - `signature(instructions, {inputs, outputs})` with the `t` shape
 *   builders: TypeScript's equivalent of annotations. The builders produce
 *   plain JSON Schema and carry a static type, so `plan.parse` is typed.
 *
 * Type names are the frontend's own (§1): the builders name nothing unless
 * you pass `type`, because TypeScript types do not exist at run time. That is
 * the stated place where two frontends of one signature may differ (Python
 * writes `str`, `int`, `list[Person]`); `signatureFromDict` never differs.
 */

import { refuse } from "./errors.ts";
import { copyObject, deepCopy, memberNames, type Json, type JsonObject } from "./json.ts";
import { isObj, type Field, type Shape } from "./core.ts";
import { isIdentifier, pyRepr, PURPOSE_RE } from "./text.ts";
import { brand } from "./brand.ts";

const DIRECTIONS = ["input", "output"];

/** A JSON-Schema shape carrying the static type of its values (erased at run time). */
export type TypedShape<T> = JsonObject & { readonly __lmcc_value?: T };

/** A field spec: a shape plus purpose, description and type name. */
export interface FieldSpec<T = unknown> {
  readonly __lmcc_field: true;
  readonly shape: TypedShape<T>;
  readonly purpose: string;
  readonly desc: string | null;
  readonly type: string | null;
}

type SpecValue<S> = S extends FieldSpec<infer T> ? T : S extends TypedShape<infer T> ? (unknown extends T ? unknown : T) : unknown;
export type ValuesOf<M> = { [K in keyof M]: SpecValue<M[K]> };

/** A field as a caller writes it: `purpose` defaults to `"plain"`, `type` and `desc` to none. */
export interface FieldInput {
  readonly name: string;
  readonly direction: "input" | "output";
  readonly shape: Shape;
  readonly type?: string | null;
  readonly purpose?: string;
  readonly desc?: string | null;
}

/**
 * A signature (kernel §1): instructions and ordered fields. Constructing one
 * validates it (`signature-malformed`, naming the offender), so an invalid
 * signature cannot exist. Fields and shapes are copied and frozen: the
 * signature's fingerprint (§3a) cannot change after it is made.
 *
 * `new Signature(instructions, fields)` is the surface for frontends that
 * build fields themselves; `signature(...)` with the `t` builders and
 * `signatureFromDict(...)` are the others.
 */
export class Signature<I = Record<string, unknown>, O = Record<string, unknown>> {
  readonly instructions: string;
  readonly fields: readonly Field[];
  /** Phantom members: the static types of inputs and outputs. */
  declare readonly __inputs?: I;
  declare readonly __outputs?: O;

  constructor(instructions: string, fields: readonly FieldInput[]) {
    if (typeof instructions !== "string") {
      refuse("signature-malformed", `instructions must be text, not ${instructions === null ? "None" : Array.isArray(instructions) ? "list" : typeof instructions}`,
        { fix: { action: "edit-signature" } });
    }
    if (!Array.isArray(fields)) refuse("signature-malformed", "a signature is an object with a fields list", { fix: { action: "edit-signature" } });
    this.instructions = instructions;
    this.fields = Object.freeze(fields.map((input): Field => {
      if (!isObj(input)) refuse("signature-malformed", "each field is an object", { fix: { action: "edit-signature" } });
      const f = input as unknown as FieldInput;
      return Object.freeze({
        name: f.name,
        direction: f.direction,
        shape: deepFreeze(deepCopy(f.shape)),
        type: f.type === undefined ? null : f.type,
        purpose: f.purpose === undefined ? "plain" : f.purpose,
        desc: f.desc === undefined ? null : f.desc,
      });
    }));
    validate(this.fields);
  }

  get inputs(): Field[] {
    return this.fields.filter((f) => f.direction === "input");
  }

  get outputs(): Field[] {
    return this.fields.filter((f) => f.direction === "output");
  }

  fieldNamed(name: string): Field | undefined {
    return this.fields.find((f) => f.name === name);
  }

  toJSON(): JsonObject {
    return signatureToDict(this);
  }
}

function fixField(f: { name: unknown }): { action: string; field?: string } {
  return typeof f.name === "string" && f.name ? { action: "edit-signature", field: f.name } : { action: "edit-signature" };
}

function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    for (const k of memberNames(value)) deepFreeze((value as Record<string, unknown>)[k]);
    Object.freeze(value);
  }
  return value;
}

/** The rules of schema/signature.schema.json plus name uniqueness. */
function validate(fields: readonly Field[]): void {
  const seen = new Set<string>();
  for (const f of fields) {
    const raw = f as unknown as Record<string, unknown>;
    if (!isIdentifier(f.name)) {
      refuse("signature-malformed", `field name ${pyRepr(f.name)} is not an ASCII identifier ([A-Za-z_][A-Za-z0-9_]*)`, { fix: fixField(f) });
    }
    if (seen.has(f.name)) refuse("signature-malformed", `field ${pyRepr(f.name)} is declared twice`, { fix: fixField(f) });
    seen.add(f.name);
    if (!DIRECTIONS.includes(raw["direction"] as string)) {
      refuse("signature-malformed", `field ${pyRepr(f.name)}: direction ${pyRepr(raw["direction"])} is not input/output`, { fix: fixField(f) });
    }
    if (!isObj(raw["shape"])) refuse("signature-malformed", `field ${pyRepr(f.name)}: shape must be an object`, { fix: fixField(f) });
    if (typeof raw["purpose"] !== "string" || !PURPOSE_RE.test(raw["purpose"])) {
      refuse("signature-malformed", `field ${pyRepr(f.name)}: purpose ${pyRepr(raw["purpose"])} is not a (dotted) identifier`, { fix: fixField(f) });
    }
    if (raw["type"] !== null && typeof raw["type"] !== "string") {
      refuse("signature-malformed", `field ${pyRepr(f.name)}: type must be a string`, { fix: fixField(f) });
    }
    if (raw["desc"] !== null && typeof raw["desc"] !== "string") {
      refuse("signature-malformed", `field ${pyRepr(f.name)}: desc must be a string`, { fix: fixField(f) });
    }
  }
}

/** Load a signature from its plain-data form (the corpus form). */
export function signatureFromDict<I = Record<string, unknown>, O = Record<string, unknown>>(data: unknown): Signature<I, O> {
  if (!isObj(data) || !Array.isArray(data["fields"] ?? [])) {
    refuse("signature-malformed", "a signature is an object with a fields list", { fix: { action: "edit-signature" } });
  }
  const fields: FieldInput[] = [];
  for (const f of (data["fields"] ?? []) as unknown[]) {
    if (!isObj(f)) refuse("signature-malformed", "each field is an object", { fix: { action: "edit-signature" } });
    fields.push({
      name: f["name"] as string,
      direction: f["direction"] as "input" | "output",
      shape: f["shape"] as Shape,
      type: (f["type"] ?? null) as string | null,
      purpose: f["purpose"] as string | undefined,
      desc: (f["desc"] ?? null) as string | null,
    });
  }
  const instructions = data["instructions"] === undefined ? "" : (data["instructions"] as string);
  return new Signature<I, O>(instructions, fields);
}

export function signatureToDict(sig: Signature<unknown, unknown>): JsonObject {
  return {
    instructions: sig.instructions,
    fields: sig.fields.map((f) => {
      const out: JsonObject = { name: f.name, direction: f.direction, shape: f.shape };
      if (f.type) out["type"] = f.type;
      if (f.purpose !== "plain") out["purpose"] = f.purpose;
      if (f.desc !== null) out["desc"] = f.desc;
      return out;
    }),
  };
}

// ------------------------------------------------------------- builders

function isFieldSpec(v: unknown): v is FieldSpec {
  return isObj(v) && v["__lmcc_field"] === true;
}

/** Annotate a shape with a purpose, a description and/or a type name. */
export function field<T>(shape: TypedShape<T>, opts: { purpose?: string; desc?: string; type?: string } = {}): FieldSpec<T> {
  return { __lmcc_field: true, shape, purpose: opts.purpose ?? "plain", desc: opts.desc ?? null, type: opts.type ?? null };
}

type Entries = Record<string, TypedShape<unknown> | FieldSpec<unknown>>;

/**
 * Build a signature: `signature("Answer.", {inputs: {question: t.string()},
 * outputs: {answer: t.string()}})`. Inputs come first, then outputs, each in
 * the order written.
 */
export function signature<IM extends Entries = {}, OM extends Entries = {}>(
  instructions: string,
  spec: { inputs?: IM; outputs?: OM } = {},
): Signature<ValuesOf<IM>, ValuesOf<OM>> {
  const fields: FieldInput[] = [];
  for (const [direction, entries] of [["input", spec.inputs ?? {}], ["output", spec.outputs ?? {}]] as const) {
    for (const name of memberNames(entries)) {
      const value = (entries as Entries)[name];
      const f = isFieldSpec(value) ? value : field(value as TypedShape<unknown>);
      if (!isObj(f.shape)) {
        refuse("unmapped-type", `field ${pyRepr(name)}: a shape is a JSON-Schema object (use the t builders)`,
          { fix: { action: "edit-signature", field: name } });
      }
      fields.push({ name, direction, shape: copyObject<Json>(f.shape), type: f.type, purpose: f.purpose, desc: f.desc });
    }
  }
  return new Signature(instructions, fields);
}

type Members = readonly (string | number)[];

/** Shape builders: plain JSON Schema with a static type for TypeScript. */
export const t = {
  string: (extra: JsonObject = {}): TypedShape<string> => copyObject({ type: "string" }, extra),
  /**
   * An integer. Its values are `number` when exact; beyond ±(2^53 − 1) the
   * kernel carries them as `bigint` (at least int64, kernel §7a).
   */
  integer: (extra: JsonObject = {}): TypedShape<number> => copyObject({ type: "integer" }, extra),
  number: (extra: JsonObject = {}): TypedShape<number> => copyObject({ type: "number" }, extra),
  boolean: (extra: JsonObject = {}): TypedShape<boolean> => copyObject({ type: "boolean" }, extra),
  /** Membership: `t.enum("low", "high")`. */
  enum: <const M extends Members>(...members: M): TypedShape<M[number]> => {
    const shape: JsonObject = { enum: [...members] as Json[] };
    if (members.every((m) => typeof m === "string")) shape["type"] = "string";
    else if (members.every((m) => typeof m === "number" && Number.isInteger(m))) shape["type"] = "integer";
    return shape as TypedShape<M[number]>;
  },
  /** The shape or `null` (kernel §1 nullable form). */
  nullable: <T>(shape: TypedShape<T>): TypedShape<T | null> => ({ anyOf: [shape, { type: "null" }] }),
  /** A list: structured, so it needs a format (kernel §5). */
  list: <T>(items: TypedShape<T>): TypedShape<T[]> => ({ type: "array", items }),
  /** An object with these properties, all required: structured, needs a format. */
  object: <P extends Record<string, TypedShape<unknown>>>(properties: P): TypedShape<{ [K in keyof P]: SpecValue<P[K]> }> => ({
    type: "object",
    properties: properties as unknown as JsonObject,
    required: memberNames(properties),
  }),
  /** An lm15 part of this type (`image`, `document`, …); its value is the part's data. */
  media: (type: string): TypedShape<Record<string, unknown>> => ({ media: type }),
  /** Any JSON Schema, with the static type you declare: `t.json<Person[]>({type: "array"})`. */
  json: <T = unknown>(schema: JsonObject = {}): TypedShape<T> => copyObject<Json>(schema) as TypedShape<T>,
};

brand(Signature, "Signature");

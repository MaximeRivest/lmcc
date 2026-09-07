// Kernel §5 and §7b: formats, kernel defaults, and resolution.

import { refuse } from "./refusal.ts";
import { isJsonObject, type Json } from "./json.ts";
import { classifyShape, structuralKeys, mechanicalHint, type Field } from "./signature.ts";
import { strip, readInteger, readNumber, readBoolean, spellNumber, spellInteger, isIntegerValue } from "./text.ts";

export interface Part {
  kind: string;
  [k: string]: Json;
}

export interface Span {
  parts: Part[];
  /** the stripped text parts joined by "\n" */
  text: string;
}

/** `span.text` is the stripped text of every text-bearing part (any kind) joined by "\n". */
export function makeSpan(parts: Part[]): Span {
  const texts = parts.filter((p) => typeof p.text === "string").map((p) => strip(p.text as string));
  return { parts, text: texts.join("\n") };
}

export function textPart(text: string): Part {
  return { kind: "text", text };
}

/** Thrown by vocabulary formats; the kernel wraps it as format-write-error / format-read-error. */
export class FormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FormatError";
  }
}

export interface FormatContext {
  /** the format bound to a nested shape, for composing formats; refuses no-format at `path` */
  formatFor(shape: { [k: string]: Json }, path: string): Format;
}

export interface Format {
  /** registry name (`json`) or a kernel name (`kernel:scalar`) */
  name: string;
  /** vocabulary entry name (`format/json`) when registered */
  vocab?: string;
  version?: string;
  accepts: string[];
  direction: "in" | "out" | "both";
  emits: "text" | "parts";
  /** span kinds `read` accepts */
  reads: string[];
  roundTrip: boolean;
  options?: { [k: string]: Json };
  write(value: unknown, field: Field, ctx: FormatContext): Part[] | string;
  read(span: Span, field: Field, ctx: FormatContext): unknown;
  describe?(field: Field, ctx: FormatContext): string;
}

// ---------------------------------------------------------------------------
// Kernel defaults (§7b)

function spellScalar(value: unknown, field: Field): string {
  const info = classifyShape(field.shape);
  const bad = (why: string): never => refuse("value-invalid", `field ${field.name}: ${why}`, { stage: "render" });
  if (info.kind === "scalar" || info.kind === "enum") {
    if (value === null || value === undefined) {
      if (info.nullable) return "null";
      return bad("null where the shape is not nullable");
    }
  }
  if (info.kind === "enum") {
    for (const m of info.members) {
      if (typeof m === "string" ? value === m : isIntegerValue(value) && BigInt(value) === BigInt(m)) {
        return typeof m === "string" ? m : spellInteger(m);
      }
    }
    return bad(`value is not an enum member`);
  }
  if (info.kind === "scalar") {
    switch (info.scalar) {
      case "string":
        if (typeof value !== "string") return bad("expected a string");
        return value;
      case "integer":
        if (!isIntegerValue(value)) return bad("expected an integer");
        return spellInteger(value);
      case "number":
        if (typeof value === "bigint") return value.toString();
        if (typeof value !== "number") return bad("expected a number");
        if (!Number.isFinite(value)) return bad("non-finite number");
        return spellNumber(value);
      case "boolean":
        if (typeof value !== "boolean") return bad("expected a boolean");
        return value ? "true" : "false";
    }
  }
  return bad("kernel default cannot spell this shape");
}

function readScalar(text: string, field: Field): unknown {
  const info = classifyShape(field.shape);
  const bad = (why: string): never => refuse("parse-value", `field ${field.name}: ${why}: ${JSON.stringify(text)}`, { stage: "parse" });
  const t = strip(text);
  if ((info.kind === "scalar" || info.kind === "enum") && info.nullable && t === "null") return null;
  if (info.kind === "enum") {
    for (const m of info.members) {
      if (typeof m === "string" ? t === m : t === spellInteger(m)) return m;
    }
    return bad("not an enum member");
  }
  if (info.kind === "scalar") {
    switch (info.scalar) {
      case "string":
        return t;
      case "integer": {
        const v = readInteger(t);
        if (v === null) return bad("integer text must match -?[0-9]+");
        return v;
      }
      case "number": {
        const v = readNumber(t);
        if (v === null) return bad("number text must match -?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?");
        return v;
      }
      case "boolean": {
        const v = readBoolean(t);
        if (v === null) return bad("boolean text must be true|yes|false|no");
        return v;
      }
    }
  }
  return bad("kernel default cannot read this shape");
}

export const KERNEL_SCALAR: Format = {
  name: "kernel:scalar",
  accepts: ["string", "integer", "number", "boolean", "enum"],
  direction: "both",
  emits: "text",
  reads: ["*"], // reads span.text: the text-bearing parts of any kind (corpus 64)
  roundTrip: true,
  write: (value, field) => spellScalar(value, field),
  read: (span, field) => readScalar(span.text, field),
  describe: (field) => mechanicalHint(field),
};

export function kernelMedia(kind: string): Format {
  return {
    name: `kernel:media`,
    accepts: [`media:${kind}`],
    direction: "both",
    emits: "parts",
    reads: [kind],
    roundTrip: true,
    write: (value, field) => {
      if (!isJsonObject(value)) refuse("value-invalid", `field ${field.name}: a media value must be a part object`, { stage: "render" });
      if (value.kind !== undefined && value.kind !== kind) refuse("value-invalid", `field ${field.name}: part kind ${JSON.stringify(value.kind)} is not ${JSON.stringify(kind)}`, { stage: "render" });
      const part: Part = { kind };
      for (const k of Object.keys(value)) if (k !== "kind") part[k] = value[k];
      return [part];
    },
    read: (span, field) => {
      const part = span.parts.find((p) => p.kind === kind);
      if (!part) refuse("parse-value", `field ${field.name}: no ${kind} part in its span`, { stage: "parse" });
      return part;
    },
    describe: (field) => mechanicalHint(field),
  };
}

// ---------------------------------------------------------------------------
// Resolution (§5)

export interface Resolved {
  format: Format;
  /** where the format came from */
  source: "artifact:type" | "artifact:structural" | "kernel";
  /** the artifact key when from the artifact */
  key?: string;
}

/** The `bind-format.key` for a field: type name, else most specific structural key, else `*`. */
export function bindKey(field: Field): string {
  if (field.type) return field.type;
  const keys = structuralKeys(field.shape);
  return keys[0] ?? "*";
}

/**
 * Resolve a field's format against the artifact's entries. `null` means
 * "no format": the caller refuses `no-format`.
 */
export function resolveFormat(field: Field, artifact: Map<string, Format>): Resolved | null {
  if (field.type && artifact.has(field.type)) return { format: artifact.get(field.type)!, source: "artifact:type", key: field.type };
  for (const key of structuralKeys(field.shape)) {
    if (artifact.has(key)) return { format: artifact.get(key)!, source: "artifact:structural", key };
  }
  const info = classifyShape(field.shape);
  if (info.kind === "scalar" || info.kind === "enum") return { format: KERNEL_SCALAR, source: "kernel" };
  if (info.kind === "media") return { format: kernelMedia(info.media), source: "kernel" };
  return null;
}

/** Does the format's `accepts` cover the field? */
export function formatAccepts(format: Format, field: Field): boolean {
  if (format.accepts.includes("*")) return true;
  if (format.name.startsWith("kernel:")) return true; // kernel defaults are chosen by shape
  if (field.type && format.accepts.includes(field.type)) return true;
  const keys = structuralKeys(field.shape);
  const info = classifyShape(field.shape);
  if (info.kind === "media") keys.push("media:*");
  return keys.some((k) => k !== "*" && format.accepts.includes(k));
}

/** Does the format's `read` accept a span of this kind? */
export function formatReads(format: Format, kind: string): boolean {
  return format.reads.includes("*") || format.reads.includes(kind);
}

/** Normalize a write result to parts. */
export function toParts(result: Part[] | string): Part[] {
  if (typeof result === "string") return [textPart(result)];
  return result;
}

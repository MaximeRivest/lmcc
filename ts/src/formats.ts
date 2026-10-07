/**
 * Formats: how a type is written and read (kernel §5).
 *
 * A format is `write(value, field) → text | parts`, `read(capture, field) →
 * value`, and optionally `describe(field) → text`. It declares what it
 * `accepts` (type names, structural keys, `*`), its `direction`, what it
 * `writes` (`text` or `parts`), whether it round-trips, and the capture
 * kinds its `read` accepts.
 *
 * Shipped code (a UDF entry in an artifact) is admitted by the loader and
 * never run by it. This runtime places no UDF language: a JavaScript
 * format is a closure, not portable source with a checkable boundary, so a
 * shipped format refuses `format-untrusted` or `udf-unplaceable` here, and
 * `dump` of a code-built format refuses rather than drop it. Runtime
 * formats bind by type name through the registry (never serialized).
 */

import { refuse } from "./errors.ts";
import { Capture, isObj, nullableBase, isMedia, readValue, shapeSummary, spellValue, structuralKeys, SCALAR_TYPES, type Field, type Part } from "./core.ts";
import { pyRepr, pyStr } from "./text.ts";
import { hasOwn, isPlainObject, memberNames, setMember } from "./json.ts";

export type Direction = "in" | "out" | "both";

export interface Format {
  /** The registered name, for named formats; `null` for inline ones. */
  name: string | null;
  readonly accepts: readonly string[];
  readonly direction: Direction;
  readonly writes: "text" | "parts";
  readonly roundTrip: boolean;
  /** Capture kinds `read` accepts (`text`, an lm15 part type, or `*`). */
  readonly reads: readonly string[];
  describe(field: Field): string | null;
  write(value: unknown, field: Field): string | Part[];
  read?(capture: Capture, field: Field): unknown;
  /** A shipped UDF entry, kept whole for `dump`. */
  shipped?: Record<string, unknown>;
}

export interface FormatSpec {
  write: (value: any, field: Field) => string | Part[];
  read?: (capture: Capture, field: Field) => unknown;
  describe?: (field: Field) => string | null;
  accepts?: string | readonly string[];
  direction?: Direction;
  writes?: "text" | "parts";
  roundTrip?: boolean;
  reads?: readonly string[];
  name?: string | null;
}

/** Build a format from functions: the `lmcc.format(...)` surface. */
export function makeFormat(spec: FormatSpec): Format {
  const accepts = typeof spec.accepts === "string" ? [spec.accepts] : [...(spec.accepts ?? ["*"])];
  const format: Format = {
    name: spec.name ?? null,
    accepts,
    direction: spec.direction ?? (spec.read ? "both" : "in"),
    writes: spec.writes ?? "text",
    roundTrip: spec.roundTrip ?? true,
    reads: [...(spec.reads ?? ["text"])],
    describe: (field) => (spec.describe ? spec.describe(field) : null),
    write: spec.write,
  };
  if (spec.read) format.read = spec.read;
  return format;
}

export function isFormat(value: unknown): value is Format {
  return isObj(value) && typeof value["write"] === "function" && Array.isArray(value["accepts"]);
}

/** Kernel §7b: scalars, enums and nullables by §7a; reads any text-bearing capture. */
export const SCALAR_DEFAULT: Format = Object.freeze({
  name: "kernel-scalar",
  accepts: [...SCALAR_TYPES, "enum"],
  direction: "both" as const,
  writes: "text" as const,
  roundTrip: true,
  reads: ["*"],
  describe: (field: Field) => shapeSummary(field.shape) || null,
  write: (value: unknown, field: Field) => spellValue(field.shape, value, `field ${pyRepr(field.name)}`, field.name),
  read: (capture: Capture, field: Field) => readValue(field.shape, capture.text, `field ${pyRepr(field.name)}`),
});

/** Kernel §7b: a media value is its part's data; reading takes the first part of the kind. */
const MEDIA_MEMBERS = ["media_type", "data", "url", "file_id", "path", "continuation"] as const;
/** lm15's media parts and their members besides `type` (the pinned contract's spec/types.md); §7b writes these kinds exactly as lm15 serializes them. */
export const MEDIA_PART_MEMBERS = {
  image: ["media_type", "data", "url", "file_id", "path", "detail", "continuation"],
  audio: [...MEDIA_MEMBERS], video: [...MEDIA_MEMBERS], document: [...MEDIA_MEMBERS], binary: [...MEDIA_MEMBERS],
} as const satisfies Record<string, readonly string[]>;

/** lm15's omission rule: null, "", [] and {} are left out (undefined is absent anyway). */
function isEmptyMember(v: unknown): boolean {
  return v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0) || (isPlainObject(v) && memberNames(v).length === 0);
}

export const MEDIA_DEFAULT: Format = Object.freeze({
  name: "kernel-media",
  accepts: ["media:*"],
  direction: "both" as const,
  writes: "parts" as const,
  roundTrip: true,
  reads: ["*"],
  describe: (field: Field) => `(${pyStr(field.shape["media"])})`,
  write: (value: unknown, field: Field): Part[] => {
    const kind = field.shape["media"] as string;
    if (!isObj(value)) refuse("value-invalid", `field ${pyRepr(field.name)}: a media value must be a plain object of part data`);
    if ("type" in value && value["type"] !== kind) {
      refuse("value-invalid", `field ${pyRepr(field.name)}: a ${pyRepr(value["type"])} part given where a ${pyRepr(kind)} part is declared`);
    }
    const part: Record<string, unknown> = { type: kind };
    const members: readonly string[] | null = hasOwn(MEDIA_PART_MEMBERS, kind) ? MEDIA_PART_MEMBERS[kind as keyof typeof MEDIA_PART_MEMBERS] : null;
    for (const k of memberNames(value)) {
      if (k === "type") continue;
      if (members === null) {
        setMember(part, k, value[k]); // not one of lm15's media parts: written as given
        continue;
      }
      // §7b: exactly as lm15 serializes the part
      if (!members.includes(k)) {
        refuse("value-invalid", `field ${pyRepr(field.name)}: ${pyRepr(k)} is not a member of lm15's ${kind} part (${members.join(", ")}); give the part's data, or an lm15 part through its bridge`);
      }
      if (k !== "media_type" && isEmptyMember(value[k])) continue; // lm15's omission rule
      setMember(part, k, value[k]);
    }
    return [part as Part];
  },
  read: (capture: Capture, field: Field) => {
    const parts = capture.of(field.shape["media"] as string);
    if (!parts.length) refuse("parse-value", `field ${pyRepr(field.name)}: no ${pyStr(field.shape["media"])} part in the capture`);
    const out: Record<string, unknown> = {};
    for (const k of memberNames(parts[0])) if (k !== "type") setMember(out, k, parts[0][k]);
    return out;
  },
});

export function kernelDefault(shape: Record<string, unknown>): Format | null {
  const [base] = nullableBase(shape as never);
  if (isMedia(base)) return MEDIA_DEFAULT;
  if ("enum" in base || (SCALAR_TYPES as readonly string[]).includes(base["type"] as string)) return SCALAR_DEFAULT;
  return null;
}

export function accepts(fmt: Format, field: Field): boolean {
  const keys = new Set([...structuralKeys(field.shape), "*"]);
  if (field.type) keys.add(field.type);
  return fmt.accepts.some((a) => keys.has(a));
}

/** Kernel §5: this runtime places no shipped code; say so by the admission rules. */
export function loadUdf(entry: Record<string, unknown>, where: string): Format {
  refuse("udf-unplaceable", `${where}: this host places no UDF language (a TypeScript runtime cannot admit ${pyRepr(entry["language"])} source); bind a runtime format for the type instead`,
    { fix: { action: "place-udf", language: pyStr(entry["language"]), path: where } });
}

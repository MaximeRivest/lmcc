/**
 * Standard formats: json, table, scaled_number (spec/vocab/format-*.md).
 *
 * Each format is one spelling of a value. Normative behavior (escaping,
 * nulls, fences) lives in contract/spec/vocab/ and is pinned by corpus
 * cases: two implementations that disagree have a failing test, not an
 * argument. Values are plain JSON here; TypeScript types are erased, so there
 * is no host-type lifting (the Python pack lifts dataclasses and Enums).
 */

import { Refusal } from "../errors.ts";
import { readValue, type Field, type Shape } from "../core.ts";
import type { Format } from "../formats.ts";
import { formatNumber, hasToJSON, isPlainObject } from "../json.ts";
import type { Registry } from "../registry.ts";
import { strip, pyRepr } from "../text.ts";
import { dumps, loads } from "./jsontext.ts";
import type { Capture } from "../core.ts";

export const VERSION = "0.1.0";
export const TABLE_VERSION = "0.2.0";
export const SCALED_NUMBER_VERSION = "0.2.0";

const FENCE = /^[ \t\n\r\f\v]*```[a-zA-Z0-9_-]*[ \t\n\r\f\v]*\n(.*?)\n?[ \t\n\r\f\v]*```[ \t\n\r\f\v]*$/s;

/** Objects with `toJSON` become their JSON (as `JSON.stringify` does); plain data passes through. */
export function lower(value: unknown): unknown {
  if (hasToJSON(value)) return lower(value.toJSON());
  if (Array.isArray(value)) return value.map(lower);
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value)) out[k] = lower(value[k]);
    return out;
  }
  return value;
}

abstract class Base implements Format {
  name: string | null = null;
  abstract readonly accepts: readonly string[];
  direction: "in" | "out" | "both" = "both";
  writes: "text" | "parts" = "text";
  roundTrip = true;
  reads: readonly string[] = ["text"];
  describe(_field: Field): string | null {
    return null;
  }
  abstract write(value: unknown, field: Field): string;
}

/** Values spelled as JSON. Options: `indent` (default 2). */
export class JsonFormat extends Base {
  readonly accepts = ["*"];
  readonly indent: number | null;

  constructor(options: Record<string, unknown>) {
    super();
    this.indent = "indent" in options ? (options["indent"] as number | null) : 2;
  }

  override describe(field: Field): string {
    return "JSON matching this schema: " + dumps(field.shape, null);
  }

  write(value: unknown): string {
    return dumps(lower(value), this.indent);
  }

  read(capture: Capture): unknown {
    let text = capture.text;
    const m = FENCE.exec(text);
    if (m) text = m[1];
    return loads(text);
  }
}

function cellRead(shape: Shape, text: string, where: string): unknown {
  try {
    return readValue(shape, text, where);
  } catch (err) {
    if (err instanceof Refusal) throw new Error(err.hint);
    throw err;
  }
}

/**
 * A list of flat objects spelled as a delimiter table. Options: `columns`
 * (required), `delimiter` ("|"), `escape` ("\\"), `null` (""). A row whose
 * cells equal the column names is a header and is skipped on parse.
 */
export class TableFormat extends Base {
  readonly accepts = ["list[object]", "list[*]"];
  readonly columns: string[];
  readonly delimiter: string;
  readonly escape: string;
  readonly nullText: string;

  constructor(options: Record<string, unknown>) {
    super();
    if (!("columns" in options)) throw new Error("table codec requires the 'columns' option");
    this.columns = [...(options["columns"] as string[])];
    this.delimiter = (options["delimiter"] as string | undefined) ?? "|";
    this.escape = (options["escape"] as string | undefined) ?? "\\";
    this.nullText = (options["null"] as string | undefined) ?? "";
  }

  override describe(): string {
    const d = this.delimiter;
    return `${d} ` + this.columns.join(` ${d} `) + ` ${d}` + "  (one row per item)";
  }

  write(value: unknown): string {
    const rows: string[] = [];
    for (const item of lower(value) as Record<string, unknown>[]) {
      const cells = this.columns.map((col) => {
        const raw = item[col];
        let cell = raw === undefined || raw === null ? this.nullText : spellCell(raw, col);
        cell = cell.split(this.escape).join(this.escape + this.escape);
        cell = cell.split(this.delimiter).join(this.escape + this.delimiter);
        return cell;
      });
      const d = this.delimiter;
      rows.push(`${d} ` + cells.join(` ${d} `) + ` ${d}`);
    }
    return rows.join("\n");
  }

  read(capture: Capture, field: Field): unknown {
    const items = (field.shape["items"] || {}) as Record<string, unknown>;
    const itemProps = (items["properties"] ?? {}) as Record<string, Shape>;
    const out: Record<string, unknown>[] = [];
    const lines = capture.text.split("\n");
    const rows = lines.filter((ln) => strip(ln).startsWith(this.delimiter));
    if (!rows.length && strip(capture.text)) {
      throw new Error(`no table row (a line starting with ${pyRepr(this.delimiter)}) in ${pyRepr(Array.from(strip(capture.text)).slice(0, 60).join(""))}; an empty table is written as nothing`);
    }
    for (let line of lines) {
      line = strip(line);
      if (!line.startsWith(this.delimiter)) continue;
      const cells = this.split(line);
      if (cells.map((c) => strip(c)).join("\u0000") === this.columns.join("\u0000") && cells.length === this.columns.length) continue;
      if (cells.length !== this.columns.length) {
        throw new Error(`row has ${cells.length} cells, expected ${this.columns.length} (${pyRepr(this.columns)}): ${pyRepr(line)}`);
      }
      const item: Record<string, unknown> = {};
      this.columns.forEach((col, i) => {
        const cell = strip(cells[i]);
        item[col] = cell === this.nullText ? null : cellRead(itemProps[col] ?? {}, cell, `column ${pyRepr(col)}`);
      });
      out.push(item);
    }
    return out;
  }

  private split(line: string): string[] {
    let inner = line.slice(this.delimiter.length);
    if (inner.endsWith(this.delimiter)) inner = inner.slice(0, inner.length - this.delimiter.length);
    const cells: string[] = [];
    let cur = "";
    let i = 0;
    while (i < inner.length) {
      const ch = inner[i];
      if (ch === this.escape && i + 1 < inner.length) {
        cur += inner[i + 1];
        i += 2;
        continue;
      }
      if (inner.startsWith(this.delimiter, i)) {
        cells.push(cur);
        cur = "";
        i += this.delimiter.length;
        continue;
      }
      cur += ch;
      i++;
    }
    cells.push(cur);
    return cells;
  }
}

function spellCell(cell: unknown, col: string): string {
  if (typeof cell === "string") return cell;
  if (typeof cell === "boolean") return cell ? "true" : "false";
  if (typeof cell === "bigint" || typeof cell === "number") return formatNumber(cell);
  throw new Error(`column ${pyRepr(col)}: ${Array.isArray(cell) ? "list" : typeof cell} is not a cell value`);
}

/** Kernel §7a rounding: half-to-even on the binary64 value. */
export function roundHalfEven(x: number): number {
  const f = Math.floor(x);
  const diff = x - f;
  if (diff < 0.5) return f;
  if (diff > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

/** Numbers spelled at a friendlier scale (0.78 ⇄ "78%"). Options: `scale` (1), `suffix` (""), `round` (null). */
export class ScaledNumberFormat extends Base {
  readonly accepts = ["number", "integer"];
  readonly scale: number;
  readonly suffix: string;
  readonly round: number | null;

  constructor(options: Record<string, unknown>) {
    super();
    this.scale = (options["scale"] as number | undefined) ?? 1;
    this.suffix = (options["suffix"] as string | undefined) ?? "";
    this.round = (options["round"] as number | null | undefined) ?? null;
    this.roundTrip = this.round === null; // rounding loses digits (plan 09 G4)
  }

  override describe(): string {
    return `a number like ${this.scale === 100 ? 83 : 0.83}${this.suffix}`;
  }

  write(value: unknown): string {
    let scaled = Number(value) * this.scale;
    if (this.round !== null) {
      const p = 10 ** this.round;
      scaled = roundHalfEven(scaled * p) / p;
    }
    return `${formatNumber(scaled)}${this.suffix}`;
  }

  read(capture: Capture): unknown {
    let text = strip(capture.text);
    if (this.suffix && text.endsWith(this.suffix)) text = text.slice(0, text.length - this.suffix.length);
    return (cellRead({ type: "number" }, text, "scaled_number") as number) / this.scale;
  }
}

export function install(registry: Registry, opts: { existOk?: boolean } = {}): void {
  const existOk = opts.existOk ?? true;
  registry.registerFormat("json", (o) => new JsonFormat(o), { version: VERSION, existOk });
  registry.registerFormat("table", (o) => new TableFormat(o), { version: TABLE_VERSION, existOk });
  registry.registerFormat("scaled_number", (o) => new ScaledNumberFormat(o), { version: SCALED_NUMBER_VERSION, existOk });
}

// std formats: json, table, scaled_number (spec/vocab/format-*.md).

import type { Format, Span, Part } from "../lmcc/formats.ts";
import { FormatError } from "../lmcc/formats.ts";
import type { Options } from "../lmcc/registry.ts";
import type { Field } from "../lmcc/signature.ts";
import { classifyShape } from "../lmcc/signature.ts";
import { parseJson, dumpJson, isJsonObject, JsonWriteError, type Json } from "../lmcc/json.ts";
import { strip, spellNumber, spellInteger, readInteger, readNumber, readBoolean, roundHalfEven, isIntegerValue } from "../lmcc/text.ts";

function unwrapFence(text: string): string {
  const t = strip(text);
  if (t.startsWith("```") && t.endsWith("```") && t.length >= 6) {
    const nl = t.indexOf("\n");
    if (nl < 0) return "";
    return strip(t.slice(nl + 1, t.length - 3));
  }
  return t;
}

// --------------------------------------------------------------- json

export function jsonFormat(options: Options): Format {
  let indent: number | null = 2;
  if ("indent" in options) {
    const v = options.indent;
    if (v === null) indent = null;
    else if (typeof v === "number" && Number.isInteger(v) && v >= 0) indent = v;
    else throw new FormatError("json: indent must be an integer or null");
  }
  return {
    name: "json",
    accepts: ["*"],
    direction: "both",
    emits: "text",
    reads: ["*"],
    roundTrip: true,
    describe: (field: Field) => "JSON matching this schema: " + dumpJson(field.shape, null),
    write: (value: unknown) => {
      try {
        return dumpJson(value, indent);
      } catch (e) {
        if (e instanceof JsonWriteError) throw new FormatError(`json: ${e.message}`);
        throw e;
      }
    },
    read: (span: Span) => {
      const doc = unwrapFence(span.text);
      try {
        return parseJson(doc);
      } catch (e) {
        throw new FormatError(`json: ${(e as Error).message}`);
      }
    },
  };
}

// -------------------------------------------------------------- table

function spellCell(v: unknown, nullText: string): string {
  if (v === null || v === undefined) return nullText;
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "bigint") return v.toString();
  if (typeof v === "number") {
    if (!Number.isFinite(v)) throw new FormatError("table: non-finite number");
    return spellNumber(v);
  }
  throw new FormatError("table: nested containers cannot be cells");
}

function readCell(text: string, shape: { [k: string]: Json } | undefined, column: string): unknown {
  if (!shape) return text;
  const info = classifyShape(shape);
  const bad = (): never => {
    throw new FormatError(`table: cell ${JSON.stringify(text)} in column ${column} does not read as ${info.kind === "scalar" ? info.scalar : info.kind}`);
  };
  if ((info.kind === "scalar" || info.kind === "enum") && info.nullable && text === "null") return null;
  if (info.kind === "enum") {
    for (const m of info.members) if (typeof m === "string" ? text === m : text === spellInteger(m)) return m;
    return bad();
  }
  if (info.kind === "scalar") {
    switch (info.scalar) {
      case "integer": {
        const v = readInteger(text);
        return v === null ? bad() : v;
      }
      case "number": {
        const v = readNumber(text);
        return v === null ? bad() : v;
      }
      case "boolean": {
        const v = readBoolean(text);
        return v === null ? bad() : v;
      }
      default:
        return text;
    }
  }
  return text;
}

export function tableFormat(options: Options): Format {
  const columns = options.columns;
  if (!Array.isArray(columns) || columns.length === 0 || columns.some((c) => typeof c !== "string")) throw new FormatError("table: columns (a list of property names) is required");
  const cols = columns as string[];
  const delimiter = typeof options.delimiter === "string" && options.delimiter.length ? options.delimiter : "|";
  const escape = typeof options.escape === "string" && options.escape.length ? options.escape : "\\";
  const nullText = typeof options.null === "string" ? options.null : "";
  const escapeCell = (s: string): string => s.split(escape).join(escape + escape).split(delimiter).join(escape + delimiter);
  const splitCells = (line: string): string[] => {
    const cells: string[] = [];
    let cur = "";
    let i = 0;
    while (i < line.length) {
      if (line.startsWith(escape, i) && i + escape.length < line.length) {
        const next = line.slice(i + escape.length);
        if (next.startsWith(escape)) {
          cur += escape;
          i += 2 * escape.length;
          continue;
        }
        if (next.startsWith(delimiter)) {
          cur += delimiter;
          i += escape.length + delimiter.length;
          continue;
        }
        cur += escape;
        i += escape.length;
        continue;
      }
      if (line.startsWith(delimiter, i)) {
        cells.push(cur);
        cur = "";
        i += delimiter.length;
        continue;
      }
      cur += line[i];
      i++;
    }
    cells.push(cur);
    return cells;
  };
  return {
    name: "table",
    accepts: ["list[object]", "list[*]"],
    direction: "both",
    emits: "text",
    reads: ["*"],
    roundTrip: true,
    describe: () => `${delimiter} ${cols.join(` ${delimiter} `)} ${delimiter}  (one row per item)`,
    write: (value: unknown) => {
      if (!Array.isArray(value)) throw new FormatError("table: value must be a list of objects");
      const lines = value.map((item) => {
        if (!isJsonObject(item)) throw new FormatError("table: every item must be an object");
        const cells = cols.map((c) => escapeCell(spellCell(item[c], nullText)));
        return `${delimiter} ${cells.join(` ${delimiter} `)} ${delimiter}`;
      });
      return lines.join("\n");
    },
    read: (span: Span, field: Field) => {
      const items = isJsonObject(field.shape.items) ? field.shape.items : undefined;
      const props = items && isJsonObject(items.properties) ? items.properties : {};
      const rows: unknown[] = [];
      for (const rawLine of span.text.split("\n")) {
        const line = strip(rawLine);
        if (!line.startsWith(delimiter)) continue;
        let cells = splitCells(line);
        cells.shift(); // before the leading delimiter
        if (cells.length && strip(cells[cells.length - 1]) === "" && line.endsWith(delimiter)) cells.pop();
        cells = cells.map(strip);
        if (cells.length === cols.length && cells.every((c, i) => c === cols[i])) continue; // header
        if (cells.length !== cols.length) throw new FormatError(`table: row has ${cells.length} cells, expected ${cols.length}: ${JSON.stringify(rawLine)}`);
        const row: { [k: string]: unknown } = {};
        cells.forEach((c, i) => {
          const col = cols[i];
          const shape = isJsonObject(props[col]) ? (props[col] as { [k: string]: Json }) : undefined;
          row[col] = c === nullText ? null : readCell(c, shape, col);
        });
        rows.push(row);
      }
      return rows;
    },
  };
}

// ------------------------------------------------------ scaled_number

export function scaledNumberFormat(options: Options): Format {
  const scale = typeof options.scale === "number" ? options.scale : 1;
  const suffix = typeof options.suffix === "string" ? options.suffix : "";
  const round = typeof options.round === "number" && Number.isInteger(options.round) ? options.round : null;
  if (options.round !== undefined && options.round !== null && round === null) throw new FormatError("scaled_number: round must be an integer or null");
  return {
    name: "scaled_number",
    accepts: ["number", "integer"],
    direction: "both",
    emits: "text",
    reads: ["*"],
    roundTrip: round === null,
    describe: () => `a number like ${scale === 100 ? "83" : "0.83"}${suffix}`,
    write: (value: unknown) => {
      if (!(typeof value === "number" || typeof value === "bigint")) throw new FormatError("scaled_number: value must be a number");
      let x = Number(value) * scale;
      if (!Number.isFinite(x)) throw new FormatError("scaled_number: non-finite number");
      if (round !== null) x = roundHalfEven(x, round);
      return spellNumber(x) + suffix;
    },
    read: (span: Span) => {
      let t = strip(span.text);
      if (suffix && t.endsWith(suffix)) t = strip(t.slice(0, t.length - suffix.length));
      const n = readNumber(t);
      if (n === null) throw new FormatError(`scaled_number: ${JSON.stringify(t)} is not a number`);
      return n / scale;
    },
  };
}

export type { Part };
export { isIntegerValue };

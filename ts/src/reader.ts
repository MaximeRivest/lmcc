/**
 * Reading the reply: find rules, captures, and the reader.
 *
 * Find rules run before the reader (kernel §6): each collects a capture of
 * parts for a field and may remove its text matches from what the reader
 * sees. The reader (§4) is one document form with three faces on one
 * object: `split` reads, `join` writes turns, `format` writes the
 * `{format}` skeleton. `derived` is the template read backwards; any other
 * kind is vocabulary through the reader socket.
 */

import { refuse } from "./errors.ts";
import { Capture, textPart, type Field, type Part } from "./core.ts";
import { countOf, pyRepr, rstrip, strip, unique, WHITESPACE } from "./text.ts";

/** A position edit: `[start, end, newLength]`, per stage (§4b). */
export type Edit = [number, number, number];

/** The `pattern/*` binding a plan uses (kernel §10). */
export interface PatternMatcher {
  captures(regex: string, text: string): [number, number, string][];
}

export type FindRule = { readonly from: string; readonly [key: string]: unknown };

/** `[start, end, capture]` for one text rule: the §6 plain scans, or the bound pattern. */
export function textCaptures(text: string, rule: FindRule, pattern: PatternMatcher | null): [number, number, string][] {
  const captures: [number, number, string][] = [];
  if ("between" in rule) {
    const [open, close] = rule["between"] as [string, string];
    let pos = 0;
    for (;;) {
      const i = text.indexOf(open, pos);
      if (i < 0) break;
      const j = text.indexOf(close, i + open.length);
      if (j < 0) break;
      captures.push([i, j + close.length, text.slice(i + open.length, j)]);
      pos = j + close.length;
    }
  } else if ("line_prefixed" in rule) {
    const prefix = rule["line_prefixed"] as string;
    let pos = 0;
    for (const line of text.split("\n")) {
      if (line.startsWith(prefix)) captures.push([pos, pos + line.length, line.slice(prefix.length)]);
      pos += line.length + 1;
    }
  } else {
    return pattern!.captures(rule["pattern"] as string, text);
  }
  return captures;
}

/** Run all find rules; return `[remaining text, {field: Capture}]` (§6). */
export function applyFindRules(text: string, parts: Part[], findRules: [string, FindRule][], pattern: PatternMatcher | null,
  edits: Edit[][] | null = null): [string, Map<string, Capture>] {
  const found = new Map<string, Capture>();
  for (const [fieldName, r] of findRules) {
    let capture: Capture;
    if (r.from.startsWith("part:")) {
      const kind = r.from.slice(r.from.indexOf(":") + 1);
      capture = new Capture(parts.filter((p) => p.type === kind));
    } else {
      const captures = textCaptures(text, r, pattern);
      capture = new Capture(captures.map(([, , cap]) => textPart(cap)));
      if (r["remove"] && captures.length) {
        if (edits !== null) edits.push(captures.map(([start, end]) => [start, end, 0] as Edit));
        const pieces: string[] = [];
        let pos = 0;
        for (const [start, end] of captures) {
          pieces.push(text.slice(pos, start));
          pos = end;
        }
        pieces.push(text.slice(pos));
        text = pieces.join("");
      }
    }
    const prior = found.get(fieldName);
    found.set(fieldName, prior ? new Capture([...prior.parts, ...capture.parts]) : capture);
  }
  return [text, found];
}

// ------------------------------------------------------------------ readers

/** A reader's streaming face (§8): stable raw prefixes per field. */
export interface ReaderStream {
  feed(textDelta: string): Record<string, string>;
  finish(): Record<string, string>;
}

/** One reply document form; three faces on one object (§4). */
export abstract class Reader {
  abstract split(text: string, fieldNames: string[]): Record<string, string>;
  abstract join(spelled: [string, string][]): string;
  format(placeholders: [string, string][]): string {
    return this.join(placeholders);
  }
  requires(): string[] {
    return [];
  }
  requestSettings(_fields: Field[]): Record<string, unknown> {
    return {};
  }
  skeleton(): { prefill?: string; stops?: string[] } {
    return {};
  }
  /** Optional §8 face; vocabulary readers override it. */
  stream(_fieldNames: string[]): ReaderStream | null {
    return null;
  }
  /** The spec a vocabulary reader was built from (for `describe()`). */
  spec?: Record<string, unknown>;
}

function cutAtClose(chunk: string, close: string, name: string): string {
  if (!close) return chunk;
  const count = countOf(chunk, close);
  if (count > 1) {
    refuse("parse-ambiguous", `close marker ${pyRepr(close)} for field ${pyRepr(name)} appears ${count} times in its section — refusing to guess where it ends`);
  }
  const idx = chunk.indexOf(close);
  return idx < 0 ? chunk : chunk.slice(0, idx);
}

export function checkCollisions(spelled: [string, string][], markers: string[]): void {
  for (const [name, value] of spelled) {
    for (const marker of markers) {
      if (marker && value.includes(marker)) {
        refuse("value-collides", `field ${pyRepr(name)}: its spelled value contains the reader marker ${pyRepr(marker)}; the turn could not be read back as written`);
      }
    }
  }
}

// ---------------------------------------------------------- marker repair
//
// Kernel §4a. A marker matches its misspellings through its key: the text
// without ignorable characters, ASCII lowercased. The line feed is not
// ignorable, so a repair never joins lines.

export const IGNORABLE = new Set(" \t\x0b\x0c\r*_#");
export const DECORATION = new Set("*_#");
export const EMPHASIS = new Set("*_");
export const HORIZONTAL = new Set(" \t\x0b\x0c\r");

export function fold(c: string): string {
  return c >= "A" && c <= "Z" ? String.fromCharCode(c.charCodeAt(0) + 32) : c;
}

/** The key a marker is matched by (§4a). */
export function markerKey(text: string): string {
  let out = "";
  for (const c of text) if (!IGNORABLE.has(c)) out += fold(c);
  return out;
}

/** `[repairable, unrepaired]`: markers with a non-empty key no other marker shares. */
export function repairableMarkers(markers: string[]): [string[], string[]] {
  const distinct = unique(markers.filter((m) => m));
  const key = (m: string) => markerKey(m).replace(/^\n+/, "");
  const byKey = new Map<string, string[]>();
  for (const m of distinct) {
    const k = key(m);
    byKey.set(k, [...(byKey.get(k) ?? []), m]);
  }
  const ok = distinct.filter((m) => key(m) && byKey.get(key(m))!.length === 1);
  return [ok, distinct.filter((m) => !ok.includes(m))];
}

/** Where the left decoration of a core begins, or null (§4a). */
export function decorationStart(text: string, runStart: number, coreStart: number): number | null {
  for (let i = runStart; i < coreStart; i++) {
    if (DECORATION.has(text[i]) && (i === 0 || WHITESPACE.includes(text[i - 1]))) return i;
  }
  return null;
}

/** The span of a loose occurrence: its core widened over decoration and leading line feeds. */
export function occurrenceSpan(text: string, coreStart: number, coreEnd: number, runStart: number, lead: number): [number, number] {
  const left = decorationStart(text, runStart, coreStart);
  let start = coreStart;
  let end = coreEnd;
  if (left !== null) {
    start = left;
    let emphasis = false;
    for (let i = left; i < coreStart; i++) if (EMPHASIS.has(text[i])) emphasis = true;
    if (emphasis) while (end < text.length && EMPHASIS.has(text[end])) end++;
  }
  if (lead) {
    let q = start;
    while (q > 0 && HORIZONTAL.has(text[q - 1])) q--;
    let taken = 0;
    while (taken < lead && q > 0 && text[q - 1] === "\n") {
      q--;
      taken++;
    }
    if (taken) start = q;
  }
  return [start, end];
}

type Normalized = [string, number[], number[]];

function normalized(text: string): Normalized {
  let chars = "";
  const pos: number[] = [];
  const runs: number[] = [];
  let run = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (IGNORABLE.has(c)) continue;
    chars += fold(c);
    pos.push(i);
    runs.push(run);
    run = i + 1;
  }
  return [chars, pos, runs];
}

/** Every loose occurrence of `marker` as its span, leftmost first, without overlap. */
export function looseOccurrences(text: string, marker: string, norm: Normalized | null = null): [number, number][] {
  const full = markerKey(marker);
  const key = full.replace(/^\n+/, "");
  if (!key) return [];
  const lead = full.length - key.length;
  const [chars, pos, runs] = norm ?? normalized(text);
  const out: [number, number][] = [];
  let k = chars.indexOf(key);
  while (k >= 0) {
    const last = k + key.length - 1;
    out.push(occurrenceSpan(text, pos[k], pos[last] + 1, runs[k], lead));
    k = chars.indexOf(key, k + key.length);
  }
  return out;
}

/** §4a: the marker occurs as plain text, not as the inside of a larger loose span. */
export function writtenExactly(text: string, marker: string, spans: [number, number][]): boolean {
  let p = text.indexOf(marker);
  while (p >= 0) {
    const q = p + marker.length;
    if (!spans.some(([a, b]) => a <= p && q <= b && b - a > q - p)) return true;
    p = text.indexOf(marker, q);
  }
  return false;
}

export type Repair = Record<string, unknown>;

/** §4a: rewrite every misspelled marker unless it is written exactly somewhere. */
export function repairMarkers(text: string, markers: string[], edits: Edit[][] | null = null): [string, Repair[]] {
  const norm = normalized(text);
  const chosen: [number, number, string][] = [];
  for (const marker of markers) {
    const spans = looseOccurrences(text, marker, norm);
    if (writtenExactly(text, marker, spans)) continue;
    for (const [a, b] of spans) chosen.push([a, b, marker]);
  }
  if (!chosen.length) return [text, []];
  chosen.sort((x, y) => x[0] - y[0] || x[1] - y[1] || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0));
  for (let i = 0; i + 1 < chosen.length; i++) {
    const [a1, b1, m1] = chosen[i];
    const [a2, b2, m2] = chosen[i + 1];
    if (a2 < b1) {
      refuse("parse-ambiguous", `the reply's ${pyRepr(text.slice(a1, b1))} and ${pyRepr(text.slice(a2, b2))} overlap; read as the markers ${pyRepr(m1)} and ${pyRepr(m2)} they would share text — refusing to guess`);
    }
  }
  const pieces: string[] = [];
  const repairs: Repair[] = [];
  let pos = 0;
  if (edits !== null) edits.push(chosen.map(([a, b, marker]) => [a, b, marker.length] as Edit));
  for (const [a, b, marker] of chosen) {
    pieces.push(text.slice(pos, a), marker);
    repairs.push({ repair: "marker", marker, saw: text.slice(a, b) });
    pos = b;
  }
  pieces.push(text.slice(pos));
  return [pieces.join(""), repairs];
}

export function refuseMissing(raw: Record<string, string>, fieldNames: string[]): void {
  const missing = fieldNames.filter((n) => !(n in raw));
  if (missing.length) {
    let hint = "reply is missing pattern section(s): " + missing.map(pyRepr).join(", ");
    if (!Object.keys(raw).length && fieldNames.length > 1) {
      hint += " — it has none of the template's markers: the model did not follow the layout (reading values by their order would be a guess)";
    }
    refuse("parse-missing-fields", hint, { partial: raw });
  }
}

/** What the derived reader found: raw captures, tolerances, fields that ran to the end. */
export interface ReaderResult {
  readonly raw: Record<string, string>;
  readonly repairs: Repair[];
  readonly toEnd: Set<string>;
  readonly spans: Map<string, [number, number]>;
  readonly text: string;
}

export type Anchor = [string, string, string];

/** The template read backwards (§4); `repair` false for a strict adapter (§4a). */
export class DerivedReader extends Reader {
  readonly anchors: Anchor[];
  readonly tail: string;
  repairable: string[];
  unrepaired: string[];

  constructor(anchors: Anchor[], tail = "", repair = true) {
    super();
    this.anchors = [...anchors];
    this.tail = tail;
    const searched = [...this.anchors.map(([, p]) => rstrip(p)), ...this.anchors.map(([, , s]) => strip(s)), strip(this.tail)];
    [this.repairable, this.unrepaired] = repairableMarkers(searched);
    if (!repair) {
      this.repairable = [];
      this.unrepaired = [];
    }
  }

  markers(): string[] {
    const out: string[] = [];
    for (const [, prefix, suffix] of this.anchors) {
      out.push(rstrip(prefix), strip(suffix));
    }
    if (strip(this.tail)) out.push(strip(this.tail));
    return out.filter((m) => m);
  }

  split(text: string, fieldNames: string[]): Record<string, string> {
    return this.read(text, fieldNames).raw;
  }

  read(text: string, fieldNames: string[], opts: { allowMissing?: boolean; edits?: Edit[][] | null } = {}): ReaderResult {
    let repairs: Repair[] = [];
    if (this.repairable.length) [text, repairs] = repairMarkers(text, this.repairable, opts.edits ?? null);
    const wanted = this.anchors.filter(([name]) => fieldNames.includes(name));
    const boundaries: [number, number, string | null, string][] = [];
    for (const [name, prefix, suffix] of wanted) {
      const marker = rstrip(prefix);
      if (!marker) {
        boundaries.push([0, 0, name, suffix]);
        continue;
      }
      const count = countOf(text, marker);
      if (count > 1) refuse("parse-ambiguous", `anchor ${pyRepr(marker)} for field ${pyRepr(name)} appears ${count} times in the reply — refusing to guess`);
      const idx = text.indexOf(marker);
      if (idx < 0) continue;
      boundaries.push([idx, idx + marker.length, name, suffix]);
    }
    const tail = strip(this.tail);
    if (tail) {
      const count = countOf(text, tail);
      if (count > 1) refuse("parse-ambiguous", `tail ${pyRepr(tail)} appears ${count} times in the reply — refusing to guess which one ends the reply`);
      const tIdx = text.indexOf(tail);
      if (tIdx >= 0) boundaries.push([tIdx, tIdx, null, ""]);
    }
    boundaries.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
    const raw: Record<string, string> = {};
    const spans = new Map<string, [number, number]>();
    const toEnd = new Set<string>();
    const notes: Repair[] = [];
    const ignored = (piece: string) => {
      if (strip(piece)) notes.push({ repair: "ignored", saw: strip(piece) });
    };
    if (boundaries.length) ignored(text.slice(0, boundaries[0][0]));
    boundaries.forEach(([start, after, name, suffix], i) => {
      const last = i + 1 === boundaries.length;
      if (name === null) {
        if (last) ignored(text.slice(start + tail.length));
        return;
      }
      const chunk = text.slice(after, last ? text.length : boundaries[i + 1][0]);
      const close = strip(suffix);
      const cut = cutAtClose(chunk, close, name);
      raw[name] = strip(cut);
      spans.set(name, [after, after + cut.length]);
      const idx = close ? chunk.indexOf(close) : -1;
      if (idx >= 0) ignored(chunk.slice(idx + close.length));
      else if (last) toEnd.add(name);
      else if (close) notes.push({ repair: "unclosed", field: name, close });
    });
    if (!opts.allowMissing) refuseMissing(raw, fieldNames);
    return { raw, repairs: [...repairs, ...notes], toEnd, spans, text };
  }

  join(spelled: [string, string][]): string {
    const byName = new Map(spelled);
    checkCollisions(spelled, this.markers());
    const pieces = this.anchors.filter(([name]) => byName.has(name)).map(([name, prefix, suffix]) => prefix + byName.get(name)! + suffix);
    return strip(pieces.join("") + (pieces.length ? this.tail : ""), "\n");
  }

  override skeleton(): { prefill: string; stops: string[] } {
    if (!this.anchors.length) return { prefill: "", stops: [] };
    const prefill = this.anchors[0][1];
    const lastClose = strip(this.anchors[this.anchors.length - 1][2]);
    const stop = strip(this.tail) || lastClose;
    return { prefill, stops: stop ? [stop] : [] };
  }
}

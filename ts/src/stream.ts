/**
 * Incremental, sans-I/O parsing (kernel §8).
 *
 * A reducer over response deltas, not a second parser. Every feed does work
 * proportional to the delta, never to the reply: markers are found by
 * incremental scanners over a small overlap window, and each field keeps
 * only the text it already emitted plus a short held tail (outer whitespace
 * and any suffix that can still grow into a marker). `finish` delegates the
 * final structural checks and typed reads to the batch parser, then releases
 * EOF-held text and typed `field_done` events, after proving that the
 * incremental projection agrees with batch.
 *
 * Hazard rule: a marker occurrence acts — opens a field's section, ends the
 * previous one, or fixes a close — only once no boundary marker can still be
 * growing across it.
 *
 * Positions are UTF-16 code units throughout; since a delta never splits a
 * scalar that a marker holds whole, every hold and boundary lands where the
 * reference's code-point positions land.
 */

import { Capture, replyProbabilities, textPart, validateResponsePart, partText, type Part } from "./core.ts";
import { DerivedReader, EMPHASIS, fold, IGNORABLE, markerKey, Reader, repairMarkers, textCaptures, type FindRule, type PatternMatcher, type ReaderStream, type Repair } from "./reader.ts";
import { lstrip, rstrip, strip, WHITESPACE } from "./text.ts";
import type { Plan } from "./plan.ts";

export type StreamEvent =
  | { kind: "field_started"; field: string }
  | { kind: "field_delta"; field: string; text: string }
  | { kind: "field_done"; field: string; value: unknown };

/** The events caused by EOF, and the same values, repairs and measurements as batch `read`. */
export class StreamResult<O = Record<string, unknown>> {
  readonly events: StreamEvent[];
  readonly values: O;
  readonly repairs: Repair[];
  readonly probabilities: Record<string, Record<string, number>>;
  readonly measuredBy: Record<string, string>;

  constructor(events: StreamEvent[], values: O, repairs: Repair[] = [], probabilities: Record<string, Record<string, number>> = {}, measuredBy: Record<string, string> = {}) {
    this.events = events;
    this.values = values;
    this.repairs = repairs;
    this.probabilities = probabilities;
    this.measuredBy = measuredBy;
  }

  toJSON(): Record<string, unknown> {
    return { events: this.events, values: this.values, repairs: this.repairs, probabilities: this.probabilities, measured_by: this.measuredBy };
  }
}

class StreamBug extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamBug";
  }
}

// ------------------------------------------------------------ primitives

/** Every proper prefix of a marker set: can this suffix still grow into a marker? */
class Prefixes {
  readonly table = new Set<string>();
  longest = 0;

  constructor(markers: string[]) {
    for (const marker of markers) {
      for (let n = 1; n < marker.length; n++) this.table.add(marker.slice(0, n));
      this.longest = Math.max(this.longest, marker.length - 1);
    }
  }

  hold(text: string): number {
    for (let n = Math.min(text.length, this.longest); n > 0; n--) {
      if (this.table.has(text.slice(text.length - n))) return n;
    }
    return 0;
  }

  growsBetween(window: string, end: number, lo: number, hi: number): boolean {
    const first = Math.max(1, end - hi + 1);
    const last = Math.min(this.longest, window.length, end - lo - 1);
    for (let n = first; n <= last; n++) {
      if (this.table.has(window.slice(window.length - n))) return true;
    }
    return false;
  }
}

/** Non-overlapping occurrences of one marker, reported by absolute start once complete. */
class Scanner {
  readonly marker: string;
  end: number;
  pending = "";

  constructor(marker: string, start: number) {
    this.marker = marker;
    this.end = start;
  }

  feed(text: string): number[] {
    const marker = this.marker;
    if (!text || !marker) {
      this.end += text.length;
      return [];
    }
    const buf = this.pending + text;
    const base = this.end - this.pending.length;
    const found: number[] = [];
    let i = 0;
    for (;;) {
      const j = buf.indexOf(marker, i);
      if (j < 0) break;
      found.push(base + j);
      i = j + marker.length;
    }
    this.end += text.length;
    const keep = Math.max(i, buf.length - (marker.length - 1));
    this.pending = buf.slice(keep);
    return found;
  }
}

class FieldState {
  present = false;
  started = false;
  emitted: string[] = [];
  hasEmitted = false;
  pending: string[] = [];
  readonly name: string;

  constructor(name: string) {
    this.name = name;
  }

  emit(text: string): void {
    if (text) {
      this.emitted.push(text);
      this.hasEmitted = true;
      this.pending.push(text);
    }
  }

  emittedText(): string {
    return this.emitted.join("");
  }
}

// -------------------------------------------------------------- find rules

interface TextStage {
  captures: string[];
  feed(delta: string, final: boolean): string;
}

class Between implements TextStage {
  readonly open: string;
  readonly close: string;
  readonly remove: boolean;
  readonly holdTable: Prefixes;
  buf = "";
  inside = false;
  captures: string[] = [];

  constructor(rule: FindRule) {
    [this.open, this.close] = rule["between"] as [string, string];
    this.remove = Boolean(rule["remove"]);
    this.holdTable = new Prefixes([this.open]);
  }

  feed(delta: string, final: boolean): string {
    const out: string[] = this.remove ? [] : [delta];
    let buf = this.buf + delta;
    for (;;) {
      if (!this.inside) {
        const i = buf.indexOf(this.open);
        if (i < 0) {
          if (this.remove) {
            const keep = final ? 0 : this.holdTable.hold(buf);
            out.push(buf.slice(0, buf.length - keep));
            buf = buf.slice(buf.length - keep);
          } else {
            const keep = Math.min(buf.length, Math.max(this.open.length - 1, 0));
            buf = buf.slice(buf.length - keep);
          }
          break;
        }
        if (this.remove) out.push(buf.slice(0, i));
        buf = buf.slice(i);
        this.inside = true;
      }
      const j = buf.indexOf(this.close, this.open.length);
      if (j < 0) {
        if (final && this.remove) {
          out.push(buf);
          buf = "";
        }
        break;
      }
      this.captures.push(strip(buf.slice(this.open.length, j)));
      buf = buf.slice(j + this.close.length);
      this.inside = false;
      if (!this.open && !this.close) break;
    }
    this.buf = buf;
    return out.join("");
  }
}

class LinePrefixed implements TextStage {
  readonly prefix: string;
  readonly remove: boolean;
  line = "";
  captures: string[] = [];

  constructor(rule: FindRule) {
    this.prefix = rule["line_prefixed"] as string;
    this.remove = Boolean(rule["remove"]);
  }

  feed(delta: string, final: boolean): string {
    const out: string[] = this.remove ? [] : [delta];
    const lines = (this.line + delta).split("\n");
    let last = lines.pop()!;
    for (const line of lines) {
      if (line.startsWith(this.prefix)) {
        this.captures.push(strip(line.slice(this.prefix.length)));
        if (this.remove) out.push("\n");
      } else if (this.remove) {
        out.push(line + "\n");
      }
    }
    if (final) {
      if (last.startsWith(this.prefix)) this.captures.push(strip(last.slice(this.prefix.length)));
      else if (this.remove) out.push(last);
      last = "";
    }
    this.line = last;
    return out.join("");
  }
}

/** A regex needs the whole text: later bytes can change any match. */
class PatternStage implements TextStage {
  readonly remove: boolean;
  readonly rule: FindRule;
  readonly pattern: PatternMatcher | null;
  pieces: string[] = [];
  captures: string[] = [];

  constructor(rule: FindRule, pattern: PatternMatcher | null) {
    this.rule = rule;
    this.pattern = pattern;
    this.remove = Boolean(rule["remove"]);
  }

  feed(delta: string, final: boolean): string {
    this.pieces.push(delta);
    if (!final) return this.remove ? "" : delta;
    const text = this.pieces.join("");
    const captures = textCaptures(text, this.rule, this.pattern);
    this.captures = captures.map(([, , cap]) => strip(cap));
    if (!this.remove) return "";
    if (!captures.length) return text;
    const out: string[] = [];
    let pos = 0;
    for (const [start, end] of captures) {
      out.push(text.slice(pos, start));
      pos = end;
    }
    out.push(text.slice(pos));
    return out.join("");
  }
}

/** Text of every part of one kind, each stripped, joined by newlines. */
class PartSource {
  texts: string[][] = [];
  anyPart = false;
  held = "";
  hasEmitted = false;
  readonly kind: string;

  constructor(kind: string) {
    this.kind = kind;
  }

  get captures(): string[] {
    return this.texts.map((pieces) => strip(pieces.join("")));
  }

  part(kind: string, text: string | null, newPart: boolean): string {
    if (kind !== this.kind) return "";
    this.anyPart = true;
    if (text === null) return "";
    let out = "";
    if (newPart) {
      this.texts.push([]);
      this.held = "";
      this.hasEmitted = false;
      if (this.texts.length > 1) out = "\n";
    }
    this.texts[this.texts.length - 1].push(text);
    let candidate = this.held + text;
    if (!this.hasEmitted) candidate = lstrip(candidate, WHITESPACE);
    const stable = rstrip(candidate, WHITESPACE);
    this.held = candidate.slice(stable.length);
    if (stable) this.hasEmitted = true;
    return out + stable;
  }
}

type Stage = TextStage | PartSource;

// ---------------------------------------------------------- derived reader

class Section {
  readonly scanner: Scanner | null;
  closeStarts: number[] = [];
  end: number | null = null;
  received: number;
  held = "";
  fixed: string | null = null;
  readonly field: FieldState;
  readonly start: number;
  readonly after: number;
  readonly close: string;
  readonly holdTable: Prefixes;

  constructor(field: FieldState, start: number, after: number, close: string, holdTable: Prefixes) {
    this.field = field;
    this.start = start;
    this.after = after;
    this.close = close;
    this.holdTable = holdTable;
    this.scanner = close ? new Scanner(close, after) : null;
    this.received = after;
  }

  cut(limit: number): string {
    if (limit >= this.received) return this.held;
    const drop = this.received - limit;
    if (drop > this.held.length) {
      if (this.field.hasEmitted) throw new StreamBug(`stream projection for '${this.field.name}' revised emitted text`);
      return "";
    }
    return this.held.slice(0, this.held.length - drop);
  }

  advance(limit: number | null): void {
    let candidate = limit === null ? this.held : this.cut(limit);
    const rest = limit === null ? "" : this.held.slice(candidate.length);
    if (!this.field.hasEmitted) candidate = lstrip(candidate, WHITESPACE);
    const n = this.holdTable.hold(candidate);
    const stable = rstrip(candidate.slice(0, candidate.length - n), WHITESPACE);
    this.field.emit(stable);
    this.held = candidate.slice(stable.length) + rest;
  }

  fix(limit: number): void {
    let candidate = this.cut(limit);
    if (!this.field.hasEmitted) candidate = lstrip(candidate, WHITESPACE);
    this.field.emit(rstrip(candidate, WHITESPACE));
    this.fixed = this.field.emittedText();
    this.held = "";
  }
}

class DerivedReducer {
  readonly wanted: [string, string, string][];
  readonly tail: string;
  readonly bounds: Prefixes;
  readonly holds = new Map<string, Prefixes>();
  readonly scanners = new Map<string, Scanner>();
  readonly first = new Map<string, number>();
  readonly duplicated = new Set<string>();
  readonly sections = new Map<string, Section>();
  length = 0;
  window = "";
  poisoned = false;

  readonly fields: Map<string, FieldState>;

  constructor(reader: DerivedReader, fields: Map<string, FieldState>, names: string[]) {
    this.fields = fields;
    this.wanted = reader.anchors.filter(([name]) => names.includes(name)).map(([name, prefix, suffix]) => [name, rstrip(prefix), strip(suffix)]);
    this.tail = strip(reader.tail);
    const markers = [...this.wanted.map(([, m]) => m), ...(this.tail ? [this.tail] : [])];
    this.bounds = new Prefixes(markers);
    for (const [, , close] of this.wanted) {
      if (!this.holds.has(close)) this.holds.set(close, new Prefixes([...markers, ...(close ? [close] : [])]));
    }
    for (const m of markers) if (!this.scanners.has(m)) this.scanners.set(m, new Scanner(m, 0));
  }

  feed(delta: string, final: boolean): void {
    const a = this.length;
    const b = a + delta.length;
    this.length = b;
    if (this.bounds.longest) {
      const w = this.window + delta;
      this.window = w.slice(Math.max(0, w.length - this.bounds.longest));
    }

    // 1. boundary occurrences (first position, duplicates)
    for (const [marker, scanner] of this.scanners) {
      for (const q of scanner.feed(delta)) {
        if (this.first.has(marker)) this.duplicated.add(marker);
        else this.first.set(marker, q);
      }
    }

    // 2. sections in batch order: sorted first occurrences, tail last on ties
    const bounds: [number, number, string | null, string][] = [];
    for (const [name, marker, close] of this.wanted) {
      const q = this.first.get(marker);
      if (q !== undefined) bounds.push([q, q + marker.length, name, close]);
    }
    if (this.tail && this.first.has(this.tail)) {
      const q = this.first.get(this.tail)!;
      bounds.push([q, q, null, ""]);
    }
    bounds.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
    bounds.forEach(([start, after, name, close], i) => {
      if (name === null) return;
      let section = this.sections.get(name);
      if (!section) {
        const field = this.fields.get(name)!;
        field.present = true;
        section = new Section(field, start, after, close, this.holds.get(close)!);
        this.sections.set(name, section);
      }
      const end = i + 1 < bounds.length ? bounds[i + 1][0] : null;
      if (section.end !== null && end !== null && end < section.end && section.fixed !== null) {
        throw new StreamBug(`stream projection for '${name}' revised emitted text`);
      }
      section.end = end;
    });

    // 3. route the delta into sections; feed close scanners
    for (const section of this.sections.values()) {
      const limit = section.end === null ? b : Math.min(b, section.end);
      if (section.fixed !== null) {
        // raw is final; only its close scanner keeps counting
      } else if (section.received < limit) {
        section.held += delta.slice(Math.max(0, section.received - a), limit - a);
        section.received = limit;
      } else if (section.received > limit) {
        section.held = section.cut(limit);
        section.received = limit;
      }
      const scanner = section.scanner;
      if (scanner !== null && scanner.end < b && (section.end === null || scanner.end < section.end)) {
        section.closeStarts.push(...scanner.feed(delta.slice(Math.max(0, scanner.end - a))));
      }
    }

    // 4. the longest boundary prefix still growing at the end of the text
    const growStart = b - this.bounds.hold(this.window);

    // 5. resolve: duplicates, fixes, and stable emission
    let poisoned = this.duplicated.size > 0;
    for (const section of this.sections.values()) {
      const end = section.end;
      const closes = section.closeStarts.filter((q) => end === null || q + section.close.length <= end);
      if (closes.length >= 2) poisoned = true;
      if (section.fixed !== null) continue;
      const stop = end === null ? b : end;
      if (end !== null && end <= section.after) section.fix(section.after);
      else if (final) section.fix(closes.length ? closes[0] : stop);
      else if (end !== null && growStart >= end) section.fix(closes.length ? closes[0] : end);
      else if (closes.length && end === null && growStart >= closes[0] + section.close.length) section.fix(closes[0]);
      else if (!this.bounds.growsBetween(this.window, b, section.start - 1, section.after)) section.advance(closes.length ? closes[0] : null);
    }
    this.poisoned = poisoned;
  }

  finalRaw(): Map<string, string> {
    const out = new Map<string, string>();
    for (const [name, section] of this.sections) if (section.fixed !== null) out.set(name, section.fixed);
    return out;
  }
}

// ---------------------------------------------------------- marker repair

function decorationStartAt(at: (i: number) => string, runStart: number, coreStart: number): number | null {
  for (let i = runStart; i < coreStart; i++) {
    if ("*_#".includes(at(i)) && (i === 0 || WHITESPACE.includes(at(i - 1)))) return i;
  }
  return null;
}

/**
 * §4a/§8: the stage between the find rules and the derived reader. It passes
 * text on unchanged, holding only what could still grow into a loose
 * occurrence or its decoration; from the first span that needs a repair it
 * holds everything until EOF, where the batch rewrite decides.
 */
class MarkerRepair {
  readonly keys: [string, string, number][];
  readonly lead: number;
  readonly longest: number;
  readonly prefixes: Prefixes;
  pieces: string[] = [];
  buf = "";
  before = "";
  released = 0;
  length = 0;
  runStart = 0;
  window: [string, number, number][] = [];
  pending: [string, number, number, number, number][] = [];
  heldFrom: number | null = null;
  readonly markers: string[];

  constructor(markers: string[]) {
    this.markers = markers;
    this.keys = markers.map((m) => {
      const full = markerKey(m);
      const key = full.replace(/^\n+/, "");
      return [key, m, full.length - key.length];
    });
    this.lead = Math.max(...this.keys.map(([, , lead]) => lead));
    this.longest = Math.max(...this.keys.map(([k]) => k.length));
    this.prefixes = new Prefixes(this.keys.map(([k]) => k));
  }

  private at(j: number): string {
    return j >= this.released ? this.buf[j - this.released] : this.before;
  }

  private text(a: number, b: number): string {
    return this.buf.slice(a - this.released, b - this.released);
  }

  feed(delta: string, final: boolean): string {
    const a = this.length;
    this.pieces.push(delta);
    this.buf += delta;
    this.length += delta.length;
    if (final) {
      const text = this.pieces.join("");
      const [rewritten] = repairMarkers(text, this.markers);
      if (rewritten.slice(0, this.released) !== text.slice(0, this.released)) throw new StreamBug("marker repair revised text it had already passed on");
      const out = rewritten.slice(this.released);
      this.released = text.length;
      this.buf = "";
      return out;
    }
    if (this.heldFrom !== null) return "";
    for (let offset = 0; offset < delta.length; offset++) {
      const i = a + offset;
      const c = delta[offset];
      if (IGNORABLE.has(c)) continue;
      this.window.push([fold(c), i, this.runStart]);
      this.runStart = i + 1;
      if (this.window.length > this.longest) this.window.shift();
      for (const [key, marker, lead] of this.keys) {
        const n = key.length;
        if (n <= this.window.length && key[n - 1] === this.window[this.window.length - 1][0]
          && this.window.slice(this.window.length - n).map(([ch]) => ch).join("") === key) {
          const [, coreStart, run] = this.window[this.window.length - n];
          this.pending.push([marker, run, coreStart, lead, i + 1]);
        }
      }
    }
    const waiting: [string, number, number, number, number][] = [];
    for (const item of this.pending) {
      const [marker, run, coreStart, lead, coreEnd] = item;
      const left = decorationStartAt((j) => this.at(j), run, coreStart);
      let end = coreEnd;
      let emphasis = false;
      if (left !== null) for (let j = left; j < coreStart; j++) if (EMPHASIS.has(this.at(j))) emphasis = true;
      if (left !== null && emphasis) {
        while (end < this.length && EMPHASIS.has(this.at(end))) end++;
        if (end === this.length) {
          waiting.push(item);
          continue;
        }
      }
      let start = left === null ? coreStart : left;
      if (lead) {
        let q = start;
        while (q > this.released && " \t\x0b\x0c\r".includes(this.at(q - 1))) q--;
        let taken = 0;
        while (taken < lead && q > this.released && this.at(q - 1) === "\n") {
          q--;
          taken++;
        }
        if (taken) start = q;
      }
      if (this.text(start, end) !== marker) {
        this.heldFrom = start;
        break;
      }
    }
    this.pending = this.heldFrom !== null ? [] : waiting;
    let limit = this.heldFrom === null ? this.length : this.heldFrom;
    if (this.runStart < this.length) limit = Math.min(limit, this.runStart);
    const n = this.prefixes.hold(this.window.map(([ch]) => ch).join(""));
    if (n) limit = Math.min(limit, this.window[this.window.length - n][2]);
    for (const [, run] of this.pending) limit = Math.min(limit, run);
    for (let k = 0; k < this.lead; k++) {
      while (limit > this.released && " \t\x0b\x0c\r".includes(this.at(limit - 1))) limit--;
      if (limit > this.released && this.at(limit - 1) === "\n") limit--;
    }
    limit = Math.max(limit, this.released);
    const out = this.buf.slice(0, limit - this.released);
    if (out) {
      this.before = out[out.length - 1];
      this.buf = this.buf.slice(out.length);
      this.released = limit;
    }
    return out;
  }
}

// -------------------------------------------------------------- describe

function hasStreamFace(reader: Reader): boolean {
  return reader instanceof DerivedReader || reader.stream !== Reader.prototype.stream;
}

/** The buffering choices, visible through `plan.describe()`. */
export function describeStreaming(plan: Plan<any, any>): Record<string, unknown> {
  const counts = new Map<string, number>();
  for (const [field] of plan.findRules) counts.set(field, (counts.get(field) ?? 0) + 1);
  const routes: Record<string, unknown>[] = [];
  const modes: string[] = [];
  let removingPattern = false;
  for (const [field, rule] of plan.findRules) {
    let mode: string;
    let reason: string | null = null;
    if ("pattern" in rule) {
      mode = "buffered";
      reason = "a pattern find rule waits for EOF";
      removingPattern ||= Boolean(rule["remove"]);
    } else if (counts.get(field)! > 1) {
      mode = "buffered";
      reason = "multiple find rules concatenate by declaration order";
    } else {
      mode = "incremental";
    }
    const item: Record<string, unknown> = { field, from: rule.from, mode };
    if (reason) item["reason"] = reason;
    routes.push(item);
    modes.push(mode);
  }
  let readerMode: string;
  let readerReason: string | null = null;
  if (hasStreamFace(plan.reader) && !removingPattern) readerMode = "incremental";
  else if (hasStreamFace(plan.reader)) {
    readerMode = "buffered";
    readerReason = "a removing pattern find rule can revise the reader's text";
  } else {
    readerMode = "buffered";
    readerReason = "reader provides no streaming face";
  }
  const reader: Record<string, unknown> = { mode: readerMode };
  if (readerReason) reader["reason"] = readerReason;
  modes.push(readerMode);
  const set = new Set(modes);
  const mode = set.size === 1 && set.has("incremental") ? "incremental" : set.size === 1 && set.has("buffered") ? "buffered" : "hybrid";
  return {
    mode, reader, find: routes, field_done: "finish",
    repairs: plan.adapter.strict ? { mode: "strict" }
      : { mode: "forgiving", reason: "from the first misspelled marker the rest of the reply waits for finish" },
  };
}

// ----------------------------------------------------------------- stream

type PartDelta = [string, string | null, boolean];

/** A plan-bound streaming parse reducer. Create with `plan.stream()`. */
export class Stream<O = Record<string, unknown>> {
  private readonly plan: Plan<any, O>;
  private readonly pieces: string[] = [];
  private readonly parts: Record<string, unknown>[] = [];
  private readonly partTexts: (string[] | null)[] = [];
  private partMode = false;
  private finished = false;
  private readonly fields = new Map<string, FieldState>();
  private readonly stages: [string, Stage][] = [];
  private readonly byField = new Map<string, Stage[]>();
  private readonly counted = new Map<string, number>();
  private readonly derived: DerivedReducer | null;
  private readonly repair: MarkerRepair | null;
  private readonly repairFind: MarkerRepair | null;
  private readonly readerStream: ReaderStream | null;
  private readonly readerPrefixes = new Map<string, string>();
  private readerFinalNames: Set<string> | null = null;
  private opening: StreamEvent[] = [];

  constructor(plan: Plan<any, O>) {
    this.plan = plan;
    for (const f of plan.signature.fields) this.fields.set(f.name, new FieldState(f.name));
    const names = plan.visibleOutputs.map((f) => f.name);
    for (const [field, rule] of plan.findRules) {
      const source = rule.from;
      let stage: Stage;
      if (source.startsWith("part:")) stage = new PartSource(source.slice(source.indexOf(":") + 1));
      else if ("between" in rule) stage = new Between(rule);
      else if ("line_prefixed" in rule) stage = new LinePrefixed(rule);
      else stage = new PatternStage(rule, plan.patternBinding());
      this.stages.push([field, stage]);
      if (!this.byField.has(field)) this.byField.set(field, []);
      this.byField.get(field)!.push(stage);
    }
    this.derived = plan.reader instanceof DerivedReader ? new DerivedReducer(plan.reader, this.fields, names) : null;
    this.repair = this.derived !== null && (plan.reader as DerivedReader).repairable.length ? new MarkerRepair((plan.reader as DerivedReader).repairable) : null;
    this.repairFind = plan.findRepairable.length ? new MarkerRepair(plan.findRepairable) : null;
    this.readerStream = this.derived !== null ? null : plan.reader.stream(names);
    if (plan.prefill) {
      this.run(plan.prefill, null, false);
      this.opening = this.events(false);
    }
  }

  /** One text delta, or one lm15 part delta `{type, text?, ...}`. */
  feed(delta: string | Record<string, unknown>): StreamEvent[] {
    if (this.finished) throw new Error("stream is already finished");
    const [text, part] = this.append(delta);
    this.run(text, part, false);
    const opening = this.opening;
    this.opening = [];
    return [...opening, ...this.events(false)];
  }

  /** End of stream. With `"length"` a cut output refuses `parse-truncated` (§4a). */
  finish(finishReason: string | null = null): StreamResult<O> {
    if (this.finished) throw new Error("stream is already finished");
    this.finished = true;
    let response: unknown = this.partMode ? { role: "assistant", parts: this.materializedParts() } : this.pieces.join("");
    if (finishReason !== null && finishReason !== undefined) {
      const message = typeof response === "string" ? { role: "assistant", parts: [textPart(response)] } : response;
      response = { message, finish_reason: finishReason };
    }
    const [probabilities, measuredBy] = replyProbabilities(response);
    const [values, captures, repairs] = this.plan.parseWithCaptures(response);
    this.run("", null, true);
    const events = this.events(true, captures, values);
    return new StreamResult<O>(events, values as O, repairs, probabilities, measuredBy);
  }

  private append(delta: unknown): [string, PartDelta | null] {
    if (typeof delta === "string") {
      this.pieces.push(delta);
      if (this.partMode) return [delta, this.appendPart(textPart(delta))];
      return [delta, null];
    }
    validateResponsePart(delta);
    if (!this.partMode) {
      this.partMode = true;
      if (this.pieces.length) this.appendPart(textPart(this.pieces.join("")));
    }
    const part = this.appendPart({ ...delta });
    const text = delta.type === "text" || delta.type === "data" ? partText(delta) : "";
    if (text) this.pieces.push(text);
    return [text, part];
  }

  private appendPart(part: Record<string, unknown>): PartDelta {
    const kind = part["type"] as string;
    const text = part["text"];
    const hasText = typeof text === "string";
    const last = this.parts.length - 1;
    if (hasText && last >= 0 && this.parts[last]["type"] === kind && this.partTexts[last] !== null) {
      this.partTexts[last]!.push(text);
      for (const key of Object.keys(part)) if (key !== "type" && key !== "text") this.parts[last][key] = part[key];
      return [kind, text, false];
    }
    this.parts.push(part);
    this.partTexts.push(hasText ? [text] : null);
    return [kind, hasText ? text : null, true];
  }

  private materializedParts(): Record<string, unknown>[] {
    return this.parts.map((part, i) => (this.partTexts[i] !== null ? { ...part, text: this.partTexts[i]!.join("") } : part));
  }

  private run(text: string, part: PartDelta | null, final: boolean): void {
    let stageText = text;
    if (this.repairFind !== null) stageText = this.repairFind.feed(stageText, final);
    for (const [field, stage] of this.stages) {
      const f = this.fields.get(field)!;
      if (stage instanceof PartSource) {
        if (part !== null) {
          const [kind, ptext, newPart] = part;
          const delta = stage.part(kind, ptext, newPart);
          if (stage.anyPart) f.present = true;
          if (this.byField.get(field)!.length === 1) f.emit(delta);
        }
        continue;
      }
      stageText = stage.feed(stageText, final);
      if (stage.captures.length) f.present = true;
      if (this.byField.get(field)!.length === 1) {
        let done = this.counted.get(field) ?? 0;
        for (const capture of stage.captures.slice(done)) {
          f.emit((done ? "\n" : "") + capture);
          done++;
        }
        this.counted.set(field, done);
      }
    }
    if (this.derived !== null) {
      if (this.repair !== null) stageText = this.repair.feed(stageText, final);
      this.derived.feed(stageText, final);
    } else if (this.readerStream !== null) {
      let prefixes: Record<string, string> = stageText || !final ? this.readerStream.feed(stageText) : {};
      if (final) {
        prefixes = this.readerStream.finish();
        this.readerFinalNames = new Set(Object.keys(prefixes));
      }
      for (const name of Object.keys(prefixes)) {
        const f = this.fields.get(name);
        if (!f) continue;
        f.present = true;
        const raw = prefixes[name];
        const before = this.readerPrefixes.get(name) ?? "";
        if (!raw.startsWith(before)) throw new StreamBug(`reader stream prefix for '${name}' revised emitted text`);
        this.readerPrefixes.set(name, raw);
        f.emit(raw.slice(before.length));
      }
    }
  }

  private finalProjection(): Map<string, string> {
    const out = new Map<string, string>();
    if (this.derived !== null) for (const [k, v] of this.derived.finalRaw()) out.set(k, v);
    else if (this.readerStream !== null) for (const [k, v] of this.readerPrefixes) out.set(k, v);
    for (const [field, stages] of this.byField) {
      const f = this.fields.get(field)!;
      if (!f.present) continue;
      if (stages.length > 1) out.set(field, stages.flatMap((s) => s.captures).join("\n"));
      else out.set(field, f.emittedText());
    }
    return out;
  }

  private events(final: boolean, finalCaptures?: Map<string, Capture>, values?: Record<string, unknown>): StreamEvent[] {
    if (this.derived !== null && this.derived.poisoned && !final) return [];
    const events: StreamEvent[] = [];
    if (final) {
      const projected = this.finalProjection();
      if (this.readerStream !== null) {
        const expected = [...this.plan.visibleOutputs.map((f) => f.name)].sort().join(",");
        const actual = [...(this.readerFinalNames ?? [])].sort().join(",");
        if (actual !== expected) throw new StreamBug(`reader stream fields [${actual}] disagree with batch fields [${expected}]`);
      }
      for (const [name, raw] of projected) {
        if (finalCaptures!.has(name) && raw !== finalCaptures!.get(name)!.text) throw new StreamBug(`stream projection for '${name}' disagrees with batch parse`);
      }
      for (const field of this.plan.signature.fields) {
        if (!finalCaptures!.has(field.name)) continue;
        const f = this.fields.get(field.name)!;
        if (!f.started) {
          f.started = true;
          events.push({ kind: "field_started", field: field.name });
        }
        const raw = finalCaptures!.get(field.name)!.text;
        const before = f.emittedText();
        const heldBack = f.pending.join("");
        const already = before.slice(0, before.length - heldBack.length);
        if (!raw.startsWith(already)) throw new StreamBug(`stream projection for '${field.name}' revised emitted text`);
        const delta = raw.slice(already.length);
        if (delta) events.push({ kind: "field_delta", field: field.name, text: delta });
        events.push({ kind: "field_done", field: field.name, value: values![field.name] });
      }
      return events;
    }
    for (const field of this.plan.signature.fields) {
      const f = this.fields.get(field.name)!;
      if (!f.present) continue;
      if (!f.started) {
        f.started = true;
        events.push({ kind: "field_started", field: field.name });
      }
      if (f.pending.length) {
        const text = f.pending.join("");
        f.pending.length = 0;
        events.push({ kind: "field_delta", field: field.name, text });
      }
    }
    return events;
  }
}

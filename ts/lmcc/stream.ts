// Kernel §8: the streaming reducer — a refinement of batch parse.
//
// Design: the reducer keeps the whole response so far and, after every
// delta, recomputes a *stable projection*: per field, the longest raw
// prefix no future delta can change. Each projection function (routing
// stage, lens) is prefix-monotone in its input and its value on the
// complete response is a prefix of the batch raw text, so concatenated
// deltas are identical for every chunking. `finish` runs the shared
// batch path and emits what the projection withheld, then `field_done`.

import { refuse } from "./refusal.ts";
import { isJsonObject } from "./json.ts";
import { textPart, type Part } from "./formats.ts";
import { stableBetween, stableLinePrefixed } from "./routing.ts";
import { routingSpanKind } from "./strategy.ts";
import { strip } from "./text.ts";
import type { Plan, Values } from "./plan.ts";
import { appendPartDelta, textChannel } from "./plan.ts";

export type StreamEvent =
  | { kind: "field_started"; field: string }
  | { kind: "field_delta"; field: string; text: string }
  | { kind: "field_done"; field: string; value: unknown };

export interface StreamResult {
  events: StreamEvent[];
  values: Values;
}

export class Stream {
  private plan: Plan;
  private parts: Part[] = [];
  private onlyText = true;
  private emitted = new Map<string, string>();
  private started = new Set<string>();
  private finished = false;
  private buffered: Set<string>;

  constructor(plan: Plan) {
    this.plan = plan;
    // fields that buffer until finish: pattern-routed, multi-routed
    const counts = new Map<string, number>();
    for (const s of plan.routingStages) counts.set(s.field.name, (counts.get(s.field.name) ?? 0) + 1);
    this.buffered = new Set();
    for (const s of plan.routingStages) {
      if (s.routing.pattern !== undefined || (counts.get(s.field.name) ?? 0) > 1) this.buffered.add(s.field.name);
    }
  }

  feed(delta: unknown): StreamEvent[] {
    if (this.finished) throw new Error("feed after finish is host API misuse");
    if (typeof delta === "string") {
      appendPartDelta(this.parts, textPart(delta));
    } else if (isJsonObject(delta) && typeof delta.kind === "string") {
      if (delta.text !== undefined && typeof delta.text !== "string") refuse("response-malformed", "a part delta's text must be a string", { stage: "parse" });
      this.onlyText = false;
      appendPartDelta(this.parts, delta as Part);
    } else {
      refuse("response-malformed", "a delta is a text string or a part {kind, ...}", { stage: "parse" });
    }
    return this.emit(this.project());
  }

  finish(): StreamResult {
    if (this.finished) throw new Error("finish twice is host API misuse");
    this.finished = true;
    const response = this.onlyText ? textChannel(this.parts) : { content: this.parts.map((p) => ({ ...p })) };
    const { values, raws } = this.plan.parseWithRaws(response);
    const events = this.emit(raws, true);
    for (const f of this.plan.signature.fields) {
      if (f.name in values) {
        if (!this.started.has(f.name)) {
          this.started.add(f.name);
          events.push({ kind: "field_started", field: f.name });
        }
        events.push({ kind: "field_done", field: f.name, value: values[f.name] });
      }
    }
    return { events, values };
  }

  /** Emit deltas for grown prefixes, in signature field order. */
  private emit(prefixes: { [field: string]: string }, final = false): StreamEvent[] {
    const events: StreamEvent[] = [];
    for (const f of this.plan.signature.fields) {
      const next = prefixes[f.name];
      if (next === undefined) continue;
      const prev = this.emitted.get(f.name) ?? "";
      if (!next.startsWith(prev)) {
        throw new Error(`streaming refinement violated for field ${f.name}: emitted ${JSON.stringify(prev)} is not a prefix of ${JSON.stringify(next)}${final ? " (batch)" : ""}`);
      }
      const delta = next.slice(prev.length);
      if (delta.length === 0) continue;
      if (!this.started.has(f.name)) {
        this.started.add(f.name);
        events.push({ kind: "field_started", field: f.name });
      }
      events.push({ kind: "field_delta", field: f.name, text: delta });
      this.emitted.set(f.name, next);
    }
    return events;
  }

  /** The stable raw prefix per field for the response so far. */
  private project(): { [field: string]: string } {
    const out: { [field: string]: string } = {};
    let text = textChannel(this.parts);
    for (const stage of this.plan.routingStages) {
      const r = stage.routing;
      const name = stage.field.name;
      if (r.from === "text") {
        let captures: string[] = [];
        if (r.between) {
          const s = stableBetween(text, r.between[0], r.between[1], r.consume === true);
          captures = s.captures;
          text = s.remaining;
        } else if (r.line_prefixed !== undefined) {
          const s = stableLinePrefixed(text, r.line_prefixed, r.consume === true);
          captures = s.captures;
          text = s.remaining;
        } else {
          // pattern: buffer the field; a consuming regex buffers the lens text too
          if (r.consume) text = "";
          continue;
        }
        if (!this.buffered.has(name)) out[name] = captures.map(strip).join("\n");
      } else {
        if (this.buffered.has(name)) continue;
        const kind = routingSpanKind(r);
        const pieces: string[] = [];
        this.parts.forEach((p, i) => {
          if (p.kind !== kind || typeof p.text !== "string") return;
          pieces.push(strip(p.text));
          void i;
        });
        out[name] = pieces.join("\n");
      }
    }
    if (this.plan.lens.project) {
      const lensRaws = this.plan.lens.project(text);
      for (const [k, v] of Object.entries(lensRaws)) out[k] = v;
    }
    return out;
  }
}

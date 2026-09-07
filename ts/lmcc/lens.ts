// Kernel §4: the template is the lens (derived), and the lens socket
// vocabulary lenses (json_object) plug into.

import { refuse } from "./refusal.ts";
import type { Json } from "./json.ts";
import type { Field } from "./signature.ts";
import type { Node, TemplateItem } from "./template.ts";
import type { Capabilities } from "./strategy.ts";
import { strip } from "./text.ts";
import { partialMarkerStart } from "./routing.ts";

export interface LensBindContext {
  /** visible output fields, signature order */
  fields: Field[];
  template: TemplateItem[];
  capabilities: Capabilities;
  /** render a loop attribute other than `value` for a field */
  attr(field: Field, attr: string): string;
  instructions: string;
  /** the field's JSON-schema shape, for lens patches */
  shapeOf(field: Field): { [k: string]: Json };
}

export interface Spelled {
  name: string;
  text: string;
}

export interface BoundLens {
  kind: string;
  patch: { [k: string]: Json };
  /** demo assistant turn over the outputs the demo supplies (signature order) */
  join(values: Spelled[]): string;
  /** the `{format}` skeleton over placeholders */
  format(placeholders: Spelled[]): string;
  /** raw string per visible output field; refuses parse-ambiguous / parse-missing-fields / lens-parse-error */
  split(text: string): { [field: string]: string };
  skeleton(): { prefill: string; stops: string[] };
  /** stable raw prefix per field for the stable text so far; absent = buffered lens */
  project?(stableText: string): { [field: string]: string };
  streamMode: "incremental" | "buffered";
  describe(): { [k: string]: Json };
}

export interface Lens {
  kind: string;
  vocab?: string;
  version?: string;
  bind(ctx: LensBindContext): BoundLens;
}

// ---------------------------------------------------------------------------
// The derived lens

interface FieldMarkers {
  field: Field;
  anchorRaw: string;
  anchor: string; // stripped
  closeRaw: string;
  close: string; // stripped
}

interface Pattern {
  messageIndex: number;
  /** true for an outputs-loop pattern; false for bare output slots */
  loop: boolean;
  /** signature order (reading) */
  fields: FieldMarkers[];
  /** template order (writing); literals[i] precedes holes[i], literals[n] follows the last */
  holes: FieldMarkers[];
  /** literal_0, v1, literal_1, ..., vn, literal_n — literal_n includes the tail */
  literals: string[];
  tailRaw: string;
  tail: string;
}

function countOccurrences(text: string, marker: string, from: number, to: number): number {
  if (marker.length === 0 || to <= from) return 0;
  let n = 0;
  let p = from;
  for (;;) {
    const i = text.indexOf(marker, p);
    if (i < 0 || i + marker.length > to) break;
    n++;
    p = i + marker.length;
  }
  return n;
}

function renderStatic(nodes: Node[], field: Field, ctx: LensBindContext, path: string, variable: string): string {
  let out = "";
  for (const n of nodes) {
    if (n.kind === "text") out += n.text;
    else if (n.kind === "attr" && n.variable === variable && n.attr !== "value") out += ctx.attr(field, n.attr);
    else if (n.kind === "slot" && n.name === "instruction") out += ctx.instructions;
    else refuse("not-lensable", `${path}: the output pattern around field ${field.name} contains a non-literal construct`, { fix: { action: "edit-template", path, field: field.name } });
  }
  return out;
}

function derivePattern(ctx: LensBindContext): Pattern {
  const visible = new Map(ctx.fields.map((f) => [f.name, f]));
  let found: { messageIndex: number; loop: Node | null; bare: boolean } | null = null;
  let loopNode: (Node & { kind: "loop" }) | null = null;
  const messages = ctx.template.filter((t): t is TemplateItem & { kind: "message" } => t.kind === "message");
  for (const msg of messages) {
    const path = `template[${msg.index}]`;
    let bareHoles = 0;
    for (const n of msg.nodes) {
      if (n.kind === "loop" && n.source === "outputs") {
        const holes = n.body.filter((b) => b.kind === "attr" && b.variable === n.variable && b.attr === "value");
        const nested = n.body.some((b) => b.kind === "loop");
        if (holes.length === 0) continue;
        if (nested) refuse("not-lensable", `${path}: the output pattern nests a loop`, { fix: { action: "edit-template", path } });
        if (holes.length > 1) refuse("not-lensable", `${path}: two output holes share one anchor`, { fix: { action: "edit-template", path } });
        if (found) refuse("not-lensable", `${path}: a second output pattern; the reply can only be read backwards from one`, { fix: { action: "edit-template", path } });
        found = { messageIndex: msg.index, loop: n, bare: false };
        loopNode = n;
      } else if (n.kind === "slot" && visible.has(n.name)) {
        bareHoles++;
      }
    }
    if (bareHoles > 0) {
      if (found) refuse("not-lensable", `${path}: a second output pattern; the reply can only be read backwards from one`, { fix: { action: "edit-template", path } });
      found = { messageIndex: msg.index, loop: null, bare: true };
    }
  }
  if (!found) refuse("not-lensable", "no output pattern: no output hole in the template", { fix: { action: "edit-template", path: "template" } });
  const f = found as { messageIndex: number; loop: Node | null; bare: boolean };
  const msg = messages.find((m) => m.index === f.messageIndex)!;
  const path = `template[${msg.index}]`;
  const pattern: Pattern = { messageIndex: msg.index, loop: loopNode !== null, fields: [], holes: [], literals: [], tailRaw: "", tail: "" };

  if (loopNode) {
    const loop = loopNode as Node & { kind: "loop" };
    const idx = loop.body.findIndex((b) => b.kind === "attr" && b.variable === loop.variable && b.attr === "value");
    const before = loop.body.slice(0, idx);
    const after = loop.body.slice(idx + 1);
    // tail: the literal after the loop, up to the next slot and to the end of its line
    const at = msg.nodes.indexOf(loop);
    let tailRaw = "";
    for (let k = at + 1; k < msg.nodes.length; k++) {
      const n = msg.nodes[k];
      if (n.kind !== "text") break;
      tailRaw += n.text;
    }
    const nl = tailRaw.indexOf("\n");
    if (nl >= 0) tailRaw = tailRaw.slice(0, nl);
    pattern.tailRaw = tailRaw;
    pattern.tail = strip(tailRaw);
    for (const field of ctx.fields) {
      const anchorRaw = renderStatic(before, field, ctx, path, loop.variable);
      const closeRaw = renderStatic(after, field, ctx, path, loop.variable);
      pattern.fields.push({ field, anchorRaw, anchor: strip(anchorRaw), closeRaw, close: strip(closeRaw) });
    }
    for (let i = 0; i < pattern.fields.length; i++) {
      const prev = i > 0 ? pattern.fields[i - 1].closeRaw : "";
      pattern.literals.push(prev + pattern.fields[i].anchorRaw);
    }
    pattern.literals.push((pattern.fields.length ? pattern.fields[pattern.fields.length - 1].closeRaw : "") + tailRaw);
    pattern.holes = pattern.fields.slice();
  } else {
    // bare output slots: the lines holding the holes are the pattern
    type Seg = { kind: "text"; text: string } | { kind: "hole"; field: Field } | { kind: "other" };
    const segs: Seg[] = [];
    for (const n of msg.nodes) {
      if (n.kind === "text") segs.push({ kind: "text", text: n.text });
      else if (n.kind === "slot" && visible.has(n.name)) segs.push({ kind: "hole", field: visible.get(n.name)! });
      else segs.push({ kind: "other" });
    }
    const holeIdx = segs.map((s, i) => (s.kind === "hole" ? i : -1)).filter((i) => i >= 0);
    // signature order of the fields, by hole position (holes may appear in any order; keep template order)
    const literalBetween = (a: number, b: number): string => {
      let out = "";
      for (let i = a + 1; i < b; i++) {
        const s = segs[i];
        if (s.kind === "text") out += s.text;
        else if (s.kind === "other") return out; // a non-hole slot ends the literal
      }
      return out;
    };
    const textBefore = (i: number): string => {
      // literal before hole i back to the previous hole / other slot
      let out = "";
      for (let k = i - 1; k >= 0; k--) {
        const s = segs[k];
        if (s.kind === "text") out = s.text + out;
        else break;
      }
      return out;
    };
    const textAfter = (i: number): string => {
      let out = "";
      for (let k = i + 1; k < segs.length; k++) {
        const s = segs[k];
        if (s.kind === "text") out += s.text;
        else break;
      }
      return out;
    };
    for (let h = 0; h < holeIdx.length; h++) {
      const i = holeIdx[h];
      const field = (segs[i] as { kind: "hole"; field: Field }).field;
      let anchorRaw = textBefore(i);
      const lastNl = anchorRaw.lastIndexOf("\n");
      if (lastNl >= 0) anchorRaw = anchorRaw.slice(lastNl + 1);
      let closeRaw = textAfter(i);
      const nl = closeRaw.indexOf("\n");
      if (nl >= 0) closeRaw = closeRaw.slice(0, nl);
      pattern.fields.push({ field, anchorRaw, anchor: strip(anchorRaw), closeRaw, close: strip(closeRaw) });
      if (h === 0) pattern.literals.push(anchorRaw);
      else pattern.literals.push(literalBetween(holeIdx[h - 1], i));
    }
    pattern.literals.push(pattern.fields[pattern.fields.length - 1].closeRaw);
    // holes keep template order for writing; fields take signature order for reading
    pattern.holes = pattern.fields.slice();
    const order = new Map(ctx.fields.map((f, i) => [f.name, i]));
    pattern.fields = pattern.fields.slice().sort((a, b) => order.get(a.field.name)! - order.get(b.field.name)!);
    // a field appearing twice as a bare slot shares an anchor with itself
    const seen = new Set<string>();
    for (const fm of pattern.fields) {
      if (seen.has(fm.field.name)) refuse("not-lensable", `${path}: field ${fm.field.name} has two holes`, { fix: { action: "edit-template", path, field: fm.field.name } });
      seen.add(fm.field.name);
    }
  }
  // refusals: a hole with no literal before it; two holes sharing an anchor
  const anchors = new Map<string, string>();
  for (const fm of pattern.fields) {
    if (fm.anchor === "") refuse("not-lensable", `${path}: field ${fm.field.name} has no literal before its hole`, { fix: { action: "edit-template", path, field: fm.field.name } });
    const other = anchors.get(fm.anchor);
    if (other !== undefined) refuse("not-lensable", `${path}: fields ${other} and ${fm.field.name} share the anchor ${JSON.stringify(fm.anchor)}`, { fix: { action: "edit-template", path, field: fm.field.name } });
    anchors.set(fm.anchor, fm.field.name);
  }
  return pattern;
}

class DerivedBound implements BoundLens {
  kind = "derived";
  patch: { [k: string]: Json } = {};
  streamMode: "incremental" = "incremental";
  private pattern: Pattern;
  constructor(pattern: Pattern) {
    this.pattern = pattern;
  }
  markers(): string[] {
    const out = new Set<string>();
    for (const fm of this.pattern.fields) {
      out.add(fm.anchor);
      if (fm.close) out.add(fm.close);
    }
    if (this.pattern.tail) out.add(this.pattern.tail);
    return [...out];
  }
  private write(values: Spelled[], collide: boolean): string {
    const byName = new Map(values.map((v) => [v.name, v.text]));
    const markers = this.markers();
    const check = (fm: FieldMarkers, text: string): void => {
      if (!collide) return;
      for (const m of markers) {
        if (text.includes(m)) refuse("value-collides", `field ${fm.field.name}: the spelled value contains the marker ${JSON.stringify(m)} the lens reads`, { stage: "render" });
      }
    };
    if (this.pattern.loop) {
      // one loop iteration per supplied field, then the tail
      let out = "";
      for (const fm of this.pattern.holes) {
        const text = byName.get(fm.field.name);
        if (text === undefined) continue; // absent outputs are omitted
        check(fm, text);
        out += fm.anchorRaw + text + fm.closeRaw;
      }
      return strip(out + this.pattern.tailRaw);
    }
    // bare slots: the line literals stay; an absent value leaves its hole empty
    let out = this.pattern.literals[0] ?? "";
    this.pattern.holes.forEach((fm, i) => {
      const text = byName.get(fm.field.name) ?? "";
      check(fm, text);
      out += text + this.pattern.literals[i + 1];
    });
    return strip(out);
  }
  join(values: Spelled[]): string {
    return this.write(values, true);
  }
  format(placeholders: Spelled[]): string {
    return this.write(placeholders, false);
  }
  skeleton(): { prefill: string; stops: string[] } {
    const first = this.pattern.holes[0];
    const last = this.pattern.holes[this.pattern.holes.length - 1];
    const stop = this.pattern.tail || (last ? last.close : "");
    return { prefill: first ? first.anchorRaw : "", stops: stop ? [stop] : [] };
  }
  /** Structural read; `tolerant` never refuses (streaming projection). */
  private locate(text: string, tolerant: boolean): { raws: { [field: string]: string }; missing: string[] } {
    const p = this.pattern;
    const found = new Map<string, { start: number; end: number }>();
    for (const fm of p.fields) {
      const i = text.indexOf(fm.anchor);
      if (i < 0) continue;
      if (!tolerant && countOccurrences(text, fm.anchor, 0, text.length) > 1) {
        refuse("parse-ambiguous", `anchor ${JSON.stringify(fm.anchor)} of field ${fm.field.name} occurs more than once`, { stage: "parse" });
      }
      found.set(fm.field.name, { start: i, end: i + fm.anchor.length });
    }
    let tailPos = -1;
    if (p.tail) {
      const n = countOccurrences(text, p.tail, 0, text.length);
      if (!tolerant && n > 1) refuse("parse-ambiguous", `tail ${JSON.stringify(p.tail)} occurs more than once`, { stage: "parse" });
      tailPos = text.indexOf(p.tail);
    }
    // held suffix for the streaming projection
    let held = text.length;
    if (tolerant) {
      for (const m of this.markers()) held = Math.min(held, partialMarkerStart(text, m));
    }
    const raws: { [field: string]: string } = {};
    const missing: string[] = [];
    for (const fm of p.fields) {
      const at = found.get(fm.field.name);
      if (!at) {
        missing.push(fm.field.name);
        continue;
      }
      let boundary = text.length;
      if (tailPos > at.start) boundary = Math.min(boundary, tailPos);
      for (const [name, other] of found) {
        if (name !== fm.field.name && other.start > at.start) boundary = Math.min(boundary, other.start);
      }
      if (tolerant) boundary = Math.min(boundary, held);
      let end = Math.max(at.end, boundary);
      if (fm.close) {
        const n = countOccurrences(text, fm.close, at.end, end);
        if (!tolerant && n > 1) refuse("parse-ambiguous", `close ${JSON.stringify(fm.close)} of field ${fm.field.name} occurs more than once`, { stage: "parse" });
        if (n >= 1) end = text.indexOf(fm.close, at.end);
      }
      raws[fm.field.name] = strip(text.slice(at.end, end));
    }
    return { raws, missing };
  }
  split(text: string): { [field: string]: string } {
    const { raws, missing } = this.locate(text, false);
    if (missing.length) {
      refuse("parse-missing-fields", `the reply lacks field(s) ${missing.join(", ")}`, { stage: "parse", partial: raws });
    }
    return raws;
  }
  project(stableText: string): { [field: string]: string } {
    return this.locate(stableText, true).raws;
  }
  describe(): { [k: string]: Json } {
    return {
      kind: "derived",
      message: this.pattern.messageIndex,
      fields: this.pattern.holes.map((fm) => ({ field: fm.field.name, anchor: fm.anchor, close: fm.close })),
      tail: this.pattern.tail,
    };
  }
}

export const DERIVED_LENS: Lens = {
  kind: "derived",
  bind(ctx: LensBindContext): BoundLens {
    return new DerivedBound(derivePattern(ctx));
  },
};

// Kernel §3: bind → plan; render, parse, skeleton, prefix, describe.

import { refuse, Refusal } from "./refusal.ts";
import { isJsonObject, cloneJson, jsonEqual, type Json } from "./json.ts";
import { classifyShape, mechanicalHint, type Field, type Signature } from "./signature.ts";
import type { Node, TemplateItem } from "./template.ts";
import { LOOP_ATTRS, RESERVED_SLOTS, walk } from "./template.ts";
import { makeSpan, resolveFormat, formatAccepts, formatReads, bindKey, textPart, toParts, type Format, type Part, type Resolved, type FormatContext } from "./formats.ts";
import { selectStrategy, routingSpanKind, type Capabilities, type PlainStrategy, type Routing, type StrategyData } from "./strategy.ts";
import { scanBetween, scanLinePrefixed, scanPattern } from "./routing.ts";
import { compileRe2 } from "./text.ts";
import type { BoundLens, Lens, Spelled } from "./lens.ts";
import { Stream } from "./stream.ts";

export interface Message {
  role: string;
  content: Part[];
}

export interface RenderResult {
  messages: Message[];
  patch: { [k: string]: Json };
}

export interface Adapter {
  name?: string;
  entry: Json;
  versions: { kernel: string; vocab: { [k: string]: string } };
  template: TemplateItem[];
  parseKind: string;
  lens: Lens;
  strategies: Map<string, StrategyData>;
  formats: Map<string, Format>;
}

export interface BoundRouting {
  routing: Routing;
  role: string;
  index: number;
  field: Field;
  regex?: RegExp;
}

export interface BoundField {
  field: Field;
  resolved: Resolved;
  visible: boolean;
  routings: BoundRouting[];
  placement?: string;
  placementRole?: string;
}

interface Scope {
  mode: "main" | "example";
  values: { [k: string]: unknown } | null;
  loops: Map<string, Field>;
}

export type Values = { [field: string]: unknown };

/** Normalized response: the text channel and the (coalesced) parts. */
export function normalizeResponse(response: unknown): { text: string; parts: Part[] } {
  if (typeof response === "string") return { text: response, parts: [textPart(response)] };
  if (isJsonObject(response) && Array.isArray(response.content)) {
    const parts: Part[] = [];
    for (const p of response.content) {
      if (!isJsonObject(p) || typeof p.kind !== "string") refuse("response-malformed", "every response part needs a string kind", { stage: "parse" });
      if (p.text !== undefined && typeof p.text !== "string") refuse("response-malformed", "a part's text must be a string", { stage: "parse" });
      appendPartDelta(parts, p as Part);
    }
    return { text: textChannel(parts), parts };
  }
  refuse("response-malformed", "a response is a string or {content: [part, ...]}", { stage: "parse" });
}

/** §8 coalescing: adjacent text-bearing parts of one kind become one part. */
export function appendPartDelta(parts: Part[], delta: Part): void {
  const last = parts[parts.length - 1];
  if (last && typeof delta.text === "string" && typeof last.text === "string" && last.kind === delta.kind) {
    last.text = (last.text as string) + delta.text;
    return;
  }
  parts.push({ ...delta });
}

export function textChannel(parts: Part[]): string {
  return parts.filter((p) => p.kind === "text" && typeof p.text === "string").map((p) => p.text as string).join("");
}

export class Plan {
  adapter: Adapter;
  signature: Signature;
  capabilities: Capabilities;
  fields: Map<string, BoundField> = new Map();
  roles: Map<string, Field> = new Map();
  lens!: BoundLens;
  fragments: { role: string; text: string; strategyRole: string }[] = [];
  controls: { [k: string]: Json } = {};
  chosen: Map<string, PlainStrategy> = new Map();
  routingStages: BoundRouting[] = [];

  constructor(adapter: Adapter, signature: Signature, capabilities: Capabilities) {
    this.adapter = adapter;
    this.signature = signature;
    this.capabilities = capabilities;
    this.bind();
  }

  // ------------------------------------------------------------------ bind

  private bind(): void {
    const sig = this.signature;
    // roles: each bound to at most one field
    for (const f of sig.fields) {
      if (f.role === "plain") continue;
      const other = this.roles.get(f.role);
      if (other) refuse("role-ambiguous", `role ${f.role} is borne by both ${other.name} and ${f.name}`, { fix: { action: "edit-signature", field: f.name, role: f.role } });
      this.roles.set(f.role, f);
    }
    // template slots name fields or reserved names; dotted slots live in loops
    this.checkSlots();
    // strategies, in signature order of the roles' fields
    const hidden = new Set<string>();
    const placements = new Map<string, { target: string; role: string }>();
    const routingsByField = new Map<string, BoundRouting[]>();
    const controlOwner = new Map<string, string>();
    const placementKeys = new Set<string>();
    const seenRoles = new Set<string>();
    for (const f of sig.fields) {
      const data = this.adapter.strategies.get(f.role);
      if (!data || seenRoles.has(f.role)) continue;
      seenRoles.add(f.role);
      const role = f.role;
      const s = selectStrategy(role, data, this.capabilities);
      this.chosen.set(role, s);
      if (s.visible === false) hidden.add(f.name);
      for (const [msgRole, text] of Object.entries(s.fragments ?? {})) {
        this.fragments.push({ role: msgRole, text: text.split("{field}").join(f.name), strategyRole: role });
      }
      for (const [key, value] of Object.entries(s.controls ?? {})) {
        if (placementKeys.has(key)) {
          refuse("control-conflict", `strategy ${role} writes control ${key}, which a placement of strategy ${controlOwner.get(key)} also writes`, { fix: { action: "edit-entry", path: `strategies['${role}'].controls['${key}']` } });
        }
        if (key in this.controls) {
          if (!jsonEqual(this.controls[key], value)) {
            refuse("control-conflict", `strategies ${controlOwner.get(key)} and ${role} disagree on control ${key}`, { fix: { action: "edit-entry", path: `strategies['${role}'].controls['${key}']` } });
          }
        } else {
          this.controls[key] = value;
          controlOwner.set(key, role);
        }
      }
      for (const [target, where] of Object.entries(s.placement ?? {})) {
        const field = this.resolveTarget(target, role);
        placements.set(field.name, { target: where, role });
        hidden.add(field.name);
        if (s.visible === false) hidden.add(field.name);
        if (where.startsWith("controls.")) {
          const key = where.slice("controls.".length).split(".")[0];
          if (key in this.controls || placementKeys.has(key)) refuse("control-conflict", `placement of ${field.name} and strategy ${controlOwner.get(key)} both write control ${key}`, { fix: { action: "edit-entry", path: `strategies['${role}'].placement` } });
          controlOwner.set(key, role);
          placementKeys.add(key);
        }
      }
      (s.routings ?? []).forEach((r, index) => {
        const field = this.resolveTarget(r.to, role);
        if (s.visible === false) hidden.add(field.name); // visible: false covers every field the strategy targets (corpus 71/72)
        const bound: BoundRouting = { routing: r, role, index, field };
        if (r.pattern !== undefined) bound.regex = compileRe2(r.pattern);
        const list = routingsByField.get(field.name) ?? [];
        list.push(bound);
        routingsByField.set(field.name, list);
        this.routingStages.push(bound);
      });
    }
    // visibility and coverage
    for (const f of sig.fields) {
      const visible = !hidden.has(f.name);
      const routings = routingsByField.get(f.name) ?? [];
      if (visible && routings.length) {
        const role = routings[0].role;
        refuse("field-double-covered", `field ${f.name} is visible and routed by strategy ${role}; hide it or drop the routing`, { fix: { action: "edit-entry", path: `strategies['${role}'].visible` } });
      }
      const p = placements.get(f.name);
      this.fields.set(f.name, { field: f, resolved: undefined as unknown as Resolved, visible, routings, placement: p?.target, placementRole: p?.role });
    }
    // formats, per field, signature order
    for (const f of sig.fields) {
      const bf = this.fields.get(f.name)!;
      const resolved = resolveFormat(f, this.adapter.formats);
      if (!resolved) {
        refuse("no-format", `field ${f.name} (shape ${JSON.stringify(f.shape)}) is structured and no format is bound`, { fix: { action: "bind-format", field: f.name, key: bindKey(f) } });
      }
      bf.resolved = resolved;
      const fmt = resolved.format;
      const fix = { action: "bind-format" as const, field: f.name, key: bindKey(f) };
      if (!formatAccepts(fmt, f)) refuse("format-shape-mismatch", `format ${fmt.name} (accepts ${fmt.accepts.join(", ")}) is bound to field ${f.name} whose shape it does not accept`, { fix });
      if (fmt.direction === "in" && f.direction === "output") refuse("format-direction", `input-only format ${fmt.name} on output field ${f.name}`, { fix });
      if (fmt.direction === "out" && f.direction === "input") refuse("format-direction", `output-only format ${fmt.name} on input field ${f.name}`, { fix });
      for (const r of bf.routings) {
        const kind = routingSpanKind(r.routing);
        if (!formatReads(fmt, kind)) refuse("format-span-mismatch", `routing ${r.routing.from} delivers ${kind} parts to field ${f.name}, which format ${fmt.name} cannot read (reads ${fmt.reads.join(", ")})`, { fix });
      }
      if (bf.placement && bf.placement.startsWith("controls.") && fmt.emits !== "parts") {
        refuse("format-placement-mismatch", `placement ${bf.placement} of field ${f.name} needs parts but format ${fmt.name} emits ${fmt.emits}`, { fix });
      }
    }
    // the lens
    this.lens = this.adapter.lens.bind({
      fields: this.visibleOutputs(),
      template: this.adapter.template,
      capabilities: this.capabilities,
      attr: (field, attr) => this.attr(field, attr),
      instructions: sig.instructions,
      shapeOf: (field) => field.shape,
    });
    for (const key of Object.keys(this.lens.patch)) {
      if (key in this.controls) refuse("control-conflict", `the lens and strategy ${controlOwner.get(key)} both write control ${key}`, { fix: { action: "edit-entry", path: `strategies['${controlOwner.get(key)}'].controls['${key}']` } });
    }
    // every visible input must be reachable
    const reachable = new Set<string>();
    let hasInputsLoop = false;
    for (const item of this.adapter.template) {
      if (item.kind !== "message") continue;
      walk(item.nodes, (n) => {
        if (n.kind === "slot") reachable.add(n.name);
        if (n.kind === "loop" && n.source === "inputs") hasInputsLoop = true;
      });
    }
    for (const f of sig.fields) {
      if (f.direction !== "input") continue;
      const bf = this.fields.get(f.name)!;
      if (!bf.visible) continue;
      if (!reachable.has(f.name) && !hasInputsLoop) {
        refuse("field-uncovered", `input ${f.name} is never rendered by the template`, { fix: { action: "edit-template", path: "template", field: f.name } });
      }
    }
  }

  private resolveTarget(target: string, role: string): Field {
    let wanted: string;
    if (target === "@role") wanted = role;
    else if (target.startsWith("@role.")) wanted = `${role}.${target.slice("@role.".length)}`;
    else refuse("entry-malformed", `strategies['${role}']: bad target ${JSON.stringify(target)}`, { fix: { action: "edit-entry", path: `strategies['${role}']` }, stage: "load" });
    const field = this.roles.get(wanted);
    if (!field) refuse("unknown-slot", `strategies['${role}'] targets ${target} but no field bears role ${wanted}`, { fix: { action: "assign-role", role: wanted } });
    return field;
  }

  private checkSlots(): void {
    const names = new Set(this.signature.fields.map((f) => f.name));
    for (const item of this.adapter.template) {
      if (item.kind !== "message") continue;
      const path = `template[${item.index}]`;
      walk(item.nodes, (n, loop) => {
        if (n.kind === "slot" && !RESERVED_SLOTS.has(n.name) && !names.has(n.name)) {
          refuse("unknown-slot", `${path}: slot {${n.name}} names no field`, { fix: { action: "edit-template", path, slot: n.name } });
        }
        if (n.kind === "attr") {
          const loopVar = loop && loop.kind === "loop" ? loop.variable : null;
          if (loopVar !== n.variable) refuse("unknown-slot", `${path}: dotted slot {${n.variable}.${n.attr}} outside its loop`, { fix: { action: "edit-template", path, slot: `${n.variable}.${n.attr}` } });
          if (!LOOP_ATTRS.has(n.attr)) refuse("unknown-slot", `${path}: unknown loop attribute {${n.variable}.${n.attr}}`, { fix: { action: "edit-template", path, slot: `${n.variable}.${n.attr}` } });
        }
      });
    }
  }

  // ------------------------------------------------------------ helpers

  visibleOutputs(): Field[] {
    return this.signature.fields.filter((f) => f.direction === "output" && this.fields.get(f.name)!.visible);
  }
  visibleInputs(): Field[] {
    return this.signature.fields.filter((f) => f.direction === "input" && this.fields.get(f.name)!.visible);
  }

  formatOf(field: Field): Format {
    return this.fields.get(field.name)!.resolved.format;
  }

  private formatContext(): FormatContext {
    return {
      formatFor: (shape, path) => {
        const pseudo: Field = { name: path, direction: "output", shape, role: "plain" };
        const r = resolveFormat(pseudo, this.adapter.formats);
        if (!r) refuse("no-format", `no format for the nested value at ${path}`, { fix: { action: "bind-format", field: path, key: bindKey(pseudo) } });
        return r.format;
      },
    };
  }

  /** What the model is told about a field: the format's describe, else the type name, else the mechanical hint. */
  describeField(field: Field): string {
    const fmt = this.formatOf(field);
    if (fmt.describe) return fmt.describe(field, this.formatContext());
    return field.type ?? mechanicalHint(field);
  }

  placeholder(field: Field): string {
    if (field.desc) return field.desc;
    const d = this.describeField(field);
    if (d) return d;
    return "...";
  }

  attr(field: Field, attr: string): string {
    switch (attr) {
      case "name":
        return field.name;
      case "desc":
        return field.desc ?? "";
      case "type":
        return field.type ?? "";
      case "role":
        return field.role;
      case "schema":
        return this.describeField(field);
      default:
        return "";
    }
  }

  /** Spell a value through the field's format; parts out. */
  writeValue(field: Field, value: unknown, forDemo: boolean): Part[] {
    const bf = this.fields.get(field.name)!;
    const fmt = bf.resolved.format;
    if (forDemo && !fmt.roundTrip) refuse("demo-not-renderable", `field ${field.name}: format ${fmt.name} is lossy and cannot write demos`, { stage: "render" });
    try {
      return toParts(fmt.write(value, field, this.formatContext()));
    } catch (e) {
      if (e instanceof Refusal) throw e;
      refuse("format-write-error", `field ${field.name}: format ${fmt.name} failed to write: ${(e as Error).message}`, { stage: "render" });
    }
  }

  readValue(field: Field, parts: Part[]): unknown {
    const fmt = this.formatOf(field);
    try {
      return fmt.read(makeSpan(parts), field, this.formatContext());
    } catch (e) {
      if (e instanceof Refusal) throw e;
      refuse("format-read-error", `field ${field.name}: format ${fmt.name} failed to read: ${(e as Error).message}`, { stage: "parse" });
    }
  }

  private spelledText(field: Field, value: unknown, forDemo: boolean): string {
    const parts = this.writeValue(field, value, forDemo);
    return parts.map((p) => (typeof p.text === "string" ? p.text : "")).join("");
  }

  // ------------------------------------------------------------- render

  private messageReferencesInputs(item: TemplateItem & { kind: "message" }): boolean {
    const inputs = new Set(this.signature.fields.filter((f) => f.direction === "input").map((f) => f.name));
    let yes = false;
    walk(item.nodes, (n) => {
      if (n.kind === "slot" && inputs.has(n.name)) yes = true;
      if (n.kind === "loop" && n.source === "inputs") yes = true;
    });
    return yes;
  }

  private renderNodes(nodes: Node[], scope: Scope): Part[] {
    const out: Part[] = [];
    const push = (text: string): void => {
      out.push(textPart(text));
    };
    for (const n of nodes) {
      if (n.kind === "text") {
        push(n.text);
      } else if (n.kind === "slot") {
        if (n.name === "instruction") push(this.signature.instructions);
        else if (n.name === "format") push(this.lens.format(this.visibleOutputs().map((f) => ({ name: f.name, text: this.placeholder(f) }))));
        else {
          const field = this.signature.fields.find((f) => f.name === n.name)!;
          out.push(...this.renderFieldValue(field, scope));
        }
      } else if (n.kind === "attr") {
        const field = scope.loops.get(n.variable)!;
        if (n.attr === "value") out.push(...this.renderFieldValue(field, scope));
        else push(this.attr(field, n.attr));
      } else if (n.kind === "loop") {
        const fields = n.source === "inputs" ? this.visibleInputs() : this.visibleOutputs();
        for (const f of fields) {
          if (n.source === "inputs" && scope.mode === "example" && !(scope.values && f.name in scope.values)) continue;
          const inner: Scope = { ...scope, loops: new Map(scope.loops) };
          inner.loops.set(n.variable, f);
          out.push(...this.renderNodes(n.body, inner));
        }
      }
    }
    return out;
  }

  private renderFieldValue(field: Field, scope: Scope): Part[] {
    const bf = this.fields.get(field.name)!;
    if (field.direction === "output") {
      if (!bf.visible) return [];
      return [textPart(this.placeholder(field))];
    }
    if (!bf.visible) return [];
    if (!scope.values || !(field.name in scope.values)) {
      refuse("missing-input", `no value supplied for input ${field.name}`, { stage: "render" });
    }
    return this.writeValue(field, scope.values[field.name], scope.mode === "example");
  }

  private exampleTurns(values: { [k: string]: unknown }): Message[] {
    const out: Message[] = [];
    const scope: Scope = { mode: "example", values, loops: new Map() };
    for (const item of this.adapter.template) {
      if (item.kind !== "message" || !this.messageReferencesInputs(item)) continue;
      out.push({ role: item.role, content: this.renderNodes(item.nodes, scope) });
    }
    const spelled: Spelled[] = [];
    for (const f of this.visibleOutputs()) {
      if (f.name in values) spelled.push({ name: f.name, text: this.spelledText(f, values[f.name], true) });
    }
    out.push({ role: "assistant", content: [textPart(this.lens.join(spelled))] });
    return out;
  }

  private historyTurns(item: unknown): Message[] {
    if (!isJsonObject(item)) refuse("value-invalid", "a history item must be a message or {fields: {...}}", { stage: "render" });
    if (typeof item.role === "string" && "content" in item) {
      const content = item.content;
      if (typeof content === "string") return [{ role: item.role, content: [textPart(content)] }];
      if (Array.isArray(content)) {
        for (const p of content) {
          if (!isJsonObject(p) || typeof p.kind !== "string") refuse("value-invalid", "a history message part needs a string kind", { stage: "render" });
        }
        return [{ role: item.role, content: cloneJson(content) as Part[] }];
      }
      refuse("value-invalid", "a history message's content must be a string or a part list", { stage: "render" });
    }
    if (isJsonObject(item.fields) && Object.keys(item).length === 1) return this.exampleTurns(item.fields);
    refuse("value-invalid", "a history item must be a message {role, content} or {fields: {...}}", { stage: "render" });
  }

  /**
   * Render every message. With `inputs` null, stop before the first
   * message that depends on inputs (the prefix).
   */
  private renderAll(inputs: Values | null, demos: unknown[] | undefined, history: unknown[] | undefined): { messages: Message[]; patch: { [k: string]: Json } } {
    const messages: Message[] = [];
    const placed = [...this.fields.values()].filter((bf) => bf.placement);
    const placedRoles = new Set(placed.filter((bf) => bf.placement!.startsWith("message:")).map((bf) => bf.placement!.slice("message:".length)));
    for (const item of this.adapter.template) {
      if (item.kind === "directive") {
        if (item.directive === "demos") {
          for (const d of demos ?? []) {
            if (!isJsonObject(d)) refuse("value-invalid", "a demo must be a field dict", { stage: "render" });
            messages.push(...this.exampleTurns(d));
          }
        } else {
          for (const h of history ?? []) messages.push(...this.historyTurns(h));
        }
        continue;
      }
      if (inputs === null && (this.messageReferencesInputs(item) || placedRoles.has(item.role))) break;
      const scope: Scope = { mode: "main", values: inputs, loops: new Map() };
      messages.push({ role: item.role, content: this.renderNodes(item.nodes, scope) });
    }
    // fragments append to the named message (created if absent, system first)
    const target = (role: string): Message => {
      let m = messages.find((x) => x.role === role);
      if (!m) {
        m = { role, content: [] };
        if (role === "system") messages.unshift(m);
        else messages.push(m);
      }
      return m;
    };
    const patch: { [k: string]: Json } = cloneJson(this.controls);
    const fragmentRolesDone = new Set<string>();
    for (const f of this.signature.fields) {
      const role = f.role;
      const frags = fragmentRolesDone.has(role) ? [] : this.fragments.filter((x) => x.strategyRole === role);
      fragmentRolesDone.add(role);
      for (const frag of frags) {
        const m = target(frag.role);
        const hasText = m.content.some((p) => p.kind === "text" && (p.text as string).length > 0);
        m.content.push(textPart((hasText ? "\n\n" : "") + frag.text));
      }
      const bf = this.fields.get(f.name)!;
      if (bf.placement && inputs !== null) {
        if (!(f.name in inputs)) refuse("missing-input", `no value supplied for placed input ${f.name}`, { stage: "render" });
        const parts = this.writeValue(f, inputs[f.name], false);
        if (bf.placement.startsWith("message:")) {
          target(bf.placement.slice("message:".length)).content.push(...parts);
        } else {
          const path = bf.placement.slice("controls.".length).split(".");
          let cur: { [k: string]: Json } = patch;
          for (const k of path.slice(0, -1)) {
            if (!isJsonObject(cur[k])) cur[k] = {};
            cur = cur[k] as { [k: string]: Json };
          }
          cur[path[path.length - 1]] = parts as unknown as Json;
        }
      }
    }
    for (const [k, v] of Object.entries(this.lens.patch)) patch[k] = cloneJson(v);
    return { messages: messages.map(mergeParts).filter((m) => m.content.length > 0), patch };
  }

  render(inputs: Values = {}, demos?: unknown[], history?: unknown[]): RenderResult {
    return this.renderAll(inputs, demos, history);
  }

  prefix(demos?: unknown[], history?: unknown[]): Message[] {
    return this.renderAll(null, demos, history).messages;
  }

  skeleton(): { prefill: string; stops: string[] } {
    return this.lens.skeleton();
  }

  // -------------------------------------------------------------- parse

  /** Batch parse with the raw text per field (what streaming deltas must join to). */
  parseWithRaws(response: unknown): { values: Values; raws: { [field: string]: string } } {
    const { text: channel, parts } = normalizeResponse(response);
    const spans = new Map<string, Part[]>();
    let text = channel;
    for (const stage of this.routingStages) {
      const r = stage.routing;
      const list = spans.get(stage.field.name) ?? [];
      if (r.from === "text") {
        let scan;
        if (r.between) scan = scanBetween(text, r.between[0], r.between[1], r.consume === true);
        else if (r.line_prefixed !== undefined) scan = scanLinePrefixed(text, r.line_prefixed, r.consume === true);
        else scan = scanPattern(text, stage.regex!, r.consume === true);
        for (const c of scan.captures) list.push(textPart(c));
        text = scan.remaining;
      } else {
        const kind = routingSpanKind(r);
        for (const p of parts) if (p.kind === kind) list.push(p);
      }
      spans.set(stage.field.name, list);
    }
    const lensRaws = this.lens.split(text);
    const raws: { [field: string]: string } = { ...lensRaws };
    const missing: string[] = [];
    for (const f of this.signature.fields) {
      if (f.direction !== "output") continue;
      const bf = this.fields.get(f.name)!;
      if (bf.routings.length) {
        const span = spans.get(f.name) ?? [];
        if (span.length === 0) missing.push(f.name);
        else raws[f.name] = makeSpan(span).text;
      }
    }
    if (missing.length) refuse("parse-missing-fields", `the reply carries nothing for routed field(s) ${missing.join(", ")}`, { stage: "parse", partial: raws });
    const values: Values = {};
    for (const f of this.signature.fields) {
      if (f.direction !== "output") continue;
      const bf = this.fields.get(f.name)!;
      if (bf.routings.length) values[f.name] = this.readValue(f, spans.get(f.name)!);
      else if (bf.visible) values[f.name] = this.readValue(f, [textPart(lensRaws[f.name])]);
    }
    return { values, raws };
  }

  parse(response: unknown): Values {
    return this.parseWithRaws(response).values;
  }

  stream(): Stream {
    return new Stream(this);
  }

  // ----------------------------------------------------------- describe

  describe(): { [k: string]: Json } {
    const fields: Json[] = [];
    for (const f of this.signature.fields) {
      const bf = this.fields.get(f.name)!;
      fields.push({
        name: f.name,
        direction: f.direction,
        role: f.role,
        visible: bf.visible,
        format: { name: bf.resolved.format.name, source: bf.resolved.source, key: bf.resolved.key ?? null, vocab: bf.resolved.format.vocab ?? null },
        routings: bf.routings.map((r) => ({ from: r.routing.from, to: r.routing.to, strategy: r.role })),
        placement: bf.placement ?? null,
      });
    }
    return {
      lens: this.lens.describe(),
      fields,
      controls: cloneJson(this.controls),
      strategies: Object.fromEntries([...this.chosen.entries()].map(([role, s]) => [role, cloneJson(s) as unknown as Json])),
      streaming: this.streamingDescription(),
    };
  }

  streamingDescription(): { [k: string]: Json } {
    const routings: Json[] = [];
    const counts = new Map<string, number>();
    for (const s of this.routingStages) counts.set(s.field.name, (counts.get(s.field.name) ?? 0) + 1);
    let anyBuffered = false;
    let anyIncremental = false;
    for (const s of this.routingStages) {
      let mode = "incremental";
      let reason = "";
      const r = s.routing;
      if (r.pattern !== undefined) {
        mode = "buffered";
        reason = "a later byte can change a regex match";
      } else if ((counts.get(s.field.name) ?? 0) > 1) {
        mode = "buffered";
        reason = "more than one routing writes this field; batch joins by routing order";
      } else if (r.between) reason = "emits a capture after its close arrives";
      else if (r.line_prefixed !== undefined) reason = "emits a capture after its newline arrives (or at EOF)";
      else reason = "streams text from matching part deltas";
      if (mode === "buffered") anyBuffered = true;
      else anyIncremental = true;
      routings.push({ field: s.field.name, from: r.from, mode, reason });
    }
    const lensMode = this.lens.project ? "incremental" : "buffered";
    if (lensMode === "buffered") anyBuffered = true;
    else anyIncremental = true;
    const mode = anyBuffered && anyIncremental ? "hybrid" : anyBuffered ? "buffered" : "incremental";
    return { mode, lens: { kind: this.lens.kind, mode: lensMode }, routings, field_done: "finish" };
  }

  explain(): string {
    const lines: string[] = [];
    lines.push(`adapter ${this.adapter.name ?? "(unnamed)"}: lens ${this.lens.kind}`);
    for (const f of this.signature.fields) {
      const bf = this.fields.get(f.name)!;
      const via = bf.routings.length ? `routed by ${bf.routings.map((r) => r.routing.from).join(", ")}` : bf.placement ? `placed at ${bf.placement}` : bf.visible ? "visible in the template" : "hidden";
      lines.push(`  ${f.direction} ${f.name} [${f.role}] — format ${bf.resolved.format.name} (${bf.resolved.source}${bf.resolved.key ? ` ${bf.resolved.key}` : ""}); ${via}`);
    }
    const s = this.streamingDescription();
    lines.push(`  streaming: ${String(s.mode)}; typed values at finish`);
    return lines.join("\n");
  }
}

function mergeParts(m: Message): Message {
  const content: Part[] = [];
  for (const p of m.content) {
    const last = content[content.length - 1];
    if (p.kind === "text" && typeof p.text === "string") {
      if (last && last.kind === "text" && typeof last.text === "string") {
        last.text = (last.text as string) + p.text;
        continue;
      }
      if (p.text === "") {
        continue;
      }
    }
    content.push({ ...p });
  }
  return { role: m.role, content: content.filter((p) => !(p.kind === "text" && p.text === "")) };
}

export function bind(adapter: Adapter, signature: Signature, capabilities: Capabilities = {}): Plan {
  const caps: Capabilities = {};
  for (const [k, v] of Object.entries(capabilities ?? {})) caps[k] = v === true;
  return new Plan(adapter, signature, caps);
}

/** The kernel scalar classification, exported for vocabulary packs. */
export { classifyShape };

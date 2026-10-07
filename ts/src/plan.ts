/**
 * Bind: where the adapter, the signature, and the model's facts meet.
 *
 * `bind(adapter, signature, capabilities, registry)` resolves every decision
 * before any money is spent — transports by purpose, visibility and put,
 * one format per field (kernel §5), the reader, template coverage — and
 * refuses by name. The resulting {@link Plan} does pure things only:
 * `render`, `read`/`parse`, `stream`, `describe`, `skeleton`, `prefix`.
 */

import { refuse, Refusal, type Fix } from "./errors.ts";
import {
  asParts, Capture, forgiveValue, finishReason, formatKey, isObj, makeMessage, mergeTextParts, partText, replyProbabilities,
  responseTextAndParts, shapeSummary, spellValue, structuralKeys, textPart, type Field, type Message, type Part,
} from "./core.ts";
import { isDescription, type Adapter, type Reference } from "./adapter.ts";
import { accepts as formatAccepts, isFormat, kernelDefault, loadUdf, SCALAR_DEFAULT, type Format } from "./formats.ts";
import { copyObject, deepCopy, hasOwn, isPlainObject, jsonEqual, jsonText, memberNames, orderedObject, ownValue, setMember } from "./json.ts";
import {
  applyFindRules, DerivedReader, Reader, refuseMissing, repairableMarkers, repairMarkers,
  type Anchor, type Edit, type FindRule, type PatternMatcher, type ReaderResult, type Repair,
} from "./reader.ts";
import type { Registry } from "./registry.ts";
import { KERNEL_VERSION, resolveAdapterExtensions } from "./serde.ts";
import type { Signature } from "./signature.ts";
import { branches, overTurns, renderNodes, validateNodes, type LoopNode, type Node, type RenderEnv } from "./template.ts";
import { lstrip, pyRepr, pyTruthy, rstrip, strip, WHITESPACE } from "./text.ts";
import { settingLeaves, spellTurn, Transport, validateSettingPath } from "./transport.ts";
import { asMessage, callId, ModelStep, sha256, signatureFingerprint, toJson, ToolStep, Turn, type Step, type TurnJSON } from "./turn.ts";
import { describeResolved, type PatternBinding, type Resolved as ResolvedExtension } from "./extensions.ts";
import { describeStreaming, Stream } from "./stream.ts";
import { brand } from "./brand.ts";

interface Resolved {
  readonly purpose: string;
  readonly field: Field;
  readonly transport: Transport;
  readonly name: string;
}

interface FormatChoice {
  readonly format: Format;
  /** `artifact:<key>` | `runtime:<type>` | `kernel` */
  readonly resolvedBy: string;
  described: string | null;
  describedBy: string | null;
}

type Writer = Record<string, unknown> & { by: string };

/** An lm15 request minus its model (§3): `system`, `messages`, and the request settings. */
export class RenderResult {
  readonly messages: Message[];
  readonly requestSettings: Record<string, unknown>;
  readonly system: string | Part[] | null;
  readonly plan: Plan<any, any>;
  readonly turn: Turn;

  constructor(messages: Message[], requestSettings: Record<string, unknown>, system: string | Part[] | null, plan: Plan<any, any>, turn: Turn) {
    this.messages = messages;
    this.requestSettings = requestSettings;
    this.system = system;
    this.plan = plan;
    this.turn = turn;
  }

  /** The whole request as one lm15 canonical object, feedable to any lm15 implementation. */
  request(model?: string): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    if (model !== undefined) out["model"] = model;
    if (this.system !== null) out["system"] = this.system;
    out["messages"] = this.messages;
    const settings = deepCopy(this.requestSettings);
    for (const k of memberNames(settings)) setMember(out, k, settings[k]);
    return out;
  }

  /** The reply to this request, parsed and recorded as the turn's next model step (§3a). Pure. */
  step(reply: unknown): Turn {
    let message = asMessage(reply);
    const values = this.plan.parse(reply);
    if (this.plan.prefill) {
      message = copyObject(message, { parts: mergeTextParts([textPart(this.plan.prefill), ...message.parts]) }) as unknown as Message;
    }
    return this.turn.withStep(new ModelStep(values as Record<string, unknown>, message, sha256(this.request()), this.plan.callsField));
  }

  toJSON(): Record<string, unknown> {
    return this.request();
  }
}

/** A reply, read (§4a): typed values, the repairs made, and what data parts measured (§3). */
export class Reading<O = Record<string, unknown>> {
  readonly values: O;
  readonly repairs: Repair[];
  readonly probabilities: Record<string, Record<string, number>>;
  readonly measuredBy: Record<string, string>;

  constructor(values: O, repairs: Repair[] = [], probabilities: Record<string, Record<string, number>> = {}, measuredBy: Record<string, string> = {}) {
    this.values = values;
    this.repairs = repairs;
    this.probabilities = probabilities;
    this.measuredBy = measuredBy;
  }

  get clean(): boolean {
    return !this.repairs.length;
  }

  toJSON(): Record<string, unknown> {
    return { values: this.values, repairs: this.repairs, probabilities: this.probabilities, measured_by: this.measuredBy };
  }
}

class WriteContext {
  modelSteps = 0;
}

const PART_SPOT = "\ufffc"; // where a written part goes in a pattern (§4b)

class Env implements RenderEnv {
  readonly plan: Plan<any, any>;
  readonly values: Record<string, unknown>;
  readonly partial: boolean;
  readonly texts: Map<string, [string, string, string][]>;
  readonly filled: Set<string>;

  constructor(plan: Plan<any, any>, values: Record<string, unknown>, partial: boolean,
    texts: Map<string, [string, string, string][]>, filled: Set<string>) {
    this.plan = plan;
    this.values = values;
    this.partial = partial;
    this.texts = texts;
    this.filled = filled;
  }

  turnMessages(slot: string): [string, string, string][] {
    return this.texts.get(slot) ?? [];
  }

  guard(name: string): boolean | null {
    const field = this.plan.signature.fields.find((f) => f.name === name);
    if (field && field.direction === "input") {
      const value = ownValue(this.values, name);
      return !(value === undefined || value === null || value === false || value === "" || (Array.isArray(value) && value.length === 0));
    }
    if (this.partial) return null;
    return this.filled.has(name);
  }

  get instruction(): string {
    return this.plan.signature.instructions;
  }

  get replyFormat(): string {
    return this.plan.replyFormat();
  }

  loopFields(source: string): Field[] {
    if (source !== "inputs") return this.plan.visibleOutputs;
    if (this.partial) return this.plan.visibleInputs.filter((f) => hasOwn(this.values, f.name));
    return this.plan.visibleInputs;
  }

  fieldNamed(name: string): Field {
    return this.plan.signature.fieldNamed(name)!;
  }

  schemaOf(f: Field): string {
    return this.plan.schemaHint(f);
  }

  valueOf(f: Field): ["text", string] | ["parts", Part[]] {
    if (f.direction === "output") return ["text", this.plan.placeholder(f)];
    if (!hasOwn(this.values, f.name)) refuse("missing-input", `no value supplied for field ${pyRepr(f.name)}`);
    const parts = this.plan.write(f, this.values[f.name]);
    if (parts.length === 1 && parts[0].type === "text") return ["text", parts[0]["text"] as string];
    return ["parts", parts];
  }
}

export type TurnsArg = Record<string, readonly (Turn | Record<string, unknown>)[]> | readonly (Turn | Record<string, unknown>)[];

export class Plan<I = Record<string, unknown>, O = Record<string, unknown>> {
  readonly adapter: Adapter;
  readonly signature: Signature<I, O>;
  readonly capabilities: Record<string, unknown>;
  readonly registry: Registry;
  visibleInputs: Field[] = [];
  visibleOutputs: Field[] = [];
  resolved: Resolved[] = [];
  findRules: [string, FindRule][] = [];
  puts: [string, string][] = [];
  writtenAs = new Map<string, Format>();
  tell: Record<string, string> = {};
  requestSettings: Record<string, unknown> = {};
  formats = new Map<string, FormatChoice>();
  reader!: Reader;
  prefill = "";
  findRepairable: string[] = [];
  findUnrepaired: string[] = [];
  extensions = new Map<string, ResolvedExtension>();
  turnInputFormats = new Map<string, Format>();
  ruleOwner: Resolved[] = [];
  slots = new Map<string, ["messages" | "text", number]>();
  callsField: string | null = null;
  callsOwner: Resolved | null = null;
  turnWriters = new Map<string, Writer>();
  replayTypes = new Set<string>();

  constructor(adapter: Adapter, signature: Signature<I, O>, capabilities: Record<string, unknown>, registry: Registry) {
    this.adapter = adapter;
    this.signature = signature;
    this.capabilities = capabilities;
    this.registry = registry;
  }

  patternBinding(): PatternMatcher | null {
    for (const r of this.extensions.values()) if (r.binding.family === "pattern") return r.binding as PatternBinding;
    return null;
  }

  // ---------------------------------------------------------- formats

  formatFor(f: Field): Format {
    return this.formats.get(f.name)!.format;
  }

  schemaHint(f: Field): string {
    const described = this.formats.get(f.name)!.described || this.formatFor(f).describe(f);
    return described || shapeSummary(f.shape);
  }

  /** desc, else the description or the format's describe, else the mechanical hint (§2, §5). */
  placeholder(f: Field): string {
    if (f.desc) return f.desc;
    const choice = this.formats.get(f.name)!;
    const described = choice.described || choice.format.describe(f);
    if (described) return described;
    if (choice.resolvedBy !== "kernel" && f.type) return f.type;
    return shapeSummary(f.shape) || "...";
  }

  replyFormat(): string {
    return this.reader.format(this.visibleOutputs.map((f) => [f.name, this.placeholder(f)]));
  }

  write(f: Field, value: unknown, fmt?: Format): Part[] {
    const own = fmt === undefined && this.formats.get(f.name)!.resolvedBy.startsWith("runtime:");
    const format = fmt ?? this.formatFor(f);
    if (!own) {
      // a type bound with toJson reaches the format bound to it as itself,
      // every other format (the artifact's, the kernel's) as its JSON form
      const hook = this.registry.host(f.type)?.toJson;
      if (hook) {
        try {
          value = this.hostJson(f, value, `field ${pyRepr(f.name)}`);
        } catch (err) {
          if (!(err instanceof Refusal)) throw err;
          refuse("format-write-error", err.hint);
        }
      }
    }
    let written: unknown;
    try {
      written = format.write(value, f);
    } catch (err) {
      if (err instanceof Refusal) throw err;
      refuse("format-write-error", `field ${pyRepr(f.name)}: format failed to write: ${(err as Error).message}`);
    }
    return asParts(written, `field ${pyRepr(f.name)}`);
  }

  readField(f: Field, capture: Capture): unknown {
    const fmt = this.formatFor(f);
    try {
      if (!fmt.read) throw new Error(`format ${fmt.name ?? "(inline)"} does not read`);
      return fmt.read(capture, f);
    } catch (err) {
      if (err instanceof Refusal) throw err;
      refuse("format-read-error", `field ${pyRepr(f.name)}: format failed to read: ${(err as Error).message}`);
    }
  }

  private spelledText(f: Field, value: unknown): string {
    const fmt = this.formatFor(f);
    if (!fmt.roundTrip) {
      refuse("turn-not-renderable", `field ${pyRepr(f.name)}: format ${fmt.name ?? "(inline)"} does not round-trip, so a turn written with it could not be read back`);
    }
    const parts = this.write(f, value);
    if (parts.some((p) => p.type !== "text")) {
      refuse("turn-not-renderable", `field ${pyRepr(f.name)}: its format writes non-text parts, which a text pattern cannot hold`);
    }
    return parts.map((p) => p["text"] as string).join("");
  }

  // ----------------------------------------------------------- turns

  get fingerprint(): string {
    return signatureFingerprint(this.signature);
  }

  /** A new turn of this plan's signature, with no steps (§3a). */
  turn(inputs: Partial<I> = {}): Turn {
    const values = dropUndefined(inputs as Record<string, unknown>);
    this.checkNames(values, "input", "inputs");
    return new Turn(this.fingerprint, values);
  }

  /** A turn that did not happen here: inputs and outputs, no steps. */
  example(inputs: Partial<I>, outputs: Partial<O>): Turn {
    const i = dropUndefined(inputs as Record<string, unknown>);
    const o = dropUndefined(outputs as Record<string, unknown>);
    this.checkNames(i, "input", "inputs");
    this.checkNames(o, "output", "outputs");
    return new Turn(this.fingerprint, i, [], o);
  }

  /**
   * A turn from JSON, checked against this plan's signature; each value of
   * a field whose type is bound with `fromJson` is rebuilt by it (§3a: a
   * host lifts JSON to its own types).
   */
  loadTurn(data: unknown): Turn {
    const t = this.checkTurn(Turn.fromJSON(data), "turn", false, true);
    const lift = (values: Record<string, unknown>, where: string): Record<string, unknown> => {
      const out: Record<string, unknown> = {};
      for (const k of memberNames(values)) {
        const v = values[k];
        const f = this.signature.fieldNamed(k)!;
        const hook = this.registry.host(f.type)?.fromJson;
        if (!hook || v === null) {
          setMember(out, k, v);
          continue;
        }
        try {
          setMember(out, k, hook(v));
        } catch (err) {
          if (err instanceof Refusal) throw err;
          refuse("turn-invalid", `${where}.${k}: cannot rebuild a ${f.type} from its JSON: ${(err as Error).message}`);
        }
      }
      return out;
    };
    const steps = t.steps.map((s, i) => (s instanceof ModelStep
      ? new ModelStep(lift(s.outputs, `turn.steps[${i}].outputs`), s.message, s.request, s.callsField) : s));
    return new Turn(t.signature, lift(t.inputs, "turn.inputs"), steps,
      t.outputs === null ? null : lift(t.outputs, "turn.outputs"), t.score, t.meta);
  }

  /**
   * A turn of this plan as JSON (schema/turn.schema.json): each value of a
   * field whose type is bound with `toJson` is written by it, every other
   * value as `turn.toJSON()` writes it. What `loadTurn` reads back.
   */
  dumpTurn(turn: Turn): TurnJSON {
    return this.hostValues(this.checkTurn(turn, "turn", false, true)).toJSON();
  }

  /** The turn with every bound value replaced by its JSON form (for `dumpTurn` and replay). */
  private hostValues(turn: Turn): Turn {
    const json = (values: Record<string, unknown>, where: string): Record<string, unknown> => {
      const out: Record<string, unknown> = {};
      for (const k of memberNames(values)) {
        const f = this.signature.fieldNamed(k);
        setMember(out, k, f ? this.hostJson(f, values[k], `${where}.${k}`) : values[k]);
      }
      return out;
    };
    const steps = turn.steps.map((s, i) => (s instanceof ModelStep
      ? new ModelStep(json(s.outputs, `turn.steps[${i}].outputs`), s.message, s.request, s.callsField) : s));
    return new Turn(turn.signature, json(turn.inputs, "turn.inputs"), steps,
      turn.outputs === null ? null : json(turn.outputs, "turn.outputs"), turn.score, turn.meta);
  }

  /** A field's value as its JSON form: its type's `toJson` when bound with one; `turn-invalid` naming `where` if that fails. */
  private hostJson(f: Field, value: unknown, where: string): unknown {
    const hook = this.registry.host(f.type)?.toJson;
    if (!hook || value === null || value === undefined) return value;
    let data: unknown;
    try {
      data = hook(value);
    } catch (err) {
      if (err instanceof Refusal) throw err;
      refuse("turn-invalid", `${where}: ${f.type}'s toJson failed: ${(err as Error).message}`);
    }
    return toJson(data, where);
  }

  private checkNames(values: unknown, direction: string, where: string): void {
    if (!isObj(values)) refuse("turn-invalid", `${where}: an object of ${direction} field values`);
    const known = new Set(this.signature.fields.filter((f) => f.direction === direction).map((f) => f.name));
    for (const k of memberNames(values)) {
      if (!known.has(k)) refuse("turn-invalid", `${where}.${k}: not an ${direction} field of this signature`);
    }
  }

  private checkTurn(t: unknown, where: string, past: boolean, pendingOk = false): Turn {
    if (isObj(t) && !(t instanceof Turn)) {
      // plain turn JSON, or a Turn of another lmcc version: its JSON is the versioned record (§3a)
      const data = !isPlainObject(t) && typeof (t as { toJSON?: unknown }).toJSON === "function" ? (t as { toJSON: () => unknown }).toJSON() : t;
      t = Turn.fromJSON(data, where);
    }
    if (!(t instanceof Turn)) refuse("turn-invalid", `${where}: expected a turn, got ${typeof t}`);
    if (t.signature !== this.fingerprint) {
      refuse("turn-invalid", `${where}: recorded for signature ${t.signature}, but this plan's is ${this.fingerprint}`);
    }
    this.checkNames(t.inputs, "input", `${where}.inputs`);
    if (t.outputs !== null) this.checkNames(t.outputs, "output", `${where}.outputs`);
    let pending: unknown[] = [];
    t.steps.forEach((s, i) => {
      const at = `${where}.steps[${i}]`;
      if (s instanceof ModelStep) {
        if (pending.length) refuse("turn-invalid", `${at}: call ${pyRepr(callId(pending[0]))} has no tool step`);
        this.checkNames(s.outputs, "output", `${at}.outputs`);
        pending = s.calls;
      } else {
        if (!pending.length || callId(pending[0]) !== s.id) refuse("turn-invalid", `${at}: tool step ${pyRepr(s.id)} answers no pending call`);
        pending = pending.slice(1);
      }
    });
    if (pending.length && !pendingOk) {
      refuse("turn-invalid", `${where}: call ${pyRepr(callId(pending[0]))} has no tool step` + (past ? "" : "; answer it with turn.tool(id, output) first"));
    }
    return t;
  }

  // ----------------------------------------------------------- render

  /**
   * This turn, in the context of those turns (§3a). `inputs`: an input
   * object or a {@link Turn}; `turns`: `{slot: [turn]}` or a list for the
   * slot `turns`.
   */
  render(inputs: Partial<I> | Turn = {}, opts: { turns?: TurnsArg } = {}): RenderResult {
    const isTurn = inputs instanceof Turn || (isObj(inputs) && !isPlainObject(inputs) && typeof (inputs as { toJSON?: unknown }).toJSON === "function");
    const current = isTurn ? this.checkTurn(inputs, "turn", false) : this.turn(inputs as Partial<I>);
    return this.renderTurn(current, this.slotValues(opts.turns));
  }

  private slotValues(turns: TurnsArg | undefined): Map<string, Turn[]> {
    const out = new Map<string, Turn[]>();
    if (turns === undefined || turns === null) return out;
    const bySlot: Record<string, readonly unknown[]> = Array.isArray(turns) ? { turns } : (turns as Record<string, readonly unknown[]>);
    if (!isObj(bySlot)) refuse("turn-invalid", "turns is {slot: [turn]} or a list for the slot 'turns'");
    for (const name of memberNames(bySlot)) {
      const ts = bySlot[name];
      if (!ts || !ts.length) continue;
      if (name === "steps" || !this.slots.has(name)) {
        refuse("turns-unplaced", `turns given for slot ${pyRepr(name)}, which `
          + (name === "steps" ? "is the current turn's own steps" : "the template does not place")
          + `; placed slots: ${this.slots.size ? pyRepr([...this.slots.keys()].sort()) : "none"}`);
      }
      out.set(name, ts.map((t, i) => this.checkTurn(t, `turns[${pyRepr(name)}][${i}]`, true)));
    }
    return out;
  }

  private renderTurn(current: Turn, slotValues: Map<string, Turn[]>, stopAt: number | null = null): RenderResult {
    if (current.steps.length && !this.slots.size) {
      refuse("turns-unplaced", "the current turn has steps, but the template places no turn slot to write them; add lmcc.turns()");
    }
    const ctx = new WriteContext();
    const texts = new Map<string, [string, string, string][]>();
    for (const [name, [form]] of this.slots) {
      if (form !== "text") continue;
      const msgs = this.slotMessages(name, current, slotValues, new WriteContext());
      texts.set(name, msgs.map(([m, kind]) => [m.role, kind, textOf(m, name)]));
    }
    const filled = new Set([...this.slots.keys()].filter((name) => (name === "steps" ? current.steps.length > 0 : (slotValues.get(name) ?? []).length > 0)));

    const messages: Message[] = [];
    const own: Message[] = [];
    const sysTell = ownValue(this.tell, "system") as string | undefined;
    let tellDone = sysTell === undefined;
    let compiled = this.adapter.compiledMessages();
    if (this.adapter.prefill !== null) compiled = compiled.slice(0, -1);
    for (let i = 0; i < compiled.length; i++) {
      if (stopAt !== null && i >= stopAt) break;
      const [msg, nodes] = compiled[i];
      if (nodes === null) {
        messages.push(...this.slotMessages((msg["slot"] as string | undefined) ?? "turns", current, slotValues, ctx).map(([m]) => m));
        continue;
      }
      let parts = this.renderMessage(nodes, current.inputs, false, texts, filled);
      if (msg["role"] === "system" && !tellDone) {
        parts = mergeTextParts([...parts, textPart("\n\n" + sysTell)]);
        tellDone = true;
      }
      if (parts.length) {
        const m = makeMessage(msg["role"] as string, parts);
        messages.push(m);
        own.push(m);
      }
    }
    if (stopAt === null && !this.slots.has("steps") && this.slots.size) messages.push(...this.writeSteps(current, ctx).map(([m]) => m));
    if (!tellDone) {
      const m = makeMessage("system", [textPart(sysTell!)]);
      messages.unshift(m);
      own.push(m);
    }
    for (const role of memberNames(this.tell)) {
      if (role === "system") continue;
      const text = this.tell[role];
      const target = own.find((m) => m.role === role);
      if (!target) {
        const m = makeMessage(role, [textPart(text)]);
        messages.push(m);
        own.push(m);
      } else {
        (target as { parts: Part[] }).parts = mergeTextParts([...target.parts, textPart("\n\n" + text)]);
      }
    }
    const requestSettings = deepCopy(this.requestSettings);
    for (const [fname, place] of this.puts) {
      const f = this.signature.fieldNamed(fname)!;
      if (f.direction !== "input" || !hasOwn(current.inputs, fname)) continue;
      const parts = this.write(f, current.inputs[fname], this.writtenAs.get(fname));
      if (place.startsWith("request.")) {
        setPath(requestSettings, place.slice("request.".length), parts);
      } else {
        const role = place.slice(place.indexOf(":") + 1);
        const target = own.find((m) => m.role === role);
        if (!target) {
          const m = makeMessage(role, parts);
          messages.push(m);
          own.push(m);
        } else {
          (target as { parts: Part[] }).parts = mergeTextParts([...target.parts, textPart("\n\n"), ...parts]);
        }
      }
    }
    if (this.prefill && stopAt === null) messages.push(makeMessage("assistant", [textPart(this.prefill)]));
    const systemParts = messages.filter((m) => m.role === "system").flatMap((m) => m.parts);
    let system: string | Part[] | null = null;
    if (systemParts.length) {
      system = systemParts.length === 1 && systemParts[0].type === "text" ? (systemParts[0]["text"] as string) : systemParts;
    }
    return new RenderResult(messages.filter((m) => m.role !== "system"), requestSettings, system, this, current);
  }

  private renderMessage(nodes: Node[], values: Record<string, unknown>, partial = false,
    texts: Map<string, [string, string, string][]> = new Map(), filled: Set<string> = new Set()): Part[] {
    const out: Part[] = [];
    const buf: string[] = [];
    renderNodes(nodes, new Env(this, values, partial, texts, filled), out, buf);
    if (buf.length) out.push(textPart(buf.join("")));
    return mergeTextParts(out);
  }

  private slotMessages(name: string, current: Turn, slotValues: Map<string, Turn[]>, ctx: WriteContext): [Message, string][] {
    if (name === "steps") return this.writeSteps(current, ctx);
    const out: [Message, string][] = [];
    for (const t of slotValues.get(name) ?? []) {
      out.push(...this.userSide(t.inputs).map((m): [Message, string] => [m, "input"]));
      if (t.steps.length) {
        out.push(...this.writeSteps(t, ctx));
      } else if (t.outputs && memberNames(t.outputs).length) {
        const [message] = this.modelMessage(new ModelStep(t.outputs), ctx);
        if (message !== null) out.push([message, "model"]);
      }
    }
    return out;
  }

  /** A past turn's user side: every template user message over its inputs. */
  private userSide(inputs: Record<string, unknown>): Message[] {
    const out: Message[] = [];
    for (const [msg, nodes] of this.adapter.compiledMessages()) {
      if (nodes !== null && msg["role"] === "user") {
        const parts = this.renderMessage(nodes, inputs, true);
        if (parts.length) out.push(makeMessage("user", parts));
      }
    }
    return out;
  }

  private writeSteps(t: Turn, ctx: WriteContext): [Message, string][] {
    const out: [Message, string][] = [];
    let ids = new Map<string, string>();
    for (const step of t.steps) {
      if (step instanceof ModelStep) {
        const [message, written] = this.modelMessage(step, ctx);
        ids = written;
        if (message !== null) out.push([message, "model"]);
      } else {
        out.push([this.toolMessage(step, ids.get(step.id) ?? step.id), "tool"]);
      }
    }
    return out;
  }

  /** §3a: the recorded reply when this plan reads it back into the same values; else from values. */
  private modelMessage(step: ModelStep, ctx: WriteContext): [Message | null, Map<string, string>] {
    if (this.adapter.replay === "verbatim" && step.message !== null) {
      ctx.modelSteps++;
      return [makeMessage("assistant", step.message.parts.map((p) => copyObject(p) as Part)), new Map()];
    }
    if (this.adapter.replay === "recorded" && step.message !== null) {
      let same: boolean;
      try {
        const [values, , reps] = this.parseWithCaptures(step.message, false);
        const json = (v: Record<string, unknown>) => this.hostValues(new Turn(this.fingerprint, {}, [], v)).outputs;
        same = jsonEqual(toJson(json(values)), toJson(json(step.outputs))) && !reps.some((r) => ["marker", "unclosed", "value"].includes(r["repair"] as string));
      } catch (err) {
        if (!(err instanceof Refusal)) throw err;
        same = false;
      }
      if (same) {
        ctx.modelSteps++;
        return [makeMessage("assistant", step.message.parts.map((p) => copyObject(p) as Part)), new Map()];
      }
    }
    return this.writeModelStep(step, ctx);
  }

  private writeModelStep(step: ModelStep, ctx: WriteContext): [Message | null, Map<string, string>] {
    const outputs = step.outputs;
    const recorded = step.message?.parts ?? [];
    const parts: Part[] = recorded.filter((p) => this.replayTypes.has(p.type)).map((p) => copyObject(p) as Part);
    const before: string[] = [];
    const after: string[] = [];
    for (const [fname, w] of this.turnWriters) {
      const value = ownValue(outputs, fname);
      if (["dropped", "projection", "replayed", "spelling.call", "format:parts"].includes(w.by)
        || value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)) continue;
      const f = this.signature.fieldNamed(fname)!;
      const text = this.spelledText(f, value);
      let piece: string;
      if (w.by === "derived:between") {
        const [open, close] = w["between"] as [string, string];
        if (text.includes(close)) refuse("value-collides", `field ${pyRepr(fname)}: its written value contains ${pyRepr(close)}, the marker that ends it`);
        piece = open + text + close;
      } else if (w.by === "derived:line_prefixed") {
        piece = text.split("\n").map((line) => (w["prefix"] as string) + line).join("\n");
      } else {
        piece = spellTurn(w["template"] as string, { value: text });
      }
      (w["position"] === "before" ? before : after).push(piece);
    }
    const spelled: [string, string][] = [];
    const placedParts: Part[][] = [];
    for (const f of this.visibleOutputs) {
      if (!hasOwn(outputs, f.name)) continue;
      const fmt = this.formatFor(f);
      if (fmt.writes === "parts" && this.reader instanceof DerivedReader) {
        if (!fmt.roundTrip) refuse("turn-not-renderable", `field ${pyRepr(f.name)}: format ${fmt.name ?? "(inline)"} does not round-trip`);
        placedParts.push(this.write(f, outputs[f.name]));
        spelled.push([f.name, PART_SPOT]);
      } else {
        const textValue = this.spelledText(f, outputs[f.name]);
        if (textValue.includes(PART_SPOT)) refuse("value-collides", `field ${pyRepr(f.name)}: its value contains U+FFFC, which marks where a part goes`);
        spelled.push([f.name, textValue]);
      }
    }
    const body = spelled.length ? this.reader.join(spelled) : "";
    let text = [...before, body, ...after].filter((p) => p).join("\n");
    const ids = new Map<string, string>();
    const calls = this.callsField ? ownValue(outputs, this.callsField) : undefined;
    const callParts: Part[] = [];
    if (pyTruthy(calls)) {
      const f = this.signature.fieldNamed(this.callsField!)!;
      let written: Part[];
      try {
        written = this.write(f, calls);
      } catch (err) {
        if (!(err instanceof Refusal) || err.code !== "format-write-error") throw err;
        refuse("turn-not-renderable", `field ${pyRepr(this.callsField)}: ${err.hint}`);
      }
      for (const p of written) {
        if (p.type !== "tool_call" || typeof p["id"] !== "string" || typeof p["name"] !== "string" || !isObj(p["input"])) {
          refuse("turn-not-renderable", `field ${pyRepr(this.callsField)}: its format must write lm15 tool_call parts {type, id, name, input}; got ${pyRepr(p)}`);
        }
        if (p["id"] === "") {
          refuse("turn-invalid", `field ${pyRepr(this.callsField)}: call ${pyRepr(p["name"])} has the id '', and a call's id is non-empty text (lm15 ToolCallPart.id; a tool step answers the call by it)`);
        }
      }
      const owner = this.callsOwner;
      if (owner !== null && "call" in owner.transport.spelling) {
        const callText = written.map((p) => this.callText(owner, p)).join("\n");
        text = text ? text + "\n" + callText : callText;
      } else {
        const assigned = !recorded.some((p) => p.type === "tool_call");
        const k = ctx.modelSteps;
        for (let p of written) {
          if (assigned) {
            ids.set(p["id"] as string, `s${k}_${p["id"]}`);
            p = copyObject(p, { id: ids.get(p["id"] as string)! }) as Part;
          }
          callParts.push(p);
        }
      }
    }
    if (placedParts.length) {
      const pieces = text.split(PART_SPOT);
      const withTail = [...placedParts, []];
      for (let i = 0; i < Math.min(pieces.length, withTail.length); i++) {
        if (pieces[i]) parts.push(textPart(pieces[i]));
        parts.push(...withTail[i].map((x) => copyObject(x) as Part));
      }
    } else if (text) {
      parts.push(textPart(text));
    }
    parts.push(...callParts);
    if (!parts.length) return [null, ids];
    ctx.modelSteps++;
    return [makeMessage("assistant", parts), ids];
  }

  private toolMessage(step: ToolStep, writtenId: string): Message {
    const owner = this.callsOwner;
    if (owner !== null && "result" in owner.transport.spelling) {
      const output = step.output.filter((p) => p.type === "text" && typeof p["text"] === "string").map((p) => p["text"] as string).join("\n");
      const text = spellTurn(owner.transport.spelling["result"] as string, { id: step.id, name: step.name, output });
      const media = step.output.filter((p) => p.type !== "text").map((p) => copyObject(p) as Part);
      return makeMessage("user", [textPart(text), ...media]);
    }
    return makeMessage("tool", [{ type: "tool_result", id: writtenId, name: step.name, content: step.output.map((p) => copyObject(p) as Part) }]);
  }

  /** One call writer, used for written turns and the bind-time sample (§6). */
  callText(resolved: Resolved, call: Record<string, unknown>): string {
    const fmt = this.turnInputFormats.get(resolved.purpose);
    let body: string;
    const input = call["input"] ?? {};
    if (!fmt) {
      body = jsonText(input, { spaced: true, code: "format-write-error" });
    } else {
      try {
        const parts = asParts(fmt.write(input, { name: "input", direction: "input", shape: { type: "object" }, type: null, purpose: "plain", desc: null }), "spelling.input_format");
        if (parts.some((p) => p.type !== "text" || typeof p["text"] !== "string")) throw new Error("argument writer must return only text parts");
        body = parts.map((p) => p["text"] as string).join("");
      } catch (err) {
        if (err instanceof Refusal) throw err;
        refuse("format-write-error", `spelling.input_format on purpose ${pyRepr(resolved.purpose)}: ${(err as Error).message}`);
      }
    }
    return spellTurn(resolved.transport.spelling["call"] as string, { id: String(call["id"] ?? ""), name: String(call["name"] ?? ""), input: body });
  }

  /** The rendered request prefix that does not depend on inputs (§3): the cache-stable bytes. */
  prefix(opts: { turns?: TurnsArg } = {}): Record<string, unknown> {
    let stop: number | null = null;
    const inputNames = new Set(this.visibleInputs.map((f) => f.name));
    const compiled = this.adapter.compiledMessages();
    for (let i = 0; i < compiled.length; i++) {
      const nodes = compiled[i][1];
      if (nodes !== null && dependsOnInputs(nodes, inputNames)) {
        stop = i;
        break;
      }
    }
    const putRoles = new Set(this.puts
      .filter(([fname, place]) => place.startsWith("message:") && this.signature.fieldNamed(fname)!.direction === "input")
      .map(([, place]) => place.slice(place.indexOf(":") + 1)));
    for (let i = 0; i < compiled.length; i++) {
      const [msg, nodes] = compiled[i];
      if (nodes !== null && putRoles.has(msg["role"] as string)) {
        stop = stop === null ? i : Math.min(stop, i);
        break;
      }
    }
    const systemVaries = putRoles.has("system") || (stop !== null && compiled.slice(stop).some(([msg, nodes]) => nodes !== null && msg["role"] === "system"));
    if (systemVaries) return { messages: [] };
    const rendered = this.renderTurn(new Turn(this.fingerprint, {}), this.slotValues(opts.turns), stop);
    const out: Record<string, unknown> = {};
    if (rendered.system !== null) out["system"] = rendered.system;
    out["messages"] = rendered.messages;
    return out;
  }

  skeleton(): { prefill?: string; stops?: string[] } {
    return this.reader.skeleton();
  }

  /** A pure, sans-I/O streaming parser (§8). */
  stream(): Stream<O> {
    return new Stream<O>(this);
  }

  // ------------------------------------------------------------ parse

  /** The one batch parse path, shared by `read`, `parse` and stream EOF: `[values, captures, repairs]`. */
  parseWithCaptures(response: unknown, continued = true): [Record<string, unknown>, Map<string, Capture>, Repair[]] {
    const reason = finishReason(response);
    const cut = reason === "length" || reason === "error" ? reason : null; // §4a: truncated, interrupted
    let [text, parts] = responseTextAndParts(response);
    this.refuseFiltered(response, parts); // §4a: before anything is read
    const lead = continued && this.prefill ? this.prefill : "";
    text = lead + text;
    const atoms = atomsOf(parts, this.findRules, lead.length);
    const edits: Edit[][] = [];
    let repairs: Repair[] = [];
    if (this.findRepairable.length) [text, repairs] = repairMarkers(text, this.findRepairable, edits);
    let found: Map<string, Capture>;
    [text, found] = applyFindRules(text, parts, this.findRules, this.patternBinding(), edits);
    const complete = this.findRules.some(([name, r]) => r["complete_reply"] && (found.get(name)?.parts.length ?? 0) > 0);
    const names = this.visibleOutputs.map((f) => f.name);
    const derived = this.reader instanceof DerivedReader;
    let toEnd = new Set<string>();
    let missingErr: Refusal | null = null;
    let result: ReaderResult | null = null;
    let raw: Record<string, string>;
    try {
      if (derived) {
        result = (this.reader as DerivedReader).read(text, names, { allowMissing: true, edits });
        raw = result.raw;
        toEnd = result.toEnd;
        repairs = [...repairs, ...result.repairs];
      } else {
        raw = this.reader.split(text, names);
      }
    } catch (err) {
      if (err instanceof Refusal) {
        if (cut && !derived) this.refuseCut(cut, "", {}, err.hint);
        if (!(err.code === "parse-missing-fields" && isObj(err.partial))) throw err;
        raw = copyObject<string>(err.partial as object);
        missingErr = err;
      } else {
        if (cut && !derived) this.refuseCut(cut, "", {}, (err as Error).message);
        refuse("reader-error", `reader ${pyRepr(this.adapter.reader["kind"])} failed to read the reply: ${(err as Error).message}`);
      }
    }
    const missing = names.filter((n) => !hasOwn(raw, n));
    if (cut) {
      const ended: Record<string, string> = {};
      for (const k of memberNames(raw)) if (!toEnd.has(k)) setMember(ended, k, raw[k]);
      if (missing.length) this.refuseCut(cut, `before field ${pyRepr(missing[0])}`, ended);
      if (toEnd.size) this.refuseCut(cut, `inside field ${pyRepr(names.find((n) => toEnd.has(n)))}`, ended);
      if (!derived) this.refuseCut(cut, "", ended);
    }
    if (missing.length && !complete) {
      if (missingErr !== null) throw missingErr;
      refuseMissing(raw, names);
    }
    const captures = new Map<string, Capture>();
    for (const f of this.visibleOutputs) if (hasOwn(raw, f.name)) captures.set(f.name, Capture.ofText(raw[f.name]));
    if (atoms.length && derived && result !== null) {
      const [placed, ignored] = placeAtoms(atoms, edits, result);
      for (const [name, inside] of placed) {
        if (captures.has(name)) captures.set(name, interleaved(result.text, result.spans.get(name)!, inside, raw[name]));
      }
      repairs = [...repairs, ...ignored.map((p) => ({ repair: "ignored", part: p.type }))];
    }
    for (const [name, capture] of found) captures.set(name, capture);
    const values: Record<string, unknown> = {};
    for (const f of this.visibleOutputs) {
      if (captures.has(f.name)) setMember(values, f.name, this.readForgiving(f, captures.get(f.name)!, repairs));
    }
    for (const [name, capture] of found) setMember(values, name, this.readForgiving(this.signature.fieldNamed(name)!, capture, repairs));
    return [values, captures, repairs];
  }

  private readForgiving(f: Field, capture: Capture, repairs: Repair[]): unknown {
    try {
      return this.readField(f, capture);
    } catch (err) {
      if (!(err instanceof Refusal) || this.adapter.strict || err.code !== "parse-value" || this.formatFor(f) !== SCALAR_DEFAULT) throw err;
      const value = forgiveValue(f.shape, capture.text, `field ${pyRepr(f.name)}`);
      repairs.push({ repair: "value", field: f.name, saw: strip(capture.text), as: spellValue(f.shape, value, `field ${pyRepr(f.name)}`) });
      return value;
    }
  }

  /** §4a: a reply the provider stopped is not an answer, whether or not its text reads. */
  private refuseFiltered(response: unknown, parts: Part[]): void {
    const refusal = parts.find((p) => p["type"] === "refusal");
    if (refusal === undefined && finishReason(response) !== "content_filter") return;
    let hint: string;
    if (refusal !== undefined) {
      const said = strip(typeof refusal["text"] === "string" ? refusal["text"] : "");
      hint = "the model declined to answer" + (said ? `: ${pyRepr(said)}` : "");
    } else {
      hint = "the provider stopped the reply (finish_reason content_filter: its safety filter, or the model declining)";
    }
    refuse("parse-filtered", hint + "; the same request would be stopped again, so change the request or the model rather than asking again", { partial: {} });
  }

  /** §4a: the provider cut the reply (at its length limit, or by an error); say where, keep what ended. */
  private refuseCut(reason: string, where: string, partial: Record<string, string>, why = ""): never {
    const error = reason === "error";
    const cause = error ? "the provider ended the reply in error" : "the provider cut the reply at its length limit";
    const remedy = error ? "send the request again" : "raise max_tokens or ask for less";
    let hint: string;
    if (where) {
      hint = `${cause} ${where}`;
    } else {
      hint = `${cause}; reader ${pyRepr(this.adapter.reader["kind"])} cannot tell which outputs ended before it`;
      if (why) hint += ` (${why})`;
    }
    if (error) refuse("parse-interrupted", hint + "; " + remedy, { partial });
    refuse("parse-truncated", hint + "; " + remedy, { partial });
  }


  /** The typed values of a reply and every repair made to read them (§4a). Pure. */
  read(response: unknown): Reading<O> {
    const [probabilities, measuredBy] = replyProbabilities(response);
    const [values, , repairs] = this.parseWithCaptures(response);
    return new Reading<O>(values as O, repairs, probabilities, measuredBy);
  }

  /** The typed values of a reply: `read(response).values`. */
  parse(response: unknown): O {
    return this.read(response).values;
  }

  // ---------------------------------------------------------- describe

  describe(): Record<string, unknown> {
    const found = new Set(this.findRules.map(([name]) => name));
    const choice = (f: Field) => this.formats.get(f.name)!;
    const described = (f: Field) => (choice(f).describedBy ? { described_by: choice(f).describedBy } : {});
    const visibleIn = new Set(this.visibleInputs);
    const visibleOut = new Set(this.visibleOutputs);
    const out: Record<string, unknown> = {
      adapter: this.adapter.name,
      reader: { kind: this.adapter.reader["kind"] } as Record<string, unknown>,
      capabilities: copyObject(this.capabilities),
      inputs: this.visibleInputs.map((f) => copyObject({
        name: f.name, type: f.type, shape: f.shape, format: choice(f).format.name ?? "(inline)", resolved_by: choice(f).resolvedBy,
      }, described(f))),
      outputs: this.visibleOutputs.map((f) => copyObject({
        name: f.name, type: f.type, shape: f.shape, format: choice(f).format.name ?? "(inline)", resolved_by: choice(f).resolvedBy,
      }, described(f), { found: found.has(f.name) })),
      hidden: this.signature.fields.filter((f) => !visibleIn.has(f) && !visibleOut.has(f)).map((f) => f.name),
      transports: orderedObject(this.resolved.map((r) => [r.purpose, r.name])),
      extensions: orderedObject([...this.extensions.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([n, r]) => [n, describeResolved(r)])),
      find: this.findRules.map(([name, r]) => copyObject({ field: name }, r)),
      puts: this.puts.map(([name, place]) => ({ field: name, at: place })),
      tell: copyObject(this.tell),
      request_settings: deepCopy(this.requestSettings),
      strict: this.adapter.strict,
    };
    if (this.adapter.prefill !== null) out["prefill"] = { text: rstrip(this.adapter.prefill), sent: Boolean(this.prefill) };
    out["skeleton"] = this.skeleton();
    out["streaming"] = describeStreaming(this);
    const reader = out["reader"] as Record<string, unknown>;
    if (this.reader instanceof DerivedReader) {
      reader["anchors"] = this.reader.anchors.map((a) => [...a]);
      if (this.reader.unrepaired.length) reader["unrepaired"] = [...this.reader.unrepaired];
      if (this.reader.tail) reader["tail"] = this.reader.tail;
    } else if (this.reader.spec) {
      for (const k of memberNames(this.reader.spec)) if (k !== "kind") setMember(reader, k, this.reader.spec[k]);
    }
    const vocab: Record<string, string> = {};
    for (const c of this.formats.values()) {
      const named = c.format.name ? this.registry.formats.get(c.format.name) : undefined;
      if (named) setMember(vocab, `format/${c.format.name}`, named.version);
    }
    for (const r of this.resolved) {
      const named = this.registry.transports.get(r.name);
      if (named) setMember(vocab, `transport/${r.name}`, named.version);
    }
    const readerNamed = this.registry.readers.get(this.adapter.reader["kind"] as string);
    if (readerNamed) setMember(vocab, `reader/${this.adapter.reader["kind"]}`, readerNamed.version);
    const turnInfo: Record<string, unknown> = {};
    for (const r of this.resolved) {
      if (!this.turnInputFormats.has(r.purpose)) continue;
      const ref = r.transport.spelling["input_format"] as Reference;
      const version = this.registry.formats.get(ref.use)!.version;
      setMember(vocab, `format/${ref.use}`, version);
      setMember(turnInfo, r.purpose, { input_format: deepCopy(ref), version });
    }
    const writers: Record<string, unknown> = {};
    const projections: Record<string, unknown> = {};
    const replayed: string[] = [];
    for (const [k, v] of this.turnWriters) {
      if (v.by !== "projection" && v.by !== "replayed") setMember(writers, k, deepCopy(v));
      if (v.by === "projection") setMember(projections, k, v["of"]);
      if (v.by === "replayed") replayed.push(k);
    }
    out["turns"] = {
      slots: [...this.slots.entries()].map(([name, [form]]) => ({ name, form })),
      steps: !this.slots.size ? null : this.slots.has("steps") ? "placed" : "after the template",
      replay: this.adapter.replay,
      writers,
      projections,
      replayed: replayed.sort(),
      input_formats: turnInfo,
    };
    out["versions"] = { kernel: KERNEL_VERSION, vocab };
    return out;
  }

  explain(): string {
    const d = this.describe();
    const lines = [`adapter: ${d["adapter"]}`, `reader: ${(d["reader"] as Record<string, unknown>)["kind"]}`];
    for (const f of d["inputs"] as Record<string, unknown>[]) lines.push(`input  ${String(f["name"]).padEnd(20)} ${f["format"]} (${f["resolved_by"]})`);
    for (const f of d["outputs"] as Record<string, unknown>[]) {
      lines.push(`output ${String(f["name"]).padEnd(20)} ${f["format"]} (${f["resolved_by"]})${f["found"] ? " + rule" : ""}`);
    }
    for (const h of d["hidden"] as string[]) lines.push(`hidden ${h.padEnd(20)} served by transport/put`);
    if (memberNames(d["request_settings"] as object).length) lines.push(`request_settings: ${pyRepr(d["request_settings"])}`);
    return lines.join("\n");
  }
}

function dropUndefined(values: Record<string, unknown>): Record<string, unknown> {
  if (!isObj(values)) return values;
  const out: Record<string, unknown> = {};
  for (const k of memberNames(values)) if (values[k] !== undefined) setMember(out, k, values[k]);
  return out;
}

function textOf(message: Message, slot: string): string {
  for (const p of message.parts) {
    if (p.type !== "text") {
      refuse("turn-not-renderable",
        `slot ${pyRepr(slot)} is placed as text, but a ${message.role} message of its turns holds a ${pyRepr(p.type)} part, which text cannot hold; place the slot as messages (lmcc.turns(${pyRepr(slot)})) or use a text transport`);
    }
  }
  return message.parts.map((p) => p["text"] as string).join("");
}

// ------------------------------------------------------------- atoms (§4b)

type Atom = [number, Part];

function atomsOf(parts: Part[], findRules: [string, FindRule][], shift: number): Atom[] {
  const claimed = new Set(findRules.filter(([, r]) => r.from.startsWith("part:")).map(([, r]) => r.from.slice(r.from.indexOf(":") + 1)));
  const out: Atom[] = [];
  let pos = shift;
  for (const p of parts) {
    if (p.type === "text" || p.type === "data") pos += partText(p).length;
    else if (!claimed.has(p.type)) out.push([pos, p]);
  }
  return out;
}

function mapOffset(offset: number, stages: Edit[][]): number | null {
  for (const stage of stages) {
    let shift = 0;
    for (const [start, end, newLen] of stage) {
      if (offset <= start) break;
      if (offset < end) return null;
      shift += newLen - (end - start);
    }
    offset += shift;
  }
  return offset;
}

function placeAtoms(atoms: Atom[], edits: Edit[][], result: ReaderResult): [Map<string, Atom[]>, Part[]] {
  const placed = new Map<string, Atom[]>();
  const ignored: Part[] = [];
  for (const [offset, part] of atoms) {
    const o = mapOffset(offset, edits);
    let owner: string | null = null;
    if (o !== null) {
      for (const [name, [a, b]] of result.spans) {
        if (a <= o && o <= b) {
          owner = name;
          break;
        }
      }
    }
    if (owner === null) ignored.push(part);
    else placed.set(owner, [...(placed.get(owner) ?? []), [o!, part]]);
  }
  return [placed, ignored];
}

function interleaved(text: string, span: [number, number], inside: Atom[], raw: string): Capture {
  const [a, b] = span;
  const seq: Part[] = [];
  let pos = a;
  for (const [o, part] of [...inside].sort((x, y) => x[0] - y[0])) {
    seq.push(textPart(text.slice(pos, o)), part);
    pos = o;
  }
  seq.push(textPart(text.slice(pos, b)));
  if (seq[0].type === "text") seq[0] = textPart(lstrip(seq[0]["text"] as string, WHITESPACE));
  const last = seq.length - 1;
  if (seq[last].type === "text") seq[last] = textPart(rstrip(seq[last]["text"] as string, WHITESPACE));
  return new Capture(seq.filter((p) => p.type !== "text" || p["text"]), raw);
}

function bareSlots(nodes: Node[]): Set<string> {
  const out = new Set<string>();
  for (const n of nodes) {
    if (n.kind === "slot" && !n.path.includes(".")) out.add(n.path);
    else if (n.kind === "guard") for (const s of bareSlots(branches(n))) out.add(s);
  }
  return out;
}

function dependsOnInputs(nodes: Node[], inputNames: Set<string>): boolean {
  for (const n of nodes) {
    if (n.kind === "slot" && inputNames.has(n.path)) return true;
    if (n.kind === "loop" && !overTurns(n) && (n.source === "inputs" || dependsOnInputs(n.body, inputNames))) return true;
    if (n.kind === "guard" && (inputNames.has(n.slot) || dependsOnInputs(branches(n), inputNames))) return true;
  }
  return false;
}

const MISSING = Symbol("missing");

function getPath(target: unknown, path: string): unknown {
  for (const k of path.split(".")) {
    if (!isObj(target) || !hasOwn(target, k)) return MISSING;
    target = target[k];
  }
  return target;
}

function setPath(target: Record<string, unknown>, path: string, value: unknown): void {
  const keys = path.split(".");
  for (const k of keys.slice(0, -1)) {
    if (!hasOwn(target, k)) setMember(target, k, {});
    target = target[k] as Record<string, unknown>;
  }
  setMember(target, keys[keys.length - 1], value);
}

function mergeSetting(plan: Plan<any, any>, path: string, value: unknown, owner: string, settingOwner: Map<string, string>, conflictPath: string): void {
  const existing = getPath(plan.requestSettings, path);
  if (existing !== MISSING && !jsonEqual(existing, value)) {
    refuse("setting-conflict", `${pyRepr(owner)} and ${pyRepr(settingOwner.get(path) ?? null)} disagree on request control ${pyRepr(path)}`,
      { fix: { action: "edit-entry", path: conflictPath } });
  }
  setPath(plan.requestSettings, path, value);
  if (!settingOwner.has(path)) settingOwner.set(path, owner);
}

// ---------------------------------------------------------- derived reader

type Hole = ["loop", LoopNode] | ["slot", Node & { kind: "slot" }];

function outputHoles(nodes: Node[], sig: Signature<unknown, unknown>, holes: Hole[]): void {
  for (const node of nodes) {
    if (node.kind === "guard") {
      const inner: Hole[] = [];
      outputHoles(branches(node), sig, inner);
      if (inner.length) {
        refuse("not-readable", "the output pattern cannot sit inside a {% if %} guard: the reply's shape must not depend on which turns were given",
          { fix: { action: "edit-template", path: "template" } });
      }
    } else if (node.kind === "loop" && overTurns(node)) {
      continue;
    } else if (node.kind === "loop") {
      if (node.source === "outputs" && node.body.some((n) => n.kind === "slot" && n.path === `${node.var}.value`)) holes.push(["loop", node]);
      else outputHoles(node.body, sig, holes);
    } else if (node.kind === "slot") {
      const f = sig.fieldNamed(node.path);
      if (f && f.direction === "output") holes.push(["slot", node]);
    }
  }
}

function deriveReader(plan: Plan<any, any>): DerivedReader {
  const sig = plan.signature;
  const found: [number, Node[], Hole[]][] = [];
  plan.adapter.compiledMessages().forEach(([, nodes], i) => {
    if (nodes === null) return;
    const holes: Hole[] = [];
    outputHoles(nodes, sig, holes);
    if (holes.length) found.push([i, nodes, holes]);
  });
  if (!found.length) {
    refuse("not-readable", "parse kind 'derived' needs an output pattern — an outputs loop containing {f.value}, or output slots — and the template has none",
      { fix: { action: "edit-template", path: "template" } });
  }
  if (found.length > 1) {
    refuse("not-readable", `the output pattern must live in one message; found holes in messages ${pyRepr(found.map(([i]) => i))}`,
      { fix: { action: "edit-template", path: `template[${found[1][0]}]` } });
  }
  const [index, nodes, holes] = found[0];
  const here: { action: string; path: string } = { action: "edit-template", path: `template[${index}]` };
  const loops = holes.filter((h) => h[0] === "loop") as ["loop", LoopNode][];
  if (loops.length > 1) refuse("not-readable", `the template has ${loops.length} output-pattern loops; one pattern`, { fix: here });
  const anchors: Anchor[] = [];
  let tail = "";
  let texts = new Map<string, string>();
  if (loops.length) {
    if (holes.length !== 1) refuse("not-readable", "an outputs loop and bare output slots cannot both form the pattern", { fix: here });
    const loop = loops[0][1];
    for (const f of plan.visibleOutputs) {
      const [pre, post] = instantiate(loop, f, plan, here);
      anchors.push([f.name, pre, post]);
    }
    tail = tailAfter(nodes, loop);
  } else {
    texts = literalSegments(nodes, sig);
    for (const [, slot] of holes) {
      const path = (slot as { path: string }).path;
      const f = sig.fieldNamed(path)!;
      if (!plan.visibleOutputs.includes(f)) continue;
      anchors.push([f.name, texts.get(`before\u0000${path}`) ?? "", texts.get(`after\u0000${path}`) ?? ""]);
    }
  }
  for (const [name, prefix] of anchors) {
    const whole = !loops.length && anchors.length === 1 && !strip(texts.get(`rest\u0000${(holes[0][1] as { path: string }).path}`) ?? "x");
    if (!rstrip(prefix) && !whole) {
      let hint = `field ${pyRepr(name)}: no literal text before its hole — nothing anchors the parser; put the field's marker before the hole`;
      if (!loops.length) {
        hint += `, on the same line: a bare slot's marker is the text on its own line (write 'Answer: {${name}}' or '<${name}>{${name}}</${name}>', not a marker on the line above), or use an outputs loop`;
      }
      refuse("not-readable", hint, { fix: copyObject(here, { field: name }) as unknown as Fix });
    }
  }
  const seen = new Map<string, string>();
  for (const [name, prefix] of anchors) {
    const key = rstrip(prefix);
    if (seen.has(key)) {
      refuse("not-readable", `fields ${pyRepr(seen.get(key))} and ${pyRepr(name)} share the anchor ${pyRepr(key)}; anchors must tell fields apart`,
        { fix: copyObject(here, { field: name }) as unknown as Fix });
    }
    seen.set(key, name);
  }
  return new DerivedReader(anchors, tail, !plan.adapter.strict);
}

function instantiate(loop: LoopNode, f: Field, plan: Plan<any, any>, fix: { action: string; path: string }): [string, string] {
  const pre: string[] = [];
  const post: string[] = [];
  let target = pre;
  for (const node of loop.body) {
    if (node.kind === "text") {
      target.push(node.text);
    } else if (node.kind === "slot") {
      const attr = node.path.slice(node.path.indexOf(".") + 1);
      if (!node.path.includes(".")) {
        refuse("not-readable", `slot {${node.path}} inside the output pattern is not invertible`, { fix: copyObject(fix, { slot: node.path }) as unknown as Fix });
      }
      if (attr === "value") {
        if (target === post) refuse("not-readable", "the output-pattern block has two {f.value} holes per field; one value, one hole", { fix });
        target = post;
      } else if (attr === "name") target.push(f.name);
      else if (attr === "desc") target.push(f.desc ?? "");
      else if (attr === "type") target.push(f.type ?? "");
      else if (attr === "schema") target.push(plan.schemaHint(f));
      else if (attr === "purpose") target.push(f.purpose);
      else refuse("not-readable", `slot {${node.path}} inside the output pattern is not invertible`, { fix: copyObject(fix, { slot: node.path }) as unknown as Fix });
    } else {
      refuse("not-readable", "nested loops inside the output-pattern block are not invertible", { fix });
    }
  }
  return [pre.join(""), post.join("")];
}

/** The literal after the outputs loop, to the next slot and the end of its line (§4). */
function tailAfter(nodes: Node[], loop: LoopNode): string {
  let seen = false;
  const out: string[] = [];
  for (const node of nodes) {
    if (node === loop) {
      seen = true;
      continue;
    }
    if (!seen) continue;
    if (node.kind === "text") out.push(node.text);
    else break;
  }
  const literal = out.join("");
  const stripped = lstrip(literal, "\n");
  if (stripped.includes("\n")) return literal.slice(0, literal.length - stripped.length) + stripped.split("\n")[0] + "\n";
  return literal;
}

/** Bare output slots: the literal before/after each hole on its line (§4). */
function literalSegments(nodes: Node[], sig: Signature<unknown, unknown>): Map<string, string> {
  const out = new Map<string, string>();
  let prevText = "";
  let lastSlot: string | null = null;
  const firstLine = (s: string) => (s.includes("\n") ? s.slice(0, s.indexOf("\n")) : s);
  for (const node of nodes) {
    if (node.kind === "text") {
      prevText += node.text;
      continue;
    }
    if (lastSlot !== null) out.set(`after\u0000${lastSlot}`, firstLine(prevText));
    const f = node.kind === "slot" ? sig.fieldNamed(node.path) : undefined;
    if (node.kind === "slot" && f && f.direction === "output") {
      const before = lastSlot !== null ? prevText : prevText.slice(prevText.lastIndexOf("\n") + 1);
      out.set(`before\u0000${node.path}`, before);
      lastSlot = node.path;
    } else {
      lastSlot = null;
    }
    prevText = "";
  }
  if (lastSlot !== null) {
    out.set(`after\u0000${lastSlot}`, firstLine(prevText));
    out.set(`rest\u0000${lastSlot}`, prevText);
  }
  return out;
}

// -------------------------------------------------------------- resolve

function resolveFormat(plan: Plan<any, any>, f: Field): FormatChoice {
  const adp = plan.adapter;
  const reg = plan.registry;
  const materialize = (binding: unknown, key: string): Format => {
    if (isFormat(binding)) return binding;
    if (isObj(binding) && "use" in binding) return reg.namedFormat(binding["use"] as string, binding["options"] as Record<string, unknown>, `formats[${pyRepr(key)}]`);
    return loadUdf(binding as Record<string, unknown>, `formats[${pyRepr(key)}]`);
  };
  const check = (fmt: Format, by: string, key: string): FormatChoice => {
    const rebind = { action: "bind-format", field: f.name, key };
    if (!formatAccepts(fmt, f)) {
      refuse("format-shape-mismatch", `field ${pyRepr(f.name)}: format ${fmt.name ?? by} accepts ${pyRepr([...fmt.accepts])}, but the field's type/shape is ${f.type ?? pyRepr(f.shape)}`, { fix: rebind });
    }
    if ((fmt.direction === "in" && f.direction === "output") || (fmt.direction === "out" && f.direction === "input")) {
      refuse("format-direction", `field ${pyRepr(f.name)}: format ${fmt.name ?? by} is ${fmt.direction}-only, but the field is an ${f.direction}`, { fix: rebind });
    }
    return { format: fmt, resolvedBy: by, described: null, describedBy: null };
  };
  const choice = chooseFormat(plan, f, materialize, check);
  const keys = [...(f.type ? [f.type] : []), ...structuralKeys(f.shape)];
  if (choice.resolvedBy === "artifact:*") keys.push("*");
  for (const key of keys) {
    const entry = ownValue(adp.formats, key);
    if (isObj(entry) && !isFormat(entry) && !("language" in entry) && "describe" in entry) {
      choice.described = entry["describe"] as string;
      choice.describedBy = `artifact:${key}`;
      break;
    }
  }
  return choice;
}

function chooseFormat(plan: Plan<any, any>, f: Field, materialize: (b: unknown, k: string) => Format, check: (fmt: Format, by: string, key: string) => FormatChoice): FormatChoice {
  const adp = plan.adapter;
  const has = (k: string) => Object.prototype.hasOwnProperty.call(adp.formats, k) && !isDescription(adp.formats[k]);
  if (f.type && has(f.type)) return check(materialize(adp.formats[f.type], f.type), `artifact:${f.type}`, f.type);
  for (const key of structuralKeys(f.shape)) {
    if (has(key)) return check(materialize(adp.formats[key], key), `artifact:${key}`, key);
  }
  const bound = plan.registry.typeBinding(f.type);
  if (bound) return check(bound, `runtime:${f.type}`, formatKey(f.type, f.shape));
  const fallback = kernelDefault(f.shape);
  if (fallback) return { format: fallback, resolvedBy: "kernel", described: null, describedBy: null };
  if (Object.prototype.hasOwnProperty.call(adp.formats, "*")) return check(materialize(adp.formats["*"], "*"), "artifact:*", "*");
  refuse("no-format",
    `field ${pyRepr(f.name)} (${f.type ?? pyRepr(f.shape)}) has a structured shape and no format — bind one in the artifact under its type name or a structural key, register one for its type at runtime, or ship one`,
    { fix: { action: "bind-format", field: f.name, key: formatKey(f.type, f.shape) } });
}

// ------------------------------------------------------------------ bind

export function bind<I, O>(adapter: Adapter, sig: Signature<I, O>, capabilities: Record<string, unknown>, registry: Registry): Plan<I, O> {
  const plan = new Plan<I, O>(adapter, sig, capabilities, registry);
  plan.extensions = resolveAdapterExtensions(adapter, registry); // kernel §10, before anything else

  // 1. transports per purpose, in signature order.
  const byPurpose = new Map<string, Field>();
  for (const f of sig.fields) {
    if (f.purpose === "plain") continue;
    if (byPurpose.has(f.purpose)) {
      refuse("purpose-ambiguous", `purpose ${pyRepr(f.purpose)} appears on both ${pyRepr(byPurpose.get(f.purpose)!.name)} and ${pyRepr(f.name)}; a purpose may bind to one field`,
        { fix: { action: "edit-signature", field: f.name, purpose: f.purpose } });
    }
    byPurpose.set(f.purpose, f);
  }
  const hidden = new Set<string>();
  const settingOwner = new Map<string, string>();
  for (const f of sig.fields) {
    if (f.purpose === "plain") continue;
    const binding = ownValue(adapter.transports, f.purpose) as Transport | Reference | undefined;
    if (binding === undefined) continue;
    let transport: Transport;
    let name: string;
    if (binding instanceof Transport) {
      transport = binding;
      name = "(inline)";
    } else {
      name = binding.use;
      transport = registry.transport(name, binding.options, `transports[${pyRepr(f.purpose)}]`);
    }
    transport = transport.select(capabilities, f.purpose, name).bound(f.name);
    const res: Resolved = { purpose: f.purpose, field: f, transport, name };
    plan.resolved.push(res);
    const target = (ref: string, what: string): Field => {
      if (ref === "@purpose") return f;
      const sub = ref.slice("@purpose.".length);
      const t = byPurpose.get(`${f.purpose}.${sub}`);
      if (!t) {
        refuse("unknown-slot", `purpose ${pyRepr(f.purpose)}: transport ${pyRepr(name)} ${what} targets ${pyRepr(ref)}, but no field bears the purpose ${pyRepr(f.purpose + "." + sub)}`,
          { fix: { action: "assign-purpose", purpose: `${f.purpose}.${sub}` } });
      }
      return t;
    };
    if (!transport.in_template || memberNames(transport.put).length) hidden.add(f.name);
    for (const r of transport.find) {
      const t = target(r["to"] as string, "rule");
      const rule: Record<string, unknown> = {};
      for (const k of memberNames(r)) if (k !== "to") setMember(rule, k, r[k]);
      plan.findRules.push([t.name, rule as FindRule]);
      plan.ruleOwner.push(res);
      if (t !== f) hidden.add(t.name);
      if (r["to"] === "@purpose.calls" && t.direction === "output") {
        plan.callsField = t.name;
        plan.callsOwner = res;
      }
    }
    for (const ref of memberNames(transport.put)) {
      const place = transport.put[ref];
      const t = target(ref, "put");
      plan.puts.push([t.name, place]);
      hidden.add(t.name);
      if (hasOwn(transport.written_as, ref)) {
        plan.writtenAs.set(t.name, registry.namedFormat(transport.written_as[ref], {}, `transports[${pyRepr(f.purpose)}].written_as`));
      }
    }
    for (const role of memberNames(transport.tell)) {
      const existing = ownValue(plan.tell, role) as string | undefined;
      setMember(plan.tell, role, existing ? existing + "\n" + transport.tell[role] : transport.tell[role]);
    }
    for (const [path, value] of settingLeaves(transport.request_settings)) {
      mergeSetting(plan, path, value, f.purpose, settingOwner, `transports[${pyRepr(f.purpose)}].request_settings[${pyRepr(path)}]`);
    }
  }

  // 2. visibility.
  plan.visibleInputs = sig.inputs.filter((f) => !hidden.has(f.name));
  plan.visibleOutputs = sig.outputs.filter((f) => !hidden.has(f.name));

  // 3. one format per field (§5).
  for (const f of sig.fields) plan.formats.set(f.name, resolveFormat(plan, f));
  const routedKinds = new Map<string, Set<string>>();
  for (const [fname, r] of plan.findRules) {
    const kind = r.from.startsWith("part:") ? r.from.slice(r.from.indexOf(":") + 1) : "text";
    if (!routedKinds.has(fname)) routedKinds.set(fname, new Set());
    routedKinds.get(fname)!.add(kind);
  }
  for (const [fname, kinds] of routedKinds) {
    const fmt = plan.formats.get(fname)!.format;
    if (!fmt.reads.includes("*") && ![...kinds].every((k) => fmt.reads.includes(k))) {
      const f = sig.fieldNamed(fname)!;
      refuse("format-capture-mismatch", `field ${pyRepr(fname)}: its find rules deliver ${pyRepr([...kinds].sort())} parts, but its format ${fmt.name ?? "(inline)"} reads ${pyRepr([...fmt.reads])}`,
        { fix: { action: "bind-format", field: fname, key: formatKey(f.type, f.shape) } });
    }
  }
  for (const [fname, place] of plan.puts) {
    const fmt = plan.writtenAs.get(fname) ?? plan.formats.get(fname)!.format;
    if (place.startsWith("request.") && fmt.writes !== "parts") {
      const f = sig.fieldNamed(fname)!;
      refuse("format-put-mismatch", `field ${pyRepr(fname)}: put ${pyRepr(place)} needs parts, but its format ${fmt.name ?? "(inline)"} writes text`,
        { fix: { action: "bind-format", field: fname, key: formatKey(f.type, f.shape) } });
    }
  }

  // 4. the reader; its gate and request settings.
  plan.reader = adapter.reader["kind"] === "derived" ? deriveReader(plan) : registry.reader(adapter.reader);
  const delimiters = plan.findRules.filter(([, r]) => r["repair"]).flatMap(([, r]) => r["between"] as string[]);
  [plan.findRepairable, plan.findUnrepaired] = adapter.strict ? [[], []] : repairableMarkers(delimiters);
  for (const fact of plan.reader.requires()) {
    if (!pyTruthy(ownValue(capabilities, fact))) {
      refuse("capability-missing", `reader ${pyRepr(adapter.reader["kind"])} requires capability ${pyRepr(fact)}, which the model does not declare — use an invertible pattern instead`,
        { fix: { action: "declare-capability", fact } });
    }
  }
  for (const [path, value] of settingLeaves(plan.reader.requestSettings(plan.visibleOutputs) ?? {})) {
    validateSettingPath(path, "parse");
    mergeSetting(plan, path, value, "(reader)", settingOwner, `transports[${pyRepr(settingOwner.get(path) ?? null)}].request_settings[${pyRepr(path)}]`);
  }
  const stops = plan.reader.skeleton().stops ?? [];
  if (pyTruthy(ownValue(capabilities, "stop_sequences")) && stops.length) {
    mergeSetting(plan, "config.stop", [...stops], "(skeleton)", settingOwner,
      `transports[${pyRepr(settingOwner.get("config.stop") ?? null)}].request_settings['config.stop']`);
  }

  // 4b. a put into the request may not share a path with a fixed setting or another put.
  const overlaps = (a: string, b: string) => a === b || a.startsWith(b + ".") || b.startsWith(a + ".");
  const fixed = settingLeaves(plan.requestSettings).map(([path]) => path);
  const seenPuts: [string, string][] = [];
  for (const [fname, place] of plan.puts) {
    if (!place.startsWith("request.")) continue;
    const path = place.slice("request.".length);
    const where = `transports[${pyRepr(sig.fieldNamed(fname)!.purpose.split(".")[0])}].put`;
    const clash = fixed.find((q) => overlaps(path, q));
    const other = seenPuts.find(([, q]) => overlaps(path, q))?.[0];
    if (clash !== undefined || other !== undefined) {
      refuse("setting-conflict", `field ${pyRepr(fname)} is put at request ${pyRepr(path)}, which `
        + (clash !== undefined ? `the request setting ${pyRepr(clash)} also sets` : `field ${pyRepr(other)} is also put at`)
        + " — one would silently overwrite the other", { fix: { action: "edit-entry", path: where } });
    }
    seenPuts.push([fname, path]);
  }

  // 5. template validation + input coverage.
  const known = new Set(sig.fields.map((f) => f.name));
  const inputNames = new Set(plan.visibleInputs.map((f) => f.name));
  const covered = new Set<string>();
  const slotNames = new Set(adapter.turnSlots().keys());
  adapter.compiledMessages().forEach(([, nodes], i) => {
    if (nodes === null) return;
    for (const c of validateNodes(nodes, { knownFields: known, inputFields: inputNames, where: `template[${i}]`, slots: slotNames })) covered.add(c);
  });
  const uncovered = [...inputNames].filter((n) => !covered.has(n)).sort();
  if (uncovered.length) {
    refuse("field-uncovered", "input field(s) never rendered by the template: " + uncovered.map(pyRepr).join(", "),
      { fix: { action: "edit-template", path: "template", field: uncovered[0] } });
  }

  // 6. written by the template and carried by a transport is ambiguous.
  const putInputs = new Set(plan.puts.filter(([fname]) => sig.fieldNamed(fname)!.direction === "input").map(([fname]) => fname));
  adapter.compiledMessages().forEach(([, nodes], i) => {
    if (nodes === null) return;
    for (const fname of [...bareSlots(nodes)].filter((n) => putInputs.has(n)).sort()) {
      refuse("field-double-covered", `template[${i}]: input ${pyRepr(fname)} has a slot here and is also put by its transport — it would be sent twice; drop the slot or the put`,
        { fix: { action: "edit-template", path: `template[${i}]`, field: fname } });
    }
  });
  const visibleOut = new Set(plan.visibleOutputs.map((f) => f.name));
  for (const [fname] of plan.findRules) {
    if (visibleOut.has(fname)) {
      refuse("field-double-covered", `field ${pyRepr(fname)} is both a parsed section and a rule target — hide it (in_template: false) or drop the rule`,
        { fix: { action: "edit-entry", path: `transports[${pyRepr(sig.fieldNamed(fname)!.purpose)}].in_template` } });
    }
  }

  // 7. the turns probe (§6).
  if (plan.callsOwner !== null) {
    for (const r of plan.resolved) {
      if (r !== plan.callsOwner && ("call" in r.transport.spelling || "result" in r.transport.spelling)) {
        const where = `transports[${pyRepr(r.purpose)}].spelling`;
        refuse("entry-malformed",
          `${where}: spelling.call/spelling.result belong to the transport that owns the calls field (${pyRepr(plan.callsOwner.purpose)}); here they would be a second spelling of one call, or a spelling nothing uses`,
          { fix: { action: "edit-entry", path: where } });
      }
    }
  }
  for (const r of plan.resolved) {
    if (!("call" in r.transport.spelling)) continue;
    const callsField = plan.findRules.find(([name]) => sig.fieldNamed(name)!.purpose === `${r.purpose}.calls`)?.[0] ?? null;
    const ref = r.transport.spelling["input_format"] as Reference | undefined;
    if (ref !== undefined) {
      const where = `transports[${pyRepr(r.purpose)}].spelling.input_format`;
      const fmt = registry.namedFormat(ref.use, ref.options, where);
      const inputField: Field = { name: "input", direction: "input", shape: { type: "object" }, type: null, purpose: "plain", desc: null };
      if (fmt.writes !== "text" || (fmt.direction !== "in" && fmt.direction !== "both") || !formatAccepts(fmt, inputField)) {
        refuse("entry-malformed", `${where}: must write an object as text`, { fix: { action: "edit-entry", path: where } });
      }
      plan.turnInputFormats.set(r.purpose, fmt);
    }
    if (callsField === null) {
      if (ref !== undefined || "probe" in r.transport.spelling) {
        refuse("spelling-drift", `purpose ${pyRepr(r.purpose)}: formatted turns need an @purpose.calls target`,
          { fix: { action: "edit-entry", path: `transports[${pyRepr(r.purpose)}].spelling` } });
      }
      continue;
    }
    const probe: Record<string, unknown> = copyObject({ id: "probe" }, (r.transport.spelling["probe"] as object | undefined) ?? { name: "probe", input: { probe: true } });
    const own = plan.findRules.filter(([name, rt]) => name === callsField && rt.from === "text");
    let readBack: unknown = null;
    let spelled = "(writer refused)";
    try {
      spelled = plan.callText(r, probe);
      const [, got] = applyFindRules(spelled, [], own, plan.patternBinding());
      if ((got.get(callsField)?.parts.length ?? 0) > 0) readBack = plan.readField(sig.fieldNamed(callsField)!, got.get(callsField)!);
    } catch (err) {
      if (!(err instanceof Refusal)) throw err;
      readBack = null;
    }
    const first = Array.isArray(readBack) && readBack.length === 1 ? readBack[0] : null;
    const ok = isObj(first) && first["name"] === probe["name"] && jsonEqual(first["input"], probe["input"]);
    if (!ok) {
      refuse("spelling-drift",
        `purpose ${pyRepr(r.purpose)}: transport ${pyRepr(r.name)}: spelling.call spells a call as ${pyRepr(spelled)}, and its own find rule and format read back ${pyRepr(readBack)} — the spelling and the reader disagree`,
        { fix: { action: "edit-entry", path: `transports[${pyRepr(r.purpose)}].spelling` } });
    }
  }

  // 8. turn slots (§3a): layout, then a writer for every hidden output.
  plan.slots = adapter.turnSlots();
  plan.prefill = pyTruthy(ownValue(capabilities, "assistant_prefill")) ? rstrip(adapter.prefill ?? "") : "";
  bindTurns(plan);
  return plan;
}

function bindTurns(plan: Plan<any, any>): void {
  const sig = plan.signature;
  const compiled = plan.adapter.compiledMessages();
  for (const [name, [, i]] of plan.slots) {
    if (sig.fieldNamed(name)) {
      refuse("turns-layout", `template[${i}]: turn slot ${pyRepr(name)} has the name of a signature field; rename the slot`,
        { fix: { action: "edit-template", path: `template[${i}]` } });
    }
  }
  const inputs = new Set(plan.visibleInputs.map((f) => f.name));
  let live: number | null = null;
  for (let i = 0; i < compiled.length; i++) {
    const [msg, nodes] = compiled[i];
    if (nodes !== null && msg["role"] !== "system" && dependsOnInputs(nodes, inputs)) {
      live = i;
      break;
    }
  }
  for (const [name, [form, i]] of plan.slots) {
    if (form !== "messages" || live === null) continue;
    if (name !== "steps" && i > live) {
      refuse("turns-layout", `template[${i}]: turn slot ${pyRepr(name)} comes after the message that renders the live input (template[${live}]); past turns go before it`,
        { fix: { action: "edit-template", path: `template[${i}]` } });
    }
    if (name === "steps" && i < live) {
      refuse("turns-layout", `template[${i}]: the current turn's steps come after the message that renders its input (template[${live}])`,
        { fix: { action: "edit-template", path: `template[${i}]` } });
    }
  }
  if (!plan.slots.size) return;

  const drift = (field: string, owner: Resolved, why: string): never =>
    refuse("spelling-drift", `field ${pyRepr(field)}: ${why}`, { fix: { action: "edit-entry", path: `transports[${pyRepr(owner.purpose)}].spelling` } });

  const groups = new Map<string, [string, FindRule, Resolved][]>();
  plan.findRules.forEach(([fname, r], idx) => {
    if (sig.fieldNamed(fname)!.direction !== "output") return;
    const owner = plan.ruleOwner[idx];
    let key: string;
    if (r.from.startsWith("part:")) key = `channel\u0000${r.from}`;
    else {
      const k = ["between", "line_prefixed", "pattern"].find((x) => hasOwn(r, x))!;
      key = `${k}\u0000${jsonText(r[k])}`;
    }
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push([fname, r, owner]);
  });
  const replayTypes = new Set<string>();
  for (const [key, members] of groups) {
    if (!key.startsWith("channel\u0000")) continue;
    const names = members.map((m) => m[0]);
    if (plan.callsField !== null && names.includes(plan.callsField)) {
      plan.turnWriters.set(plan.callsField, { by: "format:parts" });
      for (const other of names) if (other !== plan.callsField) plan.turnWriters.set(other, { by: "projection", of: plan.callsField });
    } else {
      const from = key.slice("channel\u0000".length);
      replayTypes.add(from.slice(from.indexOf(":") + 1));
      for (const name of names) plan.turnWriters.set(name, { by: "replayed" });
    }
  }
  plan.replayTypes = replayTypes;
  for (const [key, members] of groups) {
    if (key.startsWith("channel\u0000")) continue;
    const names = members.map((m) => m[0]);
    if (plan.callsField !== null && names.includes(plan.callsField)) {
      const owner = plan.callsOwner!;
      if (!("call" in owner.transport.spelling)) drift(plan.callsField, owner, "calls are read from text, but the transport has no spelling.call to write past calls");
      plan.turnWriters.set(plan.callsField, { by: "spelling.call", position: "after" });
      for (const other of names) if (other !== plan.callsField) plan.turnWriters.set(other, { by: "projection", of: plan.callsField });
      continue;
    }
    const distinct = [...new Set(names)];
    if (distinct.length > 1) {
      drift(names[1], members[1][2], `fields ${pyRepr(distinct.sort())} read the same capture and none of them is the calls field; which writes it is ambiguous`);
    }
    const [fname, r, owner] = members[0];
    const spelling = owner.transport.spelling;
    const position = (spelling["position"] as string | undefined) ?? "after";
    if ("value" in spelling) {
      plan.turnWriters.set(fname, spelling["value"] === null ? { by: "dropped" } : { by: "spelling.value", template: spelling["value"], position });
    } else if (!r["remove"]) {
      plan.turnWriters.set(fname, { by: "projection", of: "the reader body" });
      continue;
    } else if ("between" in r) {
      plan.turnWriters.set(fname, { by: "derived:between", between: [...(r["between"] as string[])], position });
    } else if ("line_prefixed" in r) {
      plan.turnWriters.set(fname, { by: "derived:line_prefixed", prefix: r["line_prefixed"], position });
    } else {
      drift(fname, owner, "a pattern rule has a reader but no writer; declare spelling.value (text with {value}) or spelling.value: null to drop it on purpose");
    }
    if (plan.turnWriters.get(fname)!.by !== "dropped") {
      const fmt = plan.formatFor(sig.fieldNamed(fname)!);
      if (!fmt.roundTrip || fmt.writes !== "text" || (fmt.direction !== "both" && fmt.direction !== "in")) {
        drift(fname, owner, `its format ${fmt.name ?? "(inline)"} cannot write the value back as text (it reads only, is lossy, or writes parts), so a past value cannot be written into a turn; give it a write, or spelling.value: null`);
      }
    }
  }
  if (plan.callsField !== null) {
    const fmt = plan.formatFor(sig.fieldNamed(plan.callsField)!);
    if (fmt.direction !== "both" && fmt.direction !== "in") {
      drift(plan.callsField, plan.callsOwner!, `its format ${fmt.name ?? "(inline)"} only reads, so past calls cannot be written`);
    }
  }
}

brand(RenderResult, "RenderResult");
brand(Reading, "Reading");
brand(Plan, "Plan");

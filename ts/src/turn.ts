/**
 * The turn record (kernel §3a): one record for examples, past exchanges,
 * and the exchange in progress.
 *
 * A `Turn` is one call of one signature: its inputs, its steps (model replies
 * and tool results, in order) and, once finished, its outputs — all JSON
 * values. The plan writes turns into requests with its own writers; this
 * module is the record: construction, validation that needs no plan, and
 * JSON (`toJSON()` is schema/turn.schema.json, identical across languages).
 *
 * Records are immutable: every operation returns a new turn.
 */

import { refuse } from "./errors.ts";
import { isObj, textPart, validateResponsePart, type Field, type Message, type Part } from "./core.ts";
import { copyObject, hasToJSON, isPlainObject, jsonText, memberNames, ownValue, setMember } from "./json.ts";
import { sha256Hex } from "./sha256.ts";
import { pyRepr } from "./text.ts";
import { brand } from "./brand.ts";

// ------------------------------------------------------------------ identity

/** Kernel §3a canonical JSON: keys by code point, no whitespace, numbers by §7a (D-54). */
export function canonicalJson(value: unknown): string {
  return jsonText(value, { sortKeys: true });
}

/**
 * `"sha256:"` + the hex SHA-256 of `value`'s canonical JSON (§3a): how
 * signature fingerprints and request hashes are made, byte-identical to
 * every other lmcc. `sha256Hex(text)` hashes plain text instead.
 */
export function sha256(value: unknown): string {
  return "sha256:" + sha256Hex(canonicalJson(value));
}

/** Which signature a turn belongs to: each field's direction, name, purpose, shape and type. */
export function signatureFingerprint(sig: { readonly fields: readonly Field[] }): string {
  return sha256(sig.fields.map((f) => ({ direction: f.direction, name: f.name, purpose: f.purpose || "plain", shape: f.shape, type: f.type || "" })));
}

// ------------------------------------------------------------------ values

/**
 * A value as the JSON its field's shape describes: plain data passes through,
 * objects with `toJSON` are lowered, `undefined` members are dropped, and
 * anything with no JSON form (a function, `NaN`, a symbol) refuses `turn-invalid`
 * naming the path.
 */
export function toJson(value: unknown, where = "turn"): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "bigint") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) refuse("turn-invalid", `${where}: ${value} has no JSON form`);
    return value;
  }
  if (hasToJSON(value)) return toJson(value.toJSON(), where);
  if (Array.isArray(value)) return value.map((v, i) => toJson(v, `${where}[${i}]`));
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const k of memberNames(value)) if (value[k] !== undefined) setMember(out, k, toJson(value[k], `${where}.${k}`));
    return out;
  }
  refuse("turn-invalid", `${where}: a ${value === undefined ? "missing value" : typeof value} has no JSON form; a turn holds JSON values in their fields' shapes`);
}

function get(obj: unknown, key: string): unknown {
  return isObj(obj) ? obj[key] : undefined;
}

export const callId = (call: unknown): unknown => get(call, "id");
export const callName = (call: unknown): unknown => get(call, "name");

/** Parse input (a text, an lm15 message or response) as an lm15 message. */
export function asMessage(reply: unknown): Message {
  if (typeof reply === "string") return { role: "assistant", parts: [textPart(reply)] };
  let r = reply;
  if (isObj(r) && isObj(r["message"])) r = r["message"];
  if (isObj(r) && Array.isArray(r["parts"])) {
    return { role: (r["role"] as string | undefined) ?? "assistant", parts: r["parts"].map((p) => (isObj(p) ? copyObject(p) : p)) as Part[] };
  }
  refuse("response-malformed", "a reply is text, an lm15 message {role, parts}, or an lm15 response {message: ...}");
}

// ------------------------------------------------------------------ records

/** A model step as JSON (schema/turn.schema.json). */
export interface ModelStepJSON {
  kind: "model";
  outputs: Record<string, unknown>;
  message?: Message;
  request?: string;
  calls_field?: string;
}

/** A tool step as JSON (schema/turn.schema.json). */
export interface ToolStepJSON {
  kind: "tool";
  id: string;
  name: string;
  output: Part[];
  children?: TurnJSON[];
}

/** A turn as JSON (schema/turn.schema.json): the same record in every implementation. */
export interface TurnJSON {
  signature: string;
  inputs: Record<string, unknown>;
  steps: (ModelStepJSON | ToolStepJSON)[];
  outputs?: Record<string, unknown>;
  score?: number;
  meta?: Record<string, unknown>;
}

/** One model reply: parsed values, the message as it came, the request's hash, the calls field. */
export class ModelStep {
  readonly kind = "model" as const;
  readonly outputs: Record<string, unknown>;
  readonly message: Message | null;
  readonly request: string | null;
  readonly callsField: string | null;

  constructor(outputs: Record<string, unknown>, message: Message | null = null, request: string | null = null, callsField: string | null = null) {
    this.outputs = outputs;
    this.message = message;
    this.request = request;
    this.callsField = callsField;
  }

  get calls(): unknown[] {
    const value = this.callsField ? ownValue(this.outputs, this.callsField) : undefined;
    return Array.isArray(value) ? [...value] : [];
  }

  toJSON(): ModelStepJSON {
    const out: ModelStepJSON = { kind: "model", outputs: toJson(this.outputs, "step.outputs") as Record<string, unknown> };
    if (this.message !== null) out.message = this.message;
    if (this.request !== null) out.request = this.request;
    if (this.callsField !== null) out.calls_field = this.callsField;
    return out;
  }
}

/** One tool result answering one call: lm15 parts, and the turns made producing it (never written). */
export class ToolStep {
  readonly kind = "tool" as const;
  readonly id: string;
  readonly name: string;
  readonly output: readonly Part[];
  readonly children: readonly Turn[];

  constructor(id: string, name: string, output: readonly Part[], children: readonly Turn[] = []) {
    this.id = id;
    this.name = name;
    this.output = output;
    this.children = children;
  }

  toJSON(): ToolStepJSON {
    const out: ToolStepJSON = { kind: "tool", id: this.id, name: this.name, output: [...this.output] };
    if (this.children.length) out.children = this.children.map((c) => c.toJSON());
    return out;
  }
}

export type Step = ModelStep | ToolStep;

function outputParts(output: unknown): Part[] {
  if (typeof output === "string") return [textPart(output)];
  if (!Array.isArray(output)) refuse("turn-invalid", "a tool output is a text or a list of lm15 parts");
  for (const p of output) {
    if (!isObj(p) || typeof p["type"] !== "string") refuse("turn-invalid", `a tool output part must be an lm15 part with a type, got ${pyRepr(p)}`);
  }
  return output.map((p) => copyObject(p)) as Part[];
}

/** One call of one signature (§3a). Build with `plan.turn`/`plan.example`; advance with `step`, `tool`, `finish`. */
export class Turn {
  readonly signature: string;
  readonly inputs: Record<string, unknown>;
  readonly steps: readonly Step[];
  readonly outputs: Record<string, unknown> | null;
  readonly score: number | null;
  readonly meta: Record<string, unknown>;

  constructor(signature: string, inputs: Record<string, unknown>, steps: readonly Step[] = [], outputs: Record<string, unknown> | null = null,
    score: number | null = null, meta: Record<string, unknown> = {}) {
    this.signature = signature;
    this.inputs = inputs;
    this.steps = Object.freeze([...steps]);
    this.outputs = outputs;
    this.score = score;
    this.meta = meta;
  }

  private with(changes: Partial<{ steps: readonly Step[]; outputs: Record<string, unknown> | null; score: number | null; meta: Record<string, unknown> }>): Turn {
    return new Turn(this.signature, this.inputs, changes.steps ?? this.steps, "outputs" in changes ? changes.outputs! : this.outputs,
      "score" in changes ? changes.score! : this.score, changes.meta ?? this.meta);
  }

  /**
   * This turn with `meta` replaced (§3a: carried, never read by render). Merge
   * yourself to add a key: `turn.withMeta(copyObject(turn.meta, { refusal }))`. A value
   * with no JSON form refuses `turn-invalid` here, not when the turn is saved.
   */
  withMeta(meta: Record<string, unknown>): Turn {
    if (!isPlainObject(meta)) refuse("turn-invalid", "turn.meta: an object");
    toJson(meta, "turn.meta");
    return this.with({ meta: copyObject(meta) });
  }

  /** This turn with `score` replaced: a finite number, or `null` for none (§3a: carried, never read). */
  withScore(score: number | null): Turn {
    if (score !== null && (typeof score !== "number" || !Number.isFinite(score))) {
      refuse("turn-invalid", `turn.score: a finite number or null, not ${pyRepr(score)}`);
    }
    return this.with({ score });
  }

  /** Calls of the last model step that no tool step has answered yet. */
  pendingCalls(): unknown[] {
    let pending: unknown[] = [];
    for (const step of this.steps) {
      if (step instanceof ModelStep) pending = step.calls;
      else if (pending.length && callId(pending[0]) === step.id) pending = pending.slice(1);
    }
    return pending;
  }

  /** Answer the next pending call. `output`: a text or lm15 parts. */
  tool(id: string, output: string | readonly Part[], opts: { children?: readonly Turn[] } = {}): Turn {
    const pending = this.pendingCalls();
    if (!pending.length) refuse("turn-invalid", `tool result ${pyRepr(id)} answers no pending call`);
    if (callId(pending[0]) !== id) {
      refuse("turn-invalid", `tool result ${pyRepr(id)} is out of order: the next pending call is ${pyRepr(callId(pending[0]))}`);
    }
    const children = opts.children ?? [];
    for (const c of children) if (!(c instanceof Turn)) refuse("turn-invalid", "tool step children are turns");
    const step = new ToolStep(String(id), String(callName(pending[0])), outputParts(output), [...children]);
    return this.with({ steps: [...this.steps, step] });
  }

  /** Close the turn: its outputs are the last model step's. */
  finish(): Turn {
    const pending = this.pendingCalls();
    if (pending.length) refuse("turn-invalid", `cannot finish with unanswered call ${pyRepr(callId(pending[0]))}`);
    const last = [...this.steps].reverse().find((s) => s instanceof ModelStep) as ModelStep | undefined;
    if (!last) refuse("turn-invalid", "cannot finish a turn with no model step");
    return this.with({ outputs: copyObject(last.outputs) });
  }

  get done(): boolean {
    return this.outputs !== null;
  }

  withStep(step: Step): Turn {
    return this.with({ steps: [...this.steps, step] });
  }

  toJSON(): TurnJSON {
    const out: TurnJSON = {
      signature: this.signature,
      inputs: toJson(this.inputs, "turn.inputs") as Record<string, unknown>,
      steps: this.steps.map((s) => s.toJSON()),
    };
    if (this.outputs !== null) out.outputs = toJson(this.outputs, "turn.outputs") as Record<string, unknown>;
    if (this.score !== null) out.score = this.score;
    if (memberNames(this.meta).length) out.meta = toJson(this.meta, "turn.meta") as Record<string, unknown>;
    return out;
  }

  /** JSON → a turn (schema/turn.schema.json). */
  static fromJSON(data: unknown, where = "turn"): Turn {
    if (!isObj(data)) refuse("turn-invalid", `${where}: a turn is an object`);
    const unknown = memberNames(data).filter((k) => !["signature", "inputs", "steps", "outputs", "score", "meta"].includes(k)).sort();
    if (unknown.length) refuse("turn-invalid", `${where}: unknown key(s) ${pyRepr(unknown)}`);
    const sig = data["signature"];
    const inputs = data["inputs"];
    if (typeof sig !== "string" || !isObj(inputs)) refuse("turn-invalid", `${where}: a turn needs a signature fingerprint and an inputs object`);
    const outputs = data["outputs"] ?? null;
    if (outputs !== null && !isObj(outputs)) refuse("turn-invalid", `${where}.outputs: an object or null`);
    const steps: Step[] = [];
    ((data["steps"] || []) as unknown[]).forEach((s, i) => {
      const at = `${where}.steps[${i}]`;
      if (!isObj(s) || (s["kind"] !== "model" && s["kind"] !== "tool")) refuse("turn-invalid", `${at}: a step is {kind: model|tool, ...}`);
      if (s["kind"] === "model") {
        if (memberNames(s).some((k) => !["kind", "outputs", "message", "request", "calls_field"].includes(k)) || !isObj(s["outputs"])) {
          refuse("turn-invalid", `${at}: a model step is {kind, outputs, message?, request?, calls_field?}`);
        }
        let message: Message | null = (s["message"] ?? null) as Message | null;
        if (message !== null) {
          message = asMessage(message);
          for (const p of message.parts) validateResponsePart(p);
        }
        steps.push(new ModelStep(copyObject(s["outputs"] as object), message, (s["request"] ?? null) as string | null, (s["calls_field"] ?? null) as string | null));
      } else {
        if (memberNames(s).some((k) => !["kind", "id", "name", "output", "children"].includes(k))
          || !["id", "name"].every((k) => typeof s[k] === "string" && s[k])) {
          refuse("turn-invalid", `${at}: a tool step is {kind, id, name, output, children?}`);
        }
        const children = ((s["children"] || []) as unknown[]).map((c, j) => Turn.fromJSON(c, `${at}.children[${j}]`));
        steps.push(new ToolStep(s["id"] as string, s["name"] as string, outputParts(s["output"] ?? []), children));
      }
    });
    const meta = data["meta"] || {};
    if (!isObj(meta)) refuse("turn-invalid", `${where}.meta: an object`);
    return new Turn(sig, copyObject(inputs), steps, outputs === null ? null : copyObject(outputs), (data["score"] ?? null) as number | null, copyObject(meta));
  }
}

brand(ModelStep, "ModelStep");
brand(ToolStep, "ToolStep");
brand(Turn, "Turn");

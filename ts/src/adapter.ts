/**
 * The Adapter: a template, a reader, transports by purpose, formats by type —
 * never a field name. It meets a signature only at `bind`.
 *
 * Construction: `adapter({messages, reader, transports, formats, ...})`, or
 * `load(entry, {registry})` from serialized data (serde.ts).
 */

import { refuse } from "./errors.ts";
import { isObj } from "./core.ts";
import { isFormat, type Format } from "./formats.ts";
import { copyObject, memberNames, setMember } from "./json.ts";
import { compileTemplate, RESERVED_SLOTS, turnSlots as nodeTurnSlots, type Node } from "./template.ts";
import { PURPOSE_RE, pyRepr } from "./text.ts";
import { Transport } from "./transport.ts";
import { defaultDeclaration, validateDeclaration } from "./extensions.ts";
import { defaultRegistry, type Registry } from "./registry.ts";
import type { Signature } from "./signature.ts";
// plan.ts and serde.ts import this module back. The cycle is safe: each side
// uses the other only inside function bodies, never while modules evaluate.
import { bind, type Plan } from "./plan.ts";
import { dump } from "./serde.ts";
import { brand } from "./brand.ts";

const SLOT_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const REPLAY = ["recorded", "values", "verbatim"] as const;
export type Replay = (typeof REPLAY)[number];

export type TemplateMessage = { readonly role: string; readonly text: string };
export type TemplateDirective = { readonly directive: "turns"; readonly slot?: string };
export type TemplateEntry = TemplateMessage | TemplateDirective;

export const system = (text: string): TemplateMessage => ({ role: "system", text });
export const developer = (text: string): TemplateMessage => ({ role: "developer", text });
export const user = (text: string): TemplateMessage => ({ role: "user", text });
export const assistant = (text: string): TemplateMessage => ({ role: "assistant", text });

export function message(role: string, text: string): TemplateMessage {
  if (!["system", "developer", "user", "assistant"].includes(role)) {
    refuse("entry-malformed", `message role ${pyRepr(role)} must be system/developer/user/assistant`, { fix: { action: "edit-entry", path: "template" } });
  }
  return { role, text };
}

/** A turn slot in messages form (§3a); `turns()` is the slot `turns`. */
export function turns(slot = "turns"): TemplateDirective {
  return slot === "turns" ? { directive: "turns" } : { directive: "turns", slot };
}

/** A reference to a named format or transport: `use("table", {columns: [...]})`. */
export function use(name: string, options: Record<string, unknown> = {}): { use: string; options: Record<string, unknown> } {
  return { use: name, options };
}

export type Reference = { use: string; options: Record<string, unknown>; describe?: string };
export type FormatBinding = Reference | { describe: string } | Record<string, unknown> | Format;

export function isDescription(binding: unknown): binding is { describe: string } {
  return isObj(binding) && !isFormat(binding) && memberNames(binding).length === 1 && "describe" in binding;
}

export function isTransport(x: unknown): x is Transport {
  return x instanceof Transport;
}

type Compiled = [Record<string, unknown>, Node[] | null][];

export class Adapter {
  readonly template: readonly Record<string, unknown>[];
  readonly reader: Record<string, unknown>;
  readonly transports: Record<string, Transport | Reference>;
  readonly formats: Record<string, FormatBinding>;
  readonly name: string;
  readonly extensions: Record<string, string>;
  readonly replay: Replay;
  readonly strict: boolean;
  private compiled: Compiled | null = null;
  /** Guards per template message, checked at bind (a guard may name an input). */
  guards: [string, number][] = [];

  constructor(init: {
    template: Record<string, unknown>[]; reader: Record<string, unknown>; transports: Record<string, Transport | Reference>;
    formats: Record<string, FormatBinding>; name: string; extensions: Record<string, string>; replay: Replay; strict: boolean;
  }) {
    this.template = Object.freeze(init.template.map((m) => copyObject(m)));
    this.reader = copyObject(init.reader);
    this.transports = init.transports;
    this.formats = init.formats;
    this.name = init.name;
    this.extensions = init.extensions;
    this.replay = init.replay;
    this.strict = init.strict;
  }

  bind<I, O>(signature: Signature<I, O>, capabilities: Record<string, unknown> = {}, opts: { registry?: Registry } = {}): Plan<I, O> {
    return bind(this, signature, capabilities, opts.registry ?? defaultRegistry);
  }

  dump(opts: { registry?: Registry } = {}): Record<string, unknown> {
    return dump(this, opts.registry ?? defaultRegistry);
  }

  /** The template's last message when it is an assistant message: the reply's prefill (§3). */
  get prefill(): string | null {
    const last = this.template[this.template.length - 1];
    return last && last["role"] === "assistant" ? (last["text"] as string) : null;
  }

  compiledMessages(): Compiled {
    if (this.compiled) return this.compiled;
    this.compiled = this.template.map((msg, i): [Record<string, unknown>, Node[] | null] =>
      "directive" in msg ? [msg, null] : [msg, compileTemplate(msg["text"] as string, `template[${i}]`)]);
    return this.compiled;
  }

  /** Every placed turn slot: name → [form, template index] (§3a). */
  turnSlots(): Map<string, ["messages" | "text", number]> {
    const slots = new Map<string, ["messages" | "text", number]>();
    const guards: [string, number][] = [];
    this.compiledMessages().forEach(([msg, nodes], i) => {
      let placed: string[];
      let guarded: string[];
      let form: "messages" | "text";
      if (nodes === null) {
        placed = [(msg["slot"] as string | undefined) ?? "turns"];
        guarded = [];
        form = "messages";
      } else {
        [placed, guarded] = nodeTurnSlots(nodes);
        form = "text";
      }
      for (const name of placed) {
        if (slots.has(name)) {
          refuse("template-syntax", `template[${i}]: turn slot ${pyRepr(name)} is already placed at template[${slots.get(name)![1]}]; a slot is placed once`,
            { fix: { action: "edit-template", path: `template[${i}]` } });
        }
        slots.set(name, [form, i]);
      }
      for (const g of guarded) guards.push([g, i]);
    });
    this.guards = guards;
    return slots;
  }

  toJSON(): Record<string, unknown> {
    return this.dump();
  }
}

function description(value: Record<string, unknown>, where: string): { describe?: string } {
  if (!("describe" in value)) return {};
  const text = value["describe"];
  if (typeof text !== "string" || !text) {
    refuse("entry-malformed", `${where}.describe: a description is non-empty text`, { fix: { action: "edit-entry", path: `${where}.describe` } });
  }
  return { describe: text };
}

/**
 * A transport's purpose, checked as it is loaded (§2): a name or dotted
 * names (`tools`, `tools.calls`), the purposes a field can bear; `""` or
 * `a-b` would key a transport no field reaches. Returns its path.
 */
export function checkPurpose(purpose: string): string {
  const where = `transports[${pyRepr(purpose)}]`;
  if (!PURPOSE_RE.test(purpose)) {
    refuse("entry-malformed", `${where}: a purpose is a name or dotted names (tools, tools.calls), as a field declares it`,
      { fix: { action: "edit-entry", path: where } });
  }
  return where;
}

/** One `formats` entry, normalized (§5). */
export function formatEntry(key: string, value: unknown): FormatBinding {
  const where = `formats[${pyRepr(key)}]`;
  if (typeof value === "string") return { use: value, options: {} };
  if (isFormat(value)) return value;
  if (isObj(value) && "use" in value) {
    const extra = memberNames(value).filter((k) => !["use", "options", "describe"].includes(k)).sort();
    if (extra.length || !isObj(value["options"] ?? {})) {
      refuse("entry-malformed", `${where}: a reference is {use, options?, describe?}` + (extra.length ? `, not ${pyRepr(extra)}` : ""),
        { fix: { action: "edit-entry", path: where } });
    }
    return copyObject({ use: value["use"] as string, options: copyObject(value["options"] as object | undefined) }, description(value, where)) as Reference;
  }
  if (isObj(value) && "language" in value) return copyObject(value);
  if (isObj(value) && "describe" in value) {
    if (memberNames(value).length !== 1) {
      refuse("entry-malformed", `${where}: a description is {describe} alone, not ${pyRepr(memberNames(value).filter((k) => k !== "describe").sort())}`,
        { fix: { action: "edit-entry", path: where } });
    }
    const described = description(value, where);
    if (key === "*") {
      refuse("entry-malformed",
        `${where}: a description alone under '*' describes nothing — '*' reaches only fields no other step spells, and a description chooses no format; put it on the reference ({"use": ..., "describe": ...}) or under a type or key`,
        { fix: { action: "edit-entry", path: where } });
    }
    return described as { describe: string };
  }
  refuse("entry-malformed", `${where}: expected a name, use(...), a shipped format, a description {describe}, or a Format`, { fix: { action: "edit-entry", path: where } });
}

export interface AdapterOptions {
  messages?: readonly TemplateEntry[] | readonly Record<string, unknown>[];
  template?: readonly TemplateEntry[] | readonly Record<string, unknown>[];
  reader?: Record<string, unknown>;
  transports?: Record<string, unknown>;
  formats?: Record<string, unknown>;
  name?: string;
  extensions?: Record<string, string> | null;
  replay?: string;
  strict?: unknown;
  /** The constructor's convenience (§10): an inline `pattern` rule declares `pattern/legacy-re2`. */
  declareDefaults?: boolean;
}

/**
 * Build an adapter. `transports` values: a name, a `Transport`, a data
 * object, or `use(...)`. `formats` keys: type names or structural keys;
 * values: a name, `use(...)`, a description `{describe}`, or a `Format`.
 */
export function adapter(opts: AdapterOptions = {}): Adapter {
  const messages = (opts.messages ?? opts.template) as unknown;
  if (!Array.isArray(messages)) {
    refuse("entry-malformed", "template must be a list of messages and directives", { fix: { action: "edit-entry", path: "template" } });
  }
  messages.forEach((m: unknown, i: number) => {
    const at = `template[${i}]`;
    if (!isObj(m) || !(("role" in m && "text" in m) || "directive" in m)) {
      refuse("entry-malformed", `${at}: a message is {role, text} or {directive}`, { fix: { action: "edit-entry", path: at } });
    }
    if ("directive" in m) {
      const slot = m["slot"] ?? "turns";
      if (m["directive"] !== "turns" || memberNames(m).some((k) => k !== "directive" && k !== "slot") || typeof slot !== "string" || !SLOT_NAME.test(slot)) {
        refuse("entry-malformed", `${at}: a directive is {"directive": "turns", "slot"?: name} (demos and history are turn slots since kernel 0.7)`,
          { fix: { action: "edit-entry", path: at } });
      }
      if (RESERVED_SLOTS.includes(slot)) {
        refuse("template-syntax", `${at}: ${pyRepr(slot)} is reserved, not a turn slot`, { fix: { action: "edit-template", path: at } });
      }
    }
    if ("role" in m && !["system", "developer", "user", "assistant"].includes(m["role"] as string)) {
      refuse("entry-malformed", `${at}: role must be system/developer/user/assistant`, { fix: { action: "edit-entry", path: at } });
    }
    if (m["role"] === "system" && messages.slice(0, i).some((x: Record<string, unknown>) => ("role" in x && x["role"] !== "system") || "directive" in x)) {
      refuse("entry-malformed", `${at}: system messages lead the template (they become the lm15 request's system field); put later instructions in a developer message`,
        { fix: { action: "edit-entry", path: at } });
    }
  });
  const replay = opts.replay ?? "recorded";
  if (!(REPLAY as readonly string[]).includes(replay)) {
    refuse("entry-malformed", `replay must be one of ${pyRepr([...REPLAY])}, not ${pyRepr(replay)}`, { fix: { action: "edit-entry", path: "replay" } });
  }
  const reader = opts.reader ?? { kind: "derived" };
  if (!isObj(reader)) refuse("entry-malformed", "entry.reader must be an object", { fix: { action: "edit-entry", path: "reader" } });
  const kind = reader["kind"];
  if (typeof kind !== "string" || !kind) refuse("unknown-reader", "reader.kind must name a reader", { fix: { action: "edit-entry", path: "reader" } });
  if (kind === "derived" && memberNames(reader).some((k) => k !== "kind")) {
    refuse("entry-malformed", `reader: the derived reader takes only 'kind', not ${pyRepr(memberNames(reader).filter((k) => k !== "kind").sort())}`,
      { fix: { action: "edit-entry", path: "reader" } });
  }
  const strict = opts.strict ?? false;
  if (typeof strict !== "boolean") refuse("entry-malformed", `strict must be true or false, not ${pyRepr(strict)}`, { fix: { action: "edit-entry", path: "strict" } });
  const sBindings: Record<string, Transport | Reference> = {};
  for (const purpose of memberNames(opts.transports ?? {})) {
    const value = opts.transports![purpose];
    const where = checkPurpose(purpose);
    if (typeof value === "string") setMember(sBindings, purpose, { use: value, options: {} });
    else if (value instanceof Transport) {
      value.validate(where);
      setMember(sBindings, purpose, value);
    } else if (isObj(value) && "use" in value) {
      setMember(sBindings, purpose, { use: value["use"] as string, options: copyObject(value["options"] as object | undefined) });
    } else if (isObj(value)) setMember(sBindings, purpose, Transport.fromDict(value, where));
    else refuse("entry-malformed", `${where}: expected a name, Transport, use(...), or object`, { fix: { action: "edit-entry", path: where } });
  }
  const fBindings: Record<string, FormatBinding> = {};
  for (const key of memberNames(opts.formats ?? {})) setMember(fBindings, key, formatEntry(key, opts.formats![key]));
  let declared = validateDeclaration(opts.extensions);
  if (opts.declareDefaults ?? true) declared = defaultDeclaration(sBindings, declared, isTransport);
  const adp = new Adapter({
    template: [...messages] as Record<string, unknown>[], reader, transports: sBindings, formats: fBindings,
    name: opts.name ?? "adapter", extensions: declared, replay: replay as Replay, strict,
  });
  const compiled = adp.compiledMessages();
  const lastIndex = compiled.length - 1;
  if (lastIndex >= 0) {
    const [last, nodes] = compiled[lastIndex];
    if (last["role"] === "assistant" && nodes !== null && nodes.some((n) => n.kind !== "text")) {
      refuse("template-syntax", `template[${lastIndex}]: a last assistant message is the reply's prefill (kernel §3) and holds literal text only, no slots, loops or guards`,
        { fix: { action: "edit-template", path: `template[${lastIndex}]` } });
    }
  }
  adp.turnSlots();
  return adp;
}

brand(Adapter, "Adapter");

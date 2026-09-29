/**
 * Transport: how a meaning travels (kernel §6), as data.
 *
 * `{when?, requires?, in_template?, tell?, request_settings?, put?,
 * written_as?, find?, spelling?}` or `{choose: [{when, use}, …, {else}]}`.
 * The class normalizes defaults and validates; `toDict()` is the artifact
 * form, identical to every other implementation's.
 */

import { refuse } from "./errors.ts";
import { CAPABILITY_FACTS, isObj } from "./core.ts";
import { copyObject, deepCopy, hasOwn, memberNames, ownValue, setMember } from "./json.ts";
import type { FindRule } from "./reader.ts";
import { pyRepr, pyTruthy } from "./text.ts";
import { brand } from "./brand.ts";

const KEYS = ["when", "requires", "in_template", "tell", "request_settings", "put", "written_as", "find", "spelling"];
const PREDICATE_KEYS = ["capability", "not", "all", "any"];
const TO = /^@purpose(\.[A-Za-z_][A-Za-z0-9_]*)?$/;
const PUT = /^(request\.[a-z_][a-z0-9_.]*|message:(system|developer|user|assistant))$/;
const FROM = /^(text|part:[a-z_]+)$/;

/** The pinned lm15 `Config` fields (lm15 1.0.1, contract 3763eec; kernel §3). */
export const LM15_CONFIG_FIELDS: ReadonlySet<string> = new Set([
  "max_tokens", "temperature", "top_p", "top_k", "stop", "response_format", "tool_choice",
  "reasoning", "cache", "seed", "frequency_penalty", "presence_penalty", "service_tier",
  "user_id", "store", "logprobs", "probabilities", "extensions",
]);

const sortedList = (xs: Iterable<string>) => pyRepr([...xs].sort());

function malformed(path: string, hint: string): never {
  refuse("entry-malformed", hint, { fix: { action: "edit-entry", path } });
}

export function validateSettingPath(path: string, where: string): void {
  const segments = path.split(".");
  const ok = segments[0] === "tools" || (segments[0] === "config" && segments.length >= 2 && LM15_CONFIG_FIELDS.has(segments[1]));
  if (!ok) {
    malformed(where, `${where}: ${pyRepr(path)} is not a field of an lm15 request — request settings 'config.<field>' (${[...LM15_CONFIG_FIELDS].sort().join(", ")}) or 'tools'; provider-native knobs go under config.extensions`);
  }
}

/** Flatten request settings to `[dotted path, value]` at the two levels the kernel validates. */
export function settingLeaves(settings: Record<string, unknown>, prefix = ""): [string, unknown][] {
  const out: [string, unknown][] = [];
  for (const key of memberNames(settings)) {
    const value = settings[key];
    if (key === "config" && !prefix && isObj(value)) out.push(...settingLeaves(value, "config."));
    else out.push([prefix + key, value]);
  }
  return out;
}

export type Predicate = Record<string, unknown>;
export interface Alternative { when?: Predicate; use?: Transport; else?: Transport }

/** `list(x)` as the reference applies it to artifact data. */
function asList(x: unknown): unknown[] {
  if (Array.isArray(x)) return [...x];
  if (typeof x === "string") return [...x];
  if (isObj(x)) return memberNames(x);
  if (x === undefined || x === null) return [];
  return [x];
}

function asDict(x: unknown, where: string, key: string): Record<string, unknown> {
  if (x === undefined) return {};
  if (!isObj(x)) malformed(`${where}.${key}`, `${where}.${key}: must be an object`);
  return copyObject(x);
}

export class Transport {
  when: Predicate | null = null;
  requires: string[] = [];
  in_template = true;
  tell: Record<string, string> = {};
  request_settings: Record<string, unknown> = {};
  put: Record<string, string> = {};
  find: FindRule[] = [];
  spelling: Record<string, unknown> = {};
  written_as: Record<string, string> = {};
  choose: Alternative[] | null = null;

  constructor(init: Partial<Pick<Transport, "when" | "requires" | "in_template" | "tell" | "request_settings" | "put" | "find" | "spelling" | "written_as" | "choose">> = {}) {
    if (init.when !== undefined) this.when = init.when;
    if (init.requires !== undefined) this.requires = init.requires;
    if (init.in_template !== undefined) this.in_template = init.in_template;
    if (init.tell !== undefined) this.tell = init.tell;
    if (init.request_settings !== undefined) this.request_settings = init.request_settings;
    if (init.put !== undefined) this.put = init.put;
    if (init.find !== undefined) this.find = init.find;
    if (init.spelling !== undefined) this.spelling = init.spelling;
    if (init.written_as !== undefined) this.written_as = init.written_as;
    if (init.choose !== undefined) this.choose = init.choose;
  }

  toDict(): Record<string, unknown> {
    if (this.choose !== null) {
      return {
        choose: this.choose.map((alt) => ("else" in alt && alt.else ? { else: alt.else.toDict() } : { when: copyObject(alt.when) as Predicate, use: alt.use!.toDict() })),
      };
    }
    const d: Record<string, unknown> = {};
    if (this.when !== null) d["when"] = deepCopy(this.when);
    if (this.requires.length) d["requires"] = [...this.requires];
    if (!this.in_template) d["in_template"] = false;
    if (memberNames(this.tell).length) d["tell"] = copyObject(this.tell);
    if (memberNames(this.request_settings).length) d["request_settings"] = deepCopy(this.request_settings);
    if (memberNames(this.put).length) d["put"] = copyObject(this.put);
    if (memberNames(this.written_as).length) d["written_as"] = copyObject(this.written_as);
    if (this.find.length) d["find"] = this.find.map((r) => copyObject(r));
    if (memberNames(this.spelling).length) d["spelling"] = deepCopy(this.spelling);
    return d;
  }

  toJSON(): Record<string, unknown> {
    return this.toDict();
  }

  static fromDict(data: unknown, where: string): Transport {
    if (data instanceof Transport) {
      data.validate(where);
      return data;
    }
    if (isObj(data) && typeof (data as { toDict?: unknown }).toDict === "function") {
      // a Transport of another lmcc version: cross through its artifact form, checked as data
      return Transport.fromDict((data as { toDict: () => unknown }).toDict(), where);
    }
    if (!isObj(data)) malformed(where, `${where}: a transport is an object`);
    if ("choose" in data) {
      const choose = data["choose"];
      if (memberNames(data).length !== 1 || !Array.isArray(choose) || !choose.length) {
        malformed(where, `${where}: choose is a non-empty list and stands alone`);
      }
      const alts: Alternative[] = [];
      choose.forEach((alt, i) => {
        const aw = `${where}.choose[${i}]`;
        if (!isObj(alt)) malformed(aw, `${aw}: an alternative is an object`);
        const keys = memberNames(alt).sort().join(",");
        if ("else" in alt) {
          if (memberNames(alt).length !== 1 || i !== choose.length - 1) malformed(aw, `${aw}: else stands alone and comes last`);
          alts.push({ else: Transport.fromDict(alt["else"], aw) });
        } else if (keys === "use,when") {
          validatePredicate(alt["when"], `${aw}.when`);
          alts.push({ when: alt["when"] as Predicate, use: Transport.fromDict(alt["use"], aw) });
        } else {
          malformed(aw, `${aw}: an alternative is {when, use} or {else}`);
        }
      });
      return new Transport({ choose: alts });
    }
    const unknown = memberNames(data).filter((k) => !KEYS.includes(k));
    if (unknown.length) malformed(where, `${where}: unknown transport key(s) ${sortedList(unknown)}; known keys are ${pyRepr(KEYS)}`);
    if ("spelling" in data && !isObj(data["spelling"])) malformed(`${where}.spelling`, `${where}.spelling: must be an object`);
    const find = asList(data["find"]).map((r, i) => {
      if (!isObj(r)) malformed(`${where}.find[${i}]`, `${where}.find[${i}]: a rule is an object`);
      return copyObject(r) as FindRule;
    });
    const s = new Transport({
      when: (data["when"] ?? null) as Predicate | null,
      requires: asList(data["requires"]) as string[],
      in_template: pyTruthy(data["in_template"] ?? true),
      tell: asDict(data["tell"], where, "tell") as Record<string, string>,
      request_settings: asDict(data["request_settings"], where, "request_settings"),
      put: asDict(data["put"], where, "put") as Record<string, string>,
      find,
      spelling: asDict(data["spelling"], where, "spelling"),
      written_as: asDict(data["written_as"], where, "written_as") as Record<string, string>,
    });
    s.validate(where);
    return s;
  }

  validate(where: string): void {
    if (this.choose !== null) {
      this.choose.forEach((alt, i) => {
        if (alt.when !== undefined) validatePredicate(alt.when, `${where}.choose[${i}].when`);
        (alt.else ?? alt.use)!.validate(`${where}.choose[${i}]`);
      });
      return;
    }
    if (this.when !== null) validatePredicate(this.when, `${where}.when`);
    this.requires.forEach((fact, i) => {
      if (!CAPABILITY_FACTS.has(fact)) {
        malformed(`${where}.requires[${i}]`, `${where}.requires: ${pyRepr(fact)} is not a capability fact; known: ${sortedList(CAPABILITY_FACTS)}`);
      }
    });
    this.find.forEach((r, i) => validateFindRule(r, `${where}.find[${i}]`));
    for (const target of memberNames(this.put)) {
      const place = this.put[target];
      if (!TO.test(target) || typeof place !== "string" || !PUT.test(place)) {
        malformed(`${where}.put`, `${where}.put: ${pyRepr(target)}: ${pyRepr(place)} — a put is '@purpose' or '@purpose.<sub>' → 'request.<key>' or 'message:<role>'`);
      }
    }
    for (const [path] of settingLeaves(this.request_settings)) validateSettingPath(path, `${where}.request_settings[${pyRepr(path)}]`);
    for (const target of memberNames(this.put)) {
      const place = this.put[target];
      if (place.startsWith("request.")) validateSettingPath(place.slice("request.".length), `${where}.put`);
    }
    for (const target of memberNames(this.written_as)) {
      const name = this.written_as[target];
      if (!hasOwn(this.put, target) || typeof name !== "string" || !name) {
        malformed(`${where}.written_as`, `${where}.written_as: ${pyRepr(target)} must name a placed field and a format name`);
      }
    }
    validateSpelling(this.spelling, `${where}.spelling`);
    for (const k of memberNames(this.tell)) {
      if (!["system", "developer", "user", "assistant"].includes(k) || typeof this.tell[k] !== "string") {
        malformed(`${where}.tell`, `${where}.tell: ${pyRepr(k)} must name a message role, text`);
      }
    }
    if (!this.in_template && !this.find.length && !memberNames(this.put).length) {
      malformed(where, `${where}: in_template=false but no rule or put serves the field — the value would be unrecoverable`);
    }
  }

  /** Resolve `choose` against the declared facts; check `when` and `requires`. */
  select(capabilities: Record<string, unknown>, purpose: string, name: string): Transport {
    let s: Transport = this;
    while (s.choose !== null) {
      let chosen: Transport | null = null;
      for (const alt of s.choose) {
        if (alt.else || evalPredicate(alt.when!, capabilities)) {
          chosen = alt.else ?? alt.use!;
          break;
        }
      }
      if (chosen === null) {
        refuse("capability-missing",
          `purpose ${pyRepr(purpose)}: transport ${pyRepr(name)}: no alternative of 'choose' holds for the declared capabilities and there is no else`,
          { fix: { action: "satisfy-predicate", purpose, predicate: { any: s.choose.map((alt) => copyObject(alt.when)) } } });
      }
      s = chosen;
    }
    if (s.when !== null && !evalPredicate(s.when, capabilities)) {
      refuse("capability-missing",
        `purpose ${pyRepr(purpose)}: transport ${pyRepr(name)}: 'when' ${pyRepr(s.when)} is false for the declared capabilities`,
        { fix: { action: "satisfy-predicate", purpose, predicate: copyObject(s.when) } });
    }
    for (const fact of s.requires) {
      if (!pyTruthy(ownValue(capabilities, fact))) {
        refuse("capability-missing", `purpose ${pyRepr(purpose)}: transport ${pyRepr(name)} requires capability ${pyRepr(fact)}, which the model does not declare`,
          { fix: { action: "declare-capability", fact } });
      }
    }
    return s;
  }

  /** A copy with `{field}` in tell bound to the purpose's field. */
  bound(fieldName: string): Transport {
    const tell: Record<string, string> = {};
    for (const k of memberNames(this.tell)) setMember(tell, k, this.tell[k].split("{field}").join(fieldName));
    return new Transport({
      when: this.when, requires: [...this.requires], in_template: this.in_template, tell,
      request_settings: copyObject(this.request_settings), put: copyObject<string>(this.put), find: this.find.map((r) => copyObject(r) as FindRule),
      spelling: copyObject(this.spelling), written_as: copyObject<string>(this.written_as),
    });
  }
}

/** The slot names a `spelling.value` text uses (`{{`/`}}` escapes). */
function writeSlots(template: string): string[] {
  const names: string[] = [];
  let i = 0;
  while (i < template.length) {
    if (template.startsWith("{{", i) || template.startsWith("}}", i)) {
      i += 2;
      continue;
    }
    if (template[i] === "{") {
      const j = template.indexOf("}", i);
      if (j < 0) return ["?"];
      names.push(template.slice(i + 1, j));
      i = j + 1;
      continue;
    }
    if (template[i] === "}") return ["?"];
    i++;
  }
  return names;
}

export function validateSpelling(spelling: unknown, where: string): void {
  let valid = isObj(spelling);
  if (valid) {
    const s = spelling as Record<string, unknown>;
    const allowed = ["call", "result", "input_format", "probe", "value", "position"];
    valid = memberNames(s).every((k) => allowed.includes(k));
    valid &&= ["call", "result"].every((k) => !hasOwn(s, k) || typeof s[k] === "string");
    if ("value" in s) {
      const w = s["value"];
      valid &&= w === null || (typeof w === "string" && writeSlots(w).join("\u0000") === "value");
    }
    if ("position" in s) valid &&= s["position"] === "before" || s["position"] === "after";
    if ("input_format" in s) {
      const ref = s["input_format"];
      valid &&= "call" in s && isObj(ref) && memberNames(ref).every((k) => k === "use" || k === "options")
        && typeof ref["use"] === "string" && Boolean(ref["use"]) && isObj(ref["options"] ?? {});
    }
    if ("probe" in s) {
      const probe = s["probe"];
      valid &&= "call" in s && isObj(probe) && memberNames(probe).every((k) => ["id", "name", "input"].includes(k))
        && typeof probe["name"] === "string" && Boolean(probe["name"]) && isObj(probe["input"])
        && typeof (probe["id"] ?? "probe") === "string" && Boolean(probe["id"] ?? "probe");
    }
  }
  if (!valid) {
    malformed(where, `${where}: expected call/result text, input_format {use, options?}, probe {name, input: object, id?} (formatter and probe require call), value (text with one {value} slot, or null) and position (before|after)`);
  }
}

/** Kernel §6 spelling: the closed slot set, `{{`/`}}` escapes. */
export function spellTurn(template: string, slots: Record<string, string>): string {
  let out = "";
  let i = 0;
  while (i < template.length) {
    const c = template[i];
    if (c === "{" && template.startsWith("{{", i)) {
      out += "{";
      i += 2;
      continue;
    }
    if (c === "}" && template.startsWith("}}", i)) {
      out += "}";
      i += 2;
      continue;
    }
    if (c === "{") {
      const j = template.indexOf("}", i);
      const name = j > i ? template.slice(i + 1, j) : "";
      if (Object.prototype.hasOwnProperty.call(slots, name)) {
        out += slots[name];
        i = j + 1;
        continue;
      }
    }
    out += c;
    i++;
  }
  return out;
}

export function validateFindRule(r: unknown, where: string): void {
  if (!isObj(r)) malformed(where, `${where}: a rule is an object`);
  const src = r["from"];
  const to = r["to"];
  if (typeof src !== "string" || !FROM.test(src)) malformed(where, `${where}: 'from' is 'text' or 'part:<part kind>'`);
  if (typeof to !== "string" || !TO.test(to)) malformed(where, `${where}: 'to' is '@purpose' or '@purpose.<sub>'`);
  const known = ["from", "to", "remove", "between", "pattern", "line_prefixed", "complete_reply", "repair"];
  const unknown = memberNames(r).filter((k) => !known.includes(k));
  if (unknown.length) malformed(where, `${where}: unknown rule key(s) ${sortedList(unknown)}`);
  const kinds = ["between", "pattern", "line_prefixed"].filter((k) => hasOwn(r, k));
  if (src === "text") {
    if (kinds.length !== 1) malformed(where, `${where}: a text rule needs exactly one of between/pattern/line_prefixed`);
    const k = kinds[0];
    const v = r[k];
    if (k === "between") {
      if (!(Array.isArray(v) && v.length === 2 && v.every((x) => typeof x === "string" && x))) {
        malformed(where, `${where}: between is [open, close], non-empty strings`);
      }
    } else if (typeof v !== "string" || !v) {
      malformed(where, `${where}: ${k} is a non-empty string`);
    }
  }
  if ("repair" in r && ((r["repair"] !== true && r["repair"] !== false) || src !== "text" || !("between" in r))) {
    malformed(where, `${where}: 'repair' is true or false, on a between rule only (its delimiters are repaired like markers, kernel §4a)`);
  }
  if (src !== "text" && (kinds.length || pyTruthy(r["remove"]))) {
    malformed(where, `${where}: a channel rule takes no text extractor and no remove`);
  }
}

export function validatePredicate(p: unknown, where: string): void {
  if (!isObj(p) || memberNames(p).length !== 1) malformed(where, `${where}: a predicate is one of ${pyRepr(PREDICATE_KEYS)}, one key`);
  const key = memberNames(p)[0];
  const value = p[key];
  if (key === "capability") {
    if (typeof value === "string" && !CAPABILITY_FACTS.has(value)) {
      malformed(where, `${where}: ${pyRepr(value)} is not a capability fact; known: ${sortedList(CAPABILITY_FACTS)}`);
    }
    if (typeof value !== "string") malformed(where, `${where}: 'capability' names a fact`);
  } else if (key === "not") {
    validatePredicate(value, `${where}.not`);
  } else if (key === "all" || key === "any") {
    if (!Array.isArray(value)) malformed(where, `${where}: ${pyRepr(key)} takes a list`);
    value.forEach((q, j) => validatePredicate(q, `${where}.${key}[${j}]`));
  } else {
    malformed(where, `${where}: unknown predicate key ${pyRepr(key)}; known: ${pyRepr(PREDICATE_KEYS)}`);
  }
}

export function evalPredicate(p: Predicate, capabilities: Record<string, unknown>): boolean {
  const key = memberNames(p)[0];
  const value = p[key];
  if (key === "capability") return pyTruthy(ownValue(capabilities, value as string));
  if (key === "not") return !evalPredicate(value as Predicate, capabilities);
  if (key === "all") return (value as Predicate[]).every((q) => evalPredicate(q, capabilities));
  return (value as Predicate[]).some((q) => evalPredicate(q, capabilities));
}

brand(Transport, "Transport");

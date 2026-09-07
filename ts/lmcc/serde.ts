// Load (plain data → adapter, every load-time refusal) and dump.

import { createHash } from "node:crypto";
import { refuse, type Fix } from "./refusal.ts";
import { isJsonObject, cloneJson, type Json } from "./json.ts";
import { parseTemplateText, type TemplateItem } from "./template.ts";
import type { Format } from "./formats.ts";
import { Registry, type Options } from "./registry.ts";
import type { StrategyData, Routing, Predicate } from "./strategy.ts";
import { lintRe2 } from "./text.ts";
import { DERIVED_LENS, type Lens } from "./lens.ts";
import type { Adapter } from "./plan.ts";

export const KERNEL_VERSION = "0.2.0";

const SEMVER = /^(\d+)\.(\d+)\.(\d+)$/;

/** Semver compatibility: same major; while major = 0, same minor; else needs.minor <= provides.minor. */
export function versionCompatible(needs: string, provides: string): boolean {
  const a = SEMVER.exec(needs);
  const b = SEMVER.exec(provides);
  if (!a || !b) return false;
  const [na, nb] = [a, b].map((m) => m.slice(1).map(Number));
  if (na[0] !== nb[0]) return false;
  if (na[0] === 0) return na[1] === nb[1];
  return na[1] <= nb[1];
}

function malformed(path: string, hint: string): never {
  refuse("entry-malformed", `${path}: ${hint}`, { fix: { action: "edit-entry", path }, stage: "load" });
}

function validatePredicate(p: unknown, path: string): Predicate {
  if (!isJsonObject(p) || Object.keys(p).length !== 1) return malformed(path, "a predicate has exactly one of capability, not, all, any");
  if ("capability" in p) {
    if (typeof p.capability !== "string") return malformed(path, "capability must be a string");
    return { capability: p.capability };
  }
  if ("not" in p) return { not: validatePredicate(p.not, `${path}.not`) };
  if ("all" in p) {
    if (!Array.isArray(p.all)) return malformed(path, "all must be a list");
    return { all: p.all.map((q, i) => validatePredicate(q, `${path}.all[${i}]`)) };
  }
  if ("any" in p) {
    if (!Array.isArray(p.any)) return malformed(path, "any must be a list");
    return { any: p.any.map((q, i) => validatePredicate(q, `${path}.any[${i}]`)) };
  }
  return malformed(path, "unknown predicate form");
}

function validateRouting(r: unknown, path: string): Routing {
  if (!isJsonObject(r)) return malformed(path, "a routing must be an object");
  if (typeof r.from !== "string" || !/^(text|channel:[a-z_]+)$/.test(r.from)) return malformed(path, "from must be text or channel:<kind>");
  if (typeof r.to !== "string" || !/^@role(\.[A-Za-z_][A-Za-z0-9_]*)?$/.test(r.to)) return malformed(path, "to must be @role or @role.<sub>");
  const sources = ["between", "pattern", "line_prefixed"].filter((k) => r[k] !== undefined);
  const out: Routing = { from: r.from, to: r.to };
  if (r.from === "text") {
    if (sources.length !== 1) return malformed(path, "a text routing needs exactly one of between, pattern, line_prefixed");
  } else if (sources.length !== 0) return malformed(path, "a channel routing takes no between/pattern/line_prefixed");
  if (r.between !== undefined) {
    if (!Array.isArray(r.between) || r.between.length !== 2 || r.between.some((x) => typeof x !== "string" || x.length === 0)) return malformed(path, "between must be [open, close] non-empty strings");
    out.between = [r.between[0] as string, r.between[1] as string];
  }
  if (r.pattern !== undefined) {
    if (typeof r.pattern !== "string") return malformed(path, "pattern must be a string");
    const problem = lintRe2(r.pattern);
    if (problem) return malformed(path, `pattern is outside the RE2 dialect: ${problem.reason}`);
    try {
      new RegExp(r.pattern, "u");
    } catch (e) {
      return malformed(path, `pattern does not compile: ${(e as Error).message}`);
    }
    out.pattern = r.pattern;
  }
  if (r.line_prefixed !== undefined) {
    if (typeof r.line_prefixed !== "string" || r.line_prefixed.length === 0) return malformed(path, "line_prefixed must be a non-empty string");
    out.line_prefixed = r.line_prefixed;
  }
  if (r.consume !== undefined) {
    if (typeof r.consume !== "boolean") return malformed(path, "consume must be a boolean");
    out.consume = r.consume;
  }
  for (const k of Object.keys(r)) if (!["from", "to", "between", "pattern", "line_prefixed", "consume"].includes(k)) return malformed(path, `unknown key ${k}`);
  return out;
}

function validateStrategy(s: unknown, path: string, registry: Registry): StrategyData {
  if (!isJsonObject(s)) return malformed(path, "a strategy must be an object");
  if ("use" in s) {
    if (typeof s.use !== "string" || s.use.length === 0) return malformed(path, "use must be a name");
    if (s.options !== undefined && !isJsonObject(s.options)) return malformed(path, "options must be an object");
    const data = registry.strategy(s.use, (s.options as Options) ?? {});
    return validateStrategy(data, path, registry);
  }
  if ("choose" in s) {
    if (!Array.isArray(s.choose) || s.choose.length === 0) return malformed(path, "choose must be a non-empty list");
    const branches: ({ when: Predicate; use: StrategyData } | { else: StrategyData })[] = [];
    s.choose.forEach((b, i) => {
      const bp = `${path}.choose[${i}]`;
      if (!isJsonObject(b)) return malformed(bp, "a branch must be an object");
      if ("else" in b) {
        if (Object.keys(b).length !== 1) return malformed(bp, "an else branch has only else");
        branches.push({ else: validateStrategy(b.else, `${bp}.else`, registry) });
      } else {
        if (!("when" in b) || !("use" in b) || Object.keys(b).length !== 2) return malformed(bp, "a branch has when and use");
        branches.push({ when: validatePredicate(b.when, `${bp}.when`), use: validateStrategy(b.use, `${bp}.use`, registry) });
      }
    });
    return { choose: branches };
  }
  const out: StrategyData = {};
  for (const k of Object.keys(s)) {
    if (!["when", "requires", "visible", "fragments", "controls", "placement", "routings"].includes(k)) return malformed(path, `unknown key ${k}`);
  }
  if (s.when !== undefined) out.when = validatePredicate(s.when, `${path}.when`);
  if (s.requires !== undefined) {
    if (!Array.isArray(s.requires) || s.requires.some((x) => typeof x !== "string")) return malformed(`${path}.requires`, "requires must be a list of facts");
    out.requires = s.requires as string[];
  }
  if (s.visible !== undefined) {
    if (typeof s.visible !== "boolean") return malformed(`${path}.visible`, "visible must be a boolean");
    out.visible = s.visible;
  }
  if (s.fragments !== undefined) {
    if (!isJsonObject(s.fragments) || Object.values(s.fragments).some((v) => typeof v !== "string")) return malformed(`${path}.fragments`, "fragments map message roles to text");
    out.fragments = s.fragments as { [k: string]: string };
  }
  if (s.controls !== undefined) {
    if (!isJsonObject(s.controls)) return malformed(`${path}.controls`, "controls must be an object");
    out.controls = s.controls;
  }
  if (s.placement !== undefined) {
    if (!isJsonObject(s.placement)) return malformed(`${path}.placement`, "placement must be an object");
    for (const [k, v] of Object.entries(s.placement)) {
      if (!/^@role(\.[A-Za-z_][A-Za-z0-9_]*)?$/.test(k)) return malformed(`${path}.placement`, `bad target ${k}`);
      if (typeof v !== "string" || !/^(controls\.[A-Za-z_][A-Za-z0-9_.]*|message:(system|user|assistant))$/.test(v)) return malformed(`${path}.placement`, `bad placement ${String(v)}`);
    }
    out.placement = s.placement as { [k: string]: string };
  }
  if (s.routings !== undefined) {
    if (!Array.isArray(s.routings)) return malformed(`${path}.routings`, "routings must be a list");
    out.routings = s.routings.map((r, i) => validateRouting(r, `${path}.routings[${i}]`));
  }
  return out;
}

/** The hash a shipped UDF carries: sha256 over "<name>\0<source>\0" for write, read, describe (present ones, in that order). */
export function udfHash(entry: { [k: string]: Json }): string {
  const h = createHash("sha256");
  for (const name of ["write", "read", "describe"]) {
    const src = entry[name];
    if (typeof src === "string") h.update(`${name}\0${src}\0`, "utf8");
  }
  return h.digest("hex");
}

function loadFormat(key: string, spec: unknown, registry: Registry): Format {
  const path = `formats['${key}']`;
  if (!isJsonObject(spec)) return malformed(path, "a format entry is a reference {use} or a shipped UDF");
  if ("use" in spec) {
    if (typeof spec.use !== "string" || spec.use.length === 0) return malformed(path, "use must be a name");
    if (spec.options !== undefined && !isJsonObject(spec.options)) return malformed(`${path}.options`, "options must be an object");
    for (const k of Object.keys(spec)) if (k !== "use" && k !== "options") return malformed(path, `unknown key ${k}`);
    return registry.format(spec.use, (spec.options as Options) ?? {});
  }
  // shipped UDF
  if (typeof spec.language !== "string") return malformed(path, "a shipped format needs language, write, sha256");
  if (typeof spec.write !== "string") return malformed(`${path}.write`, "write must be source text");
  if (typeof spec.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(spec.sha256)) return malformed(`${path}.sha256`, "sha256 must be 64 hex digits");
  for (const k of ["read", "describe", "authored_by"]) if (spec[k] !== undefined && typeof spec[k] !== "string") return malformed(`${path}.${k}`, `${k} must be a string`);
  if (spec.deps !== undefined && (!Array.isArray(spec.deps) || spec.deps.some((d) => typeof d !== "string"))) return malformed(`${path}.deps`, "deps must be a list of strings");
  if (udfHash(spec) !== spec.sha256) {
    refuse("udf-tampered", `${path}: sha256 does not match the shipped source`, { fix: { action: "reship-udf", path }, stage: "load" });
  }
  // This runtime places no code (no Python placer, no eval): refuse by name.
  refuse("format-untrusted", `${path}: the artifact ships a ${spec.language} UDF and this runtime will not place code`, {
    fix: { action: "place-udf", language: spec.language, path },
    stage: "load",
  });
}

export interface LoadOptions {
  registry?: Registry;
}

export function load(entry: unknown, options: LoadOptions = {}): Adapter {
  const registry = options.registry ?? new Registry();
  if (!isJsonObject(entry)) return malformed("entry", "the artifact must be an object");
  for (const k of Object.keys(entry)) {
    if (!["name", "versions", "template", "parse", "strategies", "formats"].includes(k)) return malformed(k, `unknown key ${k}`);
  }
  if (entry.name !== undefined && typeof entry.name !== "string") return malformed("name", "name must be a string");
  // versions.kernel
  if (!isJsonObject(entry.versions) || typeof entry.versions.kernel !== "string") return malformed("versions", "versions.kernel is required");
  const needs = entry.versions.kernel;
  if (!SEMVER.test(needs)) return malformed("versions", "versions.kernel must be semver");
  if (!versionCompatible(needs, KERNEL_VERSION)) {
    refuse("version-incompatible", `the artifact needs kernel ${needs}; this implementation provides ${KERNEL_VERSION}`, {
      fix: { action: "match-version", entry: "kernel", needs, provides: KERNEL_VERSION },
      stage: "load",
    });
  }
  const vocab: { [k: string]: string } = {};
  if (entry.versions.vocab !== undefined) {
    if (!isJsonObject(entry.versions.vocab)) return malformed("versions", "versions.vocab must be an object");
    for (const [k, v] of Object.entries(entry.versions.vocab)) {
      if (typeof v !== "string" || !SEMVER.test(v)) return malformed("versions", `versions.vocab['${k}'] must be semver`);
      vocab[k] = v;
    }
  }
  // template
  if (!Array.isArray(entry.template)) return malformed("template", "template must be a message list");
  const template: TemplateItem[] = entry.template.map((item, index): TemplateItem => {
    const path = `template[${index}]`;
    if (!isJsonObject(item)) return malformed(path, "a template item is {role, text} or {directive}");
    if ("directive" in item) {
      if (item.directive !== "demos" && item.directive !== "history") return malformed(path, "directive must be demos or history");
      if (Object.keys(item).length !== 1) return malformed(path, "a directive item has only directive");
      return { kind: "directive", directive: item.directive, index };
    }
    if (item.role !== "system" && item.role !== "user" && item.role !== "assistant") return malformed(path, "role must be system, user, or assistant");
    if (typeof item.text !== "string") return malformed(path, "text must be a string");
    if (Object.keys(item).length !== 2) return malformed(path, "a message item has role and text");
    return { kind: "message", role: item.role, text: item.text, nodes: parseTemplateText(item.text, path), index };
  });
  // parse.kind
  if (!isJsonObject(entry.parse)) return malformed("parse", "parse must be an object with kind");
  const kind = entry.parse.kind;
  if (typeof kind !== "string" || kind.length === 0) {
    refuse("unknown-parse-kind", "parse.kind must be a name", { fix: { action: "edit-entry", path: "parse" }, stage: "load" });
  }
  let lens: Lens;
  if (kind === "derived") lens = DERIVED_LENS;
  else lens = registry.lens(kind, entry.parse as Options);
  // strategies
  const strategies = new Map<string, StrategyData>();
  if (entry.strategies !== undefined) {
    if (!isJsonObject(entry.strategies)) return malformed("strategies", "strategies map roles to strategies");
    for (const [role, s] of Object.entries(entry.strategies)) {
      if (!/^[A-Za-z_][A-Za-z0-9_.]*$/.test(role)) return malformed("strategies", `bad role name ${role}`);
      strategies.set(role, validateStrategy(s, `strategies['${role}']`, registry));
    }
  }
  // formats
  const formats = new Map<string, Format>();
  if (entry.formats !== undefined) {
    if (!isJsonObject(entry.formats)) return malformed("formats", "formats map type names or structural keys to entries");
    for (const [key, spec] of Object.entries(entry.formats)) formats.set(key, loadFormat(key, spec, registry));
  }
  // vocabulary versions the artifact pins
  for (const [name, needsV] of Object.entries(vocab)) {
    const provides = registry.versionOf(name);
    if (provides === null) continue; // unreferenced or unregistered: references already refused by name
    if (!versionCompatible(needsV, provides)) {
      const fix: Fix = { action: "match-version", entry: name, needs: needsV, provides };
      refuse("version-incompatible", `the artifact needs ${name} ${needsV}; this runtime provides ${provides}`, { fix, stage: "load" });
    }
  }
  return {
    name: typeof entry.name === "string" ? entry.name : undefined,
    entry: cloneJson(entry) as Json,
    versions: { kernel: needs, vocab },
    template,
    parseKind: kind,
    lens,
    strategies,
    formats,
  };
}

/** Dump the artifact as plain data: what was loaded, unchanged. */
export function dump(adapter: Adapter, _registry?: Registry): Json {
  return cloneJson(adapter.entry);
}

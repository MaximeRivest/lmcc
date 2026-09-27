/**
 * Extensions: declared execution contracts (kernel §10, spec/portability.md).
 *
 * The core is exact and mandatory; everything else is a named, versioned
 * contract the artifact declares (`entry.extensions`) and the host binds
 * (`Registry.extensions`) or refuses — at load, and again at bind for
 * adapters built in code, always before a plan exists. A binding is a table
 * entry: it runs no artifact code and starts nothing.
 */

import { refuse } from "./errors.ts";
import { isObj } from "./core.ts";
import type { PatternMatcher } from "./reader.ts";
import { pyRepr } from "./text.ts";
import type { Transport } from "./transport.ts";

const NAME = /^[a-z][a-z0-9_]*\/[a-z][a-z0-9_-]*$/;
const SEMVER = /^\d+\.\d+\.\d+$/;

export function familyOf(name: string): string {
  return name.split("/")[0];
}

/** What a host binds under an extension name, and a label saying how (never a secret). */
export interface ExtensionBinding {
  readonly extension: string;
  readonly version: string;
  readonly binding: string;
  readonly family: string;
}

/** The `pattern` family: admit a regex at load/bind, find its captures at parse. */
export interface PatternBinding extends ExtensionBinding, PatternMatcher {
  admit(regex: string, where: string): void;
}

const NON_RE2 = /\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+/;

/**
 * `pattern/legacy-re2` 0.1.0 through ECMAScript `RegExp` with flags `s`
 * (DOTALL: `.` matches every scalar) and `u` (scalars, not UTF-16 units).
 * The excluded constructs are refused by the contract's own lexical check;
 * the rest is the engine's. Stated differences from the reference
 * (`python:re`), all inside the contract's unspecified zone: `u` mode
 * refuses identity escapes of characters that are not syntax (`\:`,
 * `\<`), `\d`/`\w`/`\b` are ASCII, and inline flags other than what the
 * engine accepts refuse. Equivalence beyond the corpus is not claimed.
 */
export class LegacyRE2 implements PatternBinding {
  static readonly extension = "pattern/legacy-re2";
  static readonly version = "0.1.0";
  readonly extension = LegacyRE2.extension;
  readonly version = LegacyRE2.version;
  readonly binding = "ecmascript:RegExp";
  readonly family = "pattern";
  private readonly compiled = new Map<string, [RegExp, number]>();

  private compile(regex: string): [RegExp, number] {
    let hit = this.compiled.get(regex);
    if (!hit) {
      const re = new RegExp(regex, "gsu");
      const groups = new RegExp(regex + "|", "su").exec("")!.length - 1;
      hit = [re, groups];
      this.compiled.set(regex, hit);
    }
    return hit;
  }

  admit(regex: string, where: string): void {
    const unescaped = regex.replace(/\\[^1-9k]/g, "");
    const hit = NON_RE2.exec(unescaped);
    if (hit) {
      refuse("entry-malformed",
        `${where}: regex ${pyRepr(regex)} uses ${pyRepr(hit[0])}, which is outside the pattern/legacy-re2 dialect (no lookaround, backreferences, named groups, atomic or possessive constructs)`,
        { fix: { action: "edit-entry", path: where } });
    }
    try {
      this.compile(regex);
    } catch (err) {
      refuse("entry-malformed", `${where}: regex ${pyRepr(regex)} does not compile: ${(err as Error).message}`,
        { fix: { action: "edit-entry", path: where } });
    }
  }

  captures(regex: string, text: string): [number, number, string][] {
    const [re, groups] = this.compile(regex);
    const out: [number, number, string][] = [];
    for (const m of text.matchAll(re)) {
      if (m[0].length === 0) continue;
      const cap = groups ? m[1] : m[0];
      out.push([m.index, m.index + m[0].length, cap ?? ""]);
    }
    return out;
  }

  describe(): { version: string; binding: string } {
    return { version: this.version, binding: this.binding };
  }
}

export function describeBinding(b: ExtensionBinding): { version: string; binding: string } {
  return { version: b.version, binding: b.binding };
}

/** The bindings this runtime can honestly claim with the language alone. */
export function nativeExtensions(): ExtensionBinding[] {
  return [new LegacyRE2()];
}

export interface Resolved {
  readonly name: string;
  readonly needs: string;
  readonly binding: ExtensionBinding;
}

export function describeResolved(r: Resolved): { needs: string; provides: string; binding: string } {
  return { needs: r.needs, provides: r.binding.version, binding: r.binding.binding };
}

function walkTransport(t: Transport, visit: (rule: Record<string, unknown>, path: string) => void, where: string): void {
  if (t.choose !== null) {
    t.choose.forEach((alt, i) => walkTransport((alt.else ?? alt.use)!, visit, `${where}.choose[${i}]`));
    return;
  }
  t.find.forEach((r, i) => visit(r, `${where}.find[${i}]`));
}

/** Whether any inline transport carries a rule of `family` (named ones are not seen). */
export function usesFamily(transports: Record<string, unknown>, family: string, isTransport: (x: unknown) => x is Transport): boolean {
  let found = false;
  for (const s of Object.values(transports)) {
    if (!isTransport(s)) continue;
    walkTransport(s, (r) => {
      if (family === "pattern" && "pattern" in r) found = true;
    }, "");
  }
  return found;
}

/** The constructor's convenience (§10): an inline `pattern` rule declares the default tier. */
export function defaultDeclaration(transports: Record<string, unknown>, declared: Record<string, string>, isTransport: (x: unknown) => x is Transport): Record<string, string> {
  if (usesFamily(transports, "pattern", isTransport) && !Object.keys(declared).some((n) => familyOf(n) === "pattern")) {
    return { ...declared, [LegacyRE2.extension]: LegacyRE2.version };
  }
  return declared;
}

/** Rules 1–2 of kernel §10: shape, names, versions, one per family. */
export function validateDeclaration(extensions: unknown): Record<string, string> {
  if (extensions === undefined || extensions === null) return {};
  if (!isObj(extensions)) {
    refuse("entry-malformed", "extensions must be an object of '<family>/<name>': version", { fix: { action: "edit-entry", path: "extensions" } });
  }
  const seen = new Map<string, string>();
  for (const name of Object.keys(extensions)) {
    const version = extensions[name];
    if (!NAME.test(name)) {
      refuse("entry-malformed", `extensions: ${pyRepr(name)} is not an extension name ('<family>/<name>', lowercase)`, { fix: { action: "edit-entry", path: "extensions" } });
    }
    if (typeof version !== "string" || !SEMVER.test(version)) {
      refuse("entry-malformed", `extensions: ${pyRepr(name)}: version ${pyRepr(version)} is not MAJOR.MINOR.PATCH`, { fix: { action: "edit-entry", path: "extensions" } });
    }
    const fam = familyOf(name);
    if (seen.has(fam)) {
      refuse("entry-malformed", `extensions: ${pyRepr(seen.get(fam))} and ${pyRepr(name)} both govern family ${pyRepr(fam)}; declare one contract per family`,
        { fix: { action: "edit-entry", path: "extensions" } });
    }
    seen.set(fam, name);
  }
  return { ...(extensions as Record<string, string>) };
}

export interface ResolveContext {
  readonly extensions: Record<string, unknown>;
  readonly transports: Record<string, unknown>;
  readonly bound: Map<string, ExtensionBinding>;
  checkCompatible(kind: string, theirs: string, ours: string): void;
  transportOf(purpose: string, binding: unknown, where: string): Transport;
}

/** Kernel §10 rules 1–6; refuses, naming the offender, before any plan exists. */
export function resolveExtensions(ctx: ResolveContext): Map<string, Resolved> {
  const declared = validateDeclaration(ctx.extensions);
  const resolved = new Map<string, Resolved>();
  for (const name of Object.keys(declared)) {
    const needs = declared[name];
    const binding = ctx.bound.get(name);
    if (!binding) {
      refuse("extension-unsupported",
        `the artifact declares extension ${pyRepr(name)} ${needs}, and this runtime binds no implementation of it (registry.describe().extensions lists what it binds)`,
        { fix: { action: "bind-extension", name, needs } });
    }
    ctx.checkCompatible(name, needs, binding.version);
    resolved.set(name, { name, needs, binding });
  }
  const byFamily = new Map<string, Resolved>();
  for (const r of resolved.values()) byFamily.set(familyOf(r.name), r);
  for (const purpose of Object.keys(ctx.transports)) {
    const where = `transports[${pyRepr(purpose)}]`;
    const transport = ctx.transportOf(purpose, ctx.transports[purpose], where);
    walkTransport(transport, (r, path) => {
      if (!("pattern" in r)) return;
      const pattern = byFamily.get("pattern");
      if (!pattern) {
        refuse("extension-undeclared",
          `${path}: 'pattern' needs a pattern/* extension and the artifact declares none (kernel §10; pattern/legacy-re2 is what 0.2 did)`,
          { fix: { action: "declare-extension", family: "pattern", path } });
      }
      (pattern.binding as PatternBinding).admit(r["pattern"] as string, path);
    }, where);
  }
  return resolved;
}

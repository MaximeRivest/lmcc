// The vocabulary socket: formats, strategies, and lenses register here.
// The kernel ships none of them (D-01).

import { refuse } from "./refusal.ts";
import type { Json } from "./json.ts";
import type { Format } from "./formats.ts";
import type { StrategyData } from "./strategy.ts";
import type { Lens } from "./lens.ts";

export type Options = { [k: string]: Json };

export interface RegistryDescription {
  formats: { [name: string]: string };
  strategies: { [name: string]: string };
  lenses: { [name: string]: string };
}

export class Registry {
  private formats = new Map<string, { version: string; factory: (options: Options) => Format }>();
  private strategies = new Map<string, { version: string; factory: (options: Options) => StrategyData }>();
  private lenses = new Map<string, { version: string; factory: (spec: Options) => Lens }>();

  registerFormat(name: string, version: string, factory: (options: Options) => Format, existOk = false): void {
    if (this.formats.has(name) && !existOk) refuse("already-registered", `format ${name} is already registered`, { stage: "registration" });
    this.formats.set(name, { version, factory });
  }
  registerStrategy(name: string, version: string, factory: (options: Options) => StrategyData, existOk = false): void {
    if (this.strategies.has(name) && !existOk) refuse("already-registered", `strategy ${name} is already registered`, { stage: "registration" });
    this.strategies.set(name, { version, factory });
  }
  registerLens(name: string, version: string, factory: (spec: Options) => Lens, existOk = false): void {
    if (this.lenses.has(name) && !existOk) refuse("already-registered", `lens ${name} is already registered`, { stage: "registration" });
    this.lenses.set(name, { version, factory });
  }

  hasFormat(name: string): boolean {
    return this.formats.has(name);
  }
  hasStrategy(name: string): boolean {
    return this.strategies.has(name);
  }
  hasLens(name: string): boolean {
    return this.lenses.has(name);
  }

  format(name: string, options: Options = {}): Format {
    const e = this.formats.get(name);
    if (!e) refuse("unknown-format", `format ${JSON.stringify(name)} is not registered`, { fix: { action: "install-vocabulary", kind: "format", name }, stage: "load" });
    const f = e.factory(options);
    f.vocab = `format/${name}`;
    f.version = e.version;
    f.options = options;
    return f;
  }
  strategy(name: string, options: Options = {}): StrategyData {
    const e = this.strategies.get(name);
    if (!e) refuse("unknown-strategy", `strategy ${JSON.stringify(name)} is not registered`, { fix: { action: "install-vocabulary", kind: "strategy", name }, stage: "load" });
    return e.factory(options);
  }
  lens(kind: string, spec: Options = {}): Lens {
    const e = this.lenses.get(kind);
    if (!e) refuse("unknown-parse-kind", `parse.kind ${JSON.stringify(kind)} is neither "derived" nor a registered lens`, { fix: { action: "install-vocabulary", kind: "lens", name: kind }, stage: "load" });
    const l = e.factory(spec);
    l.vocab = `lens/${kind}`;
    l.version = e.version;
    return l;
  }

  /** version of `format/<name>`, `strategy/<name>`, `lens/<name>`; null when unregistered */
  versionOf(entry: string): string | null {
    const slash = entry.indexOf("/");
    if (slash < 0) return null;
    const kind = entry.slice(0, slash);
    const name = entry.slice(slash + 1);
    const table = kind === "format" ? this.formats : kind === "strategy" ? this.strategies : kind === "lens" ? this.lenses : null;
    return table?.get(name)?.version ?? null;
  }

  describe(): RegistryDescription {
    const out: RegistryDescription = { formats: {}, strategies: {}, lenses: {} };
    for (const [k, v] of this.formats) out.formats[k] = v.version;
    for (const [k, v] of this.strategies) out.strategies[k] = v.version;
    for (const [k, v] of this.lenses) out.lenses[k] = v.version;
    return out;
  }
}

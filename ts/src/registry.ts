/**
 * The sockets: where everything with an opinion plugs in.
 *
 * - named formats: `factory(options) → Format` under a name an artifact can
 *   reference (`{"use": "json"}`), with a version;
 * - type bindings: a type name → its format, its shape and its JSON form
 *   both ways, per runtime, never serialized (kernel §5 step 3, §3a).
 *   TypeScript types are erased, so a binding matches the field's `type`
 *   name as the frontend spelled it;
 * - transports: `factory(options) → Transport` (or its data);
 * - readers: `factory(spec) → Reader` (`derived` is kernel grammar);
 * - extensions: the execution contracts this runtime binds (kernel §10).
 *
 * Registries are explicit objects; `load` reads only the one it is given.
 */

import { refuse, Refusal } from "./errors.ts";
import { isFormat, makeFormat, type Format, type FormatSpec } from "./formats.ts";
import { Reader } from "./reader.ts";
import { pyRepr, pyStr } from "./text.ts";
import { Transport } from "./transport.ts";
import { describeBinding, nativeExtensions, type ExtensionBinding } from "./extensions.ts";
import { brand, brandedByAnyVersion } from "./brand.ts";
import { KERNEL_VERSION } from "./version.ts";
import { copyObject, isPlainObject, orderedObject, type Json, type JsonObject } from "./json.ts";

export interface Named<F> {
  readonly factory: F;
  readonly version: string;
}

export type FormatFactory = (options: Record<string, unknown>) => Format;
export type TransportFactory = (options: Record<string, unknown>) => Transport | Record<string, unknown>;
export type ReaderFactory = (spec: Record<string, unknown>) => Reader;

/**
 * How one type name crosses in this runtime: its format (`null`: the format
 * its shape resolves), its shape (`null`: none declared), and its JSON form
 * both ways (`toJson`, `fromJson`; `null`: the value is its own JSON).
 */
export interface TypeBinding {
  readonly type: string;
  readonly binding: Format | { use: string; options: Record<string, unknown> } | null;
  readonly shape: JsonObject | null;
  readonly toJson: ((value: any) => unknown) | null;
  readonly fromJson: ((data: any) => unknown) | null;
}

/** What `registry.format(type, ...)` takes besides a format: the shape and the JSON form. */
export interface HostSpec {
  readonly shape?: JsonObject;
  /** The value's JSON form in its field's shape: what a turn holds and every other format receives. */
  readonly toJson?: (value: any) => unknown;
  /** The value rebuilt from its JSON form: what `plan.loadTurn` gives the format bound here. */
  readonly fromJson?: (data: any) => unknown;
}

export interface RegistryOptions {
  /** This runtime places no UDF language; `true` only changes which refusal a shipped format meets. */
  readonly allowUdf?: boolean;
  /** Extension names to bind natively (`[]` for a core-only host); default: every native binding. */
  readonly extensions?: readonly string[];
}

export class Registry {
  readonly formats = new Map<string, Named<FormatFactory>>();
  readonly typeBindings: TypeBinding[] = [];
  readonly transports = new Map<string, Named<TransportFactory>>();
  readonly readers = new Map<string, Named<ReaderFactory>>();
  readonly extensions = new Map<string, ExtensionBinding>();
  readonly allowUdf: boolean;

  constructor(options: RegistryOptions = {}) {
    this.allowUdf = options.allowUdf ?? false;
    const natives = new Map(nativeExtensions().map((b) => [b.extension, b] as const));
    for (const name of options.extensions ?? [...natives.keys()]) {
      const b = natives.get(name);
      if (!b) throw new Error(`no native binding for extension ${pyRepr(name)}; use registerExtension(...) with your own`);
      this.extensions.set(name, b);
    }
  }

  // ------------------------------------------------------- extensions

  /** Bind an implementation of `binding.extension`. A table entry: nothing runs. */
  registerExtension(binding: ExtensionBinding, opts: { existOk?: boolean } = {}): void {
    if (this.extensions.has(binding.extension) && !opts.existOk) {
      refuse("already-registered", `extension ${pyRepr(binding.extension)} is already bound`);
    }
    this.extensions.set(binding.extension, binding);
  }

  // ---------------------------------------------------------- formats

  registerFormat(name: string, factory: FormatFactory, opts: { version?: string; existOk?: boolean } = {}): void {
    if (this.formats.has(name) && !opts.existOk) refuse("already-registered", `format ${pyRepr(name)} is already registered`);
    this.formats.set(name, { factory, version: opts.version ?? "0.1.0" });
  }

  /** Resolve `{"use": name, "options"}`; a failing factory is `entry-malformed` at `where` (§5). */
  namedFormat(name: string, options: Record<string, unknown> | null | undefined, where?: string): Format {
    const entry = this.formats.get(name);
    if (!entry) {
      refuse("unknown-format", `format ${pyRepr(name)} is not registered — install the package that provides it, or ship the format with the artifact`,
        { fix: { action: "install-vocabulary", kind: "format", name } });
    }
    const at = where ?? `format ${pyRepr(name)}`;
    let fmt: unknown;
    try {
      fmt = entry.factory(options ?? {});
    } catch (err) {
      if (err instanceof Refusal) throw err;
      refuse("entry-malformed", `${at}: format ${pyRepr(name)} rejects its options: ${(err as Error).message}`, { fix: { action: "edit-entry", path: at } });
    }
    if (!isFormat(fmt)) {
      refuse("entry-malformed", `${at}: format ${pyRepr(name)} returned something that is not a Format`, { fix: { action: "edit-entry", path: at } });
    }
    fmt.name = name;
    return fmt;
  }

  /**
   * Bind a type name, per runtime — `registry.format("Person", {write,
   * read})` or `registry.format("DataFrame", {use: "table", options: {...}})`.
   * Never serialized.
   *
   * `shape`: what the type lowers to (default `{}`: structured, contents
   * unknown). `toJson(value)` and `fromJson(data)`: the type's JSON form,
   * both ways. `plan.dumpTurn` writes it, `plan.loadTurn` rebuilds the value
   * from it, and every format but the one bound here receives it, so the
   * format bound here always receives the value itself, live or replayed.
   *
   * With neither `write` nor `use`, no format is bound: the type crosses by
   * the format its shape resolves. Binding the same name again replaces its
   * binding. Returns the bound format, or `null`.
   */
  format(type: string, spec: (FormatSpec | { use: string; options?: Record<string, unknown> }) & HostSpec): Format;
  format(type: string, spec: HostSpec): null;
  format(type: string, spec: (Partial<FormatSpec> | { use: string; options?: Record<string, unknown> }) & HostSpec): Format | null {
    const host = spec as HostSpec;
    if (host.shape !== undefined && !isPlainObject(host.shape)) {
      refuse("unmapped-type", `${type}: shape must be a JSON-Schema object`, { fix: { action: "edit-signature" } });
    }
    for (const name of ["toJson", "fromJson"] as const) {
      if (host[name] !== undefined && typeof host[name] !== "function") {
        refuse("entry-malformed", `${type}: ${name} must be a function`, { fix: { action: "edit-entry", path: name } });
      }
    }
    const shape = host.shape === undefined ? null : copyObject<Json>(host.shape);
    const toJson = host.toJson ?? null;
    const fromJson = host.fromJson ?? null;
    let binding: TypeBinding["binding"];
    if ("use" in spec && typeof spec.use === "string") {
      binding = { use: spec.use, options: copyObject(spec.options) };
    } else {
      const s = spec as Partial<FormatSpec> & { options?: unknown };
      if (typeof s.write === "function") {
        binding = makeFormat(s as FormatSpec);
      } else if (s.write !== undefined || s.read !== undefined || s.describe !== undefined || s.options !== undefined
        || (shape === null && toJson === null && fromJson === null)) {
        refuse("entry-malformed", "a format needs at least write", { fix: { action: "edit-entry", path: "write" } });
      } else {
        binding = null;
      }
    }
    const record: TypeBinding = { type, binding, shape, toJson, fromJson };
    const at = this.typeBindings.findIndex((b) => b.type === type);
    if (at >= 0) this.typeBindings[at] = record; // bound again: the new binding replaces it
    else this.typeBindings.push(record);
    if (binding === null) return null;
    return isFormat(binding) ? binding : this.namedFormat(binding.use, binding.options);
  }

  /** The binding of a type name, or `null`. */
  host(type: string | null | undefined): TypeBinding | null {
    if (!type) return null;
    return this.typeBindings.find((b) => b.type === type) ?? null;
  }

  /** The shape a bound type name lowers to (`{}` when bound without one), or `null`. */
  shapeOf(type: string): JsonObject | null {
    const hit = this.host(type);
    return hit ? copyObject<Json>(hit.shape ?? {}) : null;
  }

  typeBinding(type: string | null): Format | null {
    const hit = this.host(type);
    if (!hit || hit.binding === null) return null;
    return isFormat(hit.binding) ? hit.binding : this.namedFormat(hit.binding.use, hit.binding.options);
  }

  // ------------------------------------------------------- transports

  registerTransport(name: string, factory: TransportFactory, opts: { version?: string; existOk?: boolean } = {}): void {
    if (this.transports.has(name) && !opts.existOk) refuse("already-registered", `transport ${pyRepr(name)} is already registered`);
    this.transports.set(name, { factory, version: opts.version ?? "0.1.0" });
  }

  /** Resolve `{"use": name}`; what the factory returns is checked as inline data (§6). */
  transport(name: string, options: Record<string, unknown> | null | undefined, where?: string): Transport {
    const entry = this.transports.get(name);
    if (!entry) {
      refuse("unknown-transport", `transport ${pyRepr(name)} is not registered — install the package that provides it, or inline the transport as data`,
        { fix: { action: "install-vocabulary", kind: "transport", name } });
    }
    const at = where ?? `transport ${pyRepr(name)}`;
    let built: unknown;
    try {
      built = entry.factory(options ?? {});
    } catch (err) {
      if (err instanceof Refusal) throw err;
      refuse("entry-malformed", `${at}: transport ${pyRepr(name)} rejects its options: ${(err as Error).message}`, { fix: { action: "edit-entry", path: at } });
    }
    try {
      if (built instanceof Transport) {
        built.validate(at);
        return built;
      }
      return Transport.fromDict(built, at);
    } catch (err) {
      if (!(err instanceof Refusal) || err.code !== "entry-malformed") throw err;
      refuse("entry-malformed", `${at}: transport ${pyRepr(name)} built malformed data — ${err.hint}`, { fix: { action: "edit-entry", path: at } });
    }
  }

  // ---------------------------------------------------------- readers

  registerReader(name: string, factory: ReaderFactory, opts: { version?: string; existOk?: boolean } = {}): void {
    if (name === "derived") refuse("already-registered", "reader 'derived' is kernel grammar and cannot be replaced");
    if (this.readers.has(name) && !opts.existOk) refuse("already-registered", `reader ${pyRepr(name)} is already registered`);
    this.readers.set(name, { factory, version: opts.version ?? "0.1.0" });
  }

  reader(spec: Record<string, unknown>): Reader {
    const kind = spec["kind"];
    const entry = typeof kind === "string" ? this.readers.get(kind) : undefined;
    if (!entry) {
      refuse("unknown-reader", `reader kind ${pyRepr(kind)} is neither the kernel reader 'derived' nor a registered reader — install the package that provides it`,
        { fix: { action: "install-vocabulary", kind: "reader", name: pyStr(kind) } });
    }
    let reader: unknown;
    try {
      reader = entry.factory(spec);
    } catch (err) {
      if (err instanceof Refusal) throw err;
      refuse("entry-malformed", `reader: ${pyRepr(kind)} rejects its spec: ${(err as Error).message}`, { fix: { action: "edit-entry", path: "reader" } });
    }
    if (!(reader instanceof Reader)) {
      const other = brandedByAnyVersion(reader, "Reader")
        ? " (a Reader of another lmcc version: install the pack against this lmcc, " + KERNEL_VERSION + ")" : "";
      refuse("entry-malformed", `reader: ${pyRepr(kind)} built something that is not a Reader${other}`, { fix: { action: "edit-entry", path: "reader" } });
    }
    return reader;
  }

  // --------------------------------------------------------- describe

  describe(): Record<string, unknown> {
    const versions = (m: Map<string, Named<unknown>>) =>
      orderedObject([...m.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([n, e]) => [n, e.version]));
    return {
      formats: versions(this.formats),
      type_bindings: this.typeBindings.map((b) => ({
        type: b.type,
        format: b.binding === null ? null : isFormat(b.binding) ? b.binding.name ?? "(inline)" : b.binding.use,
        shape: b.shape ?? {},
        json: (["toJson", "fromJson"] as const).filter((k) => b[k] !== null).map((k) => (k === "toJson" ? "to_json" : "from_json")),
      })),
      transports: versions(this.transports),
      readers: copyObject({ derived: "kernel" }, versions(this.readers)),
      allow_udf: this.allowUdf,
      extensions: orderedObject([...this.extensions.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([n, b]) => [n, describeBinding(b)])),
    };
  }
}

brand(Registry, "Registry");

/** The registry `bind`, `load` and `dump` use when you pass none. */
export const defaultRegistry = new Registry();

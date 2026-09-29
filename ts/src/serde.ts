/**
 * Serde: the artifact (kernel §5, §6; schema/entry.schema.json).
 *
 * - Zero ambient state: `load` resolves names only through the registry you
 *   hand it. A data-only entry loads with an empty one.
 * - Loud refusal: unknown names, malformed structure, incompatible versions
 *   and shipped code this runtime will not place refuse, naming the exact
 *   reference and path. Loading never runs a UDF.
 */

import { refuse } from "./errors.ts";
import { isObj } from "./core.ts";
import { adapter as makeAdapter, isTransport, type Adapter, type Reference } from "./adapter.ts";
import { isFormat, loadUdf } from "./formats.ts";
import { deepCopy, hasOwn, setMember } from "./json.ts";
import { defaultRegistry, type Registry } from "./registry.ts";
import { pyRepr, pyStr } from "./text.ts";
import { Transport, validateSpelling } from "./transport.ts";
import { resolveExtensions } from "./extensions.ts";

import { KERNEL_VERSION } from "./version.ts";
export { KERNEL_VERSION };

function parseVersion(version: unknown, what: string): [number, number, number] {
  if (typeof version !== "string") refuse("entry-malformed", `${what}: version must be a string`, { fix: { action: "edit-entry", path: "versions" } });
  const parts = version.split(".");
  if (parts.length !== 3 || !parts.every((p) => /^[0-9]+$/.test(p))) {
    refuse("entry-malformed", `${what}: version ${pyRepr(version)} is not MAJOR.MINOR.PATCH`, { fix: { action: "edit-entry", path: "versions" } });
  }
  return parts.map(Number) as [number, number, number];
}

/** Semver while major = 0: minor is breaking; patches are compatible (§9). */
export function checkCompatible(kind: string, theirs: string, ours: string): void {
  const t = parseVersion(theirs, kind);
  const o = parseVersion(ours, kind);
  const ok = t[0] === o[0] && (t[0] > 0 ? t[1] <= o[1] : t[1] === o[1]);
  if (!ok) {
    refuse("version-incompatible", `${kind}: artifact needs ${theirs}, this implementation provides ${ours}`,
      { fix: { action: "match-version", entry: kind, needs: theirs, provides: ours } });
  }
}

function checkVocabVersion(ref: string, declared: Record<string, unknown>, provided: string): void {
  if (hasOwn(declared, ref)) checkCompatible(ref, declared[ref] as string, provided);
}

function transportOf(registry: Registry) {
  return (_purpose: string, binding: unknown, where: string): Transport =>
    isTransport(binding) ? binding : registry.transport((binding as Reference).use, (binding as Reference).options, where);
}

/** Every referenced argument writer, including inactive choose branches (§6). */
export function* spellingFormatRefs(adp: Adapter, registry: Registry): Generator<[string, Reference]> {
  function* walk(t: Transport, where: string): Generator<[string, Reference]> {
    if (t.choose !== null) {
      for (const [i, alt] of t.choose.entries()) yield* walk((alt.else ?? alt.use)!, `${where}.choose[${i}]`);
      return;
    }
    validateSpelling(t.spelling, `${where}.spelling`);
    if ("input_format" in t.spelling) yield [`${where}.spelling.input_format`, t.spelling["input_format"] as Reference];
  }
  for (const purpose of Object.keys(adp.transports)) {
    const where = `transports[${pyRepr(purpose)}]`;
    yield* walk(transportOf(registry)(purpose, adp.transports[purpose], where), where);
  }
}

/** Kernel §10 at load and bind. */
export function resolveAdapterExtensions(adp: Adapter, registry: Registry) {
  return resolveExtensions({
    extensions: adp.extensions,
    transports: adp.transports,
    bound: registry.extensions,
    checkCompatible,
    transportOf: transportOf(registry),
  });
}

// ---------------------------------------------------------------------- load

export function load(entry: unknown, opts: { registry?: Registry } = {}): Adapter {
  const registry = opts.registry ?? defaultRegistry;
  if (!isObj(entry)) refuse("entry-malformed", "entry must be a JSON object", { fix: { action: "edit-entry", path: "" } });
  for (const key of ["template", "reader", "versions"]) {
    if (!(key in entry)) refuse("entry-malformed", `entry is missing required key ${pyRepr(key)}`, { fix: { action: "edit-entry", path: key } });
  }
  const versions = entry["versions"];
  if (!isObj(versions)) refuse("entry-malformed", "versions must be an object", { fix: { action: "edit-entry", path: "versions" } });
  checkCompatible("kernel", ("kernel" in versions ? versions["kernel"] : "0.0.0") as string, KERNEL_VERSION);
  const vocabVersions = (versions["vocab"] || {}) as Record<string, unknown>;

  const template = entry["template"];
  if (isObj(template) && "messages" in template) {
    refuse("entry-malformed", 'template is a list in kernel 0.2 (the 0.1 {"messages": [...]} form is gone)', { fix: { action: "edit-entry", path: "template" } });
  }
  if (!Array.isArray(template)) refuse("entry-malformed", "template must be a list", { fix: { action: "edit-entry", path: "template" } });

  const readerSpec = entry["reader"];
  if (!isObj(readerSpec)) refuse("entry-malformed", "entry.reader must be an object", { fix: { action: "edit-entry", path: "reader" } });
  const readerKind = readerSpec["kind"];
  if (readerKind !== "derived") {
    const named = typeof readerKind === "string" ? registry.readers.get(readerKind) : undefined;
    if (!named) {
      refuse("unknown-reader", `reader.kind ${pyRepr(readerKind)} is neither the kernel reader 'derived' nor a registered reader`,
        { fix: { action: "install-vocabulary", kind: "reader", name: pyStr(readerKind) } });
    }
    checkVocabVersion(`reader/${readerKind}`, vocabVersions, named.version);
    registry.reader(readerSpec); // resolve at load, like formats and transports (§5, §6)
  }

  const transports: Record<string, Transport | Reference> = {};
  const entryTransports = (entry["transports"] || {}) as Record<string, unknown>;
  for (const purpose of Object.keys(entryTransports)) {
    const s = entryTransports[purpose];
    const where = `transports[${pyRepr(purpose)}]`;
    if (!isObj(s)) refuse("entry-malformed", `${where}: must be an object`, { fix: { action: "edit-entry", path: where } });
    if ("use" in s) {
      const name = s["use"];
      const named = typeof name === "string" ? registry.transports.get(name) : undefined;
      if (!named) {
        refuse("unknown-transport", `${where}: transport ${pyRepr(name)} is not registered`,
          { fix: { action: "install-vocabulary", kind: "transport", name: pyStr(name) } });
      }
      checkVocabVersion(`transport/${name}`, vocabVersions, named.version);
      const options = { ...((s["options"] as Record<string, unknown>) ?? {}) };
      registry.transport(name as string, options, where); // resolve at load (§6)
      setMember(transports, purpose, { use: name as string, options });
    } else {
      setMember(transports, purpose, Transport.fromDict(s, where));
    }
  }

  const formats: Record<string, unknown> = {};
  const entryFormats = (entry["formats"] || {}) as Record<string, unknown>;
  for (const key of Object.keys(entryFormats)) {
    const f = entryFormats[key];
    const where = `formats[${pyRepr(key)}]`;
    if (!isObj(f)) refuse("entry-malformed", `${where}: must be an object`, { fix: { action: "edit-entry", path: where } });
    if ("use" in f) {
      const name = f["use"];
      const named = typeof name === "string" ? registry.formats.get(name) : undefined;
      if (!named) {
        refuse("unknown-format", `${where}: format ${pyRepr(name)} is not registered`, { fix: { action: "install-vocabulary", kind: "format", name: pyStr(name) } });
      }
      checkVocabVersion(`format/${name}`, vocabVersions, named.version);
      const options = { ...((f["options"] as Record<string, unknown>) ?? {}) };
      registry.namedFormat(name as string, options, where); // resolve at load (§5)
      setMember(formats, key, { ...f, options });
    } else if ("language" in f) {
      for (const req of ["write", "sha256"]) {
        if (!(req in f)) refuse("entry-malformed", `${where}: a shipped format needs ${pyRepr(req)}`, { fix: { action: "edit-entry", path: `${where}.${req}` } });
      }
      if (!registry.allowUdf) {
        refuse("format-untrusted", `${where}: the artifact ships a ${pyStr(f["language"])} UDF and this runtime will not place code (a TypeScript runtime places no UDF language; bind a runtime format for the type with registry.format)`,
          { fix: { action: "place-udf", language: pyStr(f["language"]), path: where } });
      }
      loadUdf(f, where);
    } else if ("describe" in f) {
      setMember(formats, key, { ...f });
    } else {
      refuse("entry-malformed", `${where}: a format entry is {use}, a shipped UDF, or a description {describe}`, { fix: { action: "edit-entry", path: where } });
    }
  }

  const adp = makeAdapter({
    messages: template as Record<string, unknown>[], reader: readerSpec, transports, formats,
    name: (entry["name"] ?? "adapter") as string, extensions: entry["extensions"] as Record<string, string> | undefined,
    replay: (entry["replay"] ?? "recorded") as string, strict: entry["strict"] ?? false, declareDefaults: false,
  });
  resolveAdapterExtensions(adp, registry); // kernel §10: refuse here, before any plan
  for (const [where, ref] of spellingFormatRefs(adp, registry)) {
    registry.namedFormat(ref.use, ref.options, where);
    checkVocabVersion(`format/${ref.use}`, vocabVersions, registry.formats.get(ref.use)!.version);
  }
  return adp;
}

// ---------------------------------------------------------------------- dump

function ref(binding: Reference): Record<string, unknown> {
  const out: Record<string, unknown> = { use: binding.use };
  if (binding.options && Object.keys(binding.options).length) out["options"] = deepCopy(binding.options);
  if ("describe" in binding) out["describe"] = binding.describe;
  return out;
}

export function dump(adp: Adapter, registry: Registry = defaultRegistry): Record<string, unknown> {
  const vocab: Record<string, string> = {};
  const transports: Record<string, unknown> = {};
  for (const purpose of Object.keys(adp.transports)) {
    const binding = adp.transports[purpose];
    if (isTransport(binding)) {
      setMember(transports, purpose, binding.toDict());
    } else {
      const named = registry.transports.get(binding.use);
      if (!named) {
        refuse("unknown-transport", `cannot dump: transport ${pyRepr(binding.use)} is not registered (its version is part of the artifact)`,
          { fix: { action: "install-vocabulary", kind: "transport", name: binding.use } });
      }
      setMember(vocab, `transport/${binding.use}`, named.version);
      setMember(transports, purpose, ref(binding));
    }
  }
  for (const [where, r] of spellingFormatRefs(adp, registry)) {
    registry.namedFormat(r.use, r.options, where);
    setMember(vocab, `format/${r.use}`, registry.formats.get(r.use)!.version);
  }
  const formats: Record<string, unknown> = {};
  for (const key of Object.keys(adp.formats)) {
    const binding = adp.formats[key];
    if (isFormat(binding)) {
      if (binding.shipped) {
        setMember(formats, key, { ...binding.shipped });
        continue;
      }
      refuse("format-not-self-contained",
        `cannot dump formats[${pyRepr(key)}]: a TypeScript format is a closure, not shippable source; bind it at runtime with registry.format(type, ...) (never serialized) or reference a registered format by name`,
        { fix: { action: "reship-udf", path: `formats[${pyRepr(key)}]` } });
    }
    if (isObj(binding) && "use" in binding) {
      const named = registry.formats.get(binding["use"] as string);
      if (!named) {
        refuse("unknown-format", `cannot dump: format ${pyRepr(binding["use"])} is not registered`,
          { fix: { action: "install-vocabulary", kind: "format", name: binding["use"] as string } });
      }
      setMember(vocab, `format/${binding["use"]}`, named.version);
      setMember(formats, key, ref(binding as Reference));
    } else {
      setMember(formats, key, { ...(binding as Record<string, unknown>) });
    }
  }
  const readerKind = adp.reader["kind"] as string;
  if (readerKind !== "derived") {
    const named = registry.readers.get(readerKind);
    if (!named) {
      refuse("unknown-reader", `cannot dump: reader ${pyRepr(readerKind)} is not registered (its version is part of the artifact)`,
        { fix: { action: "install-vocabulary", kind: "reader", name: pyStr(readerKind) } });
    }
    setMember(vocab, `reader/${readerKind}`, named.version);
  }
  const entry: Record<string, unknown> = { name: adp.name, versions: { kernel: KERNEL_VERSION, vocab } };
  if (Object.keys(adp.extensions).length) entry["extensions"] = { ...adp.extensions };
  entry["template"] = adp.template.map((m) => ({ ...m }));
  entry["reader"] = { ...adp.reader };
  if (adp.replay !== "recorded") entry["replay"] = adp.replay;
  if (adp.strict) entry["strict"] = true;
  if (Object.keys(transports).length) entry["transports"] = transports;
  if (Object.keys(formats).length) entry["formats"] = formats;
  return entry;
}

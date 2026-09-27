/**
 * lmcc — the language model calling convention (TypeScript kernel).
 *
 * A typed signature and an adapter (a template, a reader, transports by
 * purpose, formats by type) bind into a plan that renders lm15 requests and
 * reads replies. The kernel ships no vocabulary beyond its scalar and media
 * defaults (`lmcc/std` is the standard pack), imports nothing, and runs
 * wherever JavaScript runs. It passes the same contract corpus as the Python
 * reference, byte for byte (contract/, kernel §9).
 *
 * ```ts
 * import * as lmcc from "lmcc";
 * const answer = lmcc.signature("Answer in one sentence.", {
 *   inputs: { question: lmcc.t.string() }, outputs: { answer: lmcc.t.string() } });
 * const xml = lmcc.adapter({ messages: [
 *   lmcc.system("{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
 *   lmcc.user("{question}")] });
 * const plan = xml.bind(answer, { instruct: true });
 * plan.render({ question: "Why is the sky blue?" }).request("gpt-4o-mini");
 * plan.parse("<answer>\nRayleigh scattering.\n</answer>").answer;
 * ```
 */

import { bindHook } from "./adapter.ts";
import { Registry } from "./registry.ts";
import type { FormatSpec, Format } from "./formats.ts";
import type { JsonObject } from "./json.ts";

export { Refusal, refuse, type Fix, type RefusalData } from "./errors.ts";
export { Adapter, adapter, assistant, developer, message, system, turns, use, user, type AdapterOptions } from "./adapter.ts";
export { Capture, type Field, type Message, type Part, type Shape } from "./core.ts";
export { Signature, field, signature, signatureFromDict, signatureToDict, t, type TypedShape, type FieldSpec } from "./signature.ts";
export { makeFormat, MEDIA_DEFAULT, SCALAR_DEFAULT, type Format, type FormatSpec } from "./formats.ts";
export { Reader, DerivedReader, type ReaderStream } from "./reader.ts";
export { Plan, Reading, RenderResult, bind } from "./plan.ts";
export { Stream, StreamResult, type StreamEvent } from "./stream.ts";
export { Registry, type RegistryOptions } from "./registry.ts";
export { KERNEL_VERSION, dump, load } from "./serde.ts";
export { Transport } from "./transport.ts";
export { LegacyRE2, nativeExtensions, type ExtensionBinding, type PatternBinding } from "./extensions.ts";
export { ModelStep, ToolStep, Turn, canonicalJson, signatureFingerprint, type TurnJSON, type ModelStepJSON, type ToolStepJSON } from "./turn.ts";
export { find, put, when, choose } from "./helpers.ts";
export { parseJson, jsonText, jsonEqual, formatNumber, JsonSyntaxError, type Json, type JsonObject } from "./json.ts";
export { strip } from "./text.ts";

import "./plan.ts";
import "./serde.ts";

/** The registry `bind`, `load` and `dump` use when you pass none. */
export const defaultRegistry = new Registry();
bindHook.defaultRegistry = () => defaultRegistry;

/** Bind a type name to a format in the default registry (per runtime, never serialized). */
export function format(type: string, spec: (FormatSpec | { use: string; options?: Record<string, unknown> }) & { shape?: JsonObject }): Format {
  return defaultRegistry.format(type, spec);
}

export const VERSION = "0.8.4";

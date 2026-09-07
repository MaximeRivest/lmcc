// LMCC kernel (TypeScript, clean-room from contract/). Stdlib only; ships
// no vocabulary: formats, strategies, and lenses register through Registry.

export { Refusal, refuse, CODES, type Code, type Fix } from "./refusal.ts";
export { parseJson, parseJsonDocument, dumpJson, jsonEqual, cloneJson, quoteJsonString, isJsonObject, JsonError, type Json } from "./json.ts";
export { strip, lstrip, rstrip, readInteger, readNumber, readBoolean, spellNumber, spellInteger, roundHalfEven, lintRe2, compileRe2, scalars } from "./text.ts";
export { signatureFromData, classifyShape, structuralKeys, mechanicalHint, type Signature, type Field, type ShapeInfo } from "./signature.ts";
export { parseTemplateText, type Node, type TemplateItem } from "./template.ts";
export { makeSpan, textPart, FormatError, KERNEL_SCALAR, kernelMedia, resolveFormat, formatAccepts, bindKey, type Format, type Part, type Span, type FormatContext } from "./formats.ts";
export { Registry, type Options } from "./registry.ts";
export { evalPredicate, selectStrategy, type StrategyData, type PlainStrategy, type ChooseStrategy, type Routing, type Predicate, type Capabilities } from "./strategy.ts";
export { DERIVED_LENS, type Lens, type BoundLens, type LensBindContext, type Spelled } from "./lens.ts";
export { Plan, bind, normalizeResponse, type Adapter, type Message, type RenderResult, type Values } from "./plan.ts";
export { Stream, type StreamEvent, type StreamResult } from "./stream.ts";
export { load, dump, KERNEL_VERSION, versionCompatible, udfHash } from "./serde.ts";

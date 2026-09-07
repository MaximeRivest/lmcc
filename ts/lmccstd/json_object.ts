// lens/json_object 0.1.0 (spec/vocab/lens-json_object.md).

import { refuse } from "../lmcc/refusal.ts";
import type { Lens, BoundLens, LensBindContext, Spelled } from "../lmcc/lens.ts";
import { parseJson, parseJsonDocument, dumpJson, cloneJson, isJsonObject, type Json, type Member } from "../lmcc/json.ts";
import { strip } from "../lmcc/text.ts";

function embed(text: string): Json {
  try {
    const v = parseJson(text);
    if (typeof v !== "string") return v;
  } catch {
    // not JSON: embed as a string
  }
  return text;
}

function locateDocument(text: string): Member[] | null {
  let doc = strip(text);
  if (doc.startsWith("```")) {
    const nl = doc.indexOf("\n");
    const body = nl < 0 ? "" : doc.slice(nl + 1);
    const close = body.lastIndexOf("```");
    doc = strip(close >= 0 ? body.slice(0, close) : body);
  }
  const attempt = (s: string): Member[] | null => {
    try {
      const parsed = parseJsonDocument(s);
      if (!isJsonObject(parsed.value)) return null;
      return parsed.members ?? [];
    } catch {
      return null;
    }
  };
  let members = attempt(doc);
  if (members === null) {
    const a = doc.indexOf("{");
    const b = doc.lastIndexOf("}");
    if (a >= 0 && b > a) members = attempt(doc.slice(a, b + 1));
  }
  return members;
}

export const jsonObjectLens: Lens = {
  kind: "json_object",
  bind(ctx: LensBindContext): BoundLens {
    if (ctx.capabilities.native_structured_output !== true) {
      refuse("capability-missing", "lens json_object needs the model to declare native_structured_output; without server-side enforcement a JSON object is a meaning with many spellings", {
        fix: { action: "declare-capability", fact: "native_structured_output" },
      });
    }
    const names = ctx.fields.map((f) => f.name);
    const properties: { [k: string]: Json } = {};
    for (const f of ctx.fields) properties[f.name] = cloneJson(ctx.shapeOf(f));
    const patch: { [k: string]: Json } = {
      response_format: {
        type: "json_schema",
        schema: { type: "object", properties, required: names.slice(), additionalProperties: false },
      },
    };
    const write = (values: Spelled[]): string => {
      const obj: { [k: string]: Json } = {};
      for (const v of values) obj[v.name] = embed(v.text);
      return dumpJson(obj, 2);
    };
    return {
      kind: "json_object",
      patch,
      streamMode: "buffered",
      join: write,
      format: write,
      skeleton: () => ({ prefill: "", stops: [] }),
      split(text: string) {
        const members = locateDocument(text);
        if (members === null) refuse("lens-parse-error", "the reply is not a JSON object", { stage: "parse" });
        const raws: { [field: string]: string } = {};
        const missing: string[] = [];
        for (const name of names) {
          const hits = members.filter((m) => m.key === name);
          if (hits.length > 1) refuse("parse-ambiguous", `member ${JSON.stringify(name)} appears ${hits.length} times in the reply`, { stage: "parse", partial: raws });
          if (hits.length === 0) {
            missing.push(name);
            continue;
          }
          const m = hits[0];
          raws[name] = m.isString ? (m.value as string) : strip(m.source);
        }
        if (missing.length) refuse("parse-missing-fields", `the reply lacks member(s) ${missing.join(", ")}`, { stage: "parse", partial: raws });
        return raws;
      },
      describe: () => ({ kind: "json_object", fields: names }),
    };
  },
};

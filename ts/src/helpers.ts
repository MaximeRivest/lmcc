/**
 * Helpers you can autocomplete: `find`, `put`, `when`, `choose`. Each returns
 * the same plain data you could write by hand (kernel §6); a wrong argument
 * is host misuse (`TypeError`), not a `Refusal`: the kernel validates the data
 * they produce like any other.
 */

import { Transport, type Predicate } from "./transport.ts";
import { defaultRegistry, type Registry } from "./registry.ts";

function to(sub: string | undefined): string {
  if (sub === undefined) return "@purpose";
  if (typeof sub !== "string" || !sub || sub.startsWith("@")) throw new TypeError("to is a sub-purpose name like 'calls' (omit it for the purpose itself)");
  return `@purpose.${sub}`;
}

/** Where an output is found in the reply (§6 find rules). */
export const find = {
  /** Text between two delimiters. `repair` reads misspelled delimiters (§4a); `wholeReply` makes a match a complete reply. */
  between(open: string, close: string, opts: { to?: string; remove?: boolean; repair?: boolean; wholeReply?: boolean } = {}): Record<string, unknown> {
    if (!(typeof open === "string" && open && typeof close === "string" && close)) throw new TypeError("find.between takes two non-empty strings");
    const rule: Record<string, unknown> = { from: "text", between: [open, close], to: to(opts.to) };
    if (opts.remove) rule["remove"] = true;
    if (opts.repair) rule["repair"] = true;
    if (opts.wholeReply) rule["complete_reply"] = true;
    return rule;
  },
  /** Lines starting with `prefix`. */
  lines(prefix: string, opts: { to?: string; remove?: boolean } = {}): Record<string, unknown> {
    if (typeof prefix !== "string" || !prefix) throw new TypeError("find.lines takes a non-empty prefix");
    const rule: Record<string, unknown> = { from: "text", line_prefixed: prefix, to: to(opts.to) };
    if (opts.remove) rule["remove"] = true;
    return rule;
  },
  /** A regular expression (needs a declared `pattern/*` extension, §10). */
  pattern(regex: string, opts: { to?: string; remove?: boolean } = {}): Record<string, unknown> {
    if (typeof regex !== "string" || !regex) throw new TypeError("find.pattern takes a non-empty regex");
    const rule: Record<string, unknown> = { from: "text", pattern: regex, to: to(opts.to) };
    if (opts.remove) rule["remove"] = true;
    return rule;
  },
  /** Reply parts of one lm15 type: `find.part("thinking")`, `find.part("tool_call", {to: "calls"})`. */
  part(type: string, opts: { to?: string; wholeReply?: boolean } = {}): Record<string, unknown> {
    if (typeof type !== "string" || !type) throw new TypeError("find.part takes an lm15 part type such as 'thinking'");
    const rule: Record<string, unknown> = { from: `part:${type}`, to: to(opts.to) };
    if (opts.wholeReply) rule["complete_reply"] = true;
    return rule;
  },
};

/** Where an input goes instead of a template slot (§6 put). */
export const put = {
  system: (field?: string) => ({ [to(field)]: "message:system" }),
  developer: (field?: string) => ({ [to(field)]: "message:developer" }),
  user: (field?: string) => ({ [to(field)]: "message:user" }),
  /** Into the lm15 request: `put.request("tools")`. */
  request(path: string, field?: string): Record<string, string> {
    if (typeof path !== "string" || !path) throw new TypeError("put.request takes a request path such as 'tools'");
    return { [to(field)]: `request.${path}` };
  },
};

/** When a transport applies: predicates over declared capability facts. */
export const when = {
  has: (fact: string): Predicate => ({ capability: fact }),
  lacks: (fact: string): Predicate => ({ not: { capability: fact } }),
  all: (...predicates: Predicate[]): Predicate => ({ all: predicates }),
  any: (...predicates: Predicate[]): Predicate => ({ any: predicates }),
};

type Choice = Transport | Record<string, unknown> | string;

/** The first transport whose predicate holds: `choose([[when.has("native_reasoning"), "native_reasoning"]], {otherwise: "reasoning_tags"})`. */
export function choose(alternatives: readonly (readonly [Predicate, Choice])[], opts: { otherwise?: Choice; registry?: Registry } = {}): Transport {
  const registry = opts.registry ?? defaultRegistry;
  const resolve = (t: Choice): Transport => {
    if (t instanceof Transport) return t;
    if (typeof t === "string") return registry.transport(t, {});
    if (typeof t === "object" && t !== null) return Transport.fromDict(t, "choose");
    throw new TypeError("a choice is a Transport, an object or a registered transport name");
  };
  const items = alternatives.map((alt) => {
    if (!Array.isArray(alt) || alt.length !== 2 || typeof alt[0] !== "object") throw new TypeError("choose takes [predicate, transport] pairs");
    return { when: alt[0], use: resolve(alt[1]) };
  });
  const choices: { when?: Predicate; use?: Transport; else?: Transport }[] = [...items];
  if (opts.otherwise !== undefined) choices.push({ else: resolve(opts.otherwise) });
  const t = new Transport({ choose: choices });
  t.validate("choose");
  return t;
}

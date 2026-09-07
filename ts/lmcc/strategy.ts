// Kernel §6: strategies as data; predicates; choose.

import { refuse } from "./refusal.ts";
import type { Json } from "./json.ts";

export type Predicate = { capability: string } | { not: Predicate } | { all: Predicate[] } | { any: Predicate[] };

export interface Routing {
  from: string; // "text" | "channel:<kind>"
  between?: [string, string];
  pattern?: string;
  line_prefixed?: string;
  to: string; // "@role" | "@role.<sub>"
  consume?: boolean;
}

export interface PlainStrategy {
  when?: Predicate;
  requires?: string[];
  visible?: boolean;
  fragments?: { [messageRole: string]: string };
  controls?: { [k: string]: Json };
  placement?: { [target: string]: string };
  routings?: Routing[];
}

export interface ChooseStrategy {
  choose: ({ when: Predicate; use: StrategyData } | { else: StrategyData })[];
}

export type StrategyData = PlainStrategy | ChooseStrategy;

export type Capabilities = { [fact: string]: boolean };

export function isChoose(s: StrategyData): s is ChooseStrategy {
  return "choose" in s && Array.isArray((s as ChooseStrategy).choose);
}

/** Unknown facts are false; only the vocabulary's words can be true (capabilities.md). */
export function evalPredicate(p: Predicate, caps: Capabilities): boolean {
  if ("capability" in p) return caps[p.capability] === true;
  if ("not" in p) return !evalPredicate(p.not, caps);
  if ("all" in p) return p.all.every((q) => evalPredicate(q, caps));
  if ("any" in p) return p.any.some((q) => evalPredicate(q, caps));
  return false;
}

/**
 * Pick the strategy a role uses: `choose` takes the first branch whose
 * `when` holds (else branch when none); a plain strategy checks its own
 * `when` and `requires`. Refuses `capability-missing`.
 */
export function selectStrategy(role: string, data: StrategyData, caps: Capabilities): PlainStrategy {
  if (isChoose(data)) {
    const whens: Predicate[] = [];
    for (const branch of data.choose) {
      if ("else" in branch) return selectStrategy(role, branch.else, caps);
      whens.push(branch.when);
      if (evalPredicate(branch.when, caps)) return selectStrategy(role, branch.use, caps);
    }
    refuse("capability-missing", `role ${role}: no choose branch matches the declared capabilities and there is no else`, {
      fix: { action: "satisfy-predicate", role, predicate: { any: whens } },
    });
  }
  if (data.when && !evalPredicate(data.when, caps)) {
    refuse("capability-missing", `role ${role}: the strategy's when-predicate does not hold`, {
      fix: { action: "satisfy-predicate", role, predicate: data.when },
    });
  }
  for (const fact of data.requires ?? []) {
    if (caps[fact] !== true) {
      refuse("capability-missing", `role ${role}: the strategy requires capability ${JSON.stringify(fact)}`, {
        fix: { action: "declare-capability", fact },
      });
    }
  }
  return data;
}

/** The span kind a routing delivers. */
export function routingSpanKind(r: Routing): string {
  return r.from === "text" ? "text" : r.from.slice("channel:".length);
}

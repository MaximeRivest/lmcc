/**
 * Class identity across copies of this package.
 *
 * npm easily installs lmcc twice (a pack built against one copy, an app
 * against another; a bundler that duplicates it). JavaScript's `instanceof`
 * then fails between copies: a Refusal thrown by one copy's format would be
 * wrapped as `format-read-error` by the other, a transport from one copy's
 * `lmcc/std` would be rejected by the other's registry. So every public class
 * carries a brand, a registered symbol (`Symbol.for`), and `instanceof`
 * checks the brand — for that exact class, never for its subclasses, which
 * keep JavaScript's own rule.
 *
 * Brands carry the kernel's compatibility unit (major.minor while major = 0,
 * §9): two copies of one kernel version share objects; copies of different
 * versions do not, and the records that must cross versions go through their
 * JSON (`Turn.toJSON`, `Transport.toDict`), which the contract versions.
 * `Refusal` alone is unversioned: its shape `{code, hint, fix, partial}` is
 * the stable one (errors.md), so `isRefusal` recognizes every lmcc.
 */

import { KERNEL_VERSION } from "./version.ts";

const [MAJOR, MINOR] = KERNEL_VERSION.split(".");
export const COMPAT = MAJOR === "0" ? `${MAJOR}.${MINOR}` : MAJOR;

export function brandKey(name: string, versioned = true): symbol {
  return Symbol.for(versioned ? `lmcc.${name}@${COMPAT}` : `lmcc.${name}`);
}

/** Mark instances of `cls` and make `x instanceof cls` true for any copy's instance. */
export function brand(cls: abstract new (...args: any[]) => unknown, name: string, versioned = true): void {
  const key = brandKey(name, versioned);
  Object.defineProperty(cls.prototype, key, { value: true });
  Object.defineProperty(cls, Symbol.hasInstance, {
    value(this: unknown, x: unknown): boolean {
      // A subclass inherits this static method; for it, JavaScript's own rule.
      if (this !== cls) return Function.prototype[Symbol.hasInstance].call(this, x);
      return (typeof x === "object" || typeof x === "function") && x !== null && (x as Record<symbol, unknown>)[key] === true;
    },
  });
}

/** Whether `x` is branded `name` by some copy of lmcc, of any version (for helpful refusals). */
export function brandedByAnyVersion(x: unknown, name: string): boolean {
  if (typeof x !== "object" || x === null) return false;
  let proto = Object.getPrototypeOf(x);
  while (proto) {
    for (const s of Object.getOwnPropertySymbols(proto)) {
      if (Symbol.keyFor(s)?.startsWith(`lmcc.${name}@`)) return true;
    }
    proto = Object.getPrototypeOf(proto);
  }
  return false;
}

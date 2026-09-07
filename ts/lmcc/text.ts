// Kernel §7a text rules: strip, integer/number grammars, ECMAScript
// number spelling, boolean/enum/null reading, half-to-even rounding, and
// the RE2-subset regex admission.

/** The six strip characters: U+0009 U+000A U+000B U+000C U+000D U+0020. */
export function isStripChar(ch: string): boolean {
  return ch === "\t" || ch === "\n" || ch === "\v" || ch === "\f" || ch === "\r" || ch === " ";
}

export function strip(s: string): string {
  let a = 0;
  let b = s.length;
  while (a < b && isStripChar(s[a])) a++;
  while (b > a && isStripChar(s[b - 1])) b--;
  return s.slice(a, b);
}

export function lstrip(s: string): string {
  let a = 0;
  while (a < s.length && isStripChar(s[a])) a++;
  return s.slice(a);
}

export function rstrip(s: string): string {
  let b = s.length;
  while (b > 0 && isStripChar(s[b - 1])) b--;
  return s.slice(0, b);
}

export const INTEGER_RE = /^-?[0-9]+$/;
export const NUMBER_RE = /^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$/;

/** Integer text `-?[0-9]+`; returns null when the grammar does not match. */
export function readInteger(text: string): number | bigint | null {
  if (!INTEGER_RE.test(text)) return null;
  const big = BigInt(text);
  if (big >= BigInt(Number.MIN_SAFE_INTEGER) && big <= BigInt(Number.MAX_SAFE_INTEGER)) return Number(big);
  return big;
}

/**
 * Number text per the §7a grammar, read as binary64; null when it does not
 * match. Text whose binary64 value is not finite (`1e400`) is also null:
 * the kernel never holds a non-finite number (stated guess, AUDIT E4).
 */
export function readNumber(text: string): number | null {
  if (!NUMBER_RE.test(text)) return null;
  const v = Number(text);
  return Number.isFinite(v) ? v : null;
}

/** ECMAScript Number::toString; non-finite is the caller's refusal. */
export function spellNumber(x: number | bigint): string {
  if (typeof x === "bigint") return x.toString();
  if (!Number.isFinite(x)) throw new RangeError("non-finite number");
  return String(x);
}

/** Integers are written in decimal, never in exponent form. */
export function spellInteger(x: number | bigint): string {
  if (typeof x === "bigint") return x.toString();
  if (Object.is(x, -0)) return "0";
  return BigInt(x).toString();
}

export function isIntegerValue(v: unknown): v is number | bigint {
  return typeof v === "bigint" || (typeof v === "number" && Number.isInteger(v));
}

/** ASCII case fold, then `true|yes` / `false|no`; null otherwise. */
export function readBoolean(text: string): boolean | null {
  const folded = text.replace(/[A-Z]/g, (c) => c.toLowerCase());
  if (folded === "true" || folded === "yes") return true;
  if (folded === "false" || folded === "no") return false;
  return null;
}

/** Half-to-even in binary64: roundeven(x * 10^n) / 10^n. */
export function roundHalfEven(x: number, places: number): number {
  const scale = Math.pow(10, places);
  const y = x * scale;
  const f = Math.floor(y);
  const diff = y - f;
  let r: number;
  if (diff < 0.5) r = f;
  else if (diff > 0.5) r = f + 1;
  else r = f % 2 === 0 ? f : f + 1;
  return r / scale;
}

// ---------------------------------------------------------------------------
// Regex: RE2 syntax minus named groups (D-14). JavaScript's engine is not
// RE2, so admission is a syntactic lint: the constructs D-14 lists refuse,
// and RE2 constructs this engine cannot run refuse too (stated trade-off).

export interface RegexProblem {
  reason: string;
}

/** Returns a problem description, or null when the pattern is admitted. */
export function lintRe2(pattern: string): RegexProblem | null {
  let inClass = false;
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === "\\") {
      const n = pattern[i + 1];
      if (n === undefined) return { reason: "trailing backslash" };
      if (n >= "1" && n <= "9") return { reason: `backreference \\${n}` };
      if (n === "k") return { reason: "named backreference \\k" };
      if (n === "A" || n === "z" || n === "Z" || n === "C" || n === "Q" || n === "E" || n === "G")
        return { reason: `escape \\${n} is outside the supported RE2 subset` };
      i++;
      continue;
    }
    if (inClass) {
      if (c === "[" && pattern[i + 1] === ":") return { reason: "POSIX class [:name:]" };
      if (c === "]") inClass = false;
      continue;
    }
    if (c === "[") {
      inClass = true;
      if (pattern[i + 1] === "^") i++;
      if (pattern[i + 1] === "]") i++; // leading ] is literal
      continue;
    }
    if (c === "(" && pattern[i + 1] === "?") {
      const rest = pattern.slice(i + 2, i + 5);
      if (rest.startsWith("=") || rest.startsWith("!")) return { reason: "lookahead (?= / (?!" };
      if (rest.startsWith("<=") || rest.startsWith("<!")) return { reason: "lookbehind (?<= / (?<!" };
      if (rest.startsWith("<")) return { reason: "named group (?<name>" };
      if (rest.startsWith("P<") || rest.startsWith("P=")) return { reason: "named group (?P<name>" };
      if (rest.startsWith(">")) return { reason: "atomic group (?>" };
      if (rest.startsWith(":")) {
        i++;
        continue;
      }
      return { reason: "inline flags (?flags) are outside the supported RE2 subset" };
    }
    if ((c === "*" || c === "+" || c === "?" || c === "}") && pattern[i + 1] === "+") {
      return { reason: `possessive quantifier ${c}+` };
    }
  }
  if (inClass) return { reason: "unterminated character class" };
  return null;
}

/**
 * Translate an admitted RE2-subset pattern to a JavaScript RegExp: `.`
 * outside classes becomes `[^\n]` (RE2's default), the `u` flag makes
 * `.` consume one scalar, `g` scans globally.
 */
export function compileRe2(pattern: string): RegExp {
  let out = "";
  let inClass = false;
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === "\\") {
      out += c + (pattern[i + 1] ?? "");
      i++;
      continue;
    }
    if (inClass) {
      if (c === "]") inClass = false;
      out += c;
      continue;
    }
    if (c === "[") {
      inClass = true;
      out += c;
      if (pattern[i + 1] === "^") {
        out += "^";
        i++;
      }
      if (pattern[i + 1] === "]") {
        out += "\\]";
        i++;
      }
      continue;
    }
    if (c === ".") {
      out += "[^\\n]";
      continue;
    }
    out += c;
  }
  return new RegExp(out, "gu");
}

/** Every Unicode scalar of a string (surrogate pairs kept together). */
export function scalars(s: string): string[] {
  return Array.from(s);
}

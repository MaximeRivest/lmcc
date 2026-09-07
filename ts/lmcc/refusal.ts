// Refusal: code (stable), hint (for humans), fix (closed action vocabulary,
// present before render), partial (what a parse recovered).

export type Fix =
  | { action: "install-vocabulary"; kind: "format" | "strategy" | "lens"; name: string }
  | { action: "match-version"; entry: string; needs: string; provides: string }
  | { action: "place-udf"; language: string; path: string }
  | { action: "reship-udf"; path: string }
  | { action: "edit-entry"; path: string }
  | { action: "edit-template"; path: string; slot?: string; field?: string }
  | { action: "edit-signature"; field?: string; role?: string }
  | { action: "assign-role"; role: string }
  | { action: "declare-capability"; fact: string }
  | { action: "satisfy-predicate"; role: string; predicate: object }
  | { action: "bind-format"; field: string; key: string };

export type Stage = "construct" | "signature" | "load" | "bind" | "render" | "parse" | "registration";

export const CODES = [
  "template-syntax", "unknown-slot", "unknown-parse-kind", "unknown-format",
  "unknown-strategy", "entry-malformed", "signature-malformed",
  "version-incompatible", "already-registered", "capability-missing",
  "not-lensable", "role-ambiguous", "field-uncovered", "field-double-covered",
  "control-conflict", "no-format", "format-shape-mismatch", "format-direction",
  "format-span-mismatch", "format-placement-mismatch", "format-untrusted",
  "format-not-self-contained", "udf-tampered", "udf-unplaceable",
  "demo-not-renderable", "unmapped-type", "missing-input", "value-invalid",
  "format-write-error", "format-read-error", "value-collides", "parse-value",
  "parse-missing-fields", "parse-ambiguous", "lens-parse-error",
  "response-malformed",
] as const;
export type Code = (typeof CODES)[number];

export class Refusal extends Error {
  code: Code;
  hint: string;
  fix: Fix | undefined;
  partial: unknown;
  stage: Stage;
  constructor(code: Code, hint: string, opts: { fix?: Fix; partial?: unknown; stage?: Stage } = {}) {
    super(`[${code}] ${hint}`);
    this.name = "Refusal";
    this.code = code;
    this.hint = hint;
    this.fix = opts.fix;
    this.partial = opts.partial;
    this.stage = opts.stage ?? "bind";
  }
  describe(): { code: string; hint: string; fix: Fix | null; partial: unknown } {
    return { code: this.code, hint: this.hint, fix: this.fix ?? null, partial: this.partial ?? null };
  }
}

export function refuse(code: Code, hint: string, opts: { fix?: Fix; partial?: unknown; stage?: Stage } = {}): never {
  throw new Refusal(code, hint, opts);
}

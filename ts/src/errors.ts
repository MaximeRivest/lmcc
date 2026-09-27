/**
 * Refusals.
 *
 * Every failure in lmcc is a {@link Refusal} with a stable `code`
 * (contract/spec/errors.md), a `hint` naming the exact offender and what to
 * do, a `fix` — the one next action as plain data, carried by every refusal
 * that fires before render — and, for parse refusals, a `partial` with what
 * was read. Silent wrong behavior is the one bug this library refuses to have.
 */

/** The next action as data: `{action, ...parameters}` from the closed vocabulary of errors.md. */
export interface Fix {
  readonly action: string;
  readonly [parameter: string]: unknown;
}

export interface RefusalData {
  readonly code: string;
  readonly hint: string;
  readonly fix: Fix | null;
  readonly partial: Record<string, unknown> | null;
}

export class Refusal extends Error {
  readonly code: string;
  readonly hint: string;
  readonly fix: Fix | null;
  readonly partial: Record<string, unknown> | null;

  constructor(code: string, hint: string, opts: { fix?: Fix | null; partial?: Record<string, unknown> | null } = {}) {
    super(`[${code}] ${hint}`);
    this.name = "Refusal";
    this.code = code;
    this.hint = hint;
    this.fix = opts.fix ?? null;
    this.partial = opts.partial ?? null;
  }

  /** The refusal as plain data: `{code, hint, fix, partial}`. */
  describe(): RefusalData {
    return { code: this.code, hint: this.hint, fix: this.fix, partial: this.partial };
  }

  toJSON(): RefusalData {
    return this.describe();
  }
}

export function refuse(code: string, hint: string, opts: { fix?: Fix | null; partial?: Record<string, unknown> | null } = {}): never {
  throw new Refusal(code, hint, opts);
}

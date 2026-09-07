// Minimal ambient declarations for the Node.js APIs this project uses.
// @types/node is not available offline (no package installs); these
// cover exactly the surface the kernel, the std pack, the driver, and the
// tests touch. Runtime behavior is Node 22's.

declare module "node:crypto" {
  export interface Hash {
    update(data: string, encoding?: string): Hash;
    digest(encoding: "hex"): string;
  }
  export function createHash(algorithm: string): Hash;
}

declare module "node:readline" {
  export interface Interface {
    on(event: "line", listener: (line: string) => void): Interface;
    on(event: "close", listener: () => void): Interface;
  }
  export function createInterface(options: { input: unknown; crlfDelay?: number }): Interface;
}

declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf8"): string;
  export function readdirSync(path: string): string[];
}

declare module "node:path" {
  export function join(...parts: string[]): string;
  export function dirname(path: string): string;
}

declare module "node:url" {
  export function fileURLToPath(url: string): string;
}

declare module "node:test" {
  export function test(name: string, fn: () => void | Promise<void>): void;
  export function describe(name: string, fn: () => void): void;
  export function it(name: string, fn: () => void | Promise<void>): void;
}

declare module "node:assert/strict" {
  function assert(value: unknown, message?: string): void;
  namespace assert {
    function equal(actual: unknown, expected: unknown, message?: string): void;
    function deepEqual(actual: unknown, expected: unknown, message?: string): void;
    function ok(value: unknown, message?: string): void;
    function throws(fn: () => unknown, expected?: unknown, message?: string): void;
  }
  export default assert;
}

declare const process: {
  stdin: unknown;
  stdout: { write(chunk: string): boolean };
  stderr: { write(chunk: string): boolean };
  argv: string[];
  exit(code?: number): never;
};

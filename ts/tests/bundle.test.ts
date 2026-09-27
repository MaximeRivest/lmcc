/**
 * The package says `"sideEffects": false`: a bundler may drop any module of
 * lmcc whose exports an app does not name. That promise holds only if no
 * module works by being imported for its effect (a bare `import "./x"`, a
 * module that fills another module's slot when it loads). This test bundles
 * a small app with esbuild, which honors the flag, and runs it: the app uses
 * only the adapter's methods and the default registry, never naming `bind`,
 * `dump` or the plan module, which is exactly what a dropped module breaks.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const PKG = fileURLToPath(new URL("..", import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "lmcc-bundle-"));
after(() => rmSync(dir, { recursive: true, force: true }));

const APP = `
import { adapter, format, load, signature, system, t, user, when, choose } from "lmcc";
import { install } from "lmcc/std";
import { Registry } from "lmcc";

const sig = signature("Answer.", { inputs: { question: t.string() }, outputs: { answer: t.string() } });
const xml = adapter({ messages: [
  system("{instruction}\\n{% for f in outputs %}<{f.name}>\\n{f.value}\\n</{f.name}>\\n{% endfor %}"),
  user("{question}")] });
const plan = xml.bind(sig, { instruct: true });                 // default registry, plan module
const answer = plan.parse("<answer>\\nhi\\n</answer>").answer;
const entry = xml.dump();                                        // serde module
const again = load(entry).bind(sig, { instruct: true }).render({ question: "q" }).request("m");
format("Money", { write: (v) => String(v), read: (s) => Number(s) }); // index's own export
const registry = new Registry(); install(registry);
const picked = choose([[when.has("native_reasoning"), "native_reasoning"]], { otherwise: "reasoning_tags", registry });
console.log(JSON.stringify({ answer, entry: typeof entry.template, again: again.model, picked: Object.keys(picked.toDict()).length > 0 }));
`;

const EXPECTED = { answer: "hi", entry: "object", again: "m", picked: true };

test("a bundle that honors sideEffects: false still binds, dumps and loads", async () => {
  const outfile = join(dir, "app.mjs");
  const result = await build({
    stdin: { contents: APP, resolveDir: PKG, loader: "ts", sourcefile: "app.ts" },
    bundle: true,
    platform: "node",
    format: "esm",
    conditions: ["lmcc-source"],
    outfile,
    logLevel: "silent",
    write: true,
  });
  // esbuild warns when it drops an import because of the flag; that is the bug itself.
  assert.deepEqual(result.warnings.map((w) => w.text), []);
  const out = JSON.parse(execFileSync(process.execPath, [outfile], { encoding: "utf8" }));
  assert.deepEqual(out, EXPECTED);
});

test("the published build bundles the same way", async () => {
  // What npm users get: the real package.json and a fresh dist/, installed
  // under node_modules so resolution goes through the package's exports.
  const pkg = join(dir, "node_modules", "lmcc");
  mkdirSync(pkg, { recursive: true });
  copyFileSync(join(PKG, "package.json"), join(pkg, "package.json"));
  execFileSync(process.execPath, [join(PKG, "node_modules/typescript/bin/tsc"), "-p", join(PKG, "tsconfig.build.json"), "--outDir", join(pkg, "dist")], { cwd: PKG });
  const outfile = join(dir, "app-dist.mjs");
  const result = await build({
    stdin: { contents: APP, resolveDir: dir, loader: "ts", sourcefile: "app.ts" },
    bundle: true, platform: "node", format: "esm", outfile, logLevel: "silent", write: true,
  });
  assert.deepEqual(result.warnings.map((w) => w.text), []);
  const out = JSON.parse(execFileSync(process.execPath, [outfile], { encoding: "utf8" }));
  assert.deepEqual(out, EXPECTED);
});

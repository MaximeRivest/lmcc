/**
 * The template language (kernel §2): compile and render. Four constructs:
 *
 * - slots: `{instruction}`, `{format}`, `{field_name}`, `{f.attr}` in loops
 * - loops: `{% for f in inputs %} … {% endfor %}` (also `outputs`); any
 *   other source is a turn slot (§3a) with `m.role`, `m.kind`, `m.text`
 * - guards: `{% if name %} … {% else %} … {% endif %}`
 * - escapes: `{{` renders `{`, `}}` renders `}`
 *
 * A bare brace outside these is `template-syntax`: strictness is what keeps
 * templates analyzable.
 */

import { refuse } from "./errors.ts";
import type { Field, Part } from "./core.ts";
import { pyRepr } from "./text.ts";

// ASCII-explicit on purpose: the template grammar is one grammar everywhere.
const S = "[ \\t\\n\\r\\f\\v]";
const ID = "[A-Za-z_][A-Za-z0-9_]*";
const TOKEN = new RegExp(
  "(?<esc>\\{\\{|\\}\\})"
  + `|(?<loop>\\{%${S}*for${S}+(?<lvar>${ID})${S}+in${S}+(?<lsrc>${ID})${S}*%\\})`
  + `|(?<endfor>\\{%${S}*endfor${S}*%\\})`
  + `|(?<guard>\\{%${S}*if${S}+(?<gname>${ID})${S}*%\\})`
  + `|(?<orelse>\\{%${S}*else${S}*%\\})`
  + `|(?<endif>\\{%${S}*endif${S}*%\\})`
  + "|(?<slot>\\{(?<path>[A-Za-z_][A-Za-z0-9_.]*)\\})",
  "g",
);

export const LOOP_SOURCES = ["inputs", "outputs"];
export const LOOP_ATTRS = ["name", "desc", "type", "schema", "purpose", "value"];
export const TURN_ATTRS = ["role", "kind", "text"];
export const RESERVED_SLOTS = ["inputs", "outputs", "instruction", "format"];

export interface TextNode { readonly kind: "text"; readonly text: string }
export interface SlotNode { readonly kind: "slot"; readonly path: string }
export interface LoopNode { readonly kind: "loop"; readonly var: string; readonly source: string; readonly body: Node[] }
export interface GuardNode { readonly kind: "guard"; readonly slot: string; readonly body: Node[]; orelse: Node[]; hasElse: boolean }
export type Node = TextNode | SlotNode | LoopNode | GuardNode;

export function overTurns(loop: LoopNode): boolean {
  return !LOOP_SOURCES.includes(loop.source);
}

export function branches(guard: GuardNode): Node[] {
  return [...guard.body, ...guard.orelse];
}

function syntax(where: string, hint: string): never {
  refuse("template-syntax", `${where}: ${hint}`, { fix: { action: "edit-template", path: where } });
}

function checkLiteral(literal: string, where: string): void {
  for (const ch of ["{", "}"]) {
    if (literal.includes(ch)) syntax(where, `bare ${pyRepr(ch)} — use ${pyRepr(ch + ch)} to render a literal brace`);
  }
}

/** Compile template text to nodes, refusing loudly on any bad syntax. */
export function compileTemplate(text: string, where = "template"): Node[] {
  const root: Node[] = [];
  const stack: [LoopNode | GuardNode, Node[]][] = [];
  let current = root;
  let pos = 0;
  const inTurnLoop = () => stack.some(([n]) => n.kind === "loop" && overTurns(n));
  for (const m of text.matchAll(TOKEN)) {
    const g = m.groups!;
    const literal = text.slice(pos, m.index);
    checkLiteral(literal, where);
    if (literal) current.push({ kind: "text", text: literal });
    if (g.esc) {
      current.push({ kind: "text", text: g.esc[0] });
    } else if (g.loop) {
      const source = g.lsrc;
      if (source === "instruction" || source === "format") {
        syntax(where, `${pyRepr(source)} is reserved; a loop runs over inputs, outputs, or a turn slot`);
      }
      if (inTurnLoop()) syntax(where, "a turn loop's body holds text and m.role/m.kind/m.text only; no nested loop");
      const loop: LoopNode = { kind: "loop", var: g.lvar, source, body: [] };
      current.push(loop);
      stack.push([loop, current]);
      current = loop.body;
    } else if (g.guard) {
      const name = g.gname;
      if (RESERVED_SLOTS.includes(name)) syntax(where, `a guard names a turn slot, not ${pyRepr(name)}`);
      if (inTurnLoop()) syntax(where, "no guard inside a turn loop");
      const guard: GuardNode = { kind: "guard", slot: name, body: [], orelse: [], hasElse: false };
      current.push(guard);
      stack.push([guard, current]);
      current = guard.body;
    } else if (g.orelse) {
      const top = stack[stack.length - 1]?.[0];
      if (!top || top.kind !== "guard" || top.hasElse) syntax(where, "{% else %} outside an {% if %}, or twice");
      top.hasElse = true;
      current = top.orelse;
    } else if (g.endfor || g.endif) {
      const want = g.endfor ? "loop" : "guard";
      const word = g.endfor ? "endfor" : "endif";
      const top = stack[stack.length - 1]?.[0];
      if (!top || top.kind !== want) syntax(where, `{% ${word} %} without an open ${want}`);
      current = stack.pop()![1];
    } else {
      current.push({ kind: "slot", path: g.path });
    }
    pos = m.index + m[0].length;
  }
  const tail = text.slice(pos);
  checkLiteral(tail, where);
  if (tail) current.push({ kind: "text", text: tail });
  if (stack.length) {
    const what = stack[stack.length - 1][0].kind === "loop" ? "{% for %} loop" : "{% if %} guard";
    syntax(where, `unclosed ${what}`);
  }
  checkTurnLoops(root, where);
  return root;
}

function checkTurnLoops(nodes: Node[], where: string): void {
  for (const node of nodes) {
    if (node.kind === "loop" && overTurns(node)) {
      for (const n of node.body) {
        if (n.kind !== "slot") continue;
        const dot = n.path.indexOf(".");
        const v = dot < 0 ? n.path : n.path.slice(0, dot);
        const attr = dot < 0 ? "" : n.path.slice(dot + 1);
        if (v !== node.var || !TURN_ATTRS.includes(attr)) {
          syntax(where, `in a loop over turn slot ${pyRepr(node.source)} only {${node.var}.role}, {${node.var}.kind} and {${node.var}.text} exist; got {${n.path}}`);
        }
      }
    } else if (node.kind === "loop") {
      checkTurnLoops(node.body, where);
    } else if (node.kind === "guard") {
      checkTurnLoops(branches(node), where);
    }
  }
}

/** `[slots placed as text by turn loops, slots named by guards]`, in order. */
export function turnSlots(nodes: Node[]): [string[], string[]] {
  const placed: string[] = [];
  const guarded: string[] = [];
  for (const node of nodes) {
    if (node.kind === "loop" && overTurns(node)) {
      placed.push(node.source);
    } else if (node.kind === "guard") {
      guarded.push(node.slot);
      const [p, g] = turnSlots(branches(node));
      placed.push(...p);
      guarded.push(...g);
    } else if (node.kind === "loop") {
      const [p, g] = turnSlots(node.body);
      placed.push(...p);
      guarded.push(...g);
    }
  }
  return [placed, guarded];
}

/** Check every slot resolves against the signature; returns the inputs covered. */
export function validateNodes(nodes: Node[], opts: {
  knownFields: Set<string>; inputFields: Set<string>; where: string; inLoopVar?: string | null; slots?: Set<string>;
}): Set<string> {
  const { knownFields, inputFields, where } = opts;
  const slots = opts.slots ?? new Set<string>();
  const inLoopVar = opts.inLoopVar ?? null;
  const covered = new Set<string>();
  for (const node of nodes) {
    if (node.kind === "slot") {
      const path = node.path;
      if (inLoopVar && path.startsWith(inLoopVar + ".")) {
        const attr = path.slice(inLoopVar.length + 1);
        if (!LOOP_ATTRS.includes(attr)) {
          refuse("unknown-slot", `${where}: {${path}} — loop attributes are ${pyRepr(LOOP_ATTRS)}`,
            { fix: { action: "edit-template", path: where, slot: path } });
        }
        continue;
      }
      if (path === "instruction" || path === "format") continue;
      if (path.includes(".")) {
        refuse("unknown-slot", `${where}: {${path}} — dotted slots are only valid inside their loop`,
          { fix: { action: "edit-template", path: where, slot: path } });
      }
      if (inputFields.has(path)) {
        covered.add(path);
        continue;
      }
      if (knownFields.has(path)) continue; // an output slot renders its placeholder (§2)
      refuse("unknown-slot", `${where}: {${path}} names no field in the signature`,
        { fix: { action: "edit-template", path: where, slot: path } });
    } else if (node.kind === "loop" && overTurns(node)) {
      continue;
    } else if (node.kind === "guard") {
      if (!slots.has(node.slot) && !inputFields.has(node.slot)) {
        refuse("unknown-slot", `${where}: {% if ${node.slot} %} names neither a turn slot this template places nor an input field`,
          { fix: { action: "edit-template", path: where, slot: node.slot } });
      }
      if (inputFields.has(node.slot)) covered.add(node.slot);
      for (const c of validateNodes(branches(node), { ...opts, slots, inLoopVar })) covered.add(c);
    } else if (node.kind === "loop") {
      for (const c of validateNodes(node.body, { ...opts, slots, inLoopVar: node.var })) covered.add(c);
      if (node.source === "inputs") for (const c of inputFields) covered.add(c);
    }
  }
  return covered;
}

/** What a template sees of the plan during one render. */
export interface RenderEnv {
  readonly instruction: string;
  readonly replyFormat: string;
  loopFields(source: string): Field[];
  valueOf(field: Field): ["text", string] | ["parts", Part[]];
  schemaOf(field: Field): string;
  fieldNamed(name: string): Field;
  turnMessages(slot: string): [string, string, string][];
  guard(name: string): boolean | null;
}

/** Render nodes into message parts; text accumulates in `buf`. */
export function renderNodes(nodes: Node[], env: RenderEnv, out: Part[], buf: string[], loopCtx: Record<string, Field> | null = null): void {
  for (const node of nodes) {
    if (node.kind === "text") {
      buf.push(node.text);
    } else if (node.kind === "slot") {
      renderSlot(node, env, out, buf, loopCtx);
    } else if (node.kind === "guard") {
      const state = env.guard(node.slot);
      if (state !== null) renderNodes(state ? node.body : node.orelse, env, out, buf, loopCtx);
    } else if (overTurns(node)) {
      for (const [role, kind, text] of env.turnMessages(node.source)) {
        const attrs: Record<string, string> = { role, kind, text };
        for (const n of node.body) {
          buf.push(n.kind === "text" ? n.text : attrs[(n as SlotNode).path.slice((n as SlotNode).path.indexOf(".") + 1)]);
        }
      }
    } else {
      for (const f of env.loopFields(node.source)) {
        renderNodes(node.body, env, out, buf, { ...(loopCtx ?? {}), [node.var]: f });
      }
    }
  }
}

function renderSlot(node: SlotNode, env: RenderEnv, out: Part[], buf: string[], loopCtx: Record<string, Field> | null): void {
  const path = node.path;
  if (loopCtx) {
    const dot = path.indexOf(".");
    const v = dot < 0 ? path : path.slice(0, dot);
    const attr = dot < 0 ? "" : path.slice(dot + 1);
    if (attr && Object.prototype.hasOwnProperty.call(loopCtx, v)) {
      const f = loopCtx[v];
      if (attr === "name") buf.push(f.name);
      else if (attr === "desc") buf.push(f.desc ?? "");
      else if (attr === "purpose") buf.push(f.purpose);
      else if (attr === "type") buf.push(f.type ?? "");
      else if (attr === "schema") buf.push(env.schemaOf(f));
      else if (attr === "value") emitValue(env.valueOf(f), out, buf);
      return;
    }
  }
  if (path === "instruction") {
    buf.push(env.instruction);
    return;
  }
  if (path === "format") {
    buf.push(env.replyFormat);
    return;
  }
  emitValue(env.valueOf(env.fieldNamed(path)), out, buf);
}

function emitValue(rendered: ["text", string] | ["parts", Part[]], out: Part[], buf: string[]): void {
  if (rendered[0] === "text") {
    buf.push(rendered[1]);
    return;
  }
  for (const part of rendered[1]) {
    if (part.type === "text") {
      buf.push((part["text"] as string | undefined) ?? "");
      continue;
    }
    if (buf.length) {
      out.push({ type: "text", text: buf.join("") });
      buf.length = 0;
    }
    out.push(part);
  }
}

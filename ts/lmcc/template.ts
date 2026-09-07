// Kernel §2: the template — three constructs (slot, loop, escape).

import { refuse } from "./refusal.ts";

export type Node =
  | { kind: "text"; text: string }
  | { kind: "slot"; name: string }
  | { kind: "attr"; variable: string; attr: string }
  | { kind: "loop"; variable: string; source: "inputs" | "outputs"; body: Node[] };

export type TemplateItem =
  | { kind: "message"; role: "system" | "user" | "assistant"; text: string; nodes: Node[]; index: number }
  | { kind: "directive"; directive: "demos" | "history"; index: number };

export const LOOP_ATTRS: ReadonlySet<string> = new Set(["name", "desc", "type", "schema", "role", "value"]);
export const RESERVED_SLOTS: ReadonlySet<string> = new Set(["instruction", "format"]);

const SLOT_NAME = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$/;

/** Parse one message text into nodes; refuses `template-syntax` at `path`. */
export function parseTemplateText(text: string, path: string): Node[] {
  const bad = (hint: string): never => refuse("template-syntax", `${path}: ${hint}`, { fix: { action: "edit-template", path }, stage: "load" });
  const root: Node[] = [];
  const stack: { variable: string; source: "inputs" | "outputs"; body: Node[] }[] = [];
  const current = (): Node[] => (stack.length ? stack[stack.length - 1].body : root);
  const pushText = (t: string): void => {
    if (t === "") return;
    const nodes = current();
    const last = nodes[nodes.length - 1];
    if (last && last.kind === "text") last.text += t;
    else nodes.push({ kind: "text", text: t });
  };
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === "{") {
      if (text[i + 1] === "{") {
        pushText("{");
        i += 2;
        continue;
      }
      if (text[i + 1] === "%") {
        const end = text.indexOf("%}", i + 2);
        if (end < 0) return bad("unclosed {% tag");
        const tag = text.slice(i + 2, end).trim();
        i = end + 2;
        const m = /^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z_][A-Za-z0-9_]*)$/.exec(tag);
        if (m) {
          if (m[2] !== "inputs" && m[2] !== "outputs") return bad(`unknown loop source ${JSON.stringify(m[2])}`);
          const loop = { variable: m[1], source: m[2] as "inputs" | "outputs", body: [] as Node[] };
          stack.push(loop);
          continue;
        }
        if (tag === "endfor") {
          const loop = stack.pop();
          if (!loop) return bad("{% endfor %} without a loop");
          current().push({ kind: "loop", variable: loop.variable, source: loop.source, body: loop.body });
          continue;
        }
        return bad(`unknown tag {% ${tag} %}`);
      }
      const end = text.indexOf("}", i + 1);
      if (end < 0) return bad("bare '{' (unclosed slot); write '{{' for a literal brace");
      const name = text.slice(i + 1, end);
      if (!SLOT_NAME.test(name)) return bad(`bad slot name ${JSON.stringify(name)}; write '{{' for a literal brace`);
      i = end + 1;
      const dot = name.indexOf(".");
      if (dot >= 0) current().push({ kind: "attr", variable: name.slice(0, dot), attr: name.slice(dot + 1) });
      else current().push({ kind: "slot", name });
      continue;
    }
    if (c === "}") {
      if (text[i + 1] === "}") {
        pushText("}");
        i += 2;
        continue;
      }
      return bad("bare '}'; write '}}' for a literal brace");
    }
    let j = i;
    while (j < text.length && text[j] !== "{" && text[j] !== "}") j++;
    pushText(text.slice(i, j));
    i = j;
  }
  if (stack.length) return bad("unclosed {% for %} loop");
  return root;
}

/** Walk nodes (depth first) with the enclosing loop, if any. */
export function walk(nodes: Node[], visit: (node: Node, loop: Node | null) => void, loop: Node | null = null): void {
  for (const n of nodes) {
    visit(n, loop);
    if (n.kind === "loop") walk(n.body, visit, n);
  }
}

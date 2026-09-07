// Kernel §6 routings: batch scans, and the stable projections streaming
// uses (§8). Every stable projection returns a prefix of what the batch
// scan returns on any extension of its input.

export interface Scan {
  /** the captured texts, in text order */
  captures: string[];
  /** the text left for the next routing and the lens */
  remaining: string;
}

/** `between`: a plain scan; open, then the first close after it. */
export function scanBetween(text: string, open: string, close: string, consume: boolean): Scan {
  const captures: string[] = [];
  let remaining = "";
  let p = 0;
  for (;;) {
    const o = text.indexOf(open, p);
    if (o < 0) break;
    const c = text.indexOf(close, o + open.length);
    if (c < 0) break;
    captures.push(text.slice(o + open.length, c));
    remaining += text.slice(p, o);
    p = c + close.length;
  }
  remaining += text.slice(p);
  return { captures, remaining: consume ? remaining : text };
}

/** Longest proper suffix of `text` that is a prefix of `marker`; its start, or text.length when none. */
export function partialMarkerStart(text: string, marker: string): number {
  if (marker.length === 0) return text.length;
  const maxLen = Math.min(marker.length - 1, text.length);
  for (let len = maxLen; len >= 1; len--) {
    if (text.endsWith(marker.slice(0, len))) return text.length - len;
  }
  return text.length;
}

/** Stable projection of `scanBetween` over a growing text. */
export function stableBetween(text: string, open: string, close: string, consume: boolean): Scan {
  const captures: string[] = [];
  let remaining = "";
  let p = 0;
  for (;;) {
    const o = text.indexOf(open, p);
    if (o < 0) {
      // the tail may begin an open marker: hold it
      const cut = consume ? Math.max(p, partialMarkerStart(text, open)) : text.length;
      remaining += text.slice(p, cut);
      break;
    }
    const c = text.indexOf(close, o + open.length);
    if (c < 0) {
      remaining += text.slice(p, o);
      break;
    }
    captures.push(text.slice(o + open.length, c));
    remaining += text.slice(p, o);
    p = c + close.length;
  }
  return { captures, remaining: consume ? remaining : text };
}

/** `line_prefixed`: lines split on "\n"; matching lines are captured (and removed when consuming). */
export function scanLinePrefixed(text: string, prefix: string, consume: boolean): Scan {
  const captures: string[] = [];
  const kept: string[] = [];
  for (const line of text.split("\n")) {
    if (line.startsWith(prefix)) captures.push(line.slice(prefix.length));
    else kept.push(line);
  }
  return { captures, remaining: consume ? kept.join("\n") : text };
}

/** Stable projection of `scanLinePrefixed`: the last line is held while it can still match. */
export function stableLinePrefixed(text: string, prefix: string, consume: boolean): Scan {
  const lines = text.split("\n");
  const last = lines.pop() as string;
  const captures: string[] = [];
  const kept: string[] = [];
  for (const line of lines) {
    if (line.startsWith(prefix)) captures.push(line.slice(prefix.length));
    else kept.push(line);
  }
  const held = last.startsWith(prefix) || prefix.startsWith(last);
  if (!held) kept.push(last);
  return { captures, remaining: consume ? kept.join("\n") : text };
}

/** `pattern`: RE2 subset, group 1 (whole match without a group), empty captures discarded. */
export function scanPattern(text: string, re: RegExp, consume: boolean): Scan {
  const captures: string[] = [];
  let remaining = "";
  let p = 0;
  re.lastIndex = 0;
  for (;;) {
    const m = re.exec(text);
    if (!m) break;
    if (m[0].length === 0) {
      re.lastIndex += 1;
      continue;
    }
    const cap = m.length > 1 ? (m[1] ?? "") : m[0];
    if (cap.length === 0) continue;
    captures.push(cap);
    remaining += text.slice(p, m.index);
    p = m.index + m[0].length;
  }
  remaining += text.slice(p);
  return { captures, remaining: consume ? remaining : text };
}

/**
 * The JSON Lines protocol's reader: stdin split at "\n" only. node:readline
 * also ends a line at "\r", U+2028 and U+2029; JSON escapes "\r" but carries
 * U+2028 and U+2029 raw, so a case holding either would reach the kernel cut
 * in two.
 */
export function onLines(handle: (line: string) => void): void {
  let pending = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk: string) => {
    pending += chunk;
    let end: number;
    while ((end = pending.indexOf("\n")) >= 0) {
      const line = pending.slice(0, end);
      pending = pending.slice(end + 1);
      handle(line);
    }
  });
  process.stdin.on("end", () => {
    if (pending) handle(pending);
  });
}

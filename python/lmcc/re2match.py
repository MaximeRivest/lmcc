"""Ordered Thompson matching for the RE2 scalar-text syntax tree.

First arrival at an instruction wins. This preserves leftmost-first capture
priority, including nullable repetitions, without host backtracking behavior.
"""
from dataclasses import dataclass


@dataclass
class _Instruction:
    kind: str
    value: object = None
    next: int = -1
    other: int = -1


class Match:
    def __init__(self, text, captures):
        self.text, self.captures = text, captures

    def start(self):
        return self.captures[0]

    def end(self):
        return self.captures[1]

    def group(self, number=0):
        lo, hi = self.captures[2 * number:2 * number + 2]
        return self.text[lo:hi] if lo >= 0 and hi >= 0 else None


def _word(text, pos):
    return 0 <= pos < len(text) and ("A" <= text[pos] <= "Z" or
        "a" <= text[pos] <= "z" or "0" <= text[pos] <= "9" or text[pos] == "_")


def _assertion(kind, text, pos):
    if kind == "begin":
        return pos == 0
    if kind == "end":
        return pos == len(text)
    if kind == "begin_line":
        return pos == 0 or text[pos - 1] == "\n"
    if kind == "end_line":
        return pos == len(text) or text[pos] == "\n"
    boundary = _word(text, pos - 1) != _word(text, pos)
    return boundary if kind == "word" else not boundary


class Pattern:
    def __init__(self, tree, groups):
        self.groups = groups
        self.code = []
        end = self.emit("match")
        self.start = self.build(tree, end)

    def emit(self, kind, value=None, next=-1, other=-1):
        self.code.append(_Instruction(kind, value, next, other))
        return len(self.code) - 1

    def build(self, node, end):
        kind = node[0]
        if kind == "empty":
            return end
        if kind in ("char", "set", "assert"):
            return self.emit(kind, node[1], end)
        if kind == "seq":
            for child in reversed(node[1]):
                end = self.build(child, end)
            return end
        if kind == "alt":
            branches = node[1]
            start = self.build(branches[-1], end)
            for branch in reversed(branches[:-1]):
                start = self.emit("split", next=self.build(branch, end), other=start)
            return start
        if kind == "capture":
            close = self.emit("save", node[1] * 2 + 1, end)
            return self.emit("save", node[1] * 2, self.build(node[2], close))
        _, child, low, high, greedy = node
        if high is None:
            loop = self.emit("split")
            body = self.build(child, loop)
            self.code[loop].next, self.code[loop].other = (body, end) if greedy else (end, body)
            # A nullable star is a nullable plus with an optional entry.
            # Separate the entry from the loop so empty captures keep priority.
            if low == 0:
                if nullable(child):
                    end = self.emit("split", next=body if greedy else end,
                                    other=end if greedy else body)
                else:
                    end = loop
            else:
                end = body
                low -= 1
        else:
            for _ in range(high - low):
                body = self.build(child, end)
                end = self.emit("split", next=body if greedy else end,
                                other=end if greedy else body)
        for _ in range(low):
            end = self.build(child, end)
        return end

    def closure(self, pc, captures, text, pos, queue, seen):
        stack = [(pc, captures)]
        while stack:
            pc, captures = stack.pop()
            if pc in seen:
                continue
            seen.add(pc)
            op = self.code[pc]
            if op.kind == "split":
                stack.append((op.other, captures))
                stack.append((op.next, captures))
            elif op.kind == "save":
                updated = list(captures)
                updated[op.value] = pos
                stack.append((op.next, updated))
            elif op.kind == "assert":
                if _assertion(op.value, text, pos):
                    stack.append((op.next, captures))
            else:
                queue.append((pc, captures))

    def search(self, text, start=0):
        queue, seen, best = [], set(), None
        for pos in range(start, len(text) + 1):
            if best is None:
                captures = [-1] * (2 * (self.groups + 1))
                captures[0] = pos
                self.closure(self.start, captures, text, pos, queue, seen)
            following, next_seen = [], set()
            char = ord(text[pos]) if pos < len(text) else None
            for pc, captures in queue:
                op = self.code[pc]
                if op.kind == "match":
                    best = list(captures)
                    best[1] = pos
                    break  # Lower-priority threads cannot supersede this match.
                if char is not None and ((op.kind == "char" and op.value == char) or
                        (op.kind == "set" and (op.value >> char) & 1)):
                    self.closure(op.next, captures, text, pos + 1, following, next_seen)
            if best is not None and not following:
                return Match(text, best)
            queue, seen = following, next_seen
        return Match(text, best) if best is not None else None


def nullable(node):
    kind = node[0]
    if kind in ("empty", "assert"):
        return True
    if kind == "seq":
        return all(nullable(child) for child in node[1])
    if kind == "alt":
        return any(nullable(child) for child in node[1])
    if kind == "capture":
        return nullable(node[2])
    if kind == "repeat":
        return node[2] == 0 or nullable(node[1])
    return False

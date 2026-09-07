"""Translate RE2 scalar-text syntax into ordered matching instructions (§7a).

Never lint substrings inside quoted text, classes, or property names.
Generated Unicode data supplies categories, scripts, and simple folding.
Host regex syntax only scans the small flag/count grammars; it never decides
response matching or capture priority (including nullable repetitions).
"""
from __future__ import annotations

import functools
import re

from ._re2_unicode import FOLDS, TABLES
from .re2match import Pattern

_MAX = 0x10FFFF
_ALL = (1 << (_MAX + 1)) - 1
_I, _M, _S, _U = 1, 2, 4, 8
_FLAGS = dict(i=_I, m=_M, s=_S, U=_U)


def _range(lo: int, hi: int) -> int:
    return ((1 << (hi - lo + 1)) - 1) << lo


_POSIX = {
    "alnum": "0-9A-Za-z", "alpha": "A-Za-z", "ascii": "\x00-\x7f",
    "blank": "\t ", "cntrl": "\x00-\x1f\x7f", "digit": "0-9",
    "graph": "!-~", "lower": "a-z", "print": " -~",
    "punct": "!-/:-@[-`{-~", "space": "\t-\r ", "upper": "A-Z",
    "word": "0-9A-Za-z_", "xdigit": "0-9A-Fa-f",
}


def _ascii_set(spelling: str) -> int:
    bits, i = 0, 0
    while i < len(spelling):
        if i + 2 < len(spelling) and spelling[i + 1] == "-":
            bits |= _range(ord(spelling[i]), ord(spelling[i + 2]))
            i += 3
        else:
            bits |= 1 << ord(spelling[i])
            i += 1
    return bits


_POSIX = {name: _ascii_set(value) for name, value in _POSIX.items()}
_PERL = {"w": _POSIX["word"], "d": _POSIX["digit"], "s": _ascii_set("\t\n\f\r ")}
_FOLD_NEXT = dict(FOLDS)
_FOLD_CYCLES = []
_seen = set()
for _r in _FOLD_NEXT:
    if _r not in _seen:
        _cycle, _c = 0, _r
        while _c not in _seen:
            _seen.add(_c)
            _cycle |= 1 << _c
            _c = _FOLD_NEXT[_c]
        _FOLD_CYCLES.append(_cycle)
del _seen, _FOLD_NEXT, _r, _c, _cycle


@functools.lru_cache(maxsize=256)
def _fold(bits: int) -> int:
    for cycle in _FOLD_CYCLES:
        if bits & cycle:
            bits |= cycle
    return bits


@functools.lru_cache(maxsize=256)
def _property(name: str) -> int:
    if name == "Any":
        return _ALL
    if name not in TABLES:
        raise ValueError(f"unknown RE2 Unicode property {name!r}")
    bits = 0
    for lo, hi, stride in TABLES[name]:
        if stride == 1:
            bits |= _range(lo, hi)
        else:
            for value in range(lo, hi + 1, stride):
                bits |= 1 << value
    return bits


class _Parser:
    def __init__(self, pattern: str):
        self.text = pattern
        self.pos = 0
        self.groups = 0

    def fail(self, message: str):
        raise ValueError(f"{message} at pattern offset {self.pos}")

    def literal(self, char: str, flags: int) -> tuple:
        return ("set", _fold(1 << ord(char))) if flags & _I else ("char", ord(char))

    def charset(self, bits: int, flags: int, negative=False) -> int:
        if flags & _I:
            bits = _fold(bits)
        return _ALL ^ bits if negative else bits

    def escape(self, flags: int, in_class=False) -> tuple[str | None, int | None]:
        """Return a scalar literal or a complete set; assertions are handled by sequence."""
        self.pos += 1  # backslash
        if self.pos == len(self.text):
            self.fail("trailing backslash")
        c = self.text[self.pos]
        self.pos += 1
        if c.lower() in _PERL:
            return None, self.charset(_PERL[c.lower()], flags, c.isupper())
        if c in "pP":
            if self.pos < len(self.text) and self.text[self.pos] == "{":
                end = self.text.find("}", self.pos + 1)
                if end < 0:
                    self.fail("unclosed Unicode property")
                name = self.text[self.pos + 1:end]
                self.pos = end + 1
            elif self.pos < len(self.text):
                name = self.text[self.pos]
                self.pos += 1
            else:
                self.fail("missing Unicode property")
            negative = c == "P"
            if name.startswith("^"):
                negative = not negative
                name = name[1:]
            return None, self.charset(_property(name), flags, negative)
        if c in "afnrtv":
            return dict(a="\a", f="\f", n="\n", r="\r", t="\t", v="\v")[c], None
        if c == "x":
            if self.pos < len(self.text) and self.text[self.pos] == "{":
                end = self.text.find("}", self.pos + 1)
                digits = self.text[self.pos + 1:end] if end >= 0 else ""
                self.pos = end + 1 if end >= 0 else self.pos
            else:
                digits = self.text[self.pos:self.pos + 2]
                self.pos += len(digits)
                if len(digits) != 2:
                    self.fail("hex escape needs two digits")
            if not re.fullmatch("[0-9a-fA-F]+", digits) or int(digits, 16) > _MAX:
                self.fail("invalid hex escape")
            return chr(int(digits, 16)), None
        if c in "01234567":
            digits = c
            while len(digits) < 3 and self.pos < len(self.text) and self.text[self.pos] in "01234567":
                digits += self.text[self.pos]
                self.pos += 1
            if len(digits) == 1 and c != "0":
                self.fail("backreferences are outside RE2")
            return chr(int(digits, 8)), None
        if ord(c) < 128 and not c.isalnum():
            return c, None
        self.fail(f"invalid RE2 escape \\{c}")

    def class_item(self, flags: int) -> tuple[str | None, int | None]:
        if self.text.startswith("[:", self.pos):
            end = self.text.find(":]", self.pos + 2)
            if end < 0:
                self.fail("unclosed POSIX class")
            name = self.text[self.pos + 2:end]
            self.pos = end + 2
            negative = name.startswith("^")
            name = name[1:] if negative else name
            if name not in _POSIX:
                self.fail("unknown POSIX class")
            return None, self.charset(_POSIX[name], flags, negative)
        if self.text[self.pos] == "\\":
            return self.escape(flags, in_class=True)
        c = self.text[self.pos]
        self.pos += 1
        return c, None

    def char_class(self, flags: int) -> tuple:
        self.pos += 1
        negative = self.pos < len(self.text) and self.text[self.pos] == "^"
        self.pos += int(negative)
        first, bits = True, 0
        while self.pos < len(self.text):
            if self.text[self.pos] == "]" and not first:
                self.pos += 1
                return ("set", _ALL ^ bits if negative else bits)
            char, item = self.class_item(flags)
            first = False
            if char is not None:
                item = 1 << ord(char)
                if self.pos + 1 < len(self.text) and self.text[self.pos] == "-" and self.text[self.pos + 1] != "]":
                    self.pos += 1
                    end, _ = self.class_item(flags)
                    if end is None or ord(end) < ord(char):
                        self.fail("invalid character range")
                    item = _range(ord(char), ord(end))
                item = self.charset(item, flags)
            bits |= item
        self.fail("unclosed character class")

    def sequence(self, flags: int, grouped=False) -> tuple[tuple, int]:
        out, branches = [], []
        repeatable = False
        max_repeat, atom_repeat = 1, 1
        while self.pos < len(self.text):
            c = self.text[self.pos]
            if c == ")":
                if not grouped:
                    self.fail("unexpected closing parenthesis")
                self.pos += 1
                return _expression(branches, out), max_repeat
            if c == "|":
                branches.append(("seq", tuple(out)))
                out = []
                self.pos += 1
                repeatable = False
                continue
            # Only a syntactically complete counted repetition is an operator.
            count = re.match(r"\{([0-9]+)(?:,([0-9]*))?\}", self.text[self.pos:]) if c == "{" else None
            if count and ((len(count[1]) > 1 and count[1][0] == "0") or
                    (count[2] and len(count[2]) > 1 and count[2][0] == "0")):
                count = None  # Leading-zero braces are literal text in RE2.
            if c in "*+?" or count:
                if not repeatable:
                    self.fail("invalid or repeated quantifier")
                if count:
                    low = int(count[1])
                    high = int(count[2]) if count[2] else (low if count[2] is None else None)
                    limit = max(low, high or 0)
                    if limit > 1000 or (high is not None and high < low) or atom_repeat * limit > 1000:
                        self.fail("invalid RE2 repetition count")
                    atom_repeat *= max(limit, 1)
                    max_repeat = max(max_repeat, atom_repeat)
                else:
                    low, high = {"*": (0, None), "+": (1, None), "?": (0, 1)}[c]
                self.pos += len(count[0]) if count else 1
                greedy = not bool(flags & _U)
                if self.pos < len(self.text) and self.text[self.pos] == "?":
                    greedy = not greedy
                    self.pos += 1
                out[-1] = ("repeat", out[-1], low, high, greedy)
                repeatable = False
                continue
            atom_repeat = 1
            if c == "(":
                self.pos += 1
                capture = True
                inner_flags = flags
                if self.text.startswith("?:", self.pos):
                    capture = False
                    self.pos += 2
                elif self.text.startswith("?", self.pos):
                    match = re.match(r"\?([imsU]*)(?:-([imsU]+))?([:)])", self.text[self.pos:])
                    if not match or not (match[1] or match[2]):
                        self.fail("unsupported RE2 group (including named groups)")
                    for flag in match[1]:
                        inner_flags |= _FLAGS[flag]
                    for flag in match[2] or "":
                        inner_flags &= ~_FLAGS[flag]
                    self.pos += len(match[0])
                    if match[3] == ")":
                        flags = inner_flags
                        continue
                    capture = False
                if capture:
                    self.groups += 1
                group = self.groups
                inner, atom_repeat = self.sequence(inner_flags, grouped=True)
                out.append(("capture", group, inner) if capture else inner)
            elif c == "[":
                out.append(self.char_class(flags))
            elif c == "\\" and self.pos + 1 < len(self.text) and self.text[self.pos + 1] in "QAbBz":
                escape = self.text[self.pos + 1]
                self.pos += 2
                if escape == "Q":
                    end = self.text.find(r"\E", self.pos)
                    quoted = self.text[self.pos:end] if end >= 0 else self.text[self.pos:]
                    self.pos = end + 2 if end >= 0 else len(self.text)
                    out.extend(self.literal(char, flags) for char in quoted)
                    if not quoted:
                        continue
                else:
                    out.append(("assert", {"A": "begin", "z": "end", "b": "word", "B": "not_word"}[escape]))
            elif c == "\\":
                char, bits = self.escape(flags)
                out.append(self.literal(char, flags) if char is not None else ("set", bits))
            else:
                self.pos += 1
                if c == ".":
                    out.append(("set", _ALL if flags & _S else _ALL ^ (1 << 10)))
                elif c == "^":
                    out.append(("assert", "begin_line" if flags & _M else "begin"))
                elif c == "$":
                    out.append(("assert", "end_line" if flags & _M else "end"))
                else:
                    out.append(self.literal(c, flags))
            repeatable = True
            max_repeat = max(max_repeat, atom_repeat)
        if grouped:
            self.fail("unclosed group")
        return _expression(branches, out), max_repeat


def _expression(branches, out):
    last = ("seq", tuple(out))
    return ("alt", (*branches, last)) if branches else last


@functools.lru_cache(maxsize=256)
def compile(pattern: str) -> Pattern:
    parser = _Parser(pattern)
    tree, _ = parser.sequence(_S)
    return Pattern(tree, parser.groups)


def finditer(pattern: Pattern, text: str):
    """RE2's non-overlapping scan, without host retry after an empty match."""
    pos = 0
    while pos <= len(text):
        match = pattern.search(text, pos)
        if match is None:
            return
        if match.end() == match.start():
            pos = match.end() + 1
        else:
            yield match
            pos = match.end()

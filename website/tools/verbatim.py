#!/usr/bin/env python3
"""Keep the prototype's code blocks verbatim.

Every ``<pre data-src="FILE#N">`` in ``website/prototype/*.html`` must
contain exactly the N-th fenced code block of FILE (README.md or
GUIDE.md at the repository root), HTML-escaped.

``<pre data-src="run:README.md#1-3:i">`` blocks are rendered output:
the script executes README code blocks 1..3 with the reference kernel
and compares the figure's text with ``request.messages[i]``'s text.

Usage:
  tools/verbatim.py extract README.md 3   # print block 3, escaped
  tools/verbatim.py fill                  # rewrite every block from source
  tools/verbatim.py check                 # verify every block; exit 1 on drift
"""
import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROTO = ROOT / "website" / "prototype"

FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
PRE = re.compile(r'<pre[^>]*data-src="([^"]+)"[^>]*>(?:<code[^>]*>)?(.*?)(?:</code>)?</pre>', re.DOTALL)


def blocks(name):
    text = (ROOT / name).read_text()
    return [b for _lang, b in FENCE.findall(text)]


def extract(name, index):
    return html.escape(blocks(name)[index], quote=False)


def rendered_messages():
    code = "\n".join(blocks("README.md")[1:4])
    ns = {}
    sys.path.insert(0, str(ROOT / "python"))
    exec(compile(code, "README-1-3", "exec"), ns)
    return ns["request"].messages


def wanted(src):
    if src.startswith("run:"):
        i = int(src.rsplit(":", 1)[1])
        return rendered_messages()[i]["content"][0]["text"]
    name, idx = src.split("#")
    return blocks(name)[int(idx)]


def fill():
    for page in sorted(PROTO.glob("*.html")):
        text = page.read_text()

        def sub(m):
            open_tag, inner = m.group(1), m.group(2)
            src = re.search(r'data-src="([^"]+)"', open_tag).group(1)
            code = re.match(r"(<code[^>]*>)", inner)
            body = html.escape(wanted(src), quote=False)
            if code:
                return f"{open_tag}{code.group(1)}{body}</code></pre>"
            return f"{open_tag}{body}</pre>"

        new = re.sub(r'(<pre[^>]*data-src="[^"]+"[^>]*>)(.*?)</pre>', sub, text, flags=re.DOTALL)
        if new != text:
            page.write_text(new)
            print(f"filled {page.name}")


def check():
    bad = 0
    seen = 0
    for page in sorted(PROTO.glob("*.html")):
        text = page.read_text()
        for src, body in PRE.findall(text):
            seen += 1
            got = html.unescape(body)
            if got != wanted(src):
                bad += 1
                print(f"DRIFT {page.name}: {src}")
    print(f"{seen} blocks checked, {bad} drifted")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "extract":
        sys.stdout.write(extract(sys.argv[2], int(sys.argv[3])))
    elif len(sys.argv) >= 2 and sys.argv[1] == "fill":
        fill()
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        sys.exit(check())
    else:
        print(__doc__)
        sys.exit(2)

"""GUIDE.md is a program: every code block runs, in order, verbatim.

Same discipline as the README check in ./check — the guide cannot
drift from the kernel, because drift is a failing test (D-11).
"""

import pathlib
import re


def test_guide_runs_verbatim(capsys):
    guide = pathlib.Path(__file__).resolve().parents[2] / "GUIDE.md"
    blocks = re.findall(r"```python\n(.*?)```", guide.read_text(), re.DOTALL)
    assert len(blocks) >= 10, "the guide lost its code"
    code = "\n".join(blocks)
    exec(compile(code, "GUIDE.md", "exec"), {})

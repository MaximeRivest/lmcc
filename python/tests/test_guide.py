"""GUIDE.md is a program: every python block runs, in order, as one real
module file (so that shipped formats can read their own source)."""

import pathlib
import re
import runpy


def test_guide_runs_verbatim(tmp_path):
    text = (pathlib.Path(__file__).resolve().parents[2] / "GUIDE.md").read_text()
    code = "\n".join(re.findall(r"```python\n(.*?)```", text, re.DOTALL))
    path = tmp_path / "guide_program.py"
    path.write_text(code)
    runpy.run_path(str(path), run_name="guide")

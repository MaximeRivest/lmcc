"""Every ``docs/howto/*.md`` guide is a program: its python blocks run,
in order, as one real module file per guide (so a shipped format can
read its own source through ``inspect.getsource``).

A block whose first line is ``# requires: NAME`` needs the module NAME.
When NAME does not import as a real module (``tests/dspy/`` would
otherwise shadow ``dspy`` as an empty namespace package), the whole
guide is skipped: later blocks depend on earlier ones, so running half
a guide proves nothing.
"""

import importlib
import pathlib
import re
import runpy

import pytest

HOWTO = pathlib.Path(__file__).resolve().parents[2] / "docs" / "howto"
GUIDES = sorted(HOWTO.glob("*.md"))
GUIDES = [g for g in GUIDES if g.name != "README.md"]
REQUIRES = re.compile(r"^# requires: ([A-Za-z_][A-Za-z0-9_.]*)\s*$")


def blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, re.DOTALL)


def test_howto_index_lists_every_guide():
    index = (HOWTO / "README.md").read_text()
    for guide in GUIDES:
        assert f"({guide.name})" in index, f"{guide.name} is not in docs/howto/README.md"


def test_howto_guides_exist():
    assert len(GUIDES) >= 10


@pytest.mark.parametrize("guide", GUIDES, ids=lambda p: p.stem)
def test_howto_guide_runs_verbatim(guide, tmp_path):
    code_blocks = blocks(guide.read_text())
    assert code_blocks, f"{guide.name} has no python block"
    for block in code_blocks:
        first = block.split("\n", 1)[0]
        m = REQUIRES.match(first)
        if m:
            try:
                module = importlib.import_module(m.group(1))
            except ImportError:
                module = None
            if module is None or not getattr(module, "__file__", None):
                pytest.skip(f"{guide.name} requires {m.group(1)}, which does not import")
    path = tmp_path / f"{guide.stem.replace('-', '_')}.py"
    path.write_text("\n".join(code_blocks))
    runpy.run_path(str(path), run_name="howto")

"""The reference implementation must pass its own contract corpus.

This is the same harness any other implementation runs. Each case is its
own pytest case so a corpus failure names its file.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "contract" / "harness"))

from runner import CASES_DIR, PythonDriver  # noqa: E402

CASE_FILES = sorted(CASES_DIR.glob("*.json"))


def test_corpus_exists():
    assert len(CASE_FILES) >= 19


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_corpus_case(path):
    case = json.loads(path.read_text())
    result = PythonDriver().run(case)
    assert result["ok"], result["detail"]

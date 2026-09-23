"""The driver protocol (kernel §9) through a real subprocess: the whole
corpus, JSON Lines both ways, stream traces judged against the in-process
reference. Another language's driver is held to exactly this."""

import os
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "contract" / "harness"


def test_corpus_passes_through_the_subprocess_protocol(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS))
    import runner
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
        [str(HARNESS.parents[1] / "python"), os.environ.get("PYTHONPATH", "")]))
    driver = runner.SubprocessDriver(f"{sys.executable} python_driver.py", cwd=HARNESS)
    report = runner.run_corpus(driver)
    assert report.ok, report.failures[:3]
    assert report.passed + len(report.unclaimed) == len(list(runner.CASES_DIR.glob("*.json")))
    assert report.traced > 0, "stream traces were compared with the reference"

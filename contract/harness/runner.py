"""The conformance harness: runs any implementation against the corpus.

Cases live in ``contract/corpus/cases/*.json``. Each case names a kind:

- ``render``:    load entry, bake, render → compare messages + patch, exact.
- ``parse``:     load entry, bake, parse the given response → compare values.
- ``roundtrip``: load then dump → compare to the original entry, exact.
- ``refuse``:    the named step must refuse with the expected error code.

A driver adapts one implementation to the harness. The in-process
``PythonDriver`` covers the reference implementation; other languages
implement the same four calls behind a JSON stdin/stdout protocol
(see contract/spec/kernel.md §harness).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "corpus" / "cases"


class PythonDriver:
    """Runs cases against the reference `lmcc` + `lmcc_std` packages."""

    name = "python-reference"

    def __init__(self):
        import lmcc  # noqa: F401 — fail loudly here if not importable
        self.lmcc = lmcc

    def _registry(self, case: dict):
        registry = self.lmcc.Registry()
        if "std" in case.get("vocab", []):
            import lmcc_std
            lmcc_std.install(registry)
        return registry

    def run(self, case: dict) -> dict:
        """Returns {"ok": bool, "detail": str} for one case."""
        lmcc = self.lmcc
        expect = case["expect"]
        kind = case["kind"]
        registry = self._registry(case)
        try:
            adapter = lmcc.load(case["entry"], registry=registry)
            if kind == "roundtrip":
                dumped = lmcc.dump(adapter, registry)
                return _compare(expect["entry"], dumped, "entry")
            sig = lmcc.signature_from_dict(case["signature"])
            baked = adapter.bake(sig, case.get("capabilities", {}),
                                 registry=registry)
            if kind == "render":
                result = baked.render(inputs=case.get("inputs", {}),
                                      demos=case.get("demos"),
                                      history=case.get("history"))
                got = {"messages": result.messages, "patch": result.patch}
                return _compare(expect, got, "render result")
            if kind == "parse":
                values = baked.parse(case["response"])
                return _compare(expect["values"], values, "values")
            if kind == "refuse":
                if "inputs" in case:
                    baked.render(inputs=case["inputs"], demos=case.get("demos"))
                if "response" in case:
                    baked.parse(case["response"])
                return {"ok": False,
                        "detail": f"expected refusal {expect['code']!r}, "
                                  f"but nothing refused"}
            return {"ok": False, "detail": f"unknown case kind {kind!r}"}
        except lmcc.LMCCError as err:
            if kind == "refuse" and err.code == expect["code"]:
                return {"ok": True, "detail": ""}
            return {"ok": False,
                    "detail": f"unexpected refusal [{err.code}]: {err.detail}"}


def _compare(expected, got, what: str) -> dict:
    if expected == got:
        return {"ok": True, "detail": ""}
    return {"ok": False,
            "detail": f"{what} mismatch\n--- expected\n"
                      f"{json.dumps(expected, indent=1, ensure_ascii=False)}\n"
                      f"--- got\n{json.dumps(got, indent=1, ensure_ascii=False)}"}


@dataclass
class Report:
    passed: int
    failed: int
    failures: list[tuple[str, str]]

    @property
    def ok(self) -> bool:
        return self.failed == 0


def run_corpus(driver=None, cases_dir: Path = CASES_DIR) -> Report:
    driver = driver or PythonDriver()
    passed, failed, failures = 0, 0, []
    for path in sorted(cases_dir.glob("*.json")):
        case = json.loads(path.read_text())
        result = driver.run(case)
        if result["ok"]:
            passed += 1
        else:
            failed += 1
            failures.append((path.name, result["detail"]))
    return Report(passed, failed, failures)


def main() -> int:
    report = run_corpus()
    for name, detail in report.failures:
        print(f"FAIL {name}\n{detail}\n")
    print(f"{report.passed} passed, {report.failed} failed")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""The conformance harness: runs any implementation against the corpus.

Cases live in ``contract/corpus/cases/*.json``. Each case names a kind:

- ``render``:    load entry, bake, render → compare messages + patch, exact.
- ``parse``:     load entry, bake, parse the given response → compare values.
- ``roundtrip``: load then dump → compare to the original entry, exact.
- ``refuse``:    the named step must refuse with the expected error code.

A driver adapts one implementation to the harness. The in-process
``PythonDriver`` covers the reference implementation; other languages
implement the same four calls behind a JSON Lines stdin/stdout protocol
(``SubprocessDriver``; see contract/spec/kernel.md §10): one case object
per line in, one ``{"ok": bool, "detail": str}`` per line out, in order.

    python runner.py                     # the Python reference
    python runner.py --driver 'go run ./cmd/lmcc-conform'   # any other
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
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
                    baked.render(inputs=case["inputs"], demos=case.get("demos"),
                                 history=case.get("history"))
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


class SubprocessDriver:
    """Any implementation behind the JSON Lines protocol. The process is
    started once; cases stream through it in order."""

    def __init__(self, command: str, cwd: Path | None = None):
        self.name = command
        self.proc = subprocess.Popen(
            shlex.split(command), cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)

    def run(self, case: dict) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(case, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            code = self.proc.wait()
            return {"ok": False,
                    "detail": f"driver exited (status {code}) before answering"}
        try:
            answer = json.loads(line)
        except ValueError:
            return {"ok": False, "detail": f"driver wrote non-JSON: {line!r}"}
        if not isinstance(answer, dict) or not isinstance(answer.get("ok"), bool):
            return {"ok": False, "detail": f"driver answer malformed: {line!r}"}
        return {"ok": answer["ok"], "detail": str(answer.get("detail", ""))}

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait()


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
    try:
        for path in sorted(cases_dir.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            result = driver.run(case)
            if result["ok"]:
                passed += 1
            else:
                failed += 1
                failures.append((path.name, result["detail"]))
    finally:
        if hasattr(driver, "close"):
            driver.close()
    return Report(passed, failed, failures)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--driver", metavar="CMD",
                    help="run CMD as a JSON Lines driver instead of the "
                         "in-process Python reference")
    ap.add_argument("--cwd", metavar="DIR", help="working directory for CMD")
    args = ap.parse_args(argv)
    if args.driver:
        driver = SubprocessDriver(args.driver, cwd=Path(args.cwd) if args.cwd else None)
    else:
        driver = PythonDriver()
    report = run_corpus(driver)
    for name, detail in report.failures:
        print(f"FAIL {name}\n{detail}\n")
    print(f"[{driver.name}] {report.passed} passed, {report.failed} failed")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""The conformance harness: runs any implementation against the corpus.

Cases live in ``contract/corpus/cases/*.json``. Each case names a kind:

- ``render``:    load entry, bake, render → compare messages + patch, exact.
- ``parse``:     load entry, bake, parse the given response → compare values;
                 replay streaming whole, one scalar at a time, and at every
                 text/part split → compare values and concatenated deltas.
                 The one-scalar replay's event log is the case's
                 ``stream_trace``; an external driver's trace must equal the
                 reference kernel's (event timing is pinned across kernels).
- ``roundtrip``: load then dump → compare to the original entry, exact.
- ``refuse``:    the named step must refuse with the expected error code
                 and, when the case says so, the exact ``fix`` payload.

A driver adapts one implementation to the harness. The in-process
``PythonDriver`` covers the reference implementation; other languages
implement the same four calls behind a JSON Lines stdin/stdout protocol
(``SubprocessDriver``; see contract/spec/kernel.md §9): one case object
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
        """Exactly what the case requires (kernel §9): a core-only registry
        plus the listed UDF placement and extensions — never more, so a
        case that forgets a requirement refuses instead of passing."""
        requires = case.get("requires", [])
        extensions = [r for r in requires if not r.startswith("udf:")]
        registry = self.lmcc.Registry(allow_udf="udf:python" in requires, extensions=extensions)
        if "std" in case.get("vocab", []):
            import lmcc_std
            lmcc_std.install(registry)
        return registry

    def _unclaimed(self, case: dict) -> str | None:
        native = {b.extension for b in self.lmcc.native_extensions()}
        for r in case.get("requires", []):
            if r.startswith("udf:"):
                if r != "udf:python":
                    return r
            elif r not in native:
                return r
        return None

    def run(self, case: dict) -> dict:
        """Returns {"ok": bool, "detail": str} for one case."""
        lmcc = self.lmcc
        expect = case["expect"]
        kind = case["kind"]
        unclaimed = self._unclaimed(case)
        if unclaimed:
            return {"ok": True, "detail": "", "unclaimed": unclaimed}
        registry = self._registry(case)
        try:
            adapter = lmcc.load(case["entry"], registry=registry)
            if kind == "roundtrip":
                dumped = lmcc.dump(adapter, registry)
                return _compare(expect["entry"], dumped, "entry")
            sig = lmcc.signature_from_dict(case["signature"])
            baked = adapter.bind(sig, case.get("capabilities", {}),
                                 registry=registry)
            if kind == "plan":
                got = {"skeleton": baked.skeleton(),
                       "prefix": baked.prefix(demos=case.get("demos"), history=case.get("history"))}
                return _compare({"skeleton": expect["skeleton"], "prefix": expect["prefix"]}, got, "plan")
            if kind == "render":
                result = baked.render(inputs=case.get("inputs", {}),
                                      demos=case.get("demos"),
                                      history=case.get("history"))
                return _compare(expect["request"], result.request(), "request")
            if kind == "parse":
                values = baked.parse(case["response"])
                compared = _compare(expect["values"], values, "values")
                if not compared["ok"]:
                    return compared
                result = _check_stream_success(baked, case["response"], values)
                if result["ok"]:
                    result["stream_trace"] = _stream_trace(baked, case["response"])
                return result
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
        except lmcc.Refusal as err:
            if kind == "refuse" and err.code == expect["code"]:
                if "fix" in expect:
                    compared = _compare(expect["fix"], err.fix, f"fix of [{err.code}]")
                    if not compared["ok"]:
                        return compared
                if expect.get("at") == "parse" and "response" in case:
                    result = _check_stream_refusal(baked, case["response"], err)
                    if result["ok"]:
                        result["stream_trace"] = _stream_trace(baked, case["response"])
                    return result
                return {"ok": True, "detail": ""}
            return {"ok": False,
                    "detail": f"unexpected refusal [{err.code}]: {err.hint}"}


def _message_parts(response: object) -> list:
    """The part list of an lm15 message or response (kernel §3)."""
    if isinstance(response, dict) and isinstance(response.get("message"), dict):
        response = response["message"]
    return response.get("parts", []) if isinstance(response, dict) else []


def _stream_chunkings(response: object) -> list[list[object]]:
    """One whole feed, then every Unicode-scalar split of text and of each
    text-bearing part. Transport byte decoding is outside lmcc (§8)."""
    if isinstance(response, str):
        return [[response], list(response)] + [[response[:i], response[i:]]
                                               for i in range(len(response) + 1)]
    parts = _message_parts(response)
    out: list[list[object]] = [list(parts)]
    for pi, part in enumerate(parts):
        text = part.get("text") if isinstance(part, dict) else None
        if not isinstance(text, str):
            continue
        characters = []
        for character in text:
            delta = dict(part)
            delta["text"] = character
            characters.append(delta)
        if not characters:
            characters = [dict(part)]
        out.append([*parts[:pi], *characters, *parts[pi + 1:]])
        for i in range(len(text) + 1):
            left, right = dict(part), dict(part)
            left["text"], right["text"] = text[:i], text[i:]
            out.append([*parts[:pi], left, right, *parts[pi + 1:]])
    return out


def _feed_chunk(plan, stream, response, chunk):
    # A string in a part list is not a text delta. Check its list boundary
    # before feed can reinterpret it. Other malformed deltas reach feed.
    if not isinstance(response, str) and isinstance(chunk, str):
        plan.parse({"role": "assistant", "parts": [chunk]})
    return stream.feed(chunk)


def _delta_text(events: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for event in events:
        if event.get("kind") == "field_delta":
            field = event["field"]
            out[field] = out.get(field, "") + event["text"]
    return out


def _check_stream_success(plan, response: object, batch_values: dict) -> dict:
    baseline = None
    for n, chunks in enumerate(_stream_chunkings(response)):
        stream = plan.stream()
        events = []
        try:
            for chunk in chunks:
                events.extend(_feed_chunk(plan, stream, response, chunk))
            result = stream.finish()
            events.extend(result.events)
        except Exception as exc:  # noqa: BLE001 — conformance detail
            return {"ok": False, "detail": f"stream split {n} refused/failed: {exc}"}
        if result.values != batch_values:
            return _compare(batch_values, result.values, f"stream split {n} values")
        deltas = _delta_text(events)
        if baseline is None:
            baseline = deltas
        elif deltas != baseline:
            return _compare(baseline, deltas, f"stream split {n} field deltas")
    return {"ok": True, "detail": ""}


def _check_stream_refusal(plan, response: object, batch_error) -> dict:
    import lmcc
    expected = batch_error.describe()
    for n, chunks in enumerate(_stream_chunkings(response)):
        stream = plan.stream()
        try:
            for chunk in chunks:
                _feed_chunk(plan, stream, response, chunk)
            stream.finish()
        except lmcc.Refusal as err:
            if err.describe() == expected:
                continue
            return _compare(expected, err.describe(), f"stream split {n} refusal")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"stream split {n} failed outside Refusal: {exc}"}
        return {"ok": False,
                "detail": f"stream split {n}: expected refusal [{batch_error.code}]"}
    return {"ok": True, "detail": ""}


def _trace_chunking(response: object) -> list[object]:
    """One Unicode scalar per feed; a part without text is one feed."""
    if isinstance(response, str):
        return list(response)
    out: list[object] = []
    for part in _message_parts(response):
        text = part.get("text") if isinstance(part, dict) else None
        if isinstance(text, str) and text:
            out.extend({**part, "text": character} for character in text)
        else:
            out.append(part)
    return out


def _event_digest(event: dict) -> list:
    digest = [event["kind"], event["field"]]
    if event["kind"] == "field_delta":
        digest.append(event["text"])
    return digest


def _stream_trace(plan, response: object) -> list:
    """The events of every feed at one-scalar chunking, then the EOF events
    or the refusal code. Typed values are left out: the values comparison
    already pins them; the trace pins *when* raw text becomes visible."""
    import lmcc
    stream = plan.stream()
    trace: list = []
    try:
        for chunk in _trace_chunking(response):
            trace.append([_event_digest(e) for e in _feed_chunk(plan, stream, response, chunk)])
        trace.append([_event_digest(e) for e in stream.finish().events])
    except lmcc.Refusal as err:
        trace.append({"refusal": err.code})
    return trace


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
        out = {"ok": answer["ok"], "detail": str(answer.get("detail", ""))}
        if answer.get("unclaimed"):
            out["unclaimed"] = str(answer["unclaimed"])
        if "stream_trace" in answer:
            out["stream_trace"] = answer["stream_trace"]
        return out

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
    unclaimed: list[tuple[str, str]] = None  # (case, what the driver cannot place)
    traced: int = 0  # cases whose stream trace matched the reference kernel

    @property
    def ok(self) -> bool:
        return self.failed == 0


def run_corpus(driver=None, cases_dir: Path = CASES_DIR) -> Report:
    driver = driver or PythonDriver()
    # The reference kernel is needed only to judge a driver's stream trace
    # (D-27). A driver that sends none runs against the corpus alone, so a
    # foreign implementation never needs the Python packages importable.
    reference = None
    passed, failed, failures, unclaimed, traced = 0, 0, [], [], 0
    try:
        for path in sorted(cases_dir.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            result = driver.run(case)
            if result.get("ok") and not isinstance(driver, PythonDriver) and "stream_trace" in result:
                if reference is None:
                    reference = PythonDriver()
                expected = reference.run(case).get("stream_trace")
                if expected is None:
                    result = {"ok": False, "detail": "driver sent a stream trace the reference has none for"}
                else:
                    compared = _compare(expected, result["stream_trace"], "stream trace vs reference kernel")
                    if compared["ok"]:
                        traced += 1
                    else:
                        result = compared
            if result.get("unclaimed"):
                unclaimed.append((path.name, result["unclaimed"]))
            elif result["ok"]:
                passed += 1
            else:
                failed += 1
                failures.append((path.name, result["detail"]))
    finally:
        if hasattr(driver, "close"):
            driver.close()
    return Report(passed, failed, failures, unclaimed, traced)


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
    note = f", {len(report.unclaimed)} unclaimed ({', '.join(sorted({u for _, u in report.unclaimed}))})" if report.unclaimed else ""
    if args.driver:
        note += f", {report.traced} stream traces match the reference kernel"
    print(f"[{driver.name}] {report.passed} passed, {report.failed} failed{note}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""The harness catches what it promises to catch (plan 09 D2, D3): a
refusal at the wrong stage, and a stream whose deltas lose text."""

import copy
import json
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "contract" / "harness"
CASES = HARNESS.parent / "corpus" / "cases"


def _runner(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS))
    import runner
    return runner


def test_a_refusal_at_the_wrong_stage_fails(monkeypatch):
    runner = _runner(monkeypatch)
    case = json.loads((CASES / "77-refuse-load-unknown-transport.json").read_text())
    assert case["expect"]["at"] == "load" and runner.PythonDriver().run(case)["ok"]
    wrong = copy.deepcopy(case)
    wrong["expect"]["at"] = "bind"
    result = runner.PythonDriver().run(wrong)
    assert not result["ok"] and "fired at load" in result["detail"]


class _Silent:
    """A stream that returns the right values but never emits a delta."""

    def __init__(self, plan):
        self.plan = plan
        self.pieces = []

    def feed(self, delta):
        self.pieces.append(delta)
        return []

    def finish(self, finish_reason=None):
        reading = self.plan.read("".join(self.pieces))

        class R:
            events, values, repairs = [], reading.values, reading.repairs
        return R()


def test_a_stream_that_drops_its_deltas_fails(monkeypatch):
    runner = _runner(monkeypatch)
    import lmcc
    case = json.loads((CASES / "31-derived-reader-parse.json").read_text())
    plan = lmcc.load(case["entry"]).bind(lmcc.signature_from_dict(case["signature"]),
                                         case.get("capabilities", {}))
    reading = plan.read(case["response"])
    _, captures, _ = plan._parse_with_captures(case["response"])
    raw = {k: c.text for k, c in captures.items() if c.text}

    class Silent:
        def __init__(self, p):
            self.p = p

        def stream(self):
            return _Silent(self.p)

        def parse(self, r):
            return self.p.parse(r)

    ok = runner._check_stream_success(plan, case["response"], reading.values, reading.repairs, raw=raw)
    assert ok["ok"]
    bad = runner._check_stream_success(Silent(plan), case["response"], reading.values,
                                       reading.repairs, raw=raw)
    assert not bad["ok"] and "deltas against batch raw text" in bad["detail"]


def _differential(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS))
    import differential
    return differential


def test_the_differential_refuses_a_member_written_twice(monkeypatch):
    """A probe that writes one member twice fails, at any depth; plain
    json.loads would keep the last and compare equal (review S1, D-58)."""
    d = _differential(monkeypatch)
    ok = d.read_observation('{"a": {"description": "x", "type": "string"}}')
    assert ok == {"a": {"description": "x", "type": "string"}}
    twice = d.read_observation('{"a": {"description": "x", "type": "string", "description": "y"}}')
    assert "crash" in twice and "'description' twice" in twice["crash"]
    assert "crash" in d.read_observation('[{"k": 1, "k": 1}]'[1:-1])


def test_the_differential_splits_probe_lines_at_newline_only(monkeypatch):
    d = _differential(monkeypatch)
    out = '{"k": "a\u2028b\u2029c\x85"}\n{"k": 2}\n'
    assert [d.read_observation(x) for x in d.probe_lines(out)] == [{"k": "a\u2028b\u2029c\x85"}, {"k": 2}]

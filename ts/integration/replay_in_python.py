"""Replay the TypeScript kernel's live exchanges through the Python kernel.

    node ts/integration/live.ts                 # real models, writes live-record.json
    python ts/integration/replay_in_python.py   # offline, free

For every exchange the TypeScript kernel had with a real model, Python loads
the same artifact (as TypeScript dumped it), binds the same signature, and
checks, as JSON:

- the request it renders for the same turn equals the one TypeScript sent;
- the turn TypeScript recorded (values, message, request hash) loads, and
  the step Python records from the same lm15 response equals it;
- the reading of each reply is the same (values or refusal code).

Real replies carry what the corpus does not: provider ids, thinking parts,
data parts, odd spacing. This is the check that both kernels serialize the
same data on real traffic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import lmcc  # noqa: E402
import lmcc_std  # noqa: E402
from lmcc.turn import Turn  # noqa: E402


def main() -> int:
    record = json.loads((Path(__file__).parent / "live-record.json").read_text(encoding="utf-8"))
    problems, checked = [], 0
    for item in record:
        registry = lmcc.Registry()
        lmcc_std.install(registry)
        adapter = lmcc.load(item["entry"], registry=registry)
        if lmcc.dump(adapter, registry) != item["entry"]:
            problems.append((item["name"], "dump", "the artifact TypeScript dumped does not round-trip in Python"))
        sig = lmcc.signature_from_dict(item["signature"])
        plan = adapter.bind(sig, item["capabilities"], registry=registry)
        for n, ex in enumerate(item["exchanges"]):
            where = f"{item['name']}#{n}"
            request = ex["request"]
            model = request.get("model")
            rendered = plan.render(Turn.from_dict(ex["current"]))   # the turn as TypeScript rendered it
            if rendered.request(model) != request:
                problems.append((where, "request", json.dumps(rendered.request(model))[:300]))
            try:
                reading = plan.read(ex["response"])
                got = ("values", reading.values)
            except lmcc.Refusal as err:
                got = ("refused", err.code)
            if ex["turn"] is not None:
                ts_turn = Turn.from_dict(ex["turn"])
                py_turn = rendered.step(ex["response"])
                if py_turn.to_dict() != ts_turn.to_dict():
                    problems.append((where, "step", json.dumps(py_turn.to_dict())[:300]))
                if got[0] != "values" or got[1] != ts_turn.steps[-1].outputs:
                    problems.append((where, "read", str(got)[:300]))
            elif got[0] != "refused":
                problems.append((where, "read", f"TypeScript refused this reply, Python read {got}"))
            checked += 1
    for where, what, detail in problems:
        print(f"DIFF {where} {what}: {detail}")
    print(f"[live replay] {checked} live exchanges from {len(record)} scenarios re-rendered and re-read "
          f"in Python: {len(problems)} differences")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

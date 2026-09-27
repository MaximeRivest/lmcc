"""Differential check: another kernel against the Python reference.

The corpus pins rendered requests, parsed values and refusal codes/fixes
(kernel §9). Two implementations also serialize much more: `plan.describe()`,
`dump()`, signature fingerprints, request hashes, readings with repairs and
probabilities, recorded model steps and turns, prefixes, stream results, and
the data of every refusal. This runs every corpus case, and fuzzed replies,
through a kernel's probe and through Python, and compares all of it as JSON.

    python contract/harness/differential.py --probe 'node ts/tools/probe.ts'
    python contract/harness/differential.py --probe 'julia --project=julia julia/tools/probe.jl'
    python contract/harness/differential.py --probe 'Rscript r/tools/probe.R'

A probe reads one case per line and writes one observation per line (the
shape `observe` below builds); integers beyond 2^53 may be written as
numbers or as the text "<n>n".

Differences that are the contract's stated host differences are listed in
EXPECTED and reported separately, never silently skipped. Refusal hints are
human prose (errors.md: "hints may improve without a version bump"); they
are compared too and differences are counted, but do not fail the run.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import lmcc  # noqa: E402
import lmcc_std  # noqa: E402
from lmcc.turn import ModelStep, Turn, as_message, sha256  # noqa: E402

# (observation key, JSON path) pairs whose values are stated host
# differences (kernel §10: an extension binding's label names its host).
EXPECTED = {
    ("describe", "extensions", "*", "binding"): "the pattern/legacy-re2 binding label names its engine",
}

BIG = 2**53 - 1


def normalize(value):
    """Both sides in one spelling: integers beyond 2^53 as "<n>n"."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, float)):
        return value
    if isinstance(value, int):
        return value if abs(value) <= BIG else f"{value}n"
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def refusal(err: lmcc.Refusal) -> dict:
    return {"code": err.code, "fix": err.fix, "partial": err.partial, "hint": err.hint}


def attempt(fn):
    try:
        return {"ok": fn()}
    except lmcc.Refusal as err:
        return {"refused": refusal(err)}


def jsonable(value):
    """Python values as the JSON the TS probe writes (ints beyond 2^53 as '<n>n')."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value if abs(value) <= 2**53 - 1 else f"{value}n"
    if isinstance(value, float):
        return value
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def observe(case: dict) -> dict:
    requires = case.get("requires", [])
    if any(r.startswith("udf:") for r in requires):
        return {"skipped": "udf"}
    registry = lmcc.Registry(extensions=requires)
    if "std" in case.get("vocab", []):
        lmcc_std.install(registry)
    out: dict = {}
    try:
        adapter = lmcc.load(case["entry"], registry=registry)
    except lmcc.Refusal as err:
        return {"load": {"refused": refusal(err)}}
    out["dump"] = attempt(lambda: lmcc.dump(adapter, registry))
    if not case.get("signature"):
        return out
    try:
        sig = lmcc.signature_from_dict(case["signature"])
    except lmcc.Refusal as err:
        out["signature"] = {"refused": refusal(err)}
        return out
    out["fingerprint"] = lmcc.signature_fingerprint(sig)
    out["signature_dict"] = lmcc.signature_to_dict(sig)
    try:
        plan = adapter.bind(sig, case.get("capabilities", {}), registry=registry)
    except lmcc.Refusal as err:
        out["bind"] = {"refused": refusal(err)}
        return out
    out["describe"] = plan.describe()
    fp = lmcc.signature_fingerprint(sig)
    slots = {name: [{"signature": fp, **t} for t in ts] for name, ts in case.get("turns", {}).items()}
    out["prefix"] = attempt(lambda: plan.prefix(turns=slots))
    out["skeleton"] = plan.skeleton()
    if "inputs" in case:
        current = {"signature": fp, "inputs": case["inputs"], "steps": case.get("steps", [])}
        out["turn_json"] = attempt(lambda: Turn.from_dict(current).to_dict())
        out["slot_json"] = attempt(lambda: {k: [Turn.from_dict(t).to_dict() for t in ts] for k, ts in slots.items()})

        def render():
            rendered = plan.render(Turn.from_dict(current), turns=slots)
            return {"request": rendered.request("m"), "hash": sha256(rendered.request())}
        out["render"] = attempt(render)
    if "response" in case:
        response = case["response"]

        def read():
            r = plan.read(response)
            return {"values": r.values, "repairs": r.repairs, "probabilities": r.probabilities,
                    "measured_by": r.measured_by}
        out["read"] = attempt(read)
        out["step"] = attempt(lambda: ModelStep(plan.parse(response), as_message(response),
                                                sha256({"messages": []}), plan.calls_field).to_dict())

        def stream():
            s = plan.stream()
            events = []
            parts = [response] if isinstance(response, str) else (response.get("message") or response)["parts"]
            for p in parts:
                events += s.feed(p)
            reason = response.get("finish_reason") if isinstance(response, dict) and "message" in response else None
            end = s.finish(reason)
            return {"events": events + end.events,
                    "result": {"events": end.events, "values": end.values, "repairs": end.repairs,
                               "probabilities": end.probabilities, "measured_by": end.measured_by}}
        out["stream"] = attempt(stream)
    return out


def diff(a, b, path=()):
    """Yield (path, python, typescript) for every leaf that differs."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                yield path + (k,), a.get(k, "<absent>"), b.get(k, "<absent>")
            else:
                yield from diff(a[k], b[k], path + (k,))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from diff(x, y, path + (i,))
    elif a != b or type(a) is bool and type(b) is not bool or type(b) is bool and type(a) is not bool:
        yield path, a, b


def expected(path) -> str | None:
    for pattern, why in EXPECTED.items():
        if len(pattern) == len(path) and all(p == "*" or p == q for p, q in zip(pattern, path)):
            return why
    return None


def mutate(text: str, rng) -> str:
    """One model-like slip: case, markdown decoration, spacing, a lost or
    doubled piece, a cut, a stray line feed."""
    if not text:
        return text
    i = rng.randrange(len(text) + 1)
    j = min(len(text), i + rng.randrange(1, 12))
    op = rng.randrange(8)
    if op == 0:
        return text[:i] + text[i:j].swapcase() + text[j:]
    if op == 1:
        return text[:i] + rng.choice(["**", "*", "#", "### ", "_", "__"]) + text[i:]
    if op == 2:
        return text[:i] + rng.choice([" ", "  ", "\t", "\n", "\r\n"]) + text[i:]
    if op == 3:
        return text[:i] + text[j:]
    if op == 4:
        return text[:j] + text[i:j] + text[j:]
    if op == 5:
        return text[:i]
    if op == 6:
        return text[:i] + rng.choice(["\"", "'", "`", ".", "None", "N/A"]) + text[i:]
    return text[:i] + text[i:j].upper() + text[j:]


def fuzz_cases(cases: list, per_case: int, seed: int = 20260926) -> list:
    """Mutants of every text-reply parse case, each read by both kernels."""
    import random
    rng = random.Random(seed)
    out = []
    for case in cases:
        if case["kind"] not in ("parse", "refuse") or "response" not in case:
            continue
        if any(r.startswith("udf:") for r in case.get("requires", [])):
            continue
        response = case["response"]
        for _ in range(per_case):
            mutant = dict(case)
            if isinstance(response, str):
                text = response
                for _ in range(rng.randrange(1, 4)):
                    text = mutate(text, rng)
                mutant["response"] = text
            else:
                message = response.get("message", response)
                parts = [dict(p) if isinstance(p, dict) else p for p in message.get("parts", [])]
                texts = [k for k, p in enumerate(parts) if isinstance(p, dict) and isinstance(p.get("text"), str)]
                if not texts:
                    continue
                k = rng.choice(texts)
                parts[k]["text"] = mutate(parts[k]["text"], rng)
                if "message" in response:
                    mutant["response"] = {**response, "message": {**message, "parts": parts}}
                else:
                    mutant["response"] = {**message, "parts": parts}
            mutant.pop("inputs", None)
            out.append(mutant)
    return out


def main() -> int:
    import argparse
    import shlex
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--probe", required=True, metavar="CMD", help="the kernel's probe command")
    ap.add_argument("--name", default=None, help="a label for the report")
    args = ap.parse_args()
    files = sorted(glob.glob(str(ROOT / "contract/corpus/cases/*.json")))
    cases = [json.load(open(f, encoding="utf-8")) for f in files]
    per_case = int(os.environ.get("LMCC_FUZZ", "40"))
    mutants = fuzz_cases(cases, per_case)
    files = files + [f"fuzz:{m['name']}#{n}" for n, m in enumerate(mutants)]
    cases = cases + mutants
    proc = subprocess.run(shlex.split(args.probe), cwd=ROOT, input="\n".join(
        json.dumps(c, ensure_ascii=False) for c in cases) + "\n", capture_output=True, text=True, check=True)
    ts_obs = [normalize(json.loads(line)) for line in proc.stdout.splitlines()]
    assert len(ts_obs) == len(cases), (len(ts_obs), len(cases), proc.stderr[-2000:])
    failures, stated, hints, compared = [], {}, 0, 0
    for f, case, ts in zip(files, cases, ts_obs):
        py = normalize(json.loads(json.dumps(jsonable(observe(case)), ensure_ascii=False)))
        if "crash" in ts:
            failures.append((os.path.basename(f), ("crash",), None, ts["crash"]))
            continue
        compared += 1
        for path, a, b in diff(py, ts):
            if path and path[-1] == "hint":
                hints += 1
                continue
            why = expected(path)
            if why:
                stated[why] = stated.get(why, 0) + 1
                continue
            failures.append((os.path.basename(f), path, a, b))
    for name, path, a, b in failures[:40]:
        print(f"DIFF {name} {'/'.join(map(str, path))}\n  python: {json.dumps(a, ensure_ascii=False)[:400]}\n"
              f"  probe:  {json.dumps(b, ensure_ascii=False)[:400]}")
    for why, n in stated.items():
        print(f"stated host difference ({n}×): {why}")
    print(f"[differential {args.name or args.probe}] {compared} cases observed ({len(mutants)} of them fuzzed replies), {len(failures)} differences, "
          f"{hints} refusal hints worded differently (prose, not contract)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

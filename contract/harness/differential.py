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
    """Yield (path, python, probe) for every leaf that differs, and for every
    object whose members the two list in different orders (kernel §1,
    "Members keep their order"; a probe writes JSON in its values' order)."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) == set(b) and list(a) != list(b):
            yield path + ("<member order>",), list(a), list(b)
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


# Names a host gives meaning to (kernel §1, D-58): the empty name, array
# index names JavaScript enumerates first (and their neighbors that are not
# indexes), Object.prototype members, R's special names, spacing, non-ASCII.
# Two sequences, taken in order, so a non-index name comes before index names
# and a larger index before a smaller one: the orders JavaScript would change.
HOSTILE_NAMES = (
    ["", "10", "2", "__proto__", "0", "toString", "4294967295", "4294967294", "01", "NA",
     "...", "é", "names", " x", "-1", "1.5", "constructor", "9"],
    ["toString", "9", "", "4294967294", "names", "1", "__proto__", "0", "é", "10", "NA",
     "01", " x", "...", "constructor", "-1", "2", "1.5"],
)


def _member_names(value, into: list) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in into:
                into.append(k)
            _member_names(v, into)
    elif isinstance(value, list):
        for v in value:
            _member_names(v, into)


def _shape_names(shape, into: list) -> None:
    if isinstance(shape, dict):
        for k, v in (shape.get("properties") or {}).items() if isinstance(shape.get("properties"), dict) else ():
            if k not in into:
                into.append(k)
            _shape_names(v, into)
        for v in shape.values():
            if isinstance(v, (dict, list)):
                _shape_names(v, into)
    elif isinstance(shape, list):
        for v in shape:
            _shape_names(v, into)


def _rename_data(value, names: dict):
    """Every member name of a JSON value renamed, members kept in order."""
    if isinstance(value, dict):
        return {names.get(k, k): _rename_data(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [_rename_data(v, names) for v in value]
    return value


def _rename_shape(shape, names: dict):
    """A shape with its properties (and their `required` entries) renamed."""
    if isinstance(shape, list):
        return [_rename_shape(v, names) for v in shape]
    if not isinstance(shape, dict):
        return shape
    out = {}
    for k, v in shape.items():
        if k == "properties" and isinstance(v, dict):
            out[k] = {names.get(p, p): _rename_shape(s, names) for p, s in v.items()}
        elif k == "required" and isinstance(v, list):
            out[k] = [names.get(p, p) if isinstance(p, str) else p for p in v]
        else:
            out[k] = _rename_shape(v, names)
    return out


def _rename_text(text: str, names: dict) -> str:
    for old, new in names.items():
        text = text.replace(json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False))
        if old:
            text = text.replace(f"| {old} |", f"| {new} |")
    return text


def rename_cases(cases: list) -> list:
    """Every case whose data has member names (a shape's properties, the
    members of inputs, turns, recorded steps, replies, table columns), again
    with those names replaced by names a host gives meaning to, members kept
    in their order. The two kernels need not accept a variant; they must
    agree on everything they serialize about it, order included."""
    out = []
    for case in cases:
        if any(r.startswith("udf:") for r in case.get("requires", [])):
            continue
        found: list = []
        for f in (case.get("signature") or {}).get("fields", []) if isinstance(case.get("signature"), dict) else []:
            if isinstance(f, dict):
                _shape_names(f.get("shape"), found)
        for v in (case.get("inputs") or {}).values() if isinstance(case.get("inputs"), dict) else []:
            _member_names(v, found)
        for fmt in (case.get("entry", {}).get("formats") or {}).values():
            cols = ((fmt or {}).get("options") or {}).get("columns") if isinstance(fmt, dict) else None
            if isinstance(cols, list):
                found += [c for c in cols if isinstance(c, str) and c not in found]
        response = case.get("response")
        message = response.get("message", response) if isinstance(response, dict) else None
        for p in message.get("parts", []) if isinstance(message, dict) else []:
            if isinstance(p, dict) and p.get("type") in ("data", "tool_call"):
                _member_names(p.get("value") if p.get("type") == "data" else p.get("input"), found)
                for labels in (p.get("probabilities") or {}).values() if isinstance(p.get("probabilities"), dict) else []:
                    _member_names(labels, found)
        fields = {f.get("name") for f in (case.get("signature") or {}).get("fields", []) if isinstance(f, dict)} \
            if isinstance(case.get("signature"), dict) else set()
        found = [n for n in found if n not in fields]   # a reading's own members are field names
        if not found:
            continue
        for variant, sequence in enumerate(HOSTILE_NAMES):
            pool = [n for n in sequence if n not in found]
            names = {old: pool[i % len(pool)] for i, old in enumerate(found)}
            if len(set(names.values())) != len(names):
                continue
            m = json.loads(json.dumps(case))
            m["name"] = f"{case['name']}~names{variant}"
            if isinstance(m.get("signature"), dict):
                for f in m["signature"].get("fields", []):
                    if isinstance(f, dict) and "shape" in f:
                        f["shape"] = _rename_shape(f["shape"], names)
            if isinstance(m.get("inputs"), dict):
                m["inputs"] = {k: _rename_data(v, names) for k, v in m["inputs"].items()}
            if isinstance(m.get("turns"), dict):
                slots = {}
                for slot, ts in m["turns"].items():
                    renamed = []
                    for t in ts if isinstance(ts, list) else []:
                        t = dict(t) if isinstance(t, dict) else t
                        if isinstance(t, dict):
                            t.pop("signature", None)   # the variant's own, filled by the probe
                            for key in ("inputs", "outputs"):
                                if isinstance(t.get(key), dict):
                                    t[key] = {k: _rename_data(v, names) for k, v in t[key].items()}
                            if isinstance(t.get("steps"), list):
                                t["steps"] = _rename_data(t["steps"], names)
                        renamed.append(t)
                    slots[slot] = renamed
                m["turns"] = slots
            if isinstance(m.get("steps"), list):
                m["steps"] = _rename_data(m["steps"], names)
            for fmt in (m.get("entry", {}).get("formats") or {}).values():
                opts = (fmt or {}).get("options") if isinstance(fmt, dict) else None
                if isinstance(opts, dict) and isinstance(opts.get("columns"), list):
                    opts["columns"] = [names.get(c, c) for c in opts["columns"]]
            response = m.get("response")
            if isinstance(response, str):
                m["response"] = _rename_text(response, names)
            elif isinstance(response, dict):
                message = response.get("message", response)
                parts = []
                for p in message.get("parts", []) if isinstance(message, dict) else []:
                    if isinstance(p, dict):
                        p = dict(p)
                        if isinstance(p.get("text"), str):
                            p["text"] = _rename_text(p["text"], names)
                        if isinstance(p.get("input"), dict):
                            p["input"] = _rename_data(p["input"], names)
                        if p.get("type") == "data" and "value" in p:
                            p["value"] = _rename_data(p["value"], names)
                        if isinstance(p.get("probabilities"), dict):
                            p["probabilities"] = {k: _rename_data(v, names) for k, v in p["probabilities"].items()}
                    parts.append(p)
                if isinstance(message, dict):
                    if "message" in response:
                        m["response"] = {**response, "message": {**message, "parts": parts}}
                    else:
                        m["response"] = {**message, "parts": parts}
            out.append(m)
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
    renamed = rename_cases(cases)
    files = files + [f"fuzz:{m['name']}#{n}" for n, m in enumerate(mutants)] + [f"names:{m['name']}" for m in renamed]
    cases = cases + mutants + renamed
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
    if len(failures) > 40:
        import re
        by_path: dict = {}
        for _, path, _, _ in failures:
            key = re.sub(r"/[0-9]+(?=/|$)", "/N", "/".join(map(str, path)))
            by_path[key] = by_path.get(key, 0) + 1
        for key, n in sorted(by_path.items(), key=lambda kv: -kv[1]):
            print(f"  {n}× {key}")
    for why, n in stated.items():
        print(f"stated host difference ({n}×): {why}")
    print(f"[differential {args.name or args.probe}] {compared} cases observed ({len(mutants)} of them fuzzed replies, "
          f"{len(renamed)} with hostile member names), {len(failures)} differences (member order included), "
          f"{hints} refusal hints worded differently (prose, not contract)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

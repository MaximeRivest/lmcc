"""One-time corpus seeder.

Authors the case inputs by hand; fills `expect` for render/parse/roundtrip
kinds by running the reference implementation ONCE, at corpus-creation
time. After seeding, the corpus is the authority: if the implementation
drifts from these files, the implementation is wrong. Never re-run this
blindly over behavior changes — that would silently re-bless drift.

Run from repo root:  PYTHONPATH=python python contract/corpus/tools/bootstrap.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "contract" / "corpus" / "cases"
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "contract" / "harness"))

import a15  # noqa: E402
import a15_std  # noqa: E402

KV = a15.KERNEL_VERSION

SECTIONS_ENTRY = {
    "name": "sections_v1",
    "versions": {"kernel": KV, "vocab": {}},
    "template": {"messages": [
        {"role": "system",
         "text": "{instruction}\n\nReply with EXACTLY these sections:\n"
                 "{% for f in outputs %}<{f.name}>  {f.desc}\n{% endfor %}"
                 "Close with </done>."},
        {"directive": "demos"},
        {"directive": "history"},
        {"role": "user",
         "text": "{% for f in inputs %}== {f.name} ==\n{f.value}\n{% endfor %}"},
    ]},
    "parse": {"kind": "sections", "open": "<{name}>", "tail": "</done>"},
    "requires": [],
}

QA_SIG = {
    "instructions": "Answer the question.",
    "fields": [
        {"name": "question", "direction": "input", "shape": {"type": "string"}},
        {"name": "answer", "direction": "output", "shape": {"type": "string"},
         "desc": "short answer"},
        {"name": "score", "direction": "output", "shape": {"type": "integer"}},
    ],
}

REASONING_SIG = {
    "instructions": "Answer.",
    "fields": [
        {"name": "question", "direction": "input", "shape": {"type": "string"}},
        {"name": "reasoning", "direction": "output", "shape": {"type": "string"},
         "role": "reasoning"},
        {"name": "answer", "direction": "output", "shape": {"type": "string"}},
    ],
}


def entry(**overrides):
    e = json.loads(json.dumps(SECTIONS_ENTRY))
    e.update(overrides)
    return e


def fill_expect(case: dict) -> dict:
    """Compute expect for non-refusal kinds by running the reference."""
    from runner import PythonDriver

    a15_mod = a15
    registry = a15_mod.Registry()
    if "std" in case.get("vocab", []):
        a15_std.install(registry)
    adapter = a15_mod.load(case["entry"], registry=registry)
    if case["kind"] == "roundtrip":
        case["expect"] = {"entry": a15_mod.dump(adapter, registry)}
        return case
    sig = a15_mod.signature_from_dict(case["signature"])
    baked = adapter.bake(sig, case.get("capabilities", {}), registry=registry)
    if case["kind"] == "render":
        result = baked.render(inputs=case.get("inputs", {}),
                              demos=case.get("demos"),
                              history=case.get("history"))
        case["expect"] = {"messages": result.messages, "patch": result.patch}
    elif case["kind"] == "parse":
        case["expect"] = {"values": baked.parse(case["response"])}
    _ = PythonDriver  # imported to assert the harness loads
    return case


def main() -> None:
    cases: list[dict] = []

    cases.append(fill_expect({
        "name": "render-minimal", "kind": "render",
        "entry": entry(), "signature": QA_SIG,
        "inputs": {"question": "Why is the sky blue?"}}))

    cases.append(fill_expect({
        "name": "render-demos-lens", "kind": "render",
        "entry": entry(), "signature": QA_SIG,
        "inputs": {"question": "3+3?"},
        "demos": [{"question": "2+2?", "answer": "4", "score": 10}]}))

    cases.append(fill_expect({
        "name": "render-history", "kind": "render",
        "entry": entry(), "signature": QA_SIG,
        "inputs": {"question": "and now?"},
        "history": [{"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"}]}))

    media_entry = entry()
    media_entry["template"]["messages"] = [
        {"role": "user", "text": "{question}\n{photo}\nthanks"}]
    cases.append(fill_expect({
        "name": "render-media-part", "kind": "render",
        "entry": media_entry,
        "signature": {"instructions": "Describe.", "fields": [
            {"name": "question", "direction": "input", "shape": {"type": "string"}},
            {"name": "photo", "direction": "input", "shape": {"media": "image"}},
            {"name": "answer", "direction": "output", "shape": {"type": "string"}}]},
        "inputs": {"question": "what is this?",
                   "photo": {"data": "AAAA", "media_type": "image/png"}}}))

    escape_entry = entry()
    escape_entry["template"]["messages"] = [
        {"role": "user", "text": "literal {{braces}} and {question}"}]
    cases.append(fill_expect({
        "name": "render-escapes", "kind": "render",
        "entry": escape_entry, "signature": QA_SIG,
        "inputs": {"question": "q"}}))

    scalar_sig = {"instructions": "x", "fields": [
        {"name": "q", "direction": "input", "shape": {"type": "string"}},
        {"name": "answer", "direction": "output", "shape": {"type": "string"}},
        {"name": "score", "direction": "output", "shape": {"type": "integer"}},
        {"name": "risk", "direction": "output",
         "shape": {"type": "string", "enum": ["low", "high"]}},
        {"name": "ok", "direction": "output", "shape": {"type": "boolean"}}]}
    cases.append(fill_expect({
        "name": "parse-sections-scalars", "kind": "parse",
        "entry": entry(), "signature": scalar_sig,
        "response": "<answer>\nParis\n<score>\n9\n<risk>\nhigh\n<ok>\ntrue\n</done>"}))

    inline_entry = entry(strategies={"reasoning": {
        "requires": [], "visible": False,
        "fragments": {"system": "Think inside <think>...</think> tags."},
        "routings": [{"extract": {"kind": "between", "open": "<think>",
                                  "close": "</think>"},
                      "field": "@role", "join": "\n", "strip": True}]}})
    cases.append(fill_expect({
        "name": "parse-inline-strategy-routing", "kind": "parse",
        "entry": inline_entry, "signature": REASONING_SIG,
        "response": "<answer>\nParis<think>capital</think> indeed.\n</done>"}))

    cases.append(fill_expect({
        "name": "roundtrip-data-only", "kind": "roundtrip",
        "entry": inline_entry}))

    cases.append({
        "name": "refuse-load-unknown-codec", "kind": "refuse",
        "entry": entry(codecs={"answer": {"kind": "no_such_codec"}}),
        "signature": QA_SIG, "expect": {"code": "unknown-codec", "at": "load"}})

    cases.append({
        "name": "refuse-bake-capability", "kind": "refuse", "vocab": ["std"],
        "entry": entry(strategies={"reasoning": {"kind": "native_reasoning"}},
                       versions={"kernel": KV, "vocab":
                                 {"strategy/native_reasoning": "0.1.0"}}),
        "signature": REASONING_SIG, "capabilities": {"instruct": True},
        "expect": {"code": "capability-missing", "at": "bake"}})

    uncovered_entry = entry()
    uncovered_entry["template"]["messages"] = [
        {"role": "user", "text": "{question}"}]
    cases.append({
        "name": "refuse-bake-uncovered-input", "kind": "refuse",
        "entry": uncovered_entry,
        "signature": {"instructions": "x", "fields": [
            {"name": "question", "direction": "input", "shape": {"type": "string"}},
            {"name": "extra", "direction": "input", "shape": {"type": "string"}},
            {"name": "answer", "direction": "output", "shape": {"type": "string"}}]},
        "expect": {"code": "field-uncovered", "at": "bake"}})

    cases.append({
        "name": "refuse-parse-missing-section", "kind": "refuse",
        "entry": entry(), "signature": QA_SIG,
        "response": "<answer>\nonly this\n</done>",
        "expect": {"code": "parse-missing-fields", "at": "parse"}})

    cases.append({
        "name": "refuse-load-version", "kind": "refuse",
        "entry": entry(versions={"kernel": "9.0.0", "vocab": {}}),
        "signature": QA_SIG,
        "expect": {"code": "version-incompatible", "at": "load"}})

    cases.append({
        "name": "refuse-bake-no-codec", "kind": "refuse",
        "entry": entry(),
        "signature": {"instructions": "x", "fields": [
            {"name": "q", "direction": "input", "shape": {"type": "string"}},
            {"name": "items", "direction": "output", "shape": {"type": "array"}}]},
        "expect": {"code": "no-codec", "at": "bake"}})

    cases.append(fill_expect({
        "name": "std-reasoning-tags", "kind": "parse", "vocab": ["std"],
        "entry": entry(strategies={"reasoning": {"kind": "reasoning_tags"}},
                       versions={"kernel": KV, "vocab":
                                 {"strategy/reasoning_tags": "0.1.0"}}),
        "signature": REASONING_SIG, "capabilities": {"instruct": True},
        "response": "<answer>\nParis<think>capital</think> indeed.\n</done>"}))

    json_sig = {"instructions": "Extract.", "fields": [
        {"name": "q", "direction": "input", "shape": {"type": "string"}},
        {"name": "items", "direction": "output",
         "shape": {"type": "array", "items": {"type": "string"}}}]}
    cases.append(fill_expect({
        "name": "std-json-codec", "kind": "parse", "vocab": ["std"],
        "entry": entry(codecs={"items": {"kind": "json"}},
                       versions={"kernel": KV, "vocab": {"codec/json": "0.1.0"}}),
        "signature": json_sig,
        "response": "<items>\n```json\n[\"a\", \"b\"]\n```\n</done>"}))

    table_sig = {"instructions": "Rank.", "fields": [
        {"name": "q", "direction": "input", "shape": {"type": "string"}},
        {"name": "rows", "direction": "output",
         "shape": {"type": "array", "items": {"type": "object", "properties": {
             "name": {"type": "string"}, "score": {"type": "integer"}}}}}]}
    table_entry = entry(
        codecs={"rows": {"kind": "table",
                         "options": {"columns": ["name", "score"]}}},
        versions={"kernel": KV, "vocab": {"codec/table": "0.1.0"}})
    cases.append(fill_expect({
        "name": "std-table-codec-demo-lens", "kind": "render", "vocab": ["std"],
        "entry": table_entry, "signature": table_sig,
        "inputs": {"q": "rank these"},
        "demos": [{"q": "rank those",
                   "rows": [{"name": "a|b", "score": 3},
                            {"name": "c", "score": 1}]}]}))
    cases.append(fill_expect({
        "name": "std-table-codec-parse", "kind": "parse", "vocab": ["std"],
        "entry": table_entry, "signature": table_sig,
        "response": "<rows>\n| name | score |\n| carol | 9 |\n</done>"}))

    scaled_sig = {"instructions": "x", "fields": [
        {"name": "q", "direction": "input", "shape": {"type": "string"}},
        {"name": "confidence", "direction": "output", "shape": {"type": "number"}}]}
    cases.append(fill_expect({
        "name": "std-scaled-number", "kind": "parse", "vocab": ["std"],
        "entry": entry(codecs={"confidence": {
            "kind": "scaled_number",
            "options": {"scale": 100, "suffix": "%", "round": 0}}},
            versions={"kernel": KV,
                      "vocab": {"codec/scaled_number": "0.1.0"}}),
        "signature": scaled_sig,
        "response": "<confidence>\n83%\n</done>"}))

    CASES.mkdir(parents=True, exist_ok=True)
    for i, case in enumerate(cases, start=1):
        path = CASES / f"{i:02d}-{case['name']}.json"
        path.write_text(json.dumps(case, indent=1, ensure_ascii=False) + "\n")
        print("wrote", path.name)


if __name__ == "__main__":
    main()

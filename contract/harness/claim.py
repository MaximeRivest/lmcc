"""The conformance claim a kernel without UDF placement must print (kernel §9).

    python contract/harness/claim.py            # "205 passed, 0 failed, 6 unclaimed (udf:python), 72 stream traces match"

Every case but those needing udf:python, and a stream trace for every
claimed parse case. ./check greps each driver's report for this exact line,
so a kernel that silently stops claiming a case fails the check.
"""
import glob
import json
from pathlib import Path

CASES = Path(__file__).resolve().parent.parent / "corpus" / "cases"
cases = [json.load(open(f, encoding="utf-8")) for f in glob.glob(str(CASES / "*.json"))]
udf = [c for c in cases if any(r.startswith("udf:") for r in c.get("requires", []))]
traced = [c for c in cases if c not in udf and "response" in c and (c["kind"] == "parse" or c["expect"].get("at") == "parse")]
print(f"{len(cases) - len(udf)} passed, 0 failed, {len(udf)} unclaimed (udf:python), {len(traced)} stream traces match")

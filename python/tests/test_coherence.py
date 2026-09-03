"""The map is verified, not trusted: documentation claims are tests.

The corpus made *behavior* drift impossible; this file does the same for
the *documents*. Every cross-link the tower relies on — error codes,
the vocabulary index, corpus case naming — is checked mechanically, so
an agent reading the docs is reading verified claims.
"""

import ast
import json
import pathlib
import re

import lmcc
import lmcc_std

ROOT = pathlib.Path(lmcc.__file__).resolve().parent.parent.parent
SPEC = ROOT / "contract" / "spec"
CASES = ROOT / "contract" / "corpus" / "cases"


def _documented_codes() -> set[str]:
    text = (SPEC / "errors.md").read_text()
    return set(re.findall(r"^\| `([a-z0-9-]+)` \|", text, re.MULTILINE))


def _raised_codes() -> set[str]:
    codes: set[str] = set()
    for pkg in ("lmcc", "lmcc_std"):
        for py in sorted((ROOT / "python" / pkg).glob("*.py")):
            tree = ast.parse(py.read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "refuse"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    codes.add(node.args[0].value)
    return codes


def test_every_raised_code_is_documented():
    undocumented = _raised_codes() - _documented_codes()
    assert not undocumented, (
        f"codes raised in source but missing from spec/errors.md: "
        f"{sorted(undocumented)}")


def test_every_corpus_refusal_code_is_documented():
    documented = _documented_codes()
    for path in sorted(CASES.glob("*.json")):
        case = json.loads(path.read_text())
        if case["kind"] == "refuse":
            code = case["expect"]["code"]
            assert code in documented, f"{path.name}: {code!r} not in errors.md"


def test_corpus_case_names_match_filenames():
    for path in sorted(CASES.glob("*.json")):
        case = json.loads(path.read_text())
        number, _, name = path.stem.partition("-")
        assert number.isdigit(), f"{path.name}: expected NN-name.json"
        assert case["name"] == name, (
            f"{path.name}: file says {name!r}, case says {case['name']!r}")
        assert case["kind"] in ("render", "parse", "roundtrip", "refuse")


def test_vocab_index_is_complete_and_spec_files_exist():
    """Every registered std entry has a row in the vocab index; every
    row's spec file exists. The index cannot silently rot."""
    registry = lmcc.Registry()
    lmcc_std.install(registry)
    index = (SPEC / "vocab" / "README.md").read_text()
    for name in registry.codecs:
        assert f"`codec/{name}`" in index, f"codec/{name} missing from index"
    for name in registry.strategies:
        assert f"`strategy/{name}`" in index, f"strategy/{name} missing"
    for name in registry.lenses:
        assert f"`lens/{name}`" in index, f"lens/{name} missing from index"
    for entry, spec_file in re.findall(r"^\| `([\w/]+)` \| `([\w.-]+)` \|$",
                                       index, re.MULTILINE):
        assert (SPEC / "vocab" / spec_file).exists(), (
            f"index row {entry} points at missing spec file {spec_file}")


def test_capability_facts_used_by_std_are_in_the_vocabulary():
    """Std strategies/lenses may only name declared capability facts."""
    vocab = set(re.findall(r"^\| `([a-z_]+)` \|",
                           (SPEC / "vocab" / "capabilities.md").read_text(),
                           re.MULTILINE))
    registry = lmcc.Registry()
    lmcc_std.install(registry)
    for name, entry in registry.strategies.items():
        strategy = entry.factory({})
        for fact in strategy.requires:
            assert fact in vocab, f"strategy {name}: unknown fact {fact!r}"
    for name, entry in registry.lenses.items():
        lens = entry.factory({"kind": name})
        for fact in lens.requires():
            assert fact in vocab, f"lens {name}: unknown fact {fact!r}"


def test_plans_have_acceptance_criteria():
    """A plan without acceptance criteria is a wish (plans/README.md)."""
    plans = sorted((ROOT / "plans").glob("[0-9]*.md"))
    assert plans, "the work queue exists"
    for plan in plans:
        text = plan.read_text().lower()
        assert "acceptance" in text, f"{plan.name} has no acceptance criteria"

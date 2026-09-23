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


def _refuse_calls():
    """Every ``refuse("<code>", ...)`` call in the Python packages:
    (file, line, code, fix keyword node or None)."""
    for pkg in ("lmcc", "lmcc_std", "lmcc_dspy"):
        for py in sorted((ROOT / "python" / pkg).glob("*.py")):
            tree = ast.parse(py.read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in ("refuse",)
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    fix = next((k.value for k in node.keywords if k.arg == "fix"), None)
                    yield f"{py.name}:{node.lineno}", node.args[0].value, fix


def _raised_codes() -> set[str]:
    return {code for _, code, _ in _refuse_calls()}


def _documented_fixes() -> dict[str, set[str]]:
    """code -> the fix actions errors.md lists for it (empty when '—')."""
    text = (SPEC / "errors.md").read_text()
    out: dict[str, set[str]] = {}
    for code, actions in re.findall(r"^\| `([a-z0-9-]+)` \| [^|]+ \| ([^|]+) \|", text, re.MULTILINE):
        out[code] = set(re.findall(r"`([a-z-]+)`", actions))
    return out


def _documented_actions() -> dict[str, tuple[set[str], set[str]]]:
    """action -> (required parameters, optional parameters), from the
    fix-actions table in errors.md."""
    text = (SPEC / "errors.md").read_text().replace("\\|", "/")   # escaped pipes inside cells
    table = text[text.index("## Fix actions"):]
    out = {}
    for action, params in re.findall(r"^\| `([a-z-]+)` \| ([^|]+) \|", table, re.MULTILINE):
        required, optional = set(), set()
        for name, opt in re.findall(r"`([a-z]+)`(?: \([^)]*\))?(\?)?", params):
            (optional if opt else required).add(name)
        out[action] = (required, optional)
    return out


def test_every_raised_code_is_documented():
    undocumented = _raised_codes() - _documented_codes()
    assert not undocumented, (
        f"codes raised in source but missing from spec/errors.md: "
        f"{sorted(undocumented)}")


def test_every_documented_code_is_raised():
    """The other direction: a code in spec/errors.md that no source raises
    is dead contract. (Fix actions share the table form; they are checked
    by the fix-action tests.)"""
    dead = _documented_codes() - set(_documented_actions()) - _raised_codes()
    assert not dead, f"codes documented in spec/errors.md but never raised: {sorted(dead)}"


def _fix_action(fix_node) -> str | None:
    """The action literal of a fix expression when it is one statically:
    a dict literal, ``{**base, ...}`` over one, or a helper call whose
    name says the action."""
    if isinstance(fix_node, ast.Dict):
        for k, v in zip(fix_node.keys, fix_node.values):
            if isinstance(k, ast.Constant) and k.value == "action" and isinstance(v, ast.Constant):
                return v.value
    return None


def test_fix_actions_are_documented_and_closed():
    """Every action a Python call site writes is in the closed table; every
    documented action is emitted somewhere (the table cannot rot)."""
    documented = _documented_actions()
    assert documented, "errors.md has a fix-actions table"
    schema = json.loads((ROOT / "contract" / "schema" / "fix.schema.json").read_text())
    in_schema = {b["properties"]["action"]["const"] for b in schema["oneOf"]}
    assert in_schema == set(documented), "fix.schema.json and errors.md list the same actions"
    emitted = {a for _, _, fix in _refuse_calls() if (a := _fix_action(fix))}
    assert emitted <= set(documented), f"undocumented fix actions: {sorted(emitted - set(documented))}"
    assert emitted == set(documented), (
        f"documented actions no call site writes: {sorted(set(documented) - emitted)}")


def test_every_pre_render_refusal_carries_a_fix():
    """The rule of errors.md, mechanically: a code the table gives a fix
    passes ``fix=`` at every call site, with an action from its row; a
    code marked '—' never does."""
    fixes = _documented_fixes()
    for where, code, fix in _refuse_calls():
        allowed = fixes.get(code, set())
        if allowed:
            assert fix is not None, f"{where}: refuse({code!r}) carries no fix; errors.md says {sorted(allowed)}"
            action = _fix_action(fix)
            if action is not None:
                assert action in allowed, f"{where}: fix {action!r} is not one of {sorted(allowed)} for {code!r}"
        else:
            assert fix is None, f"{where}: refuse({code!r}) carries a fix, but errors.md says it carries none"


def test_every_corpus_fix_matches_the_closed_vocabulary():
    """Corpus fixes name a documented action with exactly its parameters."""
    documented = _documented_actions()
    seen = set()
    for path in sorted(CASES.glob("*.json")):
        case = json.loads(path.read_text())
        if case["kind"] != "refuse":
            continue
        if case["expect"]["at"] in ("load", "signature", "bind"):
            assert "fix" in case["expect"], f"{path.name}: a pre-render refuse case pins its fix"
        fix = case["expect"].get("fix")
        if fix is None:
            continue
        required, optional = documented[fix["action"]]
        keys = set(fix) - {"action"}
        assert required <= keys <= required | optional, (
            f"{path.name}: fix {fix['action']!r} has parameters {sorted(keys)}, "
            f"wants {sorted(required)} (+ optional {sorted(optional)})")
        assert fix["action"] in _documented_fixes()[case["expect"]["code"]], (
            f"{path.name}: {fix['action']!r} is not a fix errors.md lists for {case['expect']['code']!r}")
        seen.add(fix["action"])
    unpinned = set(documented) - seen
    assert not unpinned, f"documented fix actions with no corpus case: {sorted(unpinned)}"


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
        assert case["kind"] in ("render", "parse", "roundtrip", "refuse", "plan")


def test_vocab_index_is_complete_and_spec_files_exist():
    """Every registered std entry has a row in the vocab index; every
    row's spec file exists. The index cannot silently rot."""
    registry = lmcc.Registry()
    lmcc_std.install(registry)
    index = (SPEC / "vocab" / "README.md").read_text()
    for name in registry.formats:
        assert f"`format/{name}`" in index, f"format/{name} missing from index"
    for name in registry.transports:
        assert f"`transport/{name}`" in index, f"transport/{name} missing"
    for name in registry.readers:
        assert f"`reader/{name}`" in index, f"reader/{name} missing from index"
    for entry, spec_file in re.findall(r"^\| `([\w/]+)` \| `([\w.-]+)` \|$",
                                       index, re.MULTILINE):
        assert (SPEC / "vocab" / spec_file).exists(), (
            f"index row {entry} points at missing spec file {spec_file}")


def test_extension_index_is_complete():
    """Every extension the kernel binds natively has an index row with a
    real spec file at the same version (kernel §10,
    spec/extensions/README.md), so a "core + these" claim means one thing
    for any implementation that makes it."""
    index = (SPEC / "extensions" / "README.md").read_text()
    rows = {name: (version, spec_file) for name, version, spec_file in re.findall(
        r"^\| `[a-z_]+` \| [^|]+ \| `([a-z0-9_/-]+)` \| ([0-9.]+) \| `([a-z0-9_.-]+\.md)` \|",
        index, re.MULTILINE)}
    assert rows, "the extension index has rows"
    for version, spec_file in rows.values():
        assert (SPEC / "extensions" / spec_file).exists(), f"missing spec file {spec_file}"
        assert f"version {version}" in (SPEC / "extensions" / spec_file).read_text()
    python = {b.extension: b.version for b in lmcc.native_extensions()}
    for name, version in python.items():
        assert name in rows and rows[name][0] == version, f"{name} {version} is not indexed"


def test_capability_facts_used_by_std_are_in_the_vocabulary():
    """Std transports/readers may only name declared capability facts."""
    vocab = set(re.findall(r"^\| `([a-z_]+)` \|",
                           (SPEC / "vocab" / "capabilities.md").read_text(),
                           re.MULTILINE))
    registry = lmcc.Registry()
    lmcc_std.install(registry)
    for name, entry in registry.transports.items():
        transport = entry.factory({})
        for fact in transport.requires:
            assert fact in vocab, f"transport {name}: unknown fact {fact!r}"
    for name, entry in registry.readers.items():
        reader = entry.factory({"kind": name})
        for fact in reader.requires():
            assert fact in vocab, f"reader {name}: unknown fact {fact!r}"


def test_plans_have_acceptance_criteria():
    """A plan without acceptance criteria is a wish (plans/README.md)."""
    plans = sorted((ROOT / "plans").glob("[0-9]*.md"))
    assert plans, "the work queue exists"
    for plan in plans:
        text = plan.read_text().lower()
        assert "acceptance" in text, f"{plan.name} has no acceptance criteria"

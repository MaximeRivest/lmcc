"""The agent cockpit invariants: plans and registries are data; the
kernel speaks stdlib only. See AGENTS.md."""

import ast
import json
import pathlib

import a15
import a15_std

STDLIB = {"__future__", "dataclasses", "json", "re", "typing"}


def test_kernel_imports_stdlib_only():
    """The kernel must be rewritable in any language in a weekend; its
    import list is part of that promise."""
    root = pathlib.Path(a15.__file__).parent
    for py in sorted(root.glob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top in STDLIB, f"{py.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                top = (node.module or "").split(".")[0]
                assert top in STDLIB, f"{py.name} imports from {node.module}"


def _baked():
    registry = a15.Registry()
    a15_std.install(registry)
    sig = a15.signature(
        "Answer.", inputs={"q": str},
        outputs={"reasoning": a15.field(str, role="reasoning"),
                 "answer": a15.field(str, desc="short answer")})
    adp = a15.adapter(
        template=a15.template([
            a15.message("system", "{instruction}\n{% for f in outputs %}"
                        "<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
            a15.message("user", "{q}"),
        ]),
        parse={"kind": "derived"},
        strategies={"reasoning": "reasoning_tags"})
    return adp.bake(sig, {"instruct": True}, registry=registry), registry


def test_plan_describe_is_plain_data():
    baked, _ = _baked()
    d = baked.describe()
    json.dumps(d)  # serializable, or it is not data
    assert d["lens"]["kind"] == "derived"
    assert d["lens"]["anchors"] == [["answer", "<answer>\n", "\n</answer>\n"]]
    assert d["hidden"] == ["reasoning"]
    assert d["strategies"] == {"reasoning": "reasoning_tags"}
    assert d["outputs"][0]["name"] == "answer"


def test_explain_is_a_view_over_describe():
    baked, _ = _baked()
    text = baked.explain()
    assert baked.adapter.name in text
    assert "derived" in text


def test_registry_describe_is_plain_data():
    _, registry = _baked()
    d = registry.describe()
    json.dumps(d)
    assert d["codecs"]["json"] == "0.1.0"
    assert d["lenses"]["sections"] == "kernel"
    assert d["lenses"]["json_object"] == "0.1.0"
    assert "reasoning_tags" in d["strategies"]

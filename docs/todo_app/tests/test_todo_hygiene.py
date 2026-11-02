import ast
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]

ALLOWED_IMPORTS = {
    "__future__", "abc", "argparse", "dataclasses", "enum", "json", "os",
    "pathlib", "re", "sys", "tempfile", "typing",
}
EXPECTED_MODULES = {
    "__init__.py", "__main__.py", "cli.py", "errors.py", "formatter.py",
    "ids.py", "service.py", "store.py", "task.py",
}


def _module_paths():
    return sorted(PACKAGE_DIR.glob("*.py"))


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))


def _annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                yield node.returns
            args = node.args
            every = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
            every += [a for a in (args.vararg, args.kwarg) if a is not None]
            for arg in every:
                if arg.annotation is not None:
                    yield arg.annotation
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def test_expected_modules_are_present():
    assert EXPECTED_MODULES <= {p.name for p in _module_paths()}


@pytest.mark.parametrize("path", _module_paths(), ids=lambda p: p.name)
def test_module_parses_as_python_39_and_uses_only_allowed_imports(path):
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in ALLOWED_IMPORTS, (path.name, alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert (node.module or "").split(".")[0] in ALLOWED_IMPORTS, (path.name, node.module)
        match_cls = getattr(ast, "Match", None)
        if match_cls is not None:
            assert not isinstance(node, match_cls), path.name


@pytest.mark.parametrize("path", _module_paths(), ids=lambda p: p.name)
def test_no_union_operator_in_annotations(path):
    for annotation in _annotations(_parse(path)):
        for node in ast.walk(annotation):
            assert not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)), path.name


def test_readme_has_required_headings():
    lines = (PACKAGE_DIR / "README.md").read_text(encoding="utf-8").splitlines()
    headings = {line.lstrip("#").strip() for line in lines if line.startswith("## ")}
    assert {"Run", "Test", "Assumptions", "Limitations"} <= headings

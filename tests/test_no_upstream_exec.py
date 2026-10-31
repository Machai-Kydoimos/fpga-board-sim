"""Nothing in the sync tooling may execute code it did not write (U56 decision D-7).

The Amaranth and LiteX parsers once ran every upstream board file with ``exec``.
They now read them with ``scripts/upstream_reader.py``, which never compiles
upstream code. This guard keeps the old way from coming back by any door: no module
under ``scripts/`` calls ``exec``, ``eval``, ``compile`` or ``__import__``, or reaches
``importlib`` / ``runpy``. It is a shape rule over the AST, like
``tests/test_no_input_polling.py``, so a comment or a string mentioning these names is
not a hit, and ``re.compile`` (a method, not the builtin) is not either.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_BANNED_CALLS = {"exec", "eval", "compile", "__import__"}
_BANNED_MODULES = {"importlib", "runpy"}


def _violations(source: str, name: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source, name)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BANNED_CALLS:
                found.append(f"{name}:{node.lineno}: {node.func.id}()")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _BANNED_MODULES:
                    found.append(f"{name}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _BANNED_MODULES:
                found.append(f"{name}:{node.lineno}: from {node.module} import ...")
    return found


def test_no_script_executes_code_it_did_not_write():
    files = sorted(SCRIPTS.rglob("*.py"))
    assert len(files) > 10, "the scripts/ tree moved; point this guard at it"
    found: list[str] = []
    for path in files:
        found += _violations(path.read_text(encoding="utf-8"), str(path.relative_to(SCRIPTS)))
    assert not found, "D-7: read upstream code, never execute it:\n" + "\n".join(found)


def test_the_guard_catches_each_door():
    # A guard that can rot silently is no guard: prove every banned shape is a hit.
    planted = (
        "exec(src)\n"
        "eval('1')\n"
        "code = compile(src, 'f', 'exec')\n"
        "os = __import__('os')\n"
        "import importlib\n"
        "from runpy import run_path\n"
        "import importlib.util as u\n"
    )
    assert len(_violations(planted, "planted.py")) == 7
    assert _violations("import re\npat = re.compile('x')\n# exec(src)\ns = 'eval(1)'\n", "ok") == []

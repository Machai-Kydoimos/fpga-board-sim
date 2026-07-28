#!/usr/bin/env python3
"""Flag text I/O that does not name its encoding, without needing type inference.

Omitting ``encoding=`` makes Python use the *locale* default: UTF-8 on Linux and
macOS, cp1252 on Windows.  The same bytes then decode to different text per
platform, and because cp1252 has a mapping for nearly every byte the usual
result is silent mojibake rather than an exception -- a UTF-8 em-dash comes
back as three garbage characters and the run stays green.  Only five bytes
(0x81, 0x8D, 0x8F, 0x90, 0x9D) raise at all.

Ruff's ``PLW1514`` covers the same ground but only where it can *prove* the
receiver is a ``pathlib.Path``.  On this repo that was 11 of 323 real sites: it
sees ``_WRAPPER_TEMPLATE: Path = ...`` and misses ``SESSION_FILE = Path.home()
/ ...``, every unannotated ``tmp_path`` fixture in the test suite is invisible
to it, and it does not inspect ``subprocess`` at all.  This check closes those
gaps by matching on *names* instead of inferred types, which is sound here
because the names are unambiguous: ``read_text``/``write_text`` exist only on
``Path``, and ``subprocess.run(text=True)`` declares its own mode.

It is deliberately the static half of a pair.  The runtime half -- pytest
promoting ``EncodingWarning`` to an error under ``PYTHONWARNDEFAULTENCODING=1``
-- catches dynamically constructed calls this cannot see, but only on code some
test executes, and its ``subprocess`` coverage needs Python 3.13+.  See
CONTRIBUTING's "Spelling and text encoding".

Self-contained: no ``fpga_sim`` import, no third-party dependency, no network.
Runs as a pre-commit hook over changed files and over the whole tree from
``tests/test_check_encoding.py``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Methods that exist only on ``pathlib.Path`` and always do text I/O.
TEXT_METHODS = {"read_text", "write_text"}

#: ``X.open(...)`` for these X is not a text-file open -- tarfile/gzip/zipfile
#: take a binary ``mode`` and PIL takes an image.  None accepts ``encoding``, so
#: "fixing" one would be a runtime TypeError.
NOT_TEXT_OPEN = {"tarfile", "zipfile", "gzip", "bz2", "lzma", "Image", "io", "socket", "shelve"}

#: ``subprocess`` entry points that decode child output when in text mode.
SUBPROCESS_CALLS = {"run", "Popen", "check_output", "call", "check_call"}

#: Keywords that put a subprocess call into text mode.
TEXT_FLAGS = {"text", "universal_newlines"}


def _has_kwarg(call: ast.Call, name: str) -> bool:
    return any(k.arg == name for k in call.keywords)


def _mode_is_binary(call: ast.Call) -> bool:
    """Report whether the call's *mode* argument selects a non-text mode.

    Only the mode position is inspected.  Scanning every positional string
    argument instead is subtly wrong: ``write_text`` takes its payload
    positionally, so a payload like ``'{"type": "object"}'`` would read as
    binary purely because *object* contains a ``b``.
    """
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS:
        return False  # read_text/write_text have no mode parameter at all
    # builtin open(file, mode) -> args[1]; Path.open(mode) -> args[0]
    index = 1 if isinstance(func, ast.Name) else 0
    modes: list[ast.expr] = list(call.args[index : index + 1])
    modes += [k.value for k in call.keywords if k.arg == "mode"]
    return any(
        isinstance(m, ast.Constant)
        and isinstance(m.value, str)
        and ("b" in m.value or ":" in m.value)
        for m in modes
    )


def _subprocess_problem(call: ast.Call, func: ast.Attribute) -> str | None:
    if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
        return None
    in_text_mode = any(
        k.arg in TEXT_FLAGS and isinstance(k.value, ast.Constant) and k.value.value is True
        for k in call.keywords
    )
    if in_text_mode and not _has_kwarg(call, "encoding"):
        return f"subprocess.{func.attr}(text=True) without encoding="
    return None


def problem(call: ast.Call) -> str | None:
    """Describe why this call needs an explicit encoding, or None if it is fine."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in SUBPROCESS_CALLS:
        return _subprocess_problem(call, func)

    if isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS:
        target = f"Path.{func.attr}()"
    elif isinstance(func, ast.Attribute) and func.attr == "open":
        if isinstance(func.value, ast.Name) and func.value.id in NOT_TEXT_OPEN:
            return None
        target = "Path.open()"
    elif isinstance(func, ast.Name) and func.id == "open":
        target = "open()"
    else:
        return None

    if _has_kwarg(call, "encoding") or _mode_is_binary(call):
        return None
    return f"{target} without encoding="


def check_source(source: str, label: str) -> list[str]:
    """Return one message per offending call site in ``source``."""
    return [
        f"{label}:{node.lineno}: {message}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and (message := problem(node))
    ]


def check_paths(paths: list[Path]) -> list[str]:
    """Return every finding across ``paths``, deepest detail first."""
    findings: list[str] = []
    for path in paths:
        try:
            findings += check_source(path.read_text(encoding="utf-8"), str(path))
        except SyntaxError as exc:
            findings.append(f"{path}: cannot parse: {exc}")
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Takes the files to check, as pre-commit passes them."""
    names = sys.argv[1:] if argv is None else argv
    if not names:
        print(f"usage: {Path(__file__).name} FILE [FILE ...]", file=sys.stderr)
        return 2

    findings = check_paths([Path(n) for n in names])
    if findings:
        print(f"Implicit text encoding ({len(findings)} site(s)):", flush=True)
        for finding in findings:
            print(f"  {finding}", flush=True)
        print(
            '\nPass encoding="utf-8" explicitly. For third-party tool output '
            '(subprocess), add errors="replace" so a stray byte degrades instead '
            "of raising. See CONTRIBUTING: Spelling and text encoding.",
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

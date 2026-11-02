"""The LiteX sync hands the parser upstream's extension modules, and nothing else (U56 Phase 4)."""

from __future__ import annotations

import io
import tarfile

from sync_litex_boards import extract_board_files, extract_modules


def _archive(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"litex-hub-litex-boards-97186cf/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


_ARCHIVE = _archive(
    {
        "litex_boards/extensions/__init__.py": "",
        "litex_boards/extensions/sipeed.py": "class Dock: pass\n",
        "litex_boards/extensions/pmod.py": "class Pmod: pass\n",
        "litex_boards/compat.py": "def warn_deprecated(*a): pass\n",
        "litex_boards/platforms/sipeed_tang_primer_20k.py": "_io = []\n",
        "litex_boards/targets/sipeed_tang_primer_20k.py": "x = 1\n",
    }
)


def test_only_extension_modules_are_handed_over_by_dotted_name():
    """Never a board file, whose Platform could pass for the importer's own; never compat."""
    assert sorted(extract_modules(_ARCHIVE)) == [
        "litex_boards.extensions",
        "litex_boards.extensions.pmod",
        "litex_boards.extensions.sipeed",
    ]
    assert extract_modules(_ARCHIVE)["litex_boards.extensions.sipeed"] == "class Dock: pass\n"


def test_board_files_are_still_the_platforms_alone():
    assert list(extract_board_files(_ARCHIVE)) == ["sipeed_tang_primer_20k.py"]

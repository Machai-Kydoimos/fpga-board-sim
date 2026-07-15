# Installation

Full install reference for the FPGA board simulator: how to install a VHDL
simulator on every supported platform, set up the Python environment, and fix the
common problems. The [README](../README.md) has the short happy-path version; this
is the complete matrix, including from-source builds and the Windows specifics.

## Prerequisites

- **Python 3.10+**, installed as a **standalone** interpreter (not the Windows
  Store build — see [Set up the Python environment](#set-up-the-python-environment)).
- **One VHDL simulator**, either [GHDL](#ghdl) or [NVC](#nvc). Both can coexist;
  the active one is chosen by the in-app `SIM:` toggle or the `--sim` flag.
- **git**, to clone the repository.

```bash
git clone https://github.com/Machai-Kydoimos/fpga-board-sim.git
cd fpga-board-sim
```

## Install a VHDL simulator

You need at least one of GHDL or NVC. On Linux and macOS both are fully tested. On
Windows, **GHDL is the tested choice**; NVC installs but its cocotb VHPI pipeline
has not been verified there.

### GHDL

**Windows:**

```powershell
winget install ghdl.ghdl.ucrt64.mcode
```

**Linux (Ubuntu/Debian):**

```bash
sudo apt install ghdl
```

**Linux (Fedora):**

```bash
sudo dnf install ghdl
```

**macOS:**

```bash
brew install ghdl
```

### NVC

**Windows (native — PowerShell):**

```powershell
winget install NickGasson.NVC
```

> NVC is available on Windows but has **not been tested** with this simulator's
> cocotb VHPI pipeline on Windows. GHDL is the fully tested choice. If you try NVC
> on Windows, please report results in an issue.
>
> For a more Linux-like environment where NVC is more likely to work end-to-end,
> see [Windows: MSYS2 alternative](#windows-msys2-alternative) below.

**macOS / Linux (Homebrew):**

```bash
brew install nvc
```

**Arch Linux (AUR):**

```bash
yay -S nvc   # or your preferred AUR helper
```

**Gentoo:**

```bash
sudo emerge sci-electronics/nvc
```

**FreeBSD:**

```bash
sudo pkg install nvc
```

**Linux (from source — Debian/Ubuntu):**

```bash
# Install build dependencies:
sudo apt install build-essential automake autoconf flex check \
  llvm-dev pkg-config zlib1g-dev libdw-dev libffi-dev libzstd-dev

git clone https://github.com/nickg/nvc && cd nvc
./autogen.sh && mkdir build && cd build
../configure && make -j$(nproc) && sudo make install
```

**Linux (from source — Fedora/RHEL):**

```bash
sudo dnf install autoconf automake flex check llvm-devel \
  libffi-devel zlib-ng-compat-devel libzstd-devel elfutils-devel
```

See the [NVC build guide](https://github.com/nickg/nvc#building-from-source) for full instructions.

## Set up the Python environment

`uv` manages the venv and all dependencies automatically. It also installs a
standalone Python when needed — which matters on Windows, where the Windows Store
Python is sandboxed and can't be embedded by an external simulator process.

```bash
uv sync
```

That installs runtime dependencies. Contributors want `uv sync --group dev`
(pytest, ruff, mypy, pre-commit) — see [CONTRIBUTING.md](../CONTRIBUTING.md).

To confirm the install works, run the test suite — it needs no display and
exercises the full analyze/simulate path on both installed simulators:

```bash
uv run pytest
```

## Windows run notes

The launcher requires **PowerShell** (it does not work in Command Prompt):

```powershell
uv run fpga-sim                 # uses saved/default simulator
uv run fpga-sim --sim ghdl      # force GHDL (fully tested on Windows)
uv run fpga-sim --sim nvc       # NVC (available via winget; untested on Windows)
```

> GHDL must be on your `PATH`. If the command fails with "ghdl not found", see
> [Windows: GHDL not on PATH](#windows-ghdl-not-on-path-after-winget-install) below.

## pygame-ce

[pygame-ce](https://github.com/pygame-community/pygame-ce) (community edition) is an
actively maintained fork that uses the identical `import pygame` API. It cannot
coexist with standard `pygame` in the same environment — you must uninstall one
before installing the other. It has not been tested with this project, but should
work as a drop-in replacement.

## Troubleshooting

### No board definitions found

If the `boards/` directory is missing or empty:

```text
No board definitions found; using generic board.
```

Fix: run one or more sync scripts:

```bash
uv run python scripts/sync_amaranth_boards.py  # amaranth-boards
uv run python scripts/sync_litex_boards.py     # litex-boards
uv run python scripts/sync_digilent_xdc.py     # Digilent XDC
```

### Windows: Python DLL not found (`hon313.dll` / `python313.dll`)

If `test_cocotb_simulation_passes` fails with:

```text
Unable to open lib hon313.dll: The specified module could not be found.
```

GHDL cannot locate the Python shared library. `fpga_sim/sim_bridge.py` auto-detects
it via `cocotb-config --libpython` on Windows, so this should not occur on current
checkouts. If you see it on an older checkout, set the path manually before running:

```powershell
$env:LIBPYTHON_LOC = (uv run cocotb-config --libpython)
uv run pytest
```

### Windows: GHDL not on PATH after `winget install`

**Step 1 — open a new PowerShell window.** `winget` updates the system PATH but the
change is not visible to terminals that were already open.

**Step 2 — if GHDL is still not found**, add it to your PATH permanently:

1. Press **Win + R**, type `sysdm.cpl`, and press Enter.
2. Go to **Advanced → Environment Variables**.
3. Under *User variables*, select **Path** and click **Edit → New**.
4. Paste the path shown by `where.exe ghdl` (or the `bin` directory from the winget
   package, typically inside
   `%LOCALAPPDATA%\Microsoft\WinGet\Packages\ghdl.ghdl.ucrt64.mcode_…\bin`).
5. Click OK, then open a new PowerShell window.

**For a single session only** (no registry change):

```powershell
$env:PATH = "C:\Users\$env:USERNAME\AppData\Local\Microsoft\WinGet\Packages\ghdl.ghdl.ucrt64.mcode_Microsoft.Winget.Source_8wekyb3d8bbwe\bin;$env:PATH"
```

**If `winget install ghdl.ghdl.ucrt64.mcode` is unavailable** (the package's presence
in the Microsoft winget repository is not guaranteed), install via
[MSYS2](https://www.msys2.org/) instead — open an **MSYS2 UCRT64** shell and run:

```bash
pacman -S mingw-w64-ucrt-x86_64-ghdl
```

### Windows: MSYS2 alternative

[MSYS2](https://www.msys2.org/) provides a Linux-like shell environment on Windows.
It is optional — the native PowerShell path works for GHDL — but it is the best
choice if you want NVC on Windows, or if you prefer a Unix-style workflow.

**1. Install MSYS2** from [msys2.org](https://www.msys2.org/), then open the
**UCRT64** shell (search for "MSYS2 UCRT64" in the Start menu).

> Use the **UCRT64** variant (not MINGW64 or CLANG64). It is the recommended
> modern environment and matches the `ucrt64` GHDL winget package.

**2. Update the package database:**

```bash
pacman -Syu
```

Close and reopen the UCRT64 shell if prompted, then run `pacman -Syu` again.

**3. Install simulators:**

```bash
# GHDL (fully tested):
pacman -S mingw-w64-ucrt-x86_64-ghdl

# NVC (available; VHPI integration with this simulator is untested on Windows):
pacman -S mingw-w64-ucrt-x86_64-nvc
```

**4. Install uv and Python inside MSYS2:**

```bash
pacman -S mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-uv
```

Or use the standalone `uv` installer from inside the MSYS2 shell:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**5. Clone and run** exactly as on Linux:

```bash
git clone https://github.com/Machai-Kydoimos/fpga-board-sim.git
cd fpga-board-sim
uv sync
uv run fpga-sim
```

> **Important:** Tools installed in MSYS2 are not visible to native PowerShell, and
> vice versa. Pick one environment and use it consistently. If you installed GHDL via
> `winget` and also install it via `pacman`, they are independent installations on
> separate `PATH`s.

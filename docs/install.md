# Installation

Full install reference for the FPGA board simulator: how to install a VHDL
simulator on every supported platform, set up the Python environment, and fix the
common problems. The [README](../README.md) has the short happy-path version; this
is the complete matrix, including from-source builds and the Windows specifics.
Once it is installed, [docs/first_design.md](first_design.md) walks you through your
first run; [docs/troubleshooting.md](troubleshooting.md) is indexed by symptom and
covers everything past the install.

## Prerequisites

- **Python 3.10–3.14**, installed as a **standalone** interpreter (not the Windows
  Store build — see [Set up the Python environment](#set-up-the-python-environment)).
  The upper bound is cocotb's: it has no 3.15 wheel yet. You do not have to do
  anything about it — `uv` reads the bound from `pyproject.toml` and fetches a
  suitable interpreter itself, even if the only Python on your machine is newer.
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
has not been verified there. Unsure which (or which build of which)? See
[Which to install — recommendations](#which-to-install--recommendations) below.

### GHDL

**Windows:**

```powershell
winget install ghdl.ghdl.ucrt64.mcode
```

> This is the path a scheduled CI workflow re-runs on a clean `windows-latest`
> runner — the package identifier, the install, and `ghdl --version` afterwards — so
> if it has stopped resolving, we find out rather than you. See
> [`.github/workflows/install-docs.yml`](../.github/workflows/install-docs.yml).
>
> Two things it cannot prove, both covered below: that GHDL lands somewhere on your
> `PATH` (it often does not — see
> [Windows: GHDL not on PATH](#windows-ghdl-not-on-path-after-winget-install)), and
> that `winget` is present at all, since it ships as an App Installer component. If
> you do not have it, use the [MSYS2 route](#windows-msys2-alternative).

**Linux (Ubuntu/Debian):**

```bash
sudo apt install ghdl
```

**Linux (Fedora):**

```bash
sudo dnf install ghdl
```

**macOS:** download the official release tarball.

```bash
ver=6.0.0
curl -LO "https://github.com/ghdl/ghdl/releases/download/v$ver/ghdl-llvm-$ver-macos15-aarch64.tar.gz"
# --strip-components=1: the tarball nests everything under
# ghdl-llvm-$ver-macos15-aarch64/, and this puts bin/ straight in ~/ghdl.
mkdir -p ~/ghdl
tar -xzf "ghdl-llvm-$ver-macos15-aarch64.tar.gz" -C ~/ghdl --strip-components=1
echo 'export PATH="$HOME/ghdl/bin:$PATH"' >> ~/.zshrc && exec zsh
ghdl --version
```

> **Not `brew install ghdl`.** Homebrew's GHDL was a *cask*, and it was
> **disabled on 2026-09-01** for failing the macOS Gatekeeper check
> (`brew info --cask ghdl` still says so). There is no Homebrew formula for
> GHDL, so the tarball above is the macOS path until that changes. Fetching it
> with `curl` matters: a file downloaded through a browser carries the
> quarantine attribute and Gatekeeper will block it the same way. If you do end
> up with a quarantined copy, `xattr -dr com.apple.quarantine ~/ghdl` clears it.
>
> On Apple Silicon there is **no GHDL mcode** (its in-memory code generator is
> x86-only), so the release tarballs for macOS are LLVM / LLVM-JIT builds.
> Both flavors (and NVC) are CI-tested on macOS arm64. On an Intel Mac,
> substitute the `x86-64` asset from the same release.
>
> **`brew install nvc` still works**, and on macOS it is now the shorter path —
> see [Which to install](#which-to-install--recommendations).

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

## Choosing a simulator

Any installed simulator works, and the launcher's `SIM:` toggle (and `--sim`)
picks between them per run. They differ mostly in raw speed and in how long a
design takes to load:

| Simulator | Relative speed | Startup / reload | Notes |
|---|---|---|---|
| NVC | fastest (~3.5–6x mcode; more on arithmetic-heavy designs) | fast | full VHPI; the speed pick, especially for embedded-CPU designs |
| GHDL mcode | baseline (1x) | instant | the default; what most distros ship |
| GHDL LLVM-JIT | ~1.2–1.4x mcode | instant | mcode's feel, a free speedup |
| GHDL LLVM | ~2.3–4.3x mcode | slower (compiles + links each launch/reload) | width errors still surface at load time |

Ratios, not absolute times (which are machine-dependent). Measured on a Ryzen
AI 9 HX 370 (GHDL 7.0.0-dev / NVC 1.22, 2026-07-23, all release builds — GHDL
built `--disable-checks`; the profile behind these numbers is
[u25_ghdl_perf_profile.md](u25_ghdl_perf_profile.md)). Reproduce with
`uv run fpga-sim --benchmark 10 --no-ui` (add `--sim <name>` / `--board` /
`--vhdl` to compare).

### Which to install — recommendations

| You want | Install |
|---|---|
| Simplest working setup | Your distro's `ghdl` (mcode) — one package, instant startup |
| Fastest simulation, no fuss | **NVC** — prebuilt packages are fine (its default build is optimized) |
| Fast **GHDL** specifically | Self-built GHDL **LLVM** with `--disable-checks` ([below](#building-ghdls-llvm-code-generators)) |
| mcode's instant startup, some speed | Self-built GHDL **LLVM-JIT** with `--disable-checks` |
| Windows | GHDL (the tested choice; NVC unverified there) |
| **macOS** | **NVC** (`brew install nvc`) — GHDL's Homebrew cask was disabled on 2026-09-01 for failing the Gatekeeper check, so GHDL there means the [release tarball](#ghdl) |
| The full picker | Install several — the `SIM:` toggle / `--sim` selects per run |

> **Building GHDL yourself? Always pass `--disable-checks`.** GHDL's `configure`
> *defaults to a debug build* — assertions on, unoptimized runtime, unoptimized
> AOT ieee libraries — which costs the LLVM backend **40–70%** of its speed. The
> official prebuilt GHDL release zips are built with that same default (upstream
> CI audited 2026-07), so a self-built `--disable-checks` LLVM backend beats
> them. mcode barely notices the flag (+2–9%), so distro mcode packages are fine
> as the baseline. **NVC needs no such flag** — its standard build is already
> optimized. Full measurements: [u25_ghdl_perf_profile.md](u25_ghdl_perf_profile.md).

The simulator applies its own per-design optimization automatically (GHDL
analyze/elaborate runs with `-O2`; NVC's default is already `-O2`), so there is
no per-run flag to remember — the build configuration above is the only lever
left to the installer.

`fpga-sim --list-sims` prints every simulator it found — engine, code
generator, version, and path. If one lives somewhere unusual, register it with
`fpga-sim --add-sim /path/to/ghdl` (or list paths in `FPGA_SIM_EXTRA_SIMS`,
`os.pathsep`-separated).

### Building GHDL's LLVM code generators

GHDL's `llvm` (ahead-of-time) and `llvm-jit` backends aren't packaged by most
distros; build them from one source tree into **separate prefixes** so each
`ghdl` binary stays self-contained and discovery can find them:

```bash
sudo apt install llvm-dev clang gnat   # or the Fedora/… equivalents

git clone https://github.com/ghdl/ghdl && cd ghdl

# One build dir + one --prefix per backend. Never share a prefix between
# backends, and never reconfigure an existing build dir for a different one.
# --disable-checks matters: GHDL's configure DEFAULT is a debug build
# (asserting runtime, unoptimized AOT ieee libraries) that costs the llvm
# backend 40-70% (see docs/u25_ghdl_perf_profile.md).
mkdir build-llvm && cd build-llvm
../configure --prefix=/usr/local/ghdl-llvm --with-llvm-config --disable-checks
make -j"$(nproc)" && sudo make install
cd ..

mkdir build-llvm-jit && cd build-llvm-jit
../configure --prefix=/usr/local/ghdl-llvm-jit --with-llvm-jit --disable-checks
make -j"$(nproc)" && sudo make install
```

`fpga-sim --list-sims` discovers `/usr/local/ghdl-*` installs automatically.
Keep your distro's `ghdl` (mcode) as the PATH default; select a variant per run
with the `SIM:` toggle or `--sim ghdl-llvm` / `--sim ghdl-jit`.

## Set up the Python environment

`uv` manages the venv and all dependencies automatically. It also installs a
standalone Python when needed — which matters on Windows, where the Windows Store
Python is sandboxed and can't be embedded by an external simulator process.

```bash
uv sync
```

That installs the three runtime dependencies and nothing else — pygame-ce,
cocotb and find_libpython, all of them wheels on every supported platform. It is
deliberately small: you do not need the project's test and lint tooling to run
the simulator, and one of those tools has no wheels at all, so shipping it to
everyone would turn a flaky network into a failed install.

Contributing? Add the tooling with `uv sync --group dev` — see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Check the install

```bash
uv run fpga-sim --doctor
```

`--doctor` needs no display. It reports the Python, uv, pygame-ce and cocotb
versions; every simulator it can find (label, backend, version, path) and which
one a run uses by default; the number of board definitions loaded; whether
`~/.fpga_simulator/` is writable; that cocotb's VPI/VHPI plugin and the Python
shared library the simulator child loads both exist — and it finishes by
compiling and elaborating `hdl/blinky.vhd` on **each** simulator it found:

```text
fpga-sim doctor - Fedora Linux 43 - x86_64

  [ ok ] Python         3.10.20 (CPython), within >=3.10,<3.15
  [ ok ] uv             uv 0.12.10
  [ ok ] pygame-ce      2.5.8 (SDL 2.32.10)
  [ ok ] cocotb         2.0.1
  [ ok ] Boards         285 definitions in 4 sources
  [ ok ] Profile        writable: /home/you/.fpga_simulator
  [ ok ] Simulators     2 found
  [ ok ] cocotb plugin  ghdl -> libcocotbvpi_ghdl.so, nvc -> libcocotbvhpi_nvc.so
  [ ok ] Analyze        blinky.vhd on DE10-Standard: compiled and elaborated

All 9 checks passed.
```

Every failing check prints, under **How to fix**, the command for *this*
operating system, and the exit code is non-zero — so it can gate a script.

If `pygame` itself is broken (the pip collision below), `fpga-sim` cannot start
at all. The doctor also runs as a module, which does not import pygame:

```bash
uv run python -m fpga_sim.doctor
```

Contributors can additionally run the full test suite, which exercises the whole
analyze/simulate path on both installed simulators (it needs the `dev` group):

```bash
uv sync --group dev
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

The GUI is rendered with [pygame-ce](https://github.com/pygame-community/pygame-ce)
(pygame Community Edition), the actively maintained community fork. It imports as
plain `pygame`, and nothing here is written against fork-only API.

`uv sync` is the supported install path and needs no special handling: if an older
checkout left upstream `pygame` in the virtualenv, uv removes it and installs
pygame-ce in the same step.

**If you install with `pip` instead, order matters.** The two distributions own the
same `pygame/` import directory, and pip does not detect the collision:

- `pip install pygame-ce` while upstream `pygame` is installed *appears* to work —
  both are listed by `pip list`, `pip check` reports nothing wrong, and pygame-ce's
  files silently overwrite pygame's.
- `pip uninstall pygame` afterwards then **breaks the environment**, because pip
  deletes files that now belong to pygame-ce. `import pygame` fails with
  `AttributeError: module 'pygame' has no attribute 'init'`.

So with pip, uninstall `pygame` *first*, then install `pygame-ce`. To repair an
environment already in that state, uninstall both and reinstall `pygame-ce`.
`tests/test_pygame_distribution.py` fails loudly if both are ever installed at once.

Version numbers are **not** comparable across the two: pygame-ce's latest (2.5.8) is
numerically lower than upstream pygame's (2.6.1) because they are independent
version lines — a `pygame-ce>=2.6` pin is unsatisfiable.

## Troubleshooting

This section covers *installation* problems. For anything that goes wrong once the
app starts — a file that will not load, a compiler error, a board that looks dead —
see [docs/troubleshooting.md](troubleshooting.md).

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

GHDL cannot locate the Python shared library. `uv run fpga-sim --doctor` reports
that directly — its **cocotb plugin** row prints the library it resolved, or says
it could not find one. `fpga_sim/sim_runner.py` auto-detects it via
`cocotb-config --libpython` on Windows, so this should not occur on current
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

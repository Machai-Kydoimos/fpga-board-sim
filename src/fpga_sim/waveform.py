"""Capturing a run as a waveform, and handing it to a viewer (U10/U28-U30, D17).

Capture is off by default and tri-state when on -- VCD or FST -- because the
two differ by an order of magnitude in size for the same run (roadmap P13
measured 42-119 MB against 2-5 MB on the same one- to two-second smoke runs).
Enabling it writes a timestamped dump under ``~/.fpga_simulator/waveforms/``,
overridable per run through the environment.

Two conveniences ride along, and both exist because a dump nobody opens is a
dump nobody reads.  :func:`_write_gtkw` emits a GTKWave save file beside the
dump with the run's own signals already selected -- the design's *native* names
for a board-native run, since those are the names its author wrote -- and
:func:`_open_waveform` hands the pair to whatever viewer the user configured,
falling back to the OS default handler.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fpga_sim.conventions import ConventionMatch, NativePort
from fpga_sim.platform_open import open_with_default_app
from fpga_sim.sim_config import WaveConfig, WaveFormat

# ── Waveform capture ──────────────────────────────────────────────────────────

#: Default directory for waveform dumps.  A module attribute (mirroring
#: ``session_config.SESSION_FILE``) so tests can redirect it; overridable at
#: runtime by the ``FPGA_SIM_WAVEFORM_DIR`` env var so a user working in their
#: own project tree can keep captures in-tree.  The resolved path is absolute,
#: so the run subprocess writes there regardless of its temp work-dir cwd.
WAVEFORM_DIR: Path = Path.home() / ".fpga_simulator" / "waveforms"

#: Env var overriding :data:`WAVEFORM_DIR` (blank/unset → the default).
WAVEFORM_DIR_ENV = "FPGA_SIM_WAVEFORM_DIR"

#: Env var enabling capture headlessly / in CI, overriding the session ``waveform``
#: mode when set (blank/unset → the session value).  See :func:`start_simulation`.
WAVEFORM_ENV = "FPGA_SIM_WAVEFORM"

#: Env var forcing waveform auto-open on/off, overriding the session
#: ``waveform_open`` flag when set (parsed by :func:`_env_flag`).
WAVEFORM_OPEN_ENV = "FPGA_SIM_WAVEFORM_OPEN"

#: Env var forcing the U30 "include memories" depth on/off (NVC ``--dump-arrays``),
#: overriding the session ``waveform_memories`` flag when set (parsed by
#: :func:`_env_flag`).  Lets CI/headless capture the embedded-core RAM/ROM arrays.
WAVEFORM_MEMORIES_ENV = "FPGA_SIM_WAVEFORM_MEMORIES"

#: Env var holding the auto-open command template (see :func:`_viewer_argv`).
WAVEFORM_VIEWER_ENV = "FPGA_SIM_WAVEFORM_VIEWER"

#: Default auto-open command: open GTKWave on the U28 save file (preloaded view).
DEFAULT_VIEWER = "gtkwave {gtkw}"


def _waveform_dir() -> Path:
    """Effective output directory: ``$FPGA_SIM_WAVEFORM_DIR`` or :data:`WAVEFORM_DIR`."""
    override = os.environ.get(WAVEFORM_DIR_ENV, "").strip()
    return Path(override).expanduser() if override else WAVEFORM_DIR


def _normalize_wave(value: str | None) -> WaveFormat | None:
    """Coerce a persisted/CLI waveform value to a WaveFormat, or None (off).

    Anything other than ``"vcd"`` / ``"fst"`` — ``"off"``, ``None``, or junk
    from a hand-edited session file — means no capture.
    """
    if value == "vcd":
        return "vcd"
    if value == "fst":
        return "fst"
    return None


def _waveform_path(entity: str, fmt: WaveFormat, *, now: datetime | None = None) -> Path:
    """Absolute, timestamped output path for a waveform dump of *entity*.

    ``<dir>/<entity>_<YYYY-MM-DD_HH-MM-SS>.<ext>`` under :func:`_waveform_dir`, so
    successive runs of a design accumulate (compare iterations in GTKWave) instead
    of overwriting, and same-named designs from different projects never collide.
    Colons are avoided so the name is valid on Windows.  *now* is injectable so
    tests are deterministic.
    """
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    return _waveform_dir() / f"{entity}_{stamp}.{fmt}"


def _gtkw_path(wave_path: Path) -> Path:
    """Return the GTKWave save-file sibling of a dump: same stem, ``.gtkw`` suffix.

    Pairing by identical stem (``blinky_<stamp>.vcd`` → ``blinky_<stamp>.gtkw``)
    keeps each save file matched to its dump once several timestamped captures
    accumulate.
    """
    return wave_path.with_suffix(".gtkw")


def _native_gtkw_signals(match: ConventionMatch) -> list[str]:
    """GTKWave signal paths for a board-native run: the design's own ports under ``uut``.

    Names are lowercased to match the identifier case GHDL/NVC emit in the dump
    hierarchy.  A shared vector carries a ``[msb:0]`` range; a scalar bank lists
    each scalar; the clock is a scalar.
    """
    scope = "sim_wrapper.uut"

    def _port(port: NativePort) -> list[str]:
        # A scalar-port bank dumps as individual unranged scalars; a shared
        # vector carries a [msb:0] range.  (A one-bit scalar bank has no range,
        # unlike a std_logic_vector(0 downto 0), so key on scalar_ports.)
        if port.scalar_ports:
            return [f"{scope}.{name.lower()}" for name in port.names]
        return [f"{scope}.{port.names[0].lower()}[{port.width - 1}:0]"]

    sigs = [f"{scope}.{match.clk.lower()}"]
    if match.switches is not None:
        sigs += _port(match.switches)
    if match.buttons is not None:
        sigs += _port(match.buttons)
    if match.leds is not None:
        sigs += _port(match.leds)
    if match.leds_rgb is not None:
        sigs += _port(match.leds_rgb)
    if match.leds_green is not None:
        sigs += _port(match.leds_green)
    if match.seven_seg is not None:
        seg = match.seven_seg
        if seg.style == "scan":
            # Shared segment lines: unranged scalars (CA..CG) or one vector,
            # then the dp scalar and the digit-enable bank.
            if seg.scalar_segments:
                sigs += [f"{scope}.{name.lower()}" for name in seg.names]
            else:
                sigs.append(f"{scope}.{seg.names[0].lower()}[{seg.width_per_digit - 1}:0]")
            if seg.dp is not None:
                sigs.append(f"{scope}.{seg.dp.lower()}")
            if seg.digit_enable is not None:
                sigs += _port(seg.digit_enable)
        else:
            wpd = seg.width_per_digit
            sigs += [f"{scope}.{name.lower()}[{wpd - 1}:0]" for name in seg.names]
    return sigs


def _write_gtkw(
    gtkw_path: Path,
    dump_path: Path,
    generics: dict[str, str],
    match: ConventionMatch | None = None,
) -> None:
    """Write a GTKWave save file that preloads the interesting ``sim_wrapper`` signals.

    Opening ``gtkwave <gtkw_path>`` lands the user on clk / sw / btn / led (and
    seg, for 7-seg runs) instead of an empty view with the whole signal tree —
    the U28 convenience atop U10's raw capture.  Signal names mirror the
    hierarchy both backends emit: the elaborated toplevel is ``sim_wrapper`` and
    each vector carries a ``[msb:0]`` range whose width comes from *generics*
    (a port whose generic is absent or unparseable is skipped, so an unusual
    design yields a shorter list rather than a broken line).  ``[dumpfile]`` names
    *dump_path*, so the save file also loads the trace on its own.

    When *match* is given the run is board-native (U21 B3): preselect the design's
    own native ports (``sim_wrapper.uut.<native>``) — the names the user wrote —
    followed by the top-level ``led``/``seg`` so the active-low inversion is
    visible (``uut.ledr`` vs ``led``).
    """
    top = "sim_wrapper"

    def _vector(name: str, width_generic: str, *, scale: int = 1) -> str | None:
        try:
            msb = int(generics[width_generic]) * scale - 1
        except (KeyError, ValueError):
            return None
        return f"{top}.{name}[{msb}:0]" if msb >= 0 else None

    if match is not None:
        signals = _native_gtkw_signals(match)
        signals += [
            s for s in (_vector("led", "NUM_LEDS"), _vector("seg", "NUM_SEGS", scale=8)) if s
        ]
        note = "[*] Preloads the design's native ports (sim_wrapper.uut.*) + board led/seg."
    else:
        signals = [
            p
            for p in (
                f"{top}.clk",
                _vector("sw", "NUM_SWITCHES"),
                _vector("btn", "NUM_BUTTONS"),
                _vector("led", "NUM_LEDS"),
                _vector("seg", "NUM_SEGS", scale=8),  # seg packs 8 bits per digit
            )
            if p is not None
        ]
        note = "[*] Preloads the sim_wrapper top-level ports; load beside the matching dump."

    lines = [
        "[*]",
        "[*] GTKWave save file auto-written by fpga-sim (roadmap U28).",
        note,
        "[*]",
        f'[dumpfile] "{dump_path}"',
        "[timestart] 0",
        "[signals_width] 200",
        "[sst_width] 200",
        f"-{top}",
        *signals,
    ]
    gtkw_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_flag(name: str) -> bool | None:
    """Parse a boolean env var: ``1/true/yes/on`` → True, ``0/false/no/off`` → False.

    Returns ``None`` when the var is unset or empty, so a caller can fall back to
    another source (blank means "not specified", not "False").
    """
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _viewer_argv(template: str, dump: Path, gtkw: Path) -> list[str]:
    """Build the auto-open argv from a command *template*.

    ``{dump}`` / ``{gtkw}`` expand to the capture file and its GTKWave save file;
    a template naming neither gets ``{dump}`` appended (so a bare ``surfer`` still
    works).  Tokenized with :func:`shlex.split` (no shell — no injection surface)
    *before* substitution, so a path containing spaces stays one argument.
    """
    if "{dump}" not in template and "{gtkw}" not in template:
        template = f"{template} {{dump}}"

    def _sub(token: str) -> str:
        return token.replace("{dump}", str(dump)).replace("{gtkw}", str(gtkw))

    return [_sub(token) for token in shlex.split(template)]


def _open_waveform(dump: Path, gtkw: Path) -> None:
    """Launch the user's waveform viewer on a produced dump (best-effort, detached).

    The command comes from ``$FPGA_SIM_WAVEFORM_VIEWER`` or :data:`DEFAULT_VIEWER`
    (``gtkwave {gtkw}``).  If its program isn't on PATH — or launching it raises —
    fall back to the OS default handler for the raw dump
    (:func:`~fpga_sim.platform_open.open_with_default_app`), so a viewer the user
    registered without setting the env var still opens.
    """
    template = os.environ.get(WAVEFORM_VIEWER_ENV, "").strip() or DEFAULT_VIEWER
    argv = _viewer_argv(template, dump, gtkw)
    if argv and shutil.which(argv[0]):
        try:
            subprocess.Popen(argv, start_new_session=True)
            return
        except OSError as e:
            print(f"[waveform] could not launch {argv[0]}: {e}", file=sys.stderr, flush=True)
    open_with_default_app(dump)


def _announce_waveform(
    wave_cfg: WaveConfig | None,
    generics: dict[str, str],
    match: ConventionMatch | None,
    waveform_open: bool | None,
) -> None:
    """Post-run waveform tail: gtkw sidecar + hint + optional auto-open.

    A produced, non-empty dump is worth pointing at; a crashed/empty run is not.
    Called by :func:`finish_waveform` after a headless run to spell the U28
    sidecar and U29 auto-open.
    """
    if wave_cfg is None:
        return
    wpath = Path(wave_cfg.path)
    if not (wpath.is_file() and wpath.stat().st_size > 0):
        return
    # U28: drop a matching GTKWave save file so the dump opens on the interesting
    # ports (clk/sw/btn/led[/seg]) instead of an empty view.  U21 B3: for a
    # board-native run, preselect the design's own native ports.
    gtkw = _gtkw_path(wpath)
    _write_gtkw(gtkw, wpath, generics, match=match)
    print(f"Waveform written: {wpath}\n  Open it with preloaded signals:  gtkwave {gtkw}")
    # U29: optionally launch the user's viewer on the produced dump.
    env_open = _env_flag(WAVEFORM_OPEN_ENV)
    do_open = env_open if env_open is not None else bool(waveform_open)
    if do_open:
        _open_waveform(wpath, gtkw)

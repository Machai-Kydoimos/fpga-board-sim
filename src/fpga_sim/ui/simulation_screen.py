"""simulation_screen.py - the in-launcher simulation screen (single-window, U34).

The launcher owns one pygame window for the whole session.  Instead of closing
it and letting a cocotb subprocess open its own (the legacy ``sim_testbench``
path), :class:`SimulationScreen` keeps rendering the board here and drives a
*headless* GHDL/NVC + cocotb child (:class:`~fpga_sim.sim_bridge.SimChild`) over
an IPC link: it streams switch/button/speed/clock control down and applies the
LED/seg state the child streams back.

The visuals are relocated from ``sim/sim_testbench.py``'s ``interactive_sim`` and
kept pixel-identical; the run loop is the spike's host loop (see
``docs/experiments/single_window_sim.md``).  The controller constructs one of
these per launch, calls :meth:`run`, then :func:`~fpga_sim.sim_bridge.finish_waveform`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from fpga_sim.session_config import update_session
from fpga_sim.sim_bridge import SimExit
from fpga_sim.sim_link import drain, send
from fpga_sim.sim_session_log import save_session_stats
from fpga_sim.ui.board_display import FPGABoard
from fpga_sim.ui.constants import get_font as _get_font
from fpga_sim.ui.error_dialog import ErrorDialog
from fpga_sim.ui.help_dialog import HelpDialog
from fpga_sim.ui.sim_panel import _PANEL_H_BASE, SimPanel
from fpga_sim.ui.sim_toolbar import SimToolbar
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.widgets import draw_button

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef, ComponentInfo
    from fpga_sim.sim_bridge import ConventionMatch, SimChild

#: Seconds to wait for the child's connection before giving up (NVC / Windows
#: headroom); a spinner overlay is shown meanwhile.
_STARTUP_TIMEOUT_S: float = 90.0


@dataclass
class RunStats:
    """Host-side averages for one simulation run.

    Populated by :meth:`SimulationScreen.run`; feeds ``save_session_stats`` here
    and the ``--benchmark`` report (PR3).  ``avg_sim_pct`` is the mean of the
    child-reported ``timer_pct`` samples (its GHDL/NVC step share); ``draw`` and
    ``idle`` percentages are host-frame shares.
    """

    frames: int = 0
    avg_fps: float = 0.0
    avg_draw_pct: float = 0.0
    avg_idle_pct: float = 0.0
    avg_sim_pct: float = 0.0
    sim_ns: int = 0
    steps: int = 0
    duration_s: float = 0.0


def _native_active_low(match: ConventionMatch) -> str:
    """Comma-joined role labels the convention drives active-low (else ``"none"``).

    Mirrors ``sim_testbench._active_low_roles`` but reads the ``ConventionMatch``
    directly instead of a JSON env round-trip (U34 drops that env var).
    """
    roles: list[str] = []
    if match.leds.active_low:
        roles.append("LED")
    if match.switches is not None and match.switches.active_low:
        roles.append("SW")
    if match.buttons is not None and match.buttons.active_low:
        roles.append("BTN")
    if match.seven_seg is not None and match.seven_seg.active_low:
        roles.append("HEX")
    return ", ".join(roles) if roles else "none"


class SimulationScreen:
    """Render the board + panel while a headless sim child streams signal state."""

    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        board_def: BoardDef | None,
        child: SimChild,
        *,
        speed_factor: float,
        match: ConventionMatch | None,
        vhdl_path: str | Path,
        simulator: str,
        show_toolbar: bool = True,
    ) -> None:
        """Build the board/panel/toolbar and wire pygame input to link messages."""
        self.screen = screen
        self.clock = clock
        self.board_def = board_def
        self.child = child
        self.match = match
        self.simulator = simulator
        self._vhdl_name = Path(vhdl_path).name
        self._show_toolbar = show_toolbar

        clk_hz = board_def.default_clock_hz if board_def else 0.0
        self._board_name = board_def.name if board_def else "Generic"
        self._seg_digits = (
            board_def.seven_seg.num_digits if board_def and board_def.seven_seg else 0
        )
        self.panel = SimPanel(
            screen,
            height=_PANEL_H_BASE,
            board_clock_hz=clk_hz or 1e8,
            board_clocks_hz=board_def.clocks if board_def else None,
            speed_factor=speed_factor,
            native_active_low=_native_active_low(match) if match else None,
        )
        self.board = FPGABoard(
            board_def=board_def,
            screen=screen,
            width=screen.get_width(),
            height=screen.get_height(),
            height_offset=0,
            show_footer=False,
            # Reserve the footer strip the preview used, so the board stays put
            # when the sim starts — the overlays live in that strip (U34).
            reserve_footer_space=True,
        )
        self._toolbar: SimToolbar | None = SimToolbar() if show_toolbar else None

        # Info-strip segments (board | vhdl (mode) | simulator), native tag accented.
        self._mode_tag = f"(native: {match.maker})" if match else "(generic)"
        self._info_prefix = "  |  ".join(p for p in (self._board_name, self._vhdl_name) if p) + " "
        self._info_suffix = f"  |  {simulator.upper()}" if simulator else ""

        # ── Live loop state ──────────────────────────────────────────────────
        self._connected = False
        self._last_state: dict[str, Any] = {}
        self._bye: dict[str, Any] | None = None
        self._input_seq = 0
        self._show_panel = False
        self._board_offset = 0
        self._stop_btn_rect: pygame.Rect | None = None
        self._pause_btn_rect: pygame.Rect | None = None
        # Last control values sent, so we only message the child on a change.
        self._last_clk_half: int | None = None
        self._last_speed = self.panel.speed_factor
        self._last_pause = False
        # run_stats accumulators
        self.run_stats = RunStats()
        self._fps_acc: list[float] = []
        self._draw_acc: list[float] = []
        self._idle_acc: list[float] = []
        self._sim_acc: list[float] = []

        self.board.set_switch_callback(self._on_switch)
        self.board.set_button_callback(self._on_button)

    # ── Input wiring ──────────────────────────────────────────────────────────

    def _send_input(self) -> None:
        """Push the current switch/button state to the child as one input message."""
        if not self._connected:
            return
        sw_val = sum(1 << s.index for s in self.board.switches if s.state)
        btn_val = sum(1 << b.index for b in self.board.buttons if b.pressed)
        self._input_seq += 1
        send(
            self.child.link.conn,
            "input",
            {"sw": sw_val, "btn": btn_val, "seq": self._input_seq},
        )

    def _on_switch(self, idx: int, state: bool, info: ComponentInfo | None) -> None:
        self._send_input()
        label = info.display_name if info else f"SW{idx}"
        conn = f"  [{info.connector_str}]" if info else ""
        print(f"{label}: {'ON' if state else 'OFF'}{conn}")

    def _on_button(self, idx: int, pressed: bool, info: ComponentInfo | None) -> None:
        self._send_input()
        label = info.display_name if info else f"BTN{idx}"
        conn = f"  [{info.connector_str}]" if info else ""
        print(f"{label}: {'PRESSED' if pressed else 'RELEASED'}{conn}")

    # ── Control sync (host -> child on change) ─────────────────────────────────

    def _sync_controls(self) -> None:
        """Send speed / clock / pause messages when the panel state changed."""
        if not self._connected:
            return
        conn = self.child.link.conn
        half = max(1, int(self.panel.clk_state["period_ns"] / 2))
        if half != self._last_clk_half:
            send(conn, "clk", {"half_ns": half})
            self._last_clk_half = half
        if self.panel.speed_factor != self._last_speed:
            send(conn, "speed", {"factor": self.panel.speed_factor})
            self._last_speed = self.panel.speed_factor
        if self.panel.paused != self._last_pause:
            send(conn, "pause", {"on": self.panel.paused})
            self._last_pause = self.panel.paused

    # ── Main loop ──────────────────────────────────────────────────────────────

    def run(self) -> SimExit:
        """Drive the simulation to completion; return why it ended.

        Waits (with a spinner) for the child to connect, then streams state until
        an exit is requested (toolbar / ESC / [Stop] / window close) or the child
        finishes (``bye``) or dies.  Always stops the child, persists the slider
        speed, and writes the session stats before returning.
        """
        self._print_banner()
        session_start = time.monotonic()
        exit_intent: SimExit | None = None

        while exit_intent is None:
            if not self._connected:
                exit_intent = self._pump_connect(session_start)
                if exit_intent is not None:
                    break

            if self._connected:
                exit_intent = self._pump_link()
                if exit_intent is not None:
                    break

            exit_intent = self._pump_events()
            if exit_intent is not None:
                break

            self._sync_controls()
            if self._connected and self._last_state:
                self.panel.set_remote(
                    int(self._last_state.get("sim_ns", 0)),
                    bool(self._last_state.get("at_max", False)),
                )
            self._render_frame()

            if self.panel.stop_requested:
                exit_intent = SimExit.STOPPED

        self._teardown(exit_intent, session_start)
        return exit_intent

    def _pump_connect(self, session_start: float) -> SimExit | None:
        """Advance the waiting phase; return an exit if the child never connects."""
        try:
            self._connected = self.child.link.wait_connected(0.0)
        except RuntimeError as e:
            return self._crash(f"The simulator link failed: {e}")
        if self._connected:
            # Mirror today's one-time dut.clk_half_ns sync (then on every change).
            self._last_clk_half = max(1, int(self.panel.clk_state["period_ns"] / 2))
            send(self.child.link.conn, "clk", {"half_ns": self._last_clk_half})
            return None
        if self.child.poll() is not None:
            return self._crash(
                f"The {self.simulator.upper()} simulation exited before it started "
                f"(code {self.child.poll()})."
            )
        if time.monotonic() - session_start > _STARTUP_TIMEOUT_S:
            return self._crash(
                f"Timed out after {_STARTUP_TIMEOUT_S:.0f}s waiting for "
                f"{self.simulator.upper()} to start."
            )
        return None

    def _pump_link(self) -> SimExit | None:
        """Drain the link, keeping the latest state; return an exit on bye/crash."""
        for kind, payload in drain(self.child.link.conn):
            if kind == "state":
                self._last_state = payload
            elif kind == "bye":
                self._bye = payload
                return SimExit.STOPPED
            elif kind == "eof":
                rc = self.child.poll()
                if rc not in (0, None):
                    return self._crash(
                        f"The {self.simulator.upper()} simulation stopped unexpectedly (code {rc})."
                    )
                return SimExit.STOPPED
        self._apply_state()
        return None

    def _apply_state(self) -> None:
        """Reflect the latest child state onto the board LEDs / 7-seg."""
        led = int(self._last_state.get("led", 0) or 0)
        for i in range(len(self.board.leds)):
            self.board.set_led(i, bool(led & (1 << i)))
        seg = self._last_state.get("seg")
        if seg is not None:
            for i in range(self._seg_digits):
                self.board.set_seg(i, (int(seg) >> (8 * i)) & 0xFF)

    def _pump_events(self) -> SimExit | None:
        """Handle one frame of pygame events; return an exit intent if requested."""
        events = pygame.event.get()
        # Classify window-close vs ESC before the board collapses both to
        # ``running = False`` (window X quits the whole app; ESC stops the sim).
        nav: SimExit | None = None
        for ev in events:
            if ev.type == pygame.QUIT:
                nav = SimExit.QUIT
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                nav = SimExit.STOPPED

        self.board._handle_events(events)  # switches/buttons/help/resize

        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_s:
                self._show_panel = not self._show_panel
                self._board_offset = self.panel.panel_height if self._show_panel else 0
                self.board.set_height_offset(self._board_offset)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self._stop_btn_rect is not None and self._stop_btn_rect.collidepoint(ev.pos):
                    nav = SimExit.STOPPED
                elif self._pause_btn_rect is not None and self._pause_btn_rect.collidepoint(ev.pos):
                    self.panel.paused = not self.panel.paused
                elif self._toolbar is not None:
                    intent = self._toolbar.handle_click(ev.pos)
                    if intent is not None:
                        nav = intent
            self.panel.handle_event(ev)

        # F1 / ? help: pause the child around the modal so sim time does not
        # advance while it is open (today's semantics), then restore.
        if self.board._help_requested:
            self.board._help_requested = False
            self._run_help_modal()

        return nav

    def _run_help_modal(self) -> None:
        was_paused = self.panel.paused
        if self._connected and not was_paused:
            send(self.child.link.conn, "pause", {"on": True})
        HelpDialog(self.screen).run(self.clock)
        self.board._sync_to_surface()
        if self._show_panel:
            self._board_offset = self.panel.panel_height
            self.board.set_height_offset(self._board_offset)
        if self._connected and not was_paused:
            send(self.child.link.conn, "pause", {"on": False})

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _render_frame(self) -> None:
        """Draw board + panel + overlays, flip, and accumulate host-frame timing."""
        # Keep the board's panel-height reservation synced after a window resize.
        if self._show_panel:
            cur_offset = self.panel.panel_height
            if cur_offset != self._board_offset:
                self.board.set_height_offset(cur_offset)
                self._board_offset = cur_offset

        t_draw_start = time.monotonic_ns()
        self.board._draw(flip=False)
        if self._show_panel:
            self.panel.draw()
        if self._connected:
            self._draw_overlays()
        else:
            self._draw_waiting()
        pygame.display.flip()
        t_draw_end = time.monotonic_ns()

        self.clock.tick(60)
        t_tick_end = time.monotonic_ns()

        fps = self.clock.get_fps()
        draw_us = (t_draw_end - t_draw_start) / 1_000
        idle_us = (t_tick_end - t_draw_end) / 1_000
        sim_pct = float(self._last_state.get("timer_pct", 0.0)) if self._connected else 0.0
        self.panel.update_timing(
            fps=fps, timer_us=0.0, draw_us=draw_us, idle_us=idle_us, sim_pct=sim_pct
        )
        if fps > 0:
            host = max(1.0, draw_us + idle_us)
            self._fps_acc.append(fps)
            self._draw_acc.append(draw_us / host * 100)
            self._idle_acc.append(idle_us / host * 100)
            if self._connected:
                self._sim_acc.append(sim_pct)

    def _draw_waiting(self) -> None:
        """Overlay a 'Starting <SIM>...' banner while the child connects."""
        sw, sh = self.screen.get_size()
        font = _get_font(max(12, round(18 * min(sw / 1024, sh / 700))), bold=True)
        text = font.render(f"Starting {self.simulator.upper()}...", True, THEME.sim_info)
        pad = 16
        bg = pygame.Surface((text.get_width() + pad * 2, text.get_height() + pad), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        bx = (sw - bg.get_width()) // 2
        by = (sh - bg.get_height()) // 2
        self.screen.blit(bg, (bx, by))
        self.screen.blit(text, (bx + pad, by + pad // 2))

    def _draw_overlays(self) -> None:  # noqa: PLR0914, PLR0915 — verbatim from sim_testbench
        """Info strip + bottom-right Pause/Stop + toolbar + hint (relocated verbatim)."""
        sw, sh = self.screen.get_size()
        ov_s = min(sw / 1024, sh / 700)
        ov_fs = max(10, round(13 * ov_s))
        ov_font = _get_font(ov_fs, bold=True)

        # Info strip (top-left): board | VHDL (mode) | simulator; native tag accented.
        info_font = _get_font(max(9, round(11 * ov_s)))
        tag_color = THEME.info_green if self.match else THEME.sim_info
        info_segs = [
            info_font.render(self._info_prefix, True, THEME.sim_info),
            info_font.render(self._mode_tag, True, tag_color),
            info_font.render(self._info_suffix, True, THEME.sim_info),
        ]
        info_w = sum(s.get_width() for s in info_segs)
        info_h = max(s.get_height() for s in info_segs)
        info_bg = pygame.Surface((info_w + 12, info_h + 6), pygame.SRCALPHA)
        info_bg.fill((0, 0, 0, 130))
        self.screen.blit(info_bg, (0, 0))
        info_x = 6
        for seg in info_segs:
            self.screen.blit(seg, (info_x, 3))
            info_x += seg.get_width()

        # Bottom-right Pause + Stop buttons.
        ov_pad_x = max(8, round(10 * ov_s))
        ov_pad_y = max(5, round(6 * ov_s))
        ov_gap = max(6, round(8 * ov_s))
        ov_margin = max(8, round(10 * ov_s))
        board_bottom = sh - self._board_offset

        pause_label = "[RESUME]" if self.panel.paused else "[PAUSE]"
        pause_style = THEME.btn_sim_resume if self.panel.paused else THEME.btn_sim_pause
        pause_bw = ov_font.size(pause_label)[0] + ov_pad_x * 2
        pause_bh = ov_font.get_height() + ov_pad_y * 2

        stop_label = "■ Stop"
        stop_bw = ov_font.size(stop_label)[0] + ov_pad_x * 2
        stop_bh = ov_font.get_height() + ov_pad_y * 2

        btn_h = max(pause_bh, stop_bh)
        btn_py = board_bottom - btn_h - ov_margin

        stop_bx = sw - stop_bw - ov_margin
        self._stop_btn_rect = pygame.Rect(stop_bx, btn_py, stop_bw, btn_h)
        draw_button(
            self.screen,
            self._stop_btn_rect,
            stop_label,
            ov_font,
            THEME.btn_sim_stop,
            hovered=self._stop_btn_rect.collidepoint(pygame.mouse.get_pos()),
        )
        pause_bx = stop_bx - ov_gap - pause_bw
        self._pause_btn_rect = pygame.Rect(pause_bx, btn_py, pause_bw, btn_h)
        draw_button(
            self.screen,
            self._pause_btn_rect,
            pause_label,
            ov_font,
            pause_style,
            hovered=self._pause_btn_rect.collidepoint(pygame.mouse.get_pos()),
        )

        # Navigation toolbar (bottom-left, opposite Pause/Stop).
        toolbar_rect: pygame.Rect | None = None
        if self._toolbar is not None:
            toolbar_rect = self._toolbar.draw(
                self.screen,
                ov_font,
                left=ov_margin,
                bottom=board_bottom - ov_margin,
                pad_x=ov_pad_x,
                pad_y=ov_pad_y,
                gap=ov_gap,
            )

        # "S: stats · F1: help" hint (bottom-left) when the panel is hidden.
        if not self._show_panel:
            hint_font = _get_font(max(9, round(10 * ov_s)))
            hint_surf = hint_font.render("S: stats · F1: help", True, THEME.sim_hint)
            hint_pad = max(4, round(5 * ov_s))
            hint_bottom = toolbar_rect.top if toolbar_rect is not None else sh
            self.screen.blit(
                hint_surf,
                (max(6, round(8 * ov_s)), hint_bottom - hint_surf.get_height() - hint_pad),
            )

    # ── Banner + teardown ──────────────────────────────────────────────────────

    def _print_banner(self) -> None:
        """Console banner (moved from the child, which no longer has ComponentInfo)."""
        num_led = len(self.board.leds)
        num_btn = len(self.board.buttons)
        num_sw = len(self.board.switches)
        seg = f", {self._seg_digits}-digit 7-seg" if self._seg_digits else ""
        print(f"\n{'=' * 60}")
        print(f"  Simulation running: {self._board_name}")
        print(f"  VHDL: {self._vhdl_name}  |  Simulator: {self.simulator.upper()}")
        print(f"  {num_led} LEDs, {num_btn} buttons, {num_sw} switches{seg}")
        print("  Use the panel sliders to adjust speed and virtual clock.")
        print("  S: toggle stats panel  |  F1/?: help  |  Pause/Stop: bottom-right")
        if self._toolbar is not None:
            print("  Toolbar (bottom-left): Back to Boards | Change VHDL | Reload VHDL")
        print("  Press ESC or [Stop] to end the simulation; close the window to quit.")
        print(f"{'=' * 60}\n")

    def _crash(self, message: str) -> SimExit:
        """Show an error dialog with the child's stderr tail, then stop."""
        tail = "\n".join(list(self.child.stderr_tail)[-20:]).strip()
        full = f"{message}\n\n{tail}" if tail else message
        ErrorDialog(self.screen, "Simulation Error", full).run(self.clock)
        return SimExit.STOPPED

    def _teardown(self, exit_intent: SimExit, session_start: float) -> None:
        """Stop the child and persist speed + session stats on every exit path."""
        self.child.stop()
        update_session(speed_factor=self.panel.speed_factor)

        duration = time.monotonic() - session_start
        last = self._bye or self._last_state
        sim_ns = int(last.get("sim_ns", 0)) if last else 0
        n = len(self._fps_acc)
        stats = self.run_stats
        stats.frames = n
        stats.sim_ns = sim_ns
        stats.steps = int(last.get("steps", 0)) if last else 0
        stats.duration_s = duration
        if n:
            stats.avg_fps = sum(self._fps_acc) / n
            stats.avg_draw_pct = sum(self._draw_acc) / n
            stats.avg_idle_pct = sum(self._idle_acc) / n
        if self._sim_acc:
            stats.avg_sim_pct = sum(self._sim_acc) / len(self._sim_acc)

        if n:
            save_session_stats(
                board_name=self._board_name,
                simulator=self.simulator,
                duration_s=duration,
                avg_fps=stats.avg_fps,
                sim_time_ns=sim_ns,
                avg_ghdl_pct=stats.avg_sim_pct,
                avg_draw_pct=stats.avg_draw_pct,
                avg_idle_pct=stats.avg_idle_pct,
                clock_hz=self.panel.current_clock_hz,
                mode="native" if self.match else "generic",
                convention=self.match.maker if self.match else None,
            )
        print(f"Simulation stopped ({exit_intent.value}).")

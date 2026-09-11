# UI map — inspect-mode addresses

**Generated — do not edit.** Regenerate with `uv run python scripts/gen_ui_map.py`;
`tests/test_ui_map.py` fails when this file and the product disagree.

Press **F3** in the app to see these names on screen and **F4** to copy the
one under the cursor. Quote the address in a question or a bug report — it
is stable across releases, which is what makes this table safe to regenerate.

`[i]` stands for a widget index: `sim.board.led[5]` is LED channel 5, numbered
as `manifest.json`'s LED legend numbers it.

70 addresses.

| Address | Kind | Registered at |
| --- | --- | --- |
| `dlg.error.back-to-boards` | item | `fpga_sim/ui/error_dialog.py:432` |
| `dlg.error.copy` | item | `fpga_sim/ui/error_dialog.py:432` |
| `dlg.error.panel` | zone | `fpga_sim/ui/error_dialog.py:360` |
| `dlg.error.try-another-file` | item | `fpga_sim/ui/error_dialog.py:432` |
| `dlg.error.view-example` | item | `fpga_sim/ui/error_dialog.py:432` |
| `dlg.generics.apply` | item | `fpga_sim/ui/generics_dialog.py:293` |
| `dlg.generics.cancel` | item | `fpga_sim/ui/generics_dialog.py:293` |
| `dlg.generics.defaults` | item | `fpga_sim/ui/generics_dialog.py:293` |
| `dlg.help.close` | item | `fpga_sim/ui/help_dialog.py:282` |
| `dlg.help.panel` | zone | `fpga_sim/ui/help_dialog.py:225` |
| `dlg.settings.auto-open` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `dlg.settings.close` | item | `fpga_sim/ui/settings_dialog.py:410` |
| `dlg.settings.duty-bars` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `dlg.settings.led-pwm` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `dlg.settings.memories` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `dlg.settings.panel` | zone | `fpga_sim/ui/settings_dialog.py:345` |
| `dlg.settings.recent-files` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `dlg.settings.sim-speed` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `dlg.settings.theme` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `dlg.settings.waveform` | item | `fpga_sim/ui/settings_dialog.py:376` |
| `pick.header` | zone | `fpga_sim/ui/vhdl_picker.py:221` |
| `pick.header.help` | item | `fpga_sim/ui/help_dialog.py:315` |
| `pick.list` | zone | `fpga_sim/ui/vhdl_picker.py:222` |
| `preview.board.btn[i]` | widget | `fpga_sim/ui/board_display.py:1072` |
| `preview.board.chip` | widget | `fpga_sim/ui/board_display.py:1066` |
| `preview.board.led[i]` | widget | `fpga_sim/ui/board_display.py:1068` |
| `preview.board.leds.ledr` | zone | `fpga_sim/ui/board_display.py:1090` |
| `preview.board.seg[i]` | widget | `fpga_sim/ui/board_display.py:1078` |
| `preview.board.sw[i]` | widget | `fpga_sim/ui/board_display.py:1070` |
| `preview.footer.load-vhdl` | item | `fpga_sim/ui/board_display.py:1341` |
| `preview.footer.select-board` | item | `fpga_sim/ui/board_display.py:1328` |
| `preview.footer.sim-toggle` | item | `fpga_sim/ui/board_display.py:1379` |
| `preview.footer.simulate` | item | `fpga_sim/ui/board_display.py:1356` |
| `preview.header.generics` | item | `fpga_sim/ui/board_display.py:1311` |
| `preview.header.help` | item | `fpga_sim/ui/help_dialog.py:315` |
| `preview.header.settings` | item | `fpga_sim/ui/settings_dialog.py:136` |
| `select.header` | zone | `fpga_sim/ui/board_selector.py:451` |
| `select.header.chip.component.has-7seg` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.component.has-buttons` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.component.has-leds` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.component.has-switches` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.vendor.colognechip` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.vendor.efinix` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.vendor.gowin` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.vendor.intel` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.vendor.lattice` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.vendor.other` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.chip.vendor.xilinx` | widget | `fpga_sim/ui/board_selector.py:567` |
| `select.header.help` | item | `fpga_sim/ui/help_dialog.py:315` |
| `select.header.sort` | item | `fpga_sim/ui/board_selector.py:538` |
| `select.list` | zone | `fpga_sim/ui/board_selector.py:452` |
| `sim.board.btn[i]` | widget | `fpga_sim/ui/board_display.py:1072` |
| `sim.board.chip` | widget | `fpga_sim/ui/board_display.py:1066` |
| `sim.board.led[i]` | widget | `fpga_sim/ui/board_display.py:1068` |
| `sim.board.leds.ledr` | zone | `fpga_sim/ui/board_display.py:1090` |
| `sim.board.seg[i]` | widget | `fpga_sim/ui/board_display.py:1078` |
| `sim.board.sw[i]` | widget | `fpga_sim/ui/board_display.py:1070` |
| `sim.overlay.pause` | item | `fpga_sim/ui/simulation_screen.py:1100` |
| `sim.overlay.stop` | item | `fpga_sim/ui/simulation_screen.py:1089` |
| `sim.panel` | zone | `fpga_sim/ui/sim_panel.py:387` |
| `sim.panel.clock` | zone | `fpga_sim/ui/sim_panel.py:390` |
| `sim.panel.clock.faster` | item | `fpga_sim/ui/sim_panel.py:635` |
| `sim.panel.clock.slower` | item | `fpga_sim/ui/sim_panel.py:620` |
| `sim.panel.info` | zone | `fpga_sim/ui/sim_panel.py:388` |
| `sim.panel.speed` | zone | `fpga_sim/ui/sim_panel.py:389` |
| `sim.panel.speed.slider` | item | `fpga_sim/ui/sim_panel.py:526` |
| `sim.panel.speed.track` | item | `fpga_sim/ui/sim_panel.py:504` |
| `sim.toolbar.back` | item | `fpga_sim/ui/sim_toolbar.py:77` |
| `sim.toolbar.change-vhdl` | item | `fpga_sim/ui/sim_toolbar.py:77` |
| `sim.toolbar.reload` | item | `fpga_sim/ui/sim_toolbar.py:77` |

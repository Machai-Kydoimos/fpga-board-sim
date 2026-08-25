"""Tests for the keyboard bindings (:mod:`fpga_sim.ui.keymap`, U44 phase 4).

Pure resolution logic — no board, no window. The board-level consequences
(holds taken and released, focus loss, modals) live in
``tests/test_board_display_events.py``.
"""

from __future__ import annotations

import pygame
import pytest

from fpga_sim.ui import keymap


def _keydown(**attrs: int) -> pygame.event.Event:
    """A KEYDOWN carrying only the attributes a test names — like the real ones."""
    attrs.setdefault("mod", 0)
    return pygame.event.Event(pygame.KEYDOWN, attrs)


# ── Digit tier: physical position ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("scancode", "index"),
    [
        (pygame.KSCAN_1, 0),  # key `1` is the FIRST button, matching btn(0)
        (pygame.KSCAN_2, 1),
        (pygame.KSCAN_9, 8),
        (pygame.KSCAN_0, 9),  # the digit row runs 1..9 then 0
    ],
)
def test_digit_row_binds_by_scancode(scancode, index):
    assert keymap.resolve(_keydown(key=pygame.K_UNKNOWN, scancode=scancode)) == index


@pytest.mark.parametrize(
    ("scancode", "index"),
    [(pygame.KSCAN_KP_1, 0), (pygame.KSCAN_KP_5, 4), (pygame.KSCAN_KP_0, 9)],
)
def test_numpad_binds_to_the_same_indices(scancode, index):
    """The numpad is the closest thing a user has to a physical button pad."""
    assert keymap.resolve(_keydown(key=pygame.K_UNKNOWN, scancode=scancode)) == index


def test_scancode_wins_over_a_conflicting_key_code():
    """On AZERTY the digit row is shifted, so position must beat character."""
    ev = _keydown(key=pygame.K_9, scancode=pygame.KSCAN_1)
    assert keymap.resolve(ev) == 0


# ── Letter tier: layout-mapped key code ──────────────────────────────────────


@pytest.mark.parametrize(("key", "index"), [(pygame.K_a, 10), (pygame.K_b, 11), (pygame.K_c, 12)])
def test_letters_bind_by_key_code(key, index):
    """Bound by ev.key so the badge matches the keycap on every layout."""
    assert keymap.resolve(_keydown(key=key, scancode=pygame.KSCAN_Q)) == index


def test_letter_binding_is_case_insensitive_via_key_code():
    """ev.key is immune to Shift/CapsLock, unlike ev.unicode ('A' vs 'a')."""
    assert keymap.resolve(_keydown(key=pygame.K_a, mod=pygame.KMOD_SHIFT)) == 10


# ── Unbound keys and modifier guards ─────────────────────────────────────────


@pytest.mark.parametrize("key", [pygame.K_r, pygame.K_s, pygame.K_d, pygame.K_RETURN, pygame.K_z])
def test_unbound_keys_resolve_to_none(key):
    assert keymap.resolve(_keydown(key=key)) is None


@pytest.mark.parametrize("mod", [pygame.KMOD_CTRL, pygame.KMOD_ALT, pygame.KMOD_MODE])
def test_modifier_chords_do_not_press_buttons(mod):
    """Ctrl/Alt belong to the OS; AltGr synthesizes LCTRL+RALT on Windows/X11."""
    ev = _keydown(key=pygame.K_1, scancode=pygame.KSCAN_1, mod=mod)
    assert keymap.resolve(ev) is None


def test_shift_is_allowed():
    """The digit tier binds by position, so Shift changes nothing about it."""
    ev = _keydown(key=pygame.K_1, scancode=pygame.KSCAN_1, mod=pygame.KMOD_SHIFT)
    assert keymap.resolve(ev) == 0


# ── Sparse synthetic events ──────────────────────────────────────────────────


def test_missing_scancode_falls_back_to_the_key_code():
    """Synthetic test events carry neither .scancode nor .unicode."""
    assert keymap.resolve(_keydown(key=pygame.K_3)) == 2
    assert keymap.resolve(_keydown(key=pygame.K_KP7)) == 6


def test_resolve_tolerates_a_missing_mod_attribute():
    ev = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_1})
    assert keymap.resolve(ev) == 0


# ── Tokens pair a KEYUP with its KEYDOWN ─────────────────────────────────────


def test_token_prefers_the_scancode():
    ev = _keydown(key=pygame.K_9, scancode=pygame.KSCAN_1)
    assert keymap.event_token(ev) == f"s{pygame.KSCAN_1}"


def test_token_falls_back_to_the_key_code():
    assert keymap.event_token(_keydown(key=pygame.K_3)) == f"k{pygame.K_3}"


def test_scancode_and_key_code_tokens_never_collide():
    """Both live in one integer space — scancode 97 and K_a are both 97.

    An unprefixed token would let a physical key and a letter key overwrite each
    other in the hold registry and release the wrong button.
    """
    by_scancode = keymap.event_token(_keydown(key=pygame.K_UNKNOWN, scancode=97))
    by_key = keymap.event_token(_keydown(key=97))
    assert by_scancode != by_key


def test_token_is_stable_across_the_key_edges():
    """The KEYUP must produce the token its KEYDOWN was recorded under."""
    down = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_1, "scancode": pygame.KSCAN_1})
    up = pygame.event.Event(pygame.KEYUP, {"key": pygame.K_1, "scancode": pygame.KSCAN_1})
    assert keymap.event_token(down) == keymap.event_token(up)


# ── Badges ───────────────────────────────────────────────────────────────────


def test_badges_are_hex_across_the_whole_map():
    got = [keymap.badge_for(i) for i in range(keymap.MAX_BOUND_INDEX + 1)]
    assert got == list("0123456789ABC")


def test_badge_beyond_the_map_is_none():
    """No board has a 14th button; if one appears it gets no badge, not a crash."""
    assert keymap.badge_for(keymap.MAX_BOUND_INDEX + 1) is None
    assert keymap.badge_for(-1) is None


def test_the_map_covers_the_whole_fleet():
    """13 buttons is the fleet maximum (four ULX3S variants)."""
    assert keymap.MAX_BOUND_INDEX + 1 >= 13

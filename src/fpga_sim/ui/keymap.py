"""Keyboard bindings for board buttons (roadmap U44 phase 4).

The keyboard is the only input device a user already owns that can express true
simultaneity: hold ``1`` and ``2`` and both buttons go down in the same frame,
and release them in whatever order you like. A mouse has one cursor.

**Hex numbering** — ``0``-``9`` then ``A``/``B``/``C`` — covers all 285 boards in
the fleet (the maximum is 13 buttons) and is the native idiom for a digital-logic
tool. Key *d* presses the button at *index* d, so ``0`` is the **first** button:
consistent with the 0-based labels the board draws and with the ``btn(0)`` VHDL
contract used throughout ``hdl/`` and the docs.

Two tiers, and the split is forced rather than stylistic:

``0``-``9`` bind by **scancode** (physical position)
    On AZERTY and Czech layouts the digit row is *shifted*, so a key-code binding
    would lose the digits entirely for those users. Scancodes are the physical
    key, and the digit row carries the same printed labels on every Latin layout,
    so the badge stays honest. The numpad comes along free (``KSCAN_KP_*`` are
    NumLock-independent), which is the closest thing a user has to a button pad.

``A``/``B``/``C`` bind by **key code** (``ev.key``, already layout-mapped by SDL)
    pygame exposes no scancode -> current-layout-keycap lookup (``pygame.key`` has
    only ``ScancodeWrapper``, ``key_code``, and ``name``), so a scancode-bound
    letter *could not be badged accurately* — on AZERTY the physical ``A`` key is
    labeled ``Q``. Binding by key code is the only way every badge matches the
    keycap under the user's fingers.

``ev.key`` rather than ``ev.unicode`` for the letters: both are layout-mapped, but
``ev.key`` is present on both edges, immune to Shift/CapsLock case, carried by
this repo's synthetic test events, and matches the existing ``K_r``/``K_s``/``K_d``
idiom.

**All input state comes from the event stream.** Never ``pygame.key.get_pressed()``
or pygame-ce's ``get_just_pressed()`` / ``get_just_released()``: every one of them
re-maps its index through ``SDL_GetScancodeFromKey``, so ``ks[KSCAN_1]`` is
silently ``False`` forever, and the ``get_just_*`` pair additionally cannot
distinguish a same-frame release/re-press and never sees a KEYUP a modal's own
``event.get()`` loop consumed.
"""

from __future__ import annotations

import pygame

#: Highest button index the map reaches: 13 buttons (0-12) covers every board.
#: The fleet maximum is 13 (four ULX3S variants); only 6 of 285 exceed 10.
MAX_BOUND_INDEX: int = 12

# ── Digit tier: physical position ────────────────────────────────────────────
# Note the order: the digit row runs 1..9 then 0, so scancode KSCAN_1 is index 0
# and KSCAN_0 is index 9.
_DIGIT_SCANCODES: dict[int, int] = {
    scancode: i
    for i, scancode in enumerate(
        (
            pygame.KSCAN_1,
            pygame.KSCAN_2,
            pygame.KSCAN_3,
            pygame.KSCAN_4,
            pygame.KSCAN_5,
            pygame.KSCAN_6,
            pygame.KSCAN_7,
            pygame.KSCAN_8,
            pygame.KSCAN_9,
            pygame.KSCAN_0,
        )
    )
}
_DIGIT_SCANCODES.update(
    {
        scancode: i
        for i, scancode in enumerate(
            (
                pygame.KSCAN_KP_1,
                pygame.KSCAN_KP_2,
                pygame.KSCAN_KP_3,
                pygame.KSCAN_KP_4,
                pygame.KSCAN_KP_5,
                pygame.KSCAN_KP_6,
                pygame.KSCAN_KP_7,
                pygame.KSCAN_KP_8,
                pygame.KSCAN_KP_9,
                pygame.KSCAN_KP_0,
            )
        )
    }
)

#: Key-code fallback for the digit tier, used when an event carries no
#: ``.scancode`` — synthetic test events are sparse, exactly the trap this repo
#: already records for ``.unicode``.
_DIGIT_KEYS: dict[int, int] = {
    key: i
    for i, key in enumerate(
        (
            pygame.K_1,
            pygame.K_2,
            pygame.K_3,
            pygame.K_4,
            pygame.K_5,
            pygame.K_6,
            pygame.K_7,
            pygame.K_8,
            pygame.K_9,
            pygame.K_0,
        )
    )
}
_DIGIT_KEYS.update(
    {
        key: i
        for i, key in enumerate(
            (
                pygame.K_KP1,
                pygame.K_KP2,
                pygame.K_KP3,
                pygame.K_KP4,
                pygame.K_KP5,
                pygame.K_KP6,
                pygame.K_KP7,
                pygame.K_KP8,
                pygame.K_KP9,
                pygame.K_KP0,
            )
        )
    }
)

# ── Letter tier: layout-mapped key code ──────────────────────────────────────
_LETTER_KEYS: dict[int, int] = {pygame.K_a: 10, pygame.K_b: 11, pygame.K_c: 12}

#: Modifiers that suppress a binding.  Ctrl/Alt chords belong to the OS and to
#: application shortcuts, and AltGr synthesizes ``LCTRL+RALT`` on Windows/X11
#: (``KMOD_MODE`` covers it directly), so a German or Czech user typing AltGr
#: combinations must not be pressing board buttons.  **Shift is deliberately
#: allowed**: the digit tier binds by physical position, so Shift changes
#: nothing about which key was struck.
_BLOCKING_MODS: int = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_MODE

#: Badge text per bound index — hex, matching the keys themselves.
_BADGES: tuple[str, ...] = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B", "C")


def badge_for(index: int) -> str | None:
    """Return the key label bound to button *index*, or None if it has none."""
    return _BADGES[index] if 0 <= index <= MAX_BOUND_INDEX else None


def event_token(event: pygame.event.Event) -> str:
    """Stable identity for a key event, used to pair a KEYUP with its KEYDOWN.

    Prefers the scancode (physical key) and falls back to the key code for the
    sparse synthetic events tests construct, which carry neither ``.scancode``
    nor ``.unicode``.

    The tier prefix is not decoration: scancodes and key codes share one integer
    space (scancode 97 and ``K_a`` are both 97), so an unprefixed token would let
    a physical key and a letter key collide in the hold registry and release each
    other's hold.
    """
    scancode = getattr(event, "scancode", None)
    return f"s{int(scancode)}" if scancode else f"k{int(event.key)}"


def resolve(event: pygame.event.Event) -> int | None:
    """Return the button index *event* binds to, or None for an unbound key.

    Resolution happens at **key-down only**; the result is recorded under
    :func:`event_token` and popped at key-up. A KEYUP must never re-resolve,
    because SDL reports modifier state at event time and releasing a modifier
    before the key is the normal way people let go of a chord — re-resolving
    would clear a hold that was never taken and leak the real one forever.
    """
    if getattr(event, "mod", 0) & _BLOCKING_MODS:
        return None
    scancode = getattr(event, "scancode", None)
    if scancode:
        index = _DIGIT_SCANCODES.get(int(scancode))
        if index is not None:
            return index
    key = int(event.key)
    index = _DIGIT_KEYS.get(key)
    if index is not None:
        return index
    return _LETTER_KEYS.get(key)

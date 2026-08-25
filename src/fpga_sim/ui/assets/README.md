# UI assets

Runtime image assets loaded by `fpga_sim.ui.icons`.

## `locked.png`

The latched-button indicator (U44). From the **Game Icons** pack by Kenney
Vleugels (<https://kenney.nl/assets/game-icons>), file `PNG/White/2x/locked.png`
— 100x100 RGBA, white pixels plus an alpha mask, so `icons.py` recolors it to
whatever the active theme wants rather than shipping one file per theme.

**License: CC0 1.0** (public domain dedication,
<https://creativecommons.org/publicdomain/zero/1.0/>). The pack's own
`license.txt` reads: *"You may use these graphics in personal and commercial
projects. Credit (Kenney or <https://www.kenney.nl>) would be nice but is not mandatory."*
Credit is given in the repository README's License section even though it is not
required.

Provenance: `kenney_game-icons.zip`, sha256
`7a86d8d58e0b851e22004b3c70bf90b003632bbf9ac633424daa3bb17d9e7e4e`, downloaded
2026-08-25 from the URL published on the asset page above.

### Why a PNG rather than the pack's vector sheet

The pack ships `Vector/vector_whiteIcons.svg`, but it is a single `<path>`
element containing all 107 icons with no ids, no groups, and no `viewBox` —
there is no clean way to slice one icon out of it, and `load_sized_svg` on the
sheet returns all 107 squeezed into the requested box. Nor would vector help:
the icon draws at 7-30 px from a 100 px source (3-14x supersampled), and SVG
only wins when scaling *past* the source resolution.

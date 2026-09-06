"""Constraint-dialect parsers for U21 board-native VHDL port conventions.

Each dialect module (``qsf``, ``xdc``, ``ucf``, ``pcf``, ``lpf``, ``cst``, ``ccf``,
``boardstore_xml``) exposes a pure ``parse(text: str) -> PortTable`` that turns a
vendor/community constraint file into the dialect-agnostic :class:`PortTable`
shape (see ``types.py``). :mod:`classify` then buckets a ``PortTable``'s ports
into a ``port_convention``-shaped dict (clk/leds/switches/buttons/seven_seg)
using name-shape rules alone, with no dialect-specific knowledge.

Self-contained: no ``fpga_sim`` dependency, no network access. Consumed by the
(future, A3) ``scripts/sync_port_conventions.py`` generator.
"""

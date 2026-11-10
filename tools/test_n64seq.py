#!/usr/bin/env python3
"""Small original bytecode fixtures for sequence channel state regressions."""
import unittest

import n64seq


def sequence(parts):
    data = bytearray(128)
    for offset, code in parts.items():
        data[offset:offset + len(code)] = bytes(code)
    return data


class ChannelStateChecks(unittest.TestCase):
    def test_restart_preserves_instrument_and_large_notes(self):
        data = sequence({
            # Tempo 120; init channel 0; start two sections, one beat apart.
            0: [0xDD, 120, 0xD7, 0, 1, 0x90, 0, 0x20, 0xFD, 48,
                0x90, 0, 0x30, 0xFD, 48, 0xFF],
            0x20: [0xC4, 0xC1, 3, 0xDF, 127, 0x90, 0, 0x40, 0xFD, 96],
            # Section two relies on the settings from section one.
            0x30: [0x90, 0, 0x50, 0xFD, 96],
            0x40: [0x40 + 39, 48, 100, 0xFF],
            0x50: [0x40 + 43, 48, 90, 0xFF],
        })
        notes, _ = n64seq.play(data)
        self.assertEqual([(round(n.t, 3), n.instr, n.note, n.velocity) for n in notes],
                         [(0.0, 3, 39, 100), (0.5, 3, 43, 90)])

    def test_writeseq_adds_value_to_byte_at_fixed_address(self):
        data = sequence({
            0: [0xDD, 120, 0x90, 0, 0x20, 0xFD, 96, 0xFF],
            # Set value=2, write 0x65+2 to address 0x40, start layer there.
            0x20: [0xC4, 0xC1, 3, 0xCC, 2, 0xC7, 0x65, 0, 0x40,
                   0x90, 0, 0x40, 0xFD, 96],
            0x40: [0, 48, 100, 0xFF],
        })
        notes, _ = n64seq.play(data)
        self.assertEqual([(n.note, n.velocity) for n in notes], [(39, 100)])
        self.assertEqual(data[0x40], 0)  # play works on its own copy

    def test_initchannels_resets_prior_section_settings(self):
        data = sequence({
            0: [0xDD, 120, 0x90, 0, 0x20, 0xFD, 48, 0xD7, 0, 1,
                0x90, 0, 0x30, 0xFD, 48, 0xFF],
            0x20: [0xC4, 0xC1, 3, 0x90, 0, 0x40, 0xFD, 96],
            0x30: [0xC1, 4, 0x90, 0, 0x50, 0xFD, 96],
            0x40: [0x40 + 39, 48, 100, 0xFF],
            # Short-note mode must be restored by initchannels.
            0x50: [0xC3, 48, 0xC1, 90, 0x40 + 43, 0xFF],
        })
        notes, _ = n64seq.play(data)
        self.assertEqual([(n.instr, n.note, n.velocity) for n in notes],
                         [(3, 39, 100), (4, 43, 90)])


if __name__ == "__main__":
    unittest.main()

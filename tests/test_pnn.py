"""PNN decoding from received GridConnect frames."""

import unittest

from workbench.pnn import Pnn, decode_pnn


class PnnTests(unittest.TestCase):
    def test_decodes_pnn_fields(self):
        self.assertEqual(
            decode_pnn(b":SB040NB601020D2203;"),
            Pnn(node_number=258, manufacturer=13, module_type=34, flags=3),
        )

    def test_flag_properties_decode_only_their_assigned_bits(self):
        # Consumer, producer, FLiM, bootloading, own events.
        cases = (
            (0x00, (False, False, False, False, False)),
            (0x01, (True, False, False, False, False)),
            (0x02, (False, True, False, False, False)),
            (0x04, (False, False, True, False, False)),
            (0x08, (False, False, False, True, False)),
            (0x10, (False, False, False, False, True)),
            (0x1F, (True, True, True, True, True)),
            (0x20, (False, False, False, False, False)),
            (0xC0, (False, False, False, False, False)),
            (0xFF, (True, True, True, True, True)),
        )
        for flags, expected in cases:
            with self.subTest(flags=flags):
                node = Pnn(258, 13, 34, flags)
                self.assertEqual(
                    (
                        node.is_consumer,
                        node.is_producer,
                        node.is_flim,
                        node.supports_bootloading,
                        node.consumes_own_events,
                    ),
                    expected,
                )

    def test_other_opcode_is_ignored(self):
        self.assertIsNone(decode_pnn(b":SB040N0D;"))

    def test_rejects_malformed_frame(self):
        for frame in (
            b"SB040NB601020D2203;",
            b":SB040NB601020D2203",
            b":SB040RB601020D2203;",
            b":SB040NB601020D22G3;",
            b":SB040NB601020D220;",
            b":SB040NB601020D2203;:SB060N0D;",
            b":SB041NB601020D2203;",  # Unused header bits must be zero.
            b":SB40NB601020D2203;",  # Three-digit header
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_pnn(frame)

    def test_rejects_short_and_long_pnn_payloads(self):
        for frame in (b":SB040NB601020D22;", b":SB040NB601020D220300;"):
            with (
                self.subTest(frame=frame),
                self.assertRaisesRegex(
                    ValueError, "PNN payload must contain exactly six bytes"
                ),
            ):
                decode_pnn(frame)


if __name__ == "__main__":
    unittest.main()

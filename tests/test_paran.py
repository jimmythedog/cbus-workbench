"""PARAN decoding from received GridConnect frames."""

import unittest
from dataclasses import FrozenInstanceError

from workbench.paran import Paran, decode_paran


class ParanTests(unittest.TestCase):
    def test_decodes_paran_fields(self):
        self.assertEqual(
            decode_paran(b":SB040N9B01020741;"),
            Paran(node_number=258, parameter_index=7, parameter_value=65),
        )
        self.assertEqual(
            decode_paran(b":SB040N9B01020014;"),
            Paran(node_number=258, parameter_index=0, parameter_value=20),
        )

    def test_result_is_immutable(self):
        result = decode_paran(b":SB040N9B01020741;")
        with self.assertRaises(FrozenInstanceError):
            result.parameter_value = 42

    def test_other_opcode_is_ignored(self):
        self.assertIsNone(decode_paran(b":SB040NB601020D2203;"))

    def test_rejects_malformed_frame(self):
        for frame in (
            b"SB040N9B01020741;",
            b":SB040N9B01020741",
            b":SB040R9B01020741;",
            b":SB040N9B0102074G;",
            b":SB040N9B0102074;",
            b":SB040N9B01020741;:SB060N0D;",
            b":SB041N9B01020741;",  # Unused header bits must be zero.
            b":SB40N9B01020741;",  # Three-digit header
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_paran(frame)

    def test_rejects_short_and_long_paran_payloads(self):
        for frame in (b":SB040N9B010207;", b":SB040N9B0102074100;"):
            with (
                self.subTest(frame=frame),
                self.assertRaisesRegex(
                    ValueError, "PARAN payload must contain exactly five bytes"
                ),
            ):
                decode_paran(frame)


if __name__ == "__main__":
    unittest.main()

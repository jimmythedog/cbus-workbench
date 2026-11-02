"""Shared GridConnect validation and extraction contracts."""

import unittest

from workbench.gridconnect import extract_frames, validate_frame


class GridConnectTests(unittest.TestCase):
    def test_validate_one_complete_printable_frame(self):
        self.assertIsNone(validate_frame(b":S123N00;"))
        for frame in (b"", b":;", b"S123N00;", b":S123N00", b":S1;:S2;", b":S\xff;"):
            with (
                self.subTest(frame=frame),
                self.assertRaisesRegex(
                    ValueError,
                    "Expected one complete printable ASCII GridConnect frame",
                ),
            ):
                validate_frame(frame)

    def test_split_and_multiple_frames_leave_only_incomplete_tail(self):
        buffer = bytearray(b":S123N")
        self.assertEqual(extract_frames(buffer), [])
        self.assertEqual(buffer, b":S123N")

        buffer.extend(b"00;:S456N01;:S789N")
        self.assertEqual(extract_frames(buffer), [b":S123N00;", b":S456N01;"])
        self.assertEqual(buffer, b":S789N")

    def test_leading_noise_is_removed_without_validating_incoming_data(self):
        buffer = bytearray(b"noise;:S1:S2;:S\xff;trailing noise")
        self.assertEqual(extract_frames(buffer), [b":S1:S2;", b":S\xff;"])
        self.assertEqual(buffer, b"")


if __name__ == "__main__":
    unittest.main()

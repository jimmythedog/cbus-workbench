"""NUMEV decoding from received GridConnect frames."""

import unittest

from workbench.numev import Numev, decode_numev


class NumevTests(unittest.TestCase):
    def test_decodes_node_and_zero_or_positive_count(self):
        self.assertEqual(decode_numev(b":SB040N74010200;"), Numev(258, 0))
        self.assertEqual(decode_numev(b":SB040N740102FF;"), Numev(258, 255))
        self.assertIsNone(decode_numev(b":SB040N9B010204FF;"))

    def test_rejects_bad_frames_and_payload_lengths(self):
        for frame in (
            b":SB040N740102;",
            b":SB040N7401020001;",
            b":SB041N74010200;",
            b":SB040N7401020;",
            b":SB040N7401020G;",
            b":SB040R74010200;",
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_numev(frame)


if __name__ == "__main__":
    unittest.main()

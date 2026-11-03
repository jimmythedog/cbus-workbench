"""NVANS decoding from received GridConnect frames."""

import unittest

from workbench.nvans import Nvans, decode_nvans


class NvansTests(unittest.TestCase):
    def test_decodes_node_index_and_zero_value(self):
        self.assertEqual(decode_nvans(b":SB040N9701020100;"), Nvans(258, 1, 0))
        self.assertIsNone(decode_nvans(b":SB040N9B01020602;"))

    def test_rejects_malformed_or_wrong_length_reply(self):
        for frame in (
            b":SB040N97010201;",
            b":SB040N9701020100FF;",
            b":SB040N9701020000;",
            b":SB041N9701020100;",
            b":SB040N970102010G;",
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_nvans(frame)


if __name__ == "__main__":
    unittest.main()

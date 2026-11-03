"""CMDERR decoding from received GridConnect frames."""

import unittest

from workbench.cmderr import Cmderr, decode_cmderr


class CmderrTests(unittest.TestCase):
    def test_decodes_node_and_error_code(self):
        self.assertEqual(decode_cmderr(b":SB040N6F010205;"), Cmderr(258, 5))
        self.assertIsNone(decode_cmderr(b":SB040NB50102070105;"))

    def test_rejects_malformed_cmderr(self):
        for frame in (
            b":SB040N6F0102;",
            b":SB040N6F01020500;",
            b":SB041N6F010205;",
            b":SB040N6F01020;",
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_cmderr(frame)

"""ENRSP decoding from received GridConnect frames."""

import unittest

from workbench.enrsp import Enrsp, decode_enrsp


class EnrspTests(unittest.TestCase):
    def test_decodes_node_event_identity_and_internal_index(self):
        self.assertEqual(
            decode_enrsp(b":SB040NF20102000A001407;"), Enrsp(258, 10, 20, 7)
        )
        self.assertIsNone(decode_enrsp(b":SB040N74010201;"))

    def test_rejects_malformed_enrsp(self):
        for frame in (
            b":SB040NF20102000A0014;",
            b":SB040NF20102000A00140700;",
            b":SB041NF20102000A001407;",
            b":SB040NF20102000A0014070;",
            b":SB040NF20102000A00140G;",
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_enrsp(frame)

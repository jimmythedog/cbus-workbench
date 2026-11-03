"""NEVAL decoding from received GridConnect frames."""

import unittest

from workbench.neval import Neval, decode_neval


class NevalTests(unittest.TestCase):
    def test_decodes_node_indices_and_zero_value(self):
        self.assertEqual(decode_neval(b":SB040NB50102070200;"), Neval(258, 7, 2, 0))
        self.assertEqual(decode_neval(b":SB040NB501020001FF;"), Neval(258, 0, 1, 255))
        self.assertIsNone(decode_neval(b":SB040NF20102000A001407;"))

    def test_rejects_bad_length_index_and_gridconnect(self):
        for frame in (
            b":SB040NB501020702;",
            b":SB040NB5010207020001;",
            b":SB040NB50102070005;",
            b":SB041NB50102070200;",
            b":SB040NB5010207020;",
            b":SB040NB5010207020G;",
        ):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_neval(frame)

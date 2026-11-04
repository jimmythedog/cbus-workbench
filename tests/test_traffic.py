"""Diagnostics opcode labels for valid GridConnect frames."""

import unittest

from workbench.traffic import describe_frame


class TrafficTests(unittest.TestCase):
    def test_recognised_opcodes_use_cbus_mnemonics(self):
        cases = (
            ("0D", "QNN"),
            ("57", "NERD"),
            ("58", "RQEVN"),
            ("6F", "CMDERR"),
            ("71", "NVRD"),
            ("73", "RQNPN"),
            ("74", "NUMEV"),
            ("90", "ACON"),
            ("91", "ACOF"),
            ("97", "NVANS"),
            ("98", "ASON"),
            ("99", "ASOF"),
            ("9B", "PARAN"),
            ("9C", "REVAL"),
            ("B5", "NEVAL"),
            ("B6", "PNN"),
            ("53", "NNLRN"),
            ("54", "NNULN"),
            ("95", "EVULN"),
            ("B2", "REQEV"),
            ("D2", "EVLRN"),
            ("D3", "EVANS"),
            ("F2", "ENRSP"),
        )
        for opcode, mnemonic in cases:
            frame = f":SB040N{opcode}0102;".encode("ascii")
            with self.subTest(opcode=opcode):
                label, details = describe_frame(frame, "Default")
                self.assertEqual(label, mnemonic)
                self.assertEqual(details, f"Default: {frame.decode('ascii')}")

    def test_unknown_opcode_keeps_hex_label_and_raw_frame(self):
        frame = b":SB040NFE0102;"
        self.assertEqual(
            describe_frame(frame, "Default"), ("0xFE", "Default: :SB040NFE0102;")
        )

    def test_detailed_discovery_summary_is_preserved(self):
        self.assertEqual(
            describe_frame(b":SB040N0D;", "Default"),
            ("QNN", "Default: CAN ID 2"),
        )


if __name__ == "__main__":
    unittest.main()

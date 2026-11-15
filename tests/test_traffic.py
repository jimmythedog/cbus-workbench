"""Diagnostics opcode labels and frame breakdowns for GridConnect frames."""

import unittest

from workbench.traffic import decode_can_frame, describe_frame


class TrafficTests(unittest.TestCase):
    def test_frame_breakdown_is_decimal(self):
        # Header 0xB040 is CAN identifier 0b10_11_0000010.
        self.assertEqual(
            decode_can_frame(b":SB040N9B01020002;"),
            [
                ("Major priority", "2"),
                ("Minor priority", "3"),
                ("CAN ID", "2"),
                ("Opcode", "155 (PARAN)"),
                ("Node number", "258"),
                ("Parameter index", "0 (Number of parameters)"),
                ("Parameter value", "2"),
                ("Data bytes", "155, 1, 2, 0, 2"),
                ("Data length", "5"),
            ],
        )

    def test_data_fields_are_named_from_the_spec(self):
        cases = (
            (
                b":SB040ND201020005010A;",
                [
                    ("Event node number", "258"),
                    ("Event number", "5"),
                    ("EV index", "1"),
                    ("EV value", "10"),
                ],
            ),
            (
                b":SB040NF201020304050607;",
                [
                    ("Node number", "258"),
                    ("Event node number", "772"),
                    ("Event number", "1286"),
                    ("Event index", "7"),
                ],
            ),
            (
                b":SB040NB60102A50B07;",
                [
                    ("Node number", "258"),
                    ("Manufacturer", "165 (MERG)"),
                    ("Module type", "11 (CANSERVO)"),
                    ("Flags", "7 (Consumer, Producer, FLiM)"),
                ],
            ),
            (
                b":SB040N6F01020C;",
                [("Node number", "258"), ("Error", "12 (Invalid node variable value)")],
            ),
            (
                b":SB040N9B0102084F;",
                [
                    ("Node number", "258"),
                    ("Parameter index", "8 (Flags)"),
                    (
                        "Parameter value",
                        "79 (Consumer, Producer, FLiM, Bootloader, VLCB)",
                    ),
                ],
            ),
        )
        for frame, expected in cases:
            with self.subTest(frame=frame):
                rows = decode_can_frame(frame)
                # Named fields sit between the opcode and the raw data bytes.
                self.assertEqual(rows[4:-2], expected)

    def test_unknown_codes_stay_numeric(self):
        rows = dict(decode_can_frame(b":SB040NB60102FE0880;"))
        self.assertEqual(rows["Manufacturer"], "254")
        self.assertEqual(rows["Module type"], "8")
        self.assertEqual(rows["Flags"], "128")
        self.assertEqual(dict(decode_can_frame(b":SB040N6F010208;"))["Error"], "8")

    def test_fields_are_not_guessed_for_unknown_opcodes_or_wrong_lengths(self):
        # 0x40 is outside OPCODE_NAMES; the ACON is one byte short.
        for frame in (b":SB060N40FF01;", b":SB040N90010200;", b":S0FE0N0D;"):
            with self.subTest(frame=frame):
                rows = decode_can_frame(frame)
                self.assertEqual(
                    [label for label, _ in rows[4:]], ["Data bytes", "Data length"]
                )
        self.assertIn(("CAN ID", "127"), decode_can_frame(b":S0FE0N0D;"))
        self.assertIn(("Opcode", "64"), decode_can_frame(b":SB060N40FF01;"))

    def test_undecodable_frames_have_no_breakdown(self):
        for frame in (b":X00080004N0D;", b":SB040N;", b":SB041N0D;", b"garbage"):
            with self.subTest(frame=frame):
                self.assertEqual(decode_can_frame(frame), [])

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
            ("10", "RQNP"),
            ("42", "SNN"),
            ("50", "RQNN"),
            ("51", "NNREL"),
            ("52", "NNACK"),
            ("EF", "PARAMS"),
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

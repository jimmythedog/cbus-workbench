"""Verified EV transactions through observable wire exchanges."""

import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_nv_write import Connection

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.node_backup_diff import compare_live_node
from workbench.node_backup_files import node_backup
from workbench.pnn import Pnn


class EvWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        self.state = NodeState(
            Pnn(258, 13, 34, 5),
            parameters={5: 3, 8: 5, 6: 1},
            event_identities={4: (0, 1000)},
            ev_values={4: {1: 0, 2: 12, 3: None}},
            event_progress=DiscoveryProgress.COMPLETE,
            nv_progress=DiscoveryProgress.COMPLETE,
            nv_values={1: 7},
            can_id=2,
        )
        self.service.node_states[258] = self.state
        self.results = []
        self.service.ev_write.finished.connect(lambda *args: self.results.append(args))
        self.addCleanup(self.service.close)

    def reply(self, payload, header="B040"):
        self.connection.frame_received.emit(f":S{header}N{payload};".encode())

    def enter(self, changes=None):
        self.service.ev_write.begin(258, changes or {(0, 1000, 2): 13})
        self.assertEqual(
            self.connection.sent[-2:], [b":SBFC0N530102;", b":SBFC0N73010208;"]
        )
        self.reply("9B01020825")

    def verify(self, ev=2, value=13):
        self.reply("590102")
        self.assertEqual(
            self.connection.sent[-1], f":SBFC0NB2000003E8{ev:02X};".encode()
        )
        self.reply(f"D3000003E8{ev:02X}{value:02X}")

    def test_short_event_readback_with_consumer_node_number(self):
        self.enter()
        self.assertEqual(self.connection.sent[-1], b":SBFC0ND2000003E8020D;")
        self.reply("590102")
        self.assertEqual(self.connection.sent[-1], b":SBFC0NB2000003E802;")
        self.reply("D3010203E8020D")
        self.assertEqual(self.state.ev_values[4][2], 13)
        self.assertEqual(self.state.event_identities, {4: (0, 1000)})
        self.exit()
        self.reply("74010201")
        self.reply("F20102000003E807")
        for ev, value in enumerate((0, 13, 0), 1):
            self.reply(f"B5010207{ev:02X}{value:02X}")
        self.assertTrue(self.results[-1][1])

    def test_short_event_ignores_unrelated_readbacks_and_compare_is_inconclusive(self):
        self.state.parameter_progress = DiscoveryProgress.COMPLETE
        self.state.ev_progress = DiscoveryProgress.COMPLETE
        self.state.stored_event_count = 1
        backup = node_backup(self.state)
        self.assertTrue(backup["complete"])
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.enter()
            self.reply("590102")
            for payload, header in (
                ("D3010203E8020D", "B060"),  # Different source CAN ID.
                ("D3010303E8020D", "B040"),  # Unrelated node number.
                ("D3010203E9020D", "B040"),  # Different event number.
                ("D3010203E8010D", "B040"),  # Different EV index.
            ):
                self.reply(payload, header)
            self.assertNotIn(2, self.state.ev_values[4])
            QTest.qWait(20)
            self.exit()
        self.assertFalse(self.results[-1][1])
        self.assertIn("EV readback", self.results[-1][2])
        self.assertEqual(compare_live_node(self.state, backup), ([], True))
        self.assertFalse(node_backup(self.state)["complete"])

    def test_long_event_does_not_accept_consumer_node_number(self):
        self.state.event_identities[4] = (300, 1000)
        self.enter({(300, 1000, 2): 13})
        self.reply("590102")
        self.reply("D3010203E8020D")
        self.assertNotIn(2, self.state.ev_values[4])
        self.reply("D3012C03E8020D")
        self.assertEqual(self.state.ev_values[4][2], 13)

    def exit(self):
        self.assertEqual(
            self.connection.sent[-2:], [b":SBFC0N540102;", b":SBFC0N73010208;"]
        )
        self.reply("9B01020805")

    def test_ack_and_readback_are_required_and_source_is_matched(self):
        self.enter({(0, 1000, 2): 13})
        self.assertEqual(self.connection.sent[-1], b":SBFC0ND2000003E8020D;")
        self.reply("D3000003E8020D")  # Before WRACK: cannot confirm a write.
        self.assertNotIn(2, self.state.ev_values[4])
        self.reply("59010200")  # Malformed WRACK.
        self.reply("590102")
        self.reply("D3000003E8020D", "B041")  # Invalid GridConnect SID.
        self.reply("D3000003E8020D", "B060")  # Wrong sender.
        self.reply("D3000003E9020D")  # Wrong identity.
        self.assertNotIn(2, self.state.ev_values[4])
        self.reply("D3000003E8020D")
        self.assertEqual(self.state.ev_values[4][2], 13)
        self.assertFalse(self.results)
        self.exit()
        self.assertFalse(self.results)
        self.reply("74010201")
        self.reply("F20102000003E807")
        for ev, value in enumerate((0, 13, 0), 1):
            self.reply(f"B5010207{ev:02X}{value:02X}")
        self.assertTrue(self.results[-1][1])

    def test_rejected_write_and_mismatch_exit_without_confirming_value(self):
        for reply, explanation in (
            ("6F01020B", "rejected"),
            ("D3000003E8020E", "readback mismatch"),
        ):
            with self.subTest(reply=reply):
                self.enter()
                if reply.startswith("D3"):
                    self.reply("590102")
                self.reply(reply)
                self.exit()
                self.assertFalse(self.results[-1][1])
                self.assertIn(explanation, self.results[-1][2])
                self.assertNotIn(2, self.state.ev_values[4])
                self.reply("D3000003E8020D")
                self.assertNotIn(2, self.state.ev_values[4])
                self.service.close()
                self.service = CbusService(self.connection, 126)
                self.service.node_states[258] = self.state
                self.service.ev_write.finished.connect(
                    lambda *args: self.results.append(args)
                )
                self.addCleanup(self.service.close)

    def test_unexpected_learner_is_released_and_save_stops(self):
        self.enter()
        self.reply("590103")
        self.assertIn(b":SBFC0N540103;", self.connection.sent)
        self.exit()
        self.assertIn("Another node acknowledged", self.results[-1][2])
        self.assertIn("exit is unconfirmed", self.results[-1][2])
        self.assertNotIn(2, self.state.ev_values[4])

    def test_write_transmission_error_attempts_exit(self):
        send = self.connection.send

        def fail_write(frame):
            if b"ND2" in frame:
                raise OSError("write failed")
            send(frame)

        self.connection.send = fail_write
        self.enter()
        self.exit()
        self.assertIn("Could not transmit", self.results[-1][2])
        self.assertNotIn(2, self.state.ev_values[4])

    def test_exit_transmission_failure_warns_after_verified_write(self):
        self.enter()
        send = self.connection.send

        def fail_exit(frame):
            if b"N54" in frame:
                raise OSError("exit failed")
            send(frame)

        self.connection.send = fail_exit
        self.verify()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Could not transmit learn-mode exit", self.results[-1][2])
        self.assertIn("exit is unconfirmed", self.results[-1][2])

    def test_timeouts_and_unconfirmed_exit_are_bounded(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.enter()
            QTest.qWait(20)
            self.assertIn(b":SBFC0N540102;", self.connection.sent)
            QTest.qWait(20)
        self.assertFalse(self.results[-1][1])
        self.assertIn("Timed out", self.results[-1][2])
        self.assertIn("exit is unconfirmed", self.results[-1][2])
        self.assertNotIn(2, self.state.ev_values[4])

    def test_partial_failure_and_interrupt_attempt_exit(self):
        self.enter({(0, 1000, 1): 1, (0, 1000, 2): 13})
        self.verify(1, 1)
        self.assertEqual(self.state.ev_values[4], {1: 1, 3: None})
        self.service.ev_write.interrupt()
        self.exit()
        self.assertFalse(self.results[-1][1])
        self.assertIn("1 of 2 changes verified", self.results[-1][2])
        self.assertIn("interrupted", self.results[-1][2])

    def test_partial_rejection_does_not_write_remaining_values(self):
        self.enter({(0, 1000, 1): 1, (0, 1000, 2): 13, (0, 1000, 3): 9})
        self.verify(1, 1)
        self.reply("6F01020B")
        self.exit()
        self.assertEqual(self.state.ev_values[4], {1: 1, 3: None})
        self.assertIn("1 of 3 changes verified", self.results[-1][2])
        self.assertFalse(
            any(b"ND2000003E80309" in frame for frame in self.connection.sent)
        )

    def test_readback_timeout_and_still_learning_exit_are_failures(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.enter()
            self.reply("590102")
            QTest.qWait(20)
            self.assertIn(b":SBFC0N540102;", self.connection.sent)
            self.reply("9B01020825")
        self.assertIn("EV readback", self.results[-1][2])
        self.assertIn("still reports learn mode", self.results[-1][2])
        self.assertNotIn(2, self.state.ev_values[4])

    def test_disconnect_and_send_failure_report_uncertain_exit(self):
        self.enter()
        self.connection.fail_send = True
        self.service.close()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Connection ended", self.results[-1][2])
        self.assertIn("exit is unconfirmed", self.results[-1][2])

    def test_no_write_without_confirmed_learn_and_exit_still_attempted(self):
        self.state.parameters[8] = 0x45  # VLCB specifies a reliable learn flag.
        self.service.ev_write.begin(258, {(0, 1000, 2): 13})
        self.reply("9B01020805")
        self.exit()
        self.assertFalse(any(b"ND2" in frame for frame in self.connection.sent))
        self.assertIn("did not confirm learn mode", self.results[-1][2])

    def test_legacy_clear_flag_save_shows_simple_success(self):
        self.service.ev_write.begin(258, {(0, 1000, 2): 13})
        self.reply("9B01020805")  # Legacy flags do not report learn mode.
        self.assertEqual(self.connection.sent[-1], b":SBFC0ND2000003E8020D;")
        self.assertNotIn(2, self.state.ev_values[4])
        self.verify()
        self.assertEqual(
            self.connection.sent[-2:], [b":SBFC0N540102;", b":SBFC0N580102;"]
        )
        self.assertFalse(self.results)
        self.reply("74010201")
        self.reply("F20102000003E807")
        for ev, value in enumerate((0, 13, 0), 1):
            self.reply(f"B5010207{ev:02X}{value:02X}")
        self.assertTrue(self.results[-1][1])

    def test_no_flags_parameter_uses_standard_teaching_and_failure_cleanup(self):
        self.state.parameters.pop(8)
        self.service.ev_write.begin(258, {(0, 1000, 2): 13})
        self.assertEqual(
            self.connection.sent, [b":SBFC0N530102;", b":SBFC0ND2000003E8020D;"]
        )
        self.reply("6F01020B")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N540102;")
        self.assertFalse(self.results[-1][1])
        self.assertIn("rejected", self.results[-1][2])
        self.assertIn("exit cannot be confirmed", self.results[-1][2])
        self.assertNotIn(2, self.state.ev_values[4])

    def test_legacy_readback_timeout_still_sends_exit(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.service.ev_write.begin(258, {(0, 1000, 2): 13})
            self.reply("9B01020805")
            self.reply("590102")
            QTest.qWait(30)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N540102;")
        self.assertIn("Timed out waiting for EV readback", self.results[-1][2])
        self.assertIn("exit cannot be confirmed", self.results[-1][2])
        self.assertNotIn(2, self.state.ev_values[4])

    def test_refresh_failure_is_distinct_from_verified_writes(self):
        self.enter()
        self.verify()
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.exit()
            QTest.qWait(30)
        self.assertIn("Changes saved, but", self.results[-1][2])
        self.assertIn("refresh failed", self.results[-1][2])
        self.assertNotIn("successfully", self.results[-1][2])

    def test_discovery_absence_during_pending_save_is_not_a_write_rejection(self):
        # Parameter discovery starts EV reads for already confirmed identities.
        self.reply("B601020D2205")
        self.reply("9B01020005")
        self.reply("9B01020201")
        self.reply("9B01020401")
        self.reply("9B01020503")
        self.reply("9B0102010D")
        self.reply("9B01020322")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9C01020401;")
        self.service.ev_write.begin(258, {(0, 1000, 2): 13})
        self.reply("6F010205")
        self.assertFalse(self.results)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010208;")

    def test_save_waits_for_discovery_and_excludes_nv_save(self):
        self.reply("B601030D2200")
        self.service.ev_write.begin(258, {(0, 1000, 2): 13})
        self.assertEqual(self.connection.sent, [b":SBFC0N73010300;"])
        self.reply("9B01030002")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010208;")
        with self.assertRaises(ValueError):
            self.service.write_nvs(258, {1: 8})

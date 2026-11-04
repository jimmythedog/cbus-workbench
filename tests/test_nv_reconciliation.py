"""NV Save applies the editor's complete intent despite firmware side effects."""

import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_nv_write import Connection

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.node_backup_files import node_backup
from workbench.pnn import Pnn


class NvReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        done = DiscoveryProgress.COMPLETE
        self.state = NodeState(
            Pnn(258, 13, 32, 5),
            parameters={5: 2, 6: 3, 8: 5},
            nv_values={1: 1, 2: 20, 3: 30},
            stored_event_count=1,
            event_identities={4: (0, 1000)},
            ev_values={4: {1: 0, 2: None}},
            parameter_progress=done,
            nv_progress=done,
            event_progress=done,
            ev_progress=done,
            can_id=2,
        )
        self.service.nodes[258] = self.state.identity
        self.service.node_states[258] = self.state
        self.nvs = self.state.nv_values.copy()
        self.events = {(0, 1000): {1: 0, 2: None}}
        self.results = []
        self.completions = []
        self.service.nv_write.finished.connect(
            lambda *args: self.completions.append(args)
        )
        self.service.nv_write.refresh_finished.connect(
            lambda *args: self.results.append(args)
        )
        self.position = 0
        self.change_earlier = False
        self.reject_nv = None
        self.drop_ack = False
        self.add_event = False
        self.drop_nv_reads = False
        self.addCleanup(self.close_service)

    def close_service(self):
        if self.connection.state == "Connected":
            self.service.close()
            self.connection.state = "Disconnected"

    def reply(self, payload):
        self.connection.frame_received.emit(f":SB040N{payload};".encode())

    def run_node(self, completed=None):
        """Answer NV/discovery frames; any event teaching is an unexpected effect."""
        for _ in range(500):
            self.app.processEvents()
            done = completed() if completed is not None else bool(self.results)
            if done:
                return
            if self.position == len(self.connection.sent):
                QTest.qWait(1)
                continue
            frame = self.connection.sent[self.position]
            self.position += 1
            data = bytes.fromhex(frame.decode().split("N")[1][:-1])
            op = data[0]
            if op == 0x96:
                index, value = data[3:]
                if index == self.reject_nv:
                    self.reply("6F010201")
                    continue
                self.nvs[index] = value
                if index == 1:  # TYPE resets an associated, higher-numbered NV.
                    self.nvs[2] = 0
                if index == 3 and self.change_earlier:
                    self.nvs[1] = 99
                if self.add_event:
                    self.events[(258, 2000)] = {1: 7, 2: None}
                if not self.drop_ack:
                    self.reply("590102")
            elif op == 0x71:
                if self.drop_nv_reads:
                    continue
                self.reply(f"970102{data[3]:02X}{self.nvs[data[3]]:02X}")
            elif op == 0x73:
                parameters = {0: 8, 2: 97, 4: 10, 5: 2, 6: 3, 7: 1, 8: 5}
                self.reply(f"9B0102{data[3]:02X}{parameters[data[3]]:02X}")
            elif op == 0x58:
                self.reply(f"740102{len(self.events):02X}")
            elif op == 0x57:
                for slot, (nn, en) in enumerate(self.events, 9):
                    self.reply(f"F20102{nn:04X}{en:04X}{slot:02X}")
            elif op == 0x9C:
                identity = list(self.events)[data[3] - 9]
                value = self.events[identity][data[4]]
                self.reply(
                    "6F010205"
                    if value is None
                    else f"B50102{data[3]:02X}{data[4]:02X}{value:02X}"
                )
            else:
                self.fail(f"Unexpected frame during NV-only Save: {frame}")
        self.fail("NV Save did not complete")

    def test_type_reset_reconciles_matching_higher_nv_and_keeps_firmware_events(self):
        desired = {1: 2, 2: 20, 3: 30}
        self.add_event = True
        self.service.save_nvs(258, desired)
        desired[2] = 77  # The accepted configuration is independent of the caller.
        self.run_node()
        self.assertEqual(self.state.nv_values, {1: 2, 2: 20, 3: 30})
        self.assertIn("Changes saved successfully", self.results[-1][1])
        self.assertEqual(len(self.completions), 1)
        self.assertTrue(self.completions[0][1])
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.service.writes_busy())
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f],
            [b":SBFC0N9601020102;", b":SBFC0N9601020214;"],
        )
        self.assertEqual(set(self.state.event_identities.values()), set(self.events))
        self.assertEqual(self.state.ev_values[9], {1: 0, 2: None})

    def test_matching_configuration_is_verified_without_writes(self):
        self.service.save_nvs(258, self.nvs)
        self.run_node()
        self.assertFalse(any(b"N96" in f for f in self.connection.sent))
        self.assertIn("Changes saved successfully", self.results[-1][1])
        self.assertEqual(len(self.completions), 1)
        self.assertTrue(self.completions[0][1])
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.service.writes_busy())

    def test_later_write_changing_earlier_nv_fails_without_retry(self):
        self.change_earlier = True
        self.service.save_nvs(258, {1: 1, 2: 20, 3: 31})
        self.run_node()
        self.assertEqual(self.state.nv_values[1], 99)
        self.assertIn("NV verification", self.results[-1][1])
        self.assertNotIn("successfully", self.results[-1][1])
        self.assertEqual(len(self.completions), 1)
        self.assertFalse(self.completions[0][1])
        self.assertEqual(len(self.results), 1)
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f],
            [b":SBFC0N960102031F;"],
        )
        self.assertFalse(self.service.writes_busy())
        self.completions.clear()
        self.results.clear()
        self.service.save_nvs(258, self.nvs)
        self.run_node()
        self.assertEqual(len(self.completions), 1)
        self.assertTrue(self.completions[0][1])
        self.assertEqual(len(self.results), 1)

    def assert_failed_save_requires_reconnect(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            self.service.save_nvs(258, {1: 2, 2: 20, 3: 30})
            with self.assertRaises(ValueError):
                self.service.write_evs(258, {(0, 1000, 1): 9})
            self.run_node()
        self.assertFalse(self.service.writes_busy())
        self.assertNotIn("successfully", self.results[-1][1])
        self.assertEqual(len(self.completions), 1)
        self.assertFalse(self.completions[0][1])
        self.assertEqual(len(self.results), 1)
        with self.assertRaisesRegex(ValueError, "Reconnect"):
            self.service.save_nvs(258, self.nvs)

    def test_rejection_releases_ownership_and_requires_reconnect(self):
        self.reject_nv = 1
        self.assert_failed_save_requires_reconnect()

    def test_ack_timeout_releases_ownership_and_requires_reconnect(self):
        self.drop_ack = True
        self.assert_failed_save_requires_reconnect()

    def test_ownership_spans_higher_nv_rediscovery_and_deferred_comparison(self):
        self.service.save_nvs(258, {1: 2, 2: 20, 3: 30})
        self.app.processEvents()
        self.reply("590102")
        self.reply("9701020102")
        with self.assertRaises(ValueError):
            self.service.write_evs(258, {(0, 1000, 1): 9})
        self.reply("9701020200")
        self.reply("970102031E")
        # The writer has finished its refresh; the coordinator has not yet
        # resumed its next comparison. Neither another Save nor Restore may start.
        with self.assertRaises(ValueError):
            self.service.save_nvs(258, self.nvs)
        self.assertFalse(self.results)
        self.assertFalse(self.completions)
        self.close_service()
        self.assertFalse(self.service.writes_busy())
        self.assertIn("Connection ended", self.results[-1][1])
        self.assertEqual(len(self.completions), 1)
        self.assertFalse(self.completions[0][1])

    def test_incomplete_or_invalid_working_copy_sends_nothing(self):
        for desired in ({1: 2}, {1: 2, 2: 256, 3: 30}):
            with self.subTest(desired=desired), self.assertRaises(ValueError):
                self.service.save_nvs(258, desired)
        self.assertEqual(self.connection.sent, [])
        self.assertFalse(self.service.writes_busy())

    def test_incomplete_final_nv_read_cannot_claim_success(self):
        self.drop_nv_reads = True
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            self.service.save_nvs(258, self.nvs)
            self.run_node()
        self.assertIn("incomplete", self.results[-1][1])
        self.assertNotIn("successfully", self.results[-1][1])
        self.assertEqual(len(self.completions), 1)
        self.assertFalse(self.completions[0][1])
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.service.writes_busy())
        self.assertFalse(any(b"N96" in f for f in self.connection.sent))

    def test_subsequent_save_and_restore_reset_operation_mode(self):
        self.service.save_nvs(258, {1: 1, 2: 20, 3: 31})
        self.run_node()
        self.assertEqual(len(self.completions), 1)
        self.assertTrue(self.completions[0][1])

        # A second Save must still suppress intermediate writer completions.
        self.completions.clear()
        self.results.clear()
        self.service.save_nvs(258, {1: 1, 2: 20, 3: 32})
        self.run_node()
        self.assertEqual(len(self.completions), 1)
        self.assertTrue(self.completions[0][1])
        self.assertEqual(len(self.results), 1)

        backup = node_backup(self.state)
        backup["nvs"][2] = 33
        restored = []
        self.service.restore.finished.connect(lambda *args: restored.append(args))
        self.completions.clear()
        self.results.clear()
        self.service.restore.begin(258, backup)
        self.run_node(completed=lambda: bool(restored))
        self.assertEqual(len(restored), 1)
        self.assertTrue(restored[0][1])
        # Restore retains the writer's public per-transaction signals, followed
        # by its own distinct completion. They must not remain suppressed by Save.
        self.assertEqual(len(self.completions), 1)
        self.assertTrue(self.completions[0][1])
        self.assertTrue(self.results)
        self.assertFalse(self.service.writes_busy())

        self.completions.clear()
        self.results.clear()
        self.service.save_nvs(258, {1: 1, 2: 20, 3: 34})
        self.run_node()
        self.assertEqual(len(self.completions), 1)
        self.assertTrue(self.completions[0][1])
        self.assertEqual(len(self.results), 1)
        self.assertEqual(self.state.nv_values[3], 34)

    def test_disconnect_during_save_releases_ownership_without_success(self):
        self.service.save_nvs(258, {1: 2, 2: 20, 3: 30})
        self.app.processEvents()  # NVSET is waiting for its acknowledgement.
        with self.assertRaises(ValueError):
            self.service.save_nvs(258, self.nvs)
        self.close_service()
        self.app.processEvents()
        self.assertFalse(self.service.writes_busy())
        self.assertEqual(len(self.results), 1)
        self.assertTrue(
            all("successfully" not in message for _, message in self.results)
        )
        self.assertIn("Connection ended", self.results[-1][1])
        self.assertEqual(len(self.completions), 1)
        self.assertFalse(self.completions[0][1])

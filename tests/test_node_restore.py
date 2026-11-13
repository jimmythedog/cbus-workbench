"""Restore contracts through real writers and observable GridConnect exchanges."""

import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox
from test_nv_write import Connection

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.node_backup_diff import compare_live_node
from workbench.node_backup_files import node_backup
from workbench.node_details import NodeDetails
from workbench.pnn import Pnn


class NodeRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        done = DiscoveryProgress.COMPLETE
        self.state = NodeState(
            Pnn(258, 13, 32, 5),
            parameters={5: 3, 6: 3, 8: 5},
            nv_values={1: 7, 2: 8, 3: 9},
            stored_event_count=1,
            event_identities={4: (0, 1000)},
            ev_values={4: {1: 0, 2: 12, 3: None}},
            parameter_progress=done,
            nv_progress=done,
            event_progress=done,
            ev_progress=done,
            can_id=2,
        )
        self.service.nodes[258] = self.state.identity
        self.service.node_states[258] = self.state
        self.backup = node_backup(self.state)
        self.backup["events"][0]["eventVariables"][1] = 13
        self.results = []
        self.service.restore.finished.connect(lambda *args: self.results.append(args))
        self.addCleanup(self.close_service)
        self.nvs = {1: 7, 2: 8, 3: 9}
        self.events = {(0, 1000): {1: 0, 2: 12, 3: None}}
        self.read_position = 0
        self.learn = False
        self.ignore_exit = False
        self.reject_nv = None
        self.reject_ev = False
        self.mismatch_ev = None
        self.change_earlier_nv = False
        self.remove_event = False
        self.withhold_final_read = False
        self.drop_write_reply = False
        self.ev_resets_nv = False
        self.event_capacity = 255
        self.teach_adds_extra = False
        self.full_discovery = False
        self.reject_unlearn = False
        self.ignore_unlearn = False
        self.drop_removal_count = False
        self.pause_removal_count = False

    def close_service(self):
        if self.connection.state == "Connected":
            self.service.close()
            self.connection.state = "Disconnected"

    def reply(self, payload):
        self.connection.frame_received.emit(f":SB040N{payload};".encode())

    def run_node(self, stop_when=None):
        """Answer transmitted requests as a small node with changing table slots."""
        for _ in range(600):
            self.app.processEvents()
            if self.withhold_final_read or self.drop_write_reply:
                QTest.qWait(1)
            if self.results or (stop_when is not None and stop_when()):
                return
            if self.read_position == len(self.connection.sent):
                continue
            frame = self.connection.sent[self.read_position]
            self.read_position += 1
            data = bytes.fromhex(frame.decode().split("N")[1][:-1])
            op = data[0]
            if op == 0x96:
                index, value = data[3:]
                if index == self.reject_nv:
                    self.reply("6F010201")
                    continue
                self.nvs[index] = value
                # A configuration NV may reset a later value even if that value
                # matched before restore. Higher NVs must therefore be reread.
                if index == 1:
                    self.nvs[2] = 128
                if index == 3 and self.change_earlier_nv:
                    self.nvs[1] = 99
                if self.remove_event:
                    self.events.clear()
                if not self.drop_write_reply:
                    self.reply("590102")
            elif op == 0x71:
                if self.withhold_final_read and self.full_discovery:
                    continue
                self.reply(f"970102{data[3]:02X}{self.nvs[data[3]]:02X}")
            elif op == 0x73:
                index = data[3]
                if index == 0:
                    self.full_discovery = True
                parameters = {
                    0: 8,
                    1: 1,
                    2: 97,
                    3: 2,
                    4: self.event_capacity,
                    5: 3,
                    6: len(self.nvs),
                    7: 1,
                    8: 37 if self.learn else 5,
                }
                self.reply(f"9B0102{index:02X}{parameters[index]:02X}")
            elif op == 0x58:
                if any(b"N95" in f for f in self.connection.sent):
                    if self.pause_removal_count:
                        self.pause_removal_count = False
                        return
                    if self.drop_removal_count:
                        self.drop_removal_count = False
                        QTest.qWait(20)
                        continue
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
            elif op == 0x53:
                self.learn = True
            elif op == 0x54:
                if not self.ignore_exit:
                    self.learn = False
            elif op == 0xD2:
                identity = (int.from_bytes(data[1:3]), int.from_bytes(data[3:5]))
                key = (*identity, data[5])
                if self.reject_ev is True or self.reject_ev == key:
                    self.reply("6F010201")
                elif self.mismatch_ev == key:
                    self.reply("590102")
                elif identity not in self.events and data[6] == 0:
                    # Acknowledgement alone does not prove event creation.
                    self.reply("590102")
                elif (
                    identity not in self.events
                    and len(self.events) >= self.event_capacity
                ):
                    self.reply("6F010204")
                else:
                    if self.teach_adds_extra and identity not in self.events:
                        self.events[(258, 2000)] = {1: 7, 2: None, 3: None}
                    self.events.setdefault(identity, {1: None, 2: None, 3: None})[
                        data[5]
                    ] = data[6]
                    if self.ev_resets_nv:
                        self.nvs[1] = 99
                    self.reply("590102")
            elif op == 0x95:
                identity = (int.from_bytes(data[1:3]), int.from_bytes(data[3:5]))
                if self.reject_unlearn:
                    self.reply("6F010201")
                else:
                    if not self.ignore_unlearn:
                        self.events.pop(identity)
                    # EVULN has no acknowledgement, even on successful removal.
            elif op == 0xB2:
                identity = (int.from_bytes(data[1:3]), int.from_bytes(data[3:5]))
                if identity not in self.events:
                    self.reply("6F010207")
                else:
                    self.reply(
                        f"D3{identity[0]:04X}{identity[1]:04X}{data[5]:02X}{self.events[identity][data[5]]:02X}"
                    )
            else:
                self.fail(f"Unexpected frame {frame}")
        self.fail("Restore did not produce a result")

    def live_view(self):
        from workbench.node_view import NodeView

        view = NodeView({})
        self.addCleanup(view.close)
        view.state_lookup = self.service.node_states.get
        view.details.connected = True
        view.details.cbus_service = self.service
        view.show_identity(self.state.identity)
        self.service.discovery_status_changed.connect(view.discovery_status_changed)
        self.service.node_state_updated.connect(view.refresh_state)
        self.service.restore.changed.connect(view.details.show_restore_progress)
        self.service.restore.finished.connect(view.details.finish_restore)
        return view

    def test_restore_suspends_selected_details_until_final_discovery(self):
        view = self.live_view()
        tree = view.details.node_events.consumed_table
        self.service.restore.begin(258, self.backup)
        self.run_node(stop_when=lambda: view.node_list.currentItem() is None)
        self.assertFalse(view.node_list.isEnabled())
        self.assertIs(view.details.live_state, self.state)
        self.assertIn("Restoring", view.details.restore_result.text())
        self.assertEqual(tree.topLevelItem(0).text(0), "0:1000")
        self.run_node()
        self.app.processEvents()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertTrue(view.node_list.isEnabled())
        self.assertIsNotNone(view.node_list.currentItem())
        self.assertEqual(tree.topLevelItem(0).child(1).text(1), "13")
        self.assertIn("fully verified", view.details.restore_result.text())

    def test_disconnect_during_restore_releases_suspension_and_clears_live_details(
        self,
    ):
        view = self.live_view()
        self.service.restore.begin(258, self.backup)
        self.run_node(stop_when=lambda: view.node_list.currentItem() is None)
        self.service.close()
        self.connection.state = "Disconnected"
        self.assertTrue(view.node_list.isEnabled())
        self.assertIsNone(view.node_list.currentItem())
        self.assertIsNone(view.details.node)
        self.assertIsNone(view.details.live_state)
        self.assertFalse(self.results[-1][1])

    def test_events_save_keeps_working_copy_and_progress_during_discovery(self):
        view = self.live_view()
        details = view.details
        details.start_editing()
        details.raw_values.item(0, 1).setText("10")
        details.node_events.consumed_table.topLevelItem(0).child(1).setText(1, "13")
        desired = deepcopy(details.desired_configuration)
        details.save_events_editing()
        self.run_node(stop_when=lambda: view.node_list.currentItem() is None)
        self.assertEqual(details.desired_configuration, desired)
        self.assertTrue(details.saving_configuration)
        self.assertFalse(details.cancel_button.isEnabled())
        self.assertIn("Saving", details.nv_result.text())
        self.run_node()
        self.app.processEvents()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertIsNone(details.desired_configuration)
        self.assertTrue(view.node_list.isEnabled())
        self.assertIn("saved and fully verified", details.nv_result.text())
        self.assertEqual(details.raw_values.item(0, 1).text(), "10")

    def test_complete_restore_skips_matching_nvs_then_matches_events_after_slot_change(
        self,
    ):
        desired = deepcopy(self.backup)
        self.service.restore.begin(258, self.backup)
        self.backup["nvs"][0] = 99  # An accepted target is independent of the caller.
        self.run_node()
        writes = [f for f in self.connection.sent if b"N96" in f]
        self.assertEqual(
            writes,
            [],
        )
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(compare_live_node(self.state, desired), ([], False))
        self.assertEqual(self.state.event_identities, {9: (0, 1000)})
        self.assertEqual(
            [f for f in self.connection.sent if b"ND2" in f],
            [b":SBFC0ND2000003E8020D;"],
        )
        self.assertFalse(self.learn)

    def test_node_without_nvs_still_restores_and_verifies_events(self):
        self.backup["nvs"] = []
        self.state.parameters[6] = 0
        self.state.nv_values = {}
        self.nvs = {}
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertFalse(any(b"N96" in f or b"N71" in f for f in self.connection.sent))
        self.assertEqual(self.events[(0, 1000)][2], 13)

    def test_changed_nv_refreshes_higher_values_before_comparing_them(self):
        self.nvs[1] = 6
        self.state.nv_values = dict(self.nvs)
        self.service.restore.begin(258, self.backup)
        self.run_node()
        # NV1 resets previously matching NV2. NV3 still matches and is untouched.
        nv_frames = [f for f in self.connection.sent if b"N96" in f or b"N71" in f]
        self.assertEqual(
            nv_frames[:7],
            [
                b":SBFC0N9601020107;",
                b":SBFC0N71010201;",
                b":SBFC0N71010202;",
                b":SBFC0N71010203;",
                b":SBFC0N9601020208;",
                b":SBFC0N71010202;",
                b":SBFC0N71010203;",
            ],
        )
        self.assertEqual(len([f for f in nv_frames if b"N96" in f]), 2)
        self.assertTrue(self.results[-1][1], self.results)

    def test_incomplete_higher_nv_refresh_stops_before_more_writes_or_events(self):
        self.check_incomplete_nv_refresh(tail=True)

    def begin_type_and_position_change(self, next_value=10):
        """Reach NV25 verification after a TYPE write resets its position."""
        self.nvs = dict.fromkeys(range(1, 27), 0)
        self.nvs.update({23: 1, 25: 0, 26: 9})
        self.state.parameters[6] = len(self.nvs)
        self.state.nv_values = dict(self.nvs)
        self.backup = node_backup(self.state)
        self.backup["nvs"][22] = 2
        self.backup["nvs"][24] = 129
        self.backup["nvs"][25] = next_value  # Wait for NV25 verification.
        self.service.restore.begin(258, self.backup)
        self.app.processEvents()
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9601021702;")
        self.nvs.update({23: 2, 25: 128})
        self.reply("590102")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010217;")
        self.reply("9701021702")
        for index in range(24, 27):
            self.assertEqual(
                self.connection.sent[-1], f":SBFC0N710102{index:02X};".encode()
            )
            self.reply(f"970102{index:02X}{self.nvs[index]:02X}")
        self.app.processEvents()
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9601021981;")
        self.nvs[25] = 129
        self.reply("590102")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010219;")
        before_events = list(self.connection.sent)
        self.reply("91010200CA")
        self.reply("9001020066")
        self.app.processEvents()
        self.assertEqual(self.connection.sent, before_events)
        self.assertEqual(self.results, [])
        self.assertEqual(self.state.nv_values[25], 128)
        # The existing node helper takes over only requests not answered above.
        self.read_position = len(self.connection.sent)

    def test_nv25_timeout_after_events_preserves_failure_and_rediscovered_value(self):
        self.begin_type_and_position_change()
        # Deliver timer expiry explicitly: exercise the real timeout handler
        # without changing the response timeout or waiting on wall-clock timing.
        self.service.nv_write.timer.timeout.emit()
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010219;")
        self.service.nv_write.timer.timeout.emit()
        self.run_node()
        self.app.processEvents()
        self.assertEqual(len(self.results), 1)
        number, success, message = self.results[0]
        self.assertEqual(number, 258)
        self.assertFalse(success)
        self.assertIn(
            "Partial restoration: 1 NV writes and 0 EV writes verified", message
        )
        self.assertIn(
            "NV 25 could not be saved. timed out waiting for recovery NVANS", message
        )
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f],
            [b":SBFC0N9601021702;", b":SBFC0N9601021981;"],
        )
        self.assertFalse(any(b"ND2" in f or b"N95" in f for f in self.connection.sent))
        self.assertEqual(self.state.nv_values[25], 129)
        self.assertEqual(self.state.nv_values[26], 9)
        self.assertEqual(self.state.nv_progress, DiscoveryProgress.COMPLETE)

    def test_recovery_read_continues_with_higher_nv_refresh_and_final_verification(
        self,
    ):
        self.begin_type_and_position_change(next_value=9)
        self.service.nv_write.timer.timeout.emit()
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010219;")
        self.assertEqual(self.results, [])
        # Firmware changed the next NV: recovery must still refresh it before
        # deciding whether its desired value needs writing.
        self.nvs[26] = 128
        self.reply("9701021981")
        self.assertEqual(self.service.nv_write.unverified, set())
        self.assertEqual(self.connection.sent[-1], b":SBFC0N7101021A;")
        self.run_node()
        self.app.processEvents()
        self.assertEqual(len(self.results), 1)
        self.assertTrue(self.results[0][1], self.results)
        self.assertIn(
            "Verification required recovery for 1 NV write(s)", self.results[0][2]
        )
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))
        self.assertTrue(self.full_discovery)
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f],
            [b":SBFC0N9601021702;", b":SBFC0N9601021981;", b":SBFC0N9601021A09;"],
        )

    def test_recovery_followed_by_later_nv_failure_reports_recovery_once(self):
        self.begin_type_and_position_change()
        self.service.nv_write.timer.timeout.emit()
        self.reply("9701021981")
        self.reject_nv = 26
        self.run_node()
        self.app.processEvents()
        self.assertEqual(len(self.results), 1)
        _, success, message = self.results[0]
        self.assertFalse(success)
        self.assertIn("Partial restoration:", message)
        self.assertIn("NV 26 could not be saved", message)
        self.assertIn("CMDERR", message)
        self.assertEqual(message.count("Verification required recovery for"), 1)
        self.assertIn("Verification required recovery for 1 NV write(s).", message)

    def test_higher_nv_discovery_recovery_continues_reconciliation(self):
        self.begin_type_and_position_change()
        self.reply("9701021981")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N7101021A;")
        self.service._request_timer.timeout.emit()
        self.assertEqual(self.connection.sent[-2:], [b":SBFC0N7101021A;"] * 2)
        self.assertEqual(self.results, [])
        self.run_node()
        self.app.processEvents()
        self.assertEqual(len(self.results), 1)
        self.assertTrue(self.results[0][1], self.results)
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))
        self.assertTrue(self.full_discovery)
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f],
            [b":SBFC0N9601021702;", b":SBFC0N9601021981;", b":SBFC0N9601021A0A;"],
        )

    def test_recovery_read_mismatch_blocks_writes_even_after_delayed_response(self):
        self.begin_type_and_position_change()
        self.service.nv_write.timer.timeout.emit()
        self.nvs[25] = 128
        self.reply("9701021980")
        # A late matching reply to the other NVRD cannot resolve the failure.
        self.reply("9701021981")
        self.run_node()
        self.app.processEvents()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[0][1])
        self.assertIn("readback was 128, expected 129", self.results[0][2])
        self.assertEqual(self.state.nv_values[25], 128)
        self.assertEqual(self.state.nv_values[26], 9)
        before = list(self.connection.sent)
        for delayed in ("9701021981", "590102", "6F010201"):
            self.reply(delayed)
            with self.assertRaisesRegex(ValueError, "Protocol safety unresolved"):
                self.service.restore.begin(258, self.backup)
        self.assertEqual(self.connection.sent, before)
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f or b"ND2" in f],
            [b":SBFC0N9601021702;", b":SBFC0N9601021981;"],
        )

    def test_nv25_readback_after_events_continues_configuration_to_success(self):
        self.begin_type_and_position_change()
        self.reply("9701021981")
        self.assertEqual(self.state.nv_values[25], 129)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N7101021A;")
        self.run_node()
        self.app.processEvents()
        self.assertEqual(len(self.results), 1)
        self.assertTrue(self.results[0][1], self.results)
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f],
            [
                b":SBFC0N9601021702;",
                b":SBFC0N9601021981;",
                b":SBFC0N9601021A0A;",
            ],
        )
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))

    def test_incomplete_final_nv_verification_stops_before_events(self):
        self.check_incomplete_nv_refresh(tail=False)

    def check_incomplete_nv_refresh(self, *, tail):
        self.nvs[1] = 6
        self.state.nv_values = dict(self.nvs)
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 20):
            self.service.restore.begin(258, self.backup)
            self.app.processEvents()
            self.nvs[1] = 7
            self.reply("590102")
            self.reply("9701020107")
            if not tail:
                self.reply("9701020208")
                self.reply("9701020309")
                self.app.processEvents()
                self.app.processEvents()
            with self.assertRaisesRegex(ValueError, "ownership"):
                self.service.write_nvs(258, {2: 10})
        # Only the unanswered request needs the short timeout. Restore the
        # normal setting before its failure starts full-node rediscovery.
        # Retained matching values cannot substitute for fresh replies.
        self.service._request_timer.timeout.emit()
        self.service._request_timer.timeout.emit()
        self.run_node()  # Answer failure rediscovery, never retry writes.
        self.assertFalse(self.results[-1][1])
        self.assertEqual(len([f for f in self.connection.sent if b"N96" in f]), 1)
        self.assertFalse(any(b"ND2" in f or b"N95" in f for f in self.connection.sent))
        self.assertEqual(self.state.nv_values, self.nvs)

    def test_incomplete_unknown_or_invalid_backup_rejected_without_writes(self):
        for change in (
            {"complete": False},
            {"nvs": [7, None, 9]},
            {"node": 259},
            {"nvs": [7, 8, 256]},
        ):
            with self.subTest(change=change):
                backup = deepcopy(self.backup)
                backup.update(change)
                with self.assertRaises(ValueError):
                    self.service.restore.begin(258, backup)
        self.state.nv_values.pop(2)
        with self.assertRaisesRegex(ValueError, "Complete target discovery"):
            self.service.restore.begin(258, self.backup)
        self.assertEqual(self.connection.sent, [])

    def test_nv_side_effect_is_reported_and_independent_events_continue(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.change_earlier_nv = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("NV verification", self.results[-1][2])
        self.assertEqual(self.events[(0, 1000)][2], 13)
        self.assertEqual(self.state.nv_values[1], 99)
        self.assertEqual(len([f for f in self.connection.sent if b"N96" in f]), 3)

    def test_missing_event_after_nv_reset_is_taught_by_identity(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.remove_event = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(self.events, {(0, 1000): {1: 0, 2: 13, 3: None}})
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))

    def test_missing_event_verifies_nonzero_ev_before_teaching_zero_ev1(self):
        event = self.backup["events"][0]
        event["nodeNumber"], event["eventNumber"] = 258, 5
        self.events.clear()
        self.state.event_identities.clear()
        self.state.ev_values.clear()
        self.state.stored_event_count = 0
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(self.events, {(258, 5): {1: 0, 2: 13, 3: None}})
        exchanges = [f for f in self.connection.sent if b"ND2" in f or b"NB2" in f]
        self.assertEqual(
            exchanges,
            [
                b":SBFC0ND201020005020D;",
                b":SBFC0NB20102000502;",
                b":SBFC0ND2010200050100;",
                b":SBFC0NB20102000501;",
            ],
        )

    def test_existing_event_can_restore_all_zero_values(self):
        self.backup["events"][0]["eventVariables"] = [0, 0]
        self.events[(0, 1000)][1] = 9
        self.state.ev_values[4][1] = 9
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(self.events[(0, 1000)], {1: 0, 2: 0, 3: None})
        self.assertEqual(
            [f for f in self.connection.sent if b"ND2" in f or b"N95" in f],
            [b":SBFC0ND2000003E80100;", b":SBFC0ND2000003E80200;"],
        )

    def test_all_zero_event_cannot_be_created_or_reconstructed(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.results.clear()
                self.connection.sent.clear()
                self.read_position = 0
                self.events = {(0, 1000): {1: 0, 2: 0, 3: 42}} if existing else {}
                self.state.event_identities = {4: (0, 1000)} if existing else {}
                self.state.ev_values = {4: {1: 0, 2: 0, 3: 42}} if existing else {}
                self.state.stored_event_count = len(self.events)
                self.backup["events"][0]["eventVariables"] = [0, 0]
                before = deepcopy(self.events)
                self.service.restore.begin(258, self.backup)
                self.run_node()
                self.assertFalse(self.results[-1][1])
                self.assertIn("cannot be reconstructed", self.results[-1][2])
                self.assertIn("no nonzero saved EV", self.results[-1][2])
                self.assertEqual(self.events, before)
                self.assertFalse(
                    any(b"ND2" in f or b"N95" in f for f in self.connection.sent)
                )

    def test_nv_rejection_continues_independent_nvs_and_events(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.reject_nv = 2
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Partial restoration: 2 NV writes", self.results[-1][2])
        self.assertEqual(self.state.nv_values, self.nvs)
        self.assertEqual(self.nvs, {1: 7, 2: 128, 3: 9})
        self.assertEqual(self.events[(0, 1000)][2], 13)
        differences, inconclusive = compare_live_node(self.state, self.backup)
        self.assertEqual([row[1] for row in differences], ["NV 2"])
        self.assertFalse(inconclusive)

    def test_ev_failure_stops_exits_learn_mode_and_rediscover_partial_result(self):
        self.reject_ev = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Partial restoration: 0 NV writes", self.results[-1][2])
        self.assertFalse(self.learn)
        self.assertEqual(self.state.nv_values, self.nvs)
        self.assertEqual(compare_live_node(self.state, self.backup)[0][0][1], "EV 2")

    def test_ev_failure_continues_remaining_values_and_retry_only_writes_difference(
        self,
    ):
        for failure in ("rejection", "mismatch"):
            with self.subTest(failure=failure):
                self.backup["events"][0]["eventVariables"] = [4, 13, 9]
                if failure == "rejection":
                    self.reject_ev = (0, 1000, 1)
                else:
                    self.mismatch_ev = (0, 1000, 1)
                details = self.backup_details()
                self.service.restore.finished.connect(details.finish_restore)
                self.service.restore.begin(258, self.backup)
                self.run_node()
                self.assertFalse(self.results[-1][1])
                self.assertEqual(self.events[(0, 1000)], {1: 0, 2: 13, 3: 9})
                self.assertFalse(self.learn)
                report = details.failure_report
                self.assertTrue(report.dialog.retry_button.isEnabled())
                self.assertIn(("EV 1", "4", "0"), self.report_rows(details))
                self.reject_ev = False
                self.mismatch_ev = None
                self.results.clear()
                before = len(self.connection.sent)
                report.dialog.retry_button.click()
                self.run_node()
                self.assertTrue(self.results[-1][1], self.results)
                writes = [f for f in self.connection.sent[before:] if b"ND2" in f]
                self.assertEqual(writes, [b":SBFC0ND2000003E80104;"])
                report.dialog.close()
                self.service.restore.finished.disconnect(details.finish_restore)
                self.events[(0, 1000)] = {1: 0, 2: 12, 3: None}
                self.state.ev_values = {9: dict(self.events[(0, 1000)])}
                self.results.clear()

    def test_resolved_ev_rejection_with_unconfirmed_exit_stops_further_changes(self):
        self.backup["events"][0]["eventVariables"] = [4, 13, 9]
        self.reject_ev = (0, 1000, 1)
        self.ignore_exit = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("still reports learn mode", self.results[-1][2])
        self.assertEqual(self.events[(0, 1000)], {1: 0, 2: 12, 3: None})
        with self.assertRaisesRegex(ValueError, "Protocol safety unresolved"):
            self.service.restore.check(258, self.backup)

    def test_failed_creation_skips_dependent_evs_but_restores_other_event(self):
        self.backup["events"].insert(
            0,
            {
                "nodeNumber": 258,
                "eventNumber": 2000,
                "eventVariables": [7, 0, None],
            },
        )
        self.reject_ev = (258, 2000, 1)
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertNotIn((258, 2000), self.events)
        self.assertEqual(self.events[(0, 1000)][2], 13)
        self.assertFalse(any(b"ND2010207D00200" in f for f in self.connection.sent))

    def test_final_discovery_timeout_never_reports_success(self):
        self.withhold_final_read = True
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            self.service.restore.begin(258, self.backup)
            self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertTrue(compare_live_node(self.state, self.backup)[1])

    def test_nv_ack_timeout_reads_physical_result_but_never_continues_writes(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.drop_write_reply = True
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            self.service.restore.begin(258, self.backup)
            self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("timed out", self.results[-1][2])
        self.assertEqual(self.state.nv_values, self.nvs)
        self.assertEqual(len([f for f in self.connection.sent if b"N96" in f]), 1)
        with self.assertRaisesRegex(ValueError, "Protocol safety unresolved"):
            self.service.restore.begin(258, node_backup(self.state))

    def test_application_ownership_survives_deferred_nv_comparison(self):
        self.backup["nvs"][0] = 10
        self.service.restore.begin(258, self.backup)
        self.app.processEvents()
        self.reply("590102")
        self.reply("970102010A")
        self.reply("9701020280")
        self.reply("9701020309")
        # Readback and higher-NV discovery have finished, but Qt has not yet
        # resumed the coordinator. A second application still cannot start.
        sent = list(self.connection.sent)
        with self.assertRaisesRegex(ValueError, "Wait"):
            self.service.restore.begin(258, node_backup(self.state))
        self.assertEqual(self.connection.sent, sent)
        self.assertFalse(self.results)
        self.close_service()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[0][1])

    def test_absent_ev_reconstructs_event_and_restores_all_numeric_values(self):
        self.events[(0, 1000)][3] = 42
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(self.events, {(0, 1000): {1: 0, 2: 13, 3: None}})
        event_frames = [f for f in self.connection.sent if b"N95" in f or b"ND2" in f]
        self.assertEqual(
            event_frames,
            [
                b":SBFC0N95000003E8;",
                b":SBFC0ND2000003E8020D;",
                b":SBFC0ND2000003E80100;",
            ],
        )

    def test_internal_absent_ev_reconstructs_before_restoring_later_numeric_evs(self):
        self.backup["events"][0]["eventVariables"] = [0, None, 13]
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(self.events[(0, 1000)], {1: 0, 2: None, 3: 13})
        event_frames = [f for f in self.connection.sent if b"N95" in f or b"ND2" in f]
        self.assertEqual(
            event_frames,
            [
                b":SBFC0N95000003E8;",
                b":SBFC0ND2000003E8030D;",
                b":SBFC0ND2000003E80100;",
            ],
        )

    def test_reteach_failure_reports_earlier_extra_and_rebuilt_event_removals(self):
        self.reject_ev = True
        self.events[(0, 1000)][3] = 42
        self.events[(258, 2000)] = {1: 7, 2: None, 3: None}
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn(
            "2 event removals transmitted, 2 event removals verified",
            self.results[-1][2],
        )
        self.assertFalse(self.learn)
        self.assertEqual(self.events, {})
        self.assertEqual(self.state.event_identities, {})

    def test_matching_event_is_untouched(
        self,
    ):
        self.backup["events"][0]["eventVariables"][1] = 12
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertFalse(any(b"N95" in f or b"ND2" in f for f in self.connection.sent))

    def test_full_event_table_removes_extra_before_teaching_missing_event(self):
        self.event_capacity = 1
        self.events = {(258, 2000): {1: 7, 2: None, 3: None}}
        self.state.parameters[4] = 1
        self.state.event_identities = {4: (258, 2000)}
        self.state.ev_values = {4: {1: 7, 2: None, 3: None}}
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))
        event_frames = [f for f in self.connection.sent if b"N95" in f or b"ND2" in f]
        self.assertEqual(
            event_frames,
            [
                b":SBFC0N95010207D0;",
                b":SBFC0ND2000003E8020D;",
                b":SBFC0ND2000003E80100;",
            ],
        )

    def test_extra_events_are_removed_before_backed_up_events(self):
        self.events[(258, 2000)] = {1: 7, 2: None, 3: None}
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(set(self.events), {(0, 1000)})
        event_frames = [f for f in self.connection.sent if b"N95" in f or b"ND2" in f]
        self.assertEqual(
            event_frames, [b":SBFC0N95010207D0;", b":SBFC0ND2000003E8020D;"]
        )

    def test_events_created_during_teaching_fail_final_verification_without_retry(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.remove_event = True
        self.teach_adds_extra = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("differs from the known backup data", self.results[-1][2])
        self.assertEqual(set(self.events), {(0, 1000), (258, 2000)})
        self.assertNotIn(b":SBFC0N95010207D0;", self.connection.sent)
        # Rich inspection rows must not change Restore's legacy difference contract.
        self.assertEqual(
            compare_live_node(self.state, self.backup),
            (
                [("Consumed events/258:2000", "Event", None, "Present")],
                False,
            ),
        )

    def test_unlearn_rejection_stops_teaching_and_preserves_later_events(self):
        self.reject_unlearn = True
        self.events[(0, 1000)][3] = 42
        self.events[(258, 2000)] = {1: 7, 2: None, 3: None}
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("exit", self.results[-1][2])
        self.assertFalse(self.learn)
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))
        self.assertIn((258, 2000), self.events)

    def test_removal_discovery_timeout_stops_and_reads_the_physical_result(self):
        self.drop_removal_count = True
        self.events[(0, 1000)][3] = 42
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            self.service.restore.begin(258, self.backup)
            self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("removal could not be confirmed", self.results[-1][2])
        self.assertIn(
            "1 event removals transmitted, 0 event removals verified",
            self.results[-1][2],
        )
        self.assertFalse(self.learn)
        self.assertEqual(self.state.event_identities, {})
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))

    def test_ineffective_removal_cannot_report_success(self):
        self.ignore_unlearn = True
        self.events[(258, 2000)] = {1: 7, 2: None, 3: None}
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("removal could not be confirmed", self.results[-1][2])
        self.assertIn(
            "1 event removals transmitted, 0 event removals verified",
            self.results[-1][2],
        )
        self.assertEqual(self.events[(0, 1000)][2], 13)
        self.assertIn((258, 2000), self.events)

    def test_reconstruction_verifies_absence_before_teaching_without_nv_reread(self):
        self.events[(0, 1000)][3] = 42
        self.pause_removal_count = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results)
        self.assertEqual(self.events, {})
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))
        with self.assertRaises(ValueError):
            self.service.write_evs(258, {(0, 1000, 1): 9})
        removal = next(i for i, f in enumerate(self.connection.sent) if b"N95" in f)
        self.assertIn(b":SBFC0N580102;", self.connection.sent[removal + 1 :])
        self.reply("74010200")
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        teaching = next(i for i, f in enumerate(self.connection.sent) if b"ND2" in f)
        self.assertFalse(
            any(b"N71" in f for f in self.connection.sent[removal:teaching])
        )
        self.assertEqual(self.connection.sent[teaching], b":SBFC0ND2000003E8020D;")
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))

    def test_ineffective_reconstruction_stops_before_teaching(self):
        self.events[(0, 1000)][3] = 42
        self.ignore_unlearn = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("removal could not be confirmed", self.results[-1][2])
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))
        self.assertEqual(self.events[(0, 1000)][3], 42)

    def test_interrupt_during_removal_verification_never_recreates_event(self):
        self.events[(0, 1000)][3] = 42
        self.pause_removal_count = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.service.ev_write.interrupt()
        self.reply("74010200")
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("interrupted", self.results[-1][2])
        self.assertIn(
            "1 event removals transmitted, 1 event removals verified",
            self.results[-1][2],
        )
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))
        self.assertFalse(self.learn)

    def test_disconnect_during_removal_verification_does_not_count_transmission_as_removal(
        self,
    ):
        self.events[(0, 1000)][3] = 42
        self.pause_removal_count = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.close_service()
        self.reply("74010200")
        self.app.processEvents()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[-1][1])
        self.assertIn(
            "1 event removals transmitted, 0 event removals verified",
            self.results[-1][2],
        )
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))
        self.assertFalse(self.learn)

    def test_empty_event_creation_is_reported_without_inventing_an_ev(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.backup["events"][0]["eventVariables"] = []
        self.remove_event = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("no standalone empty-event teach", self.results[-1][2])
        self.assertFalse(any(b"ND2" in f or b"N95" in f for f in self.connection.sent))

    def test_incomplete_backup_restores_known_values_without_reconstructing_unknown_evs(
        self,
    ):
        self.backup["complete"] = False
        self.backup["nvs"] = [None, None, 9]
        self.nvs[3] = self.state.nv_values[3] = 10
        self.backup["events"][0]["eventVariables"] = [None, 13]
        self.events[(0, 1000)][3] = 42
        self.events[(258, 2000)] = {1: 7, 2: None, 3: None}
        self.service.restore.begin(258, self.backup, allow_incomplete=True)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertIn("Known backup values", self.results[-1][2])
        self.assertIn("full equivalence is not established", self.results[-1][2])
        self.assertEqual(self.events[(0, 1000)], {1: 0, 2: 13, 3: 42})
        self.assertEqual(set(self.events), {(0, 1000)})
        self.assertEqual(
            [f for f in self.connection.sent if b"N96" in f], [b":SBFC0N9601020309;"]
        )
        self.assertNotIn(b":SBFC0N95000003E8;", self.connection.sent)

    def test_final_comparison_detects_nv_changes_caused_by_ev_teaching(self):
        self.ev_resets_nv = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertEqual(self.state.nv_values[1], 99)
        self.assertEqual(len([f for f in self.connection.sent if b"N96" in f]), 0)

    def test_restore_excludes_other_writes_and_reports_disconnect(self):
        self.service.restore.begin(258, self.backup)
        with self.assertRaises(ValueError):
            self.service.write_nvs(258, {1: 10})
        with self.assertRaises(ValueError):
            self.service.write_evs(258, {(0, 1000, 1): 10})
        self.close_service()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Connection ended", self.results[-1][2])
        self.assertIn(
            "Reconnect after resolving the connection failure", self.results[-1][2]
        )

    def backup_details(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem, QTreeWidgetItem

        details = NodeDetails({})
        self.addCleanup(details.close)
        details.connected = True
        details.cbus_service = self.service
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.state.identity)
        details.show_node(item)
        details.show_live_state(self.state)
        selected = QTreeWidgetItem(details.node_backups, ["saved.yaml"])
        selected.setData(0, Qt.ItemDataRole.UserRole, self.backup)
        details.node_backups.setCurrentItem(selected)
        return details

    def editing_details(self):
        details = self.backup_details()
        # Only the coordinator reports application progress and completion to
        # the editor, as in the real window.
        self.service.restore.changed.connect(details.show_restore_progress)
        self.service.restore.finished.connect(details.finish_restore)
        self.service.node_state_updated.connect(
            lambda _n: details.show_live_state(self.state)
        )
        details.edit_button.click()
        details.raw_values.item(0, 1).setText("10")
        event = details.node_events.consumed_table.topLevelItem(0)
        event.child(0).setText(1, "4")
        event.child(1).setText(1, "")
        event.child(2).setText(1, "0")
        return details

    def check_editor_save(self, events_tab):
        details = self.editing_details()
        desired = deepcopy(details.desired_configuration)
        editing = []
        details.editing_changed.connect(editing.append)
        progress = []
        self.service.restore.changed.connect(
            lambda _n, message: progress.append(
                (
                    message,
                    details.variables.isEnabled(),
                    details.node_events.isEnabled(),
                )
            )
        )
        button = details.events_save_button if events_tab else details.save_button
        self.assertTrue(button.isEnabled())
        button.click()
        self.assertTrue(self.service.restore.active)
        self.assertEqual(self.service.restore.backup, desired)
        self.assertFalse(details.variables.isEnabled())
        self.assertFalse(details.node_events.isEnabled())
        self.assertFalse(details.save_button.isEnabled())
        self.assertFalse(details.events_save_button.isEnabled())
        self.assertFalse(details.cancel_button.isEnabled())
        self.assertFalse(details.events_cancel_button.isEnabled())
        # Repeated entry through either handler cannot start another application
        # or discard the desired configuration while writes are pending.
        details.save_editing()
        details.save_events_editing()
        details.cancel_editing()
        details.cancel_events_editing()
        self.assertEqual(details.desired_configuration, desired)
        self.run_node()
        self.assertEqual(len(self.results), 1)
        self.assertTrue(self.results[0][1], self.results)
        self.assertEqual(compare_live_node(self.state, desired), ([], False))
        self.assertEqual(self.nvs, {1: 10, 2: 8, 3: 9})
        self.assertEqual(self.events, {(0, 1000): {1: 4, 2: None, 3: 0}})
        self.assertEqual(editing, [False])
        self.assertTrue(progress)
        self.assertTrue(all(not nv and not ev for _message, nv, ev in progress))
        self.assertTrue(any("final configuration" in m for m, _nv, _ev in progress))
        self.assertEqual(details.nv_result.text(), details.events_result.text())
        self.assertEqual(
            details.nv_result.text(),
            "Node 258: Configuration saved and fully verified.",
        )
        self.assertTrue(details.variables.isEnabled())
        self.assertTrue(details.node_events.isEnabled())
        self.assertIsNone(details.desired_configuration)
        self.assertEqual(details.buttons.currentIndex(), 0)
        self.assertEqual(details.events_buttons.currentIndex(), 0)
        self.assertFalse(self.learn)

    def test_mdf_edits_share_raw_values_cancel_and_restore_save(self):
        from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox

        from workbench.mdfs import Mdf

        select = {
            "type": "NodeVariableSelect",
            "nodeVariableIndex": 1,
            "displayTitle": "Mode",
            "bitMask": 3,
            "options": [{"value": 0, "label": "Off"}, {"value": 3, "label": "On"}],
        }
        number = {
            "type": "NodeVariableNumber",
            "nodeVariableIndex": 2,
            "displayTitle": "Number",
            "startBit": 1,
            "endBit": 3,
            "displayScale": 0.5,
            "displayOffset": 1,
        }
        slider = {**number, "type": "NodeVariableSlider", "displayTitle": "Slider"}
        bit = {
            "type": "NodeVariableBitArray",
            "nodeVariableIndex": 3,
            "displayTitle": "Flags",
            "bitCollection": [{"bitPosition": 0, "label": "Flag"}],
            "visibilityLogic": {"nv": 1, "equals": 4},
        }
        ev = {
            "type": "EventVariableBitSingle",
            "eventVariableIndex": 1,
            "displayTitle": "EV flag",
            "bit": 0,
            "visibilityLogic": {"nv": 1, "equals": 4},
        }
        details = self.backup_details()
        mdf = Mdf(
            Path("editing.json"),
            {
                "nodeVariables": [select, dict(select), number, slider, bit],
                "eventVariables": [ev],
            },
        )
        details.show_live_state(self.state, mdf)
        form = details.mdf_values.pages.widget(1)
        combos = form.findChildren(QComboBox)
        numbers = form.findChildren(QDoubleSpinBox)
        flag = form.findChild(QCheckBox)
        self.assertFalse(combos[0].isEnabled())
        for save in (False, True):
            details.start_editing()
            combos[0].setCurrentIndex(0)
            self.assertEqual(details.desired_configuration["nvs"][0], 4)
            self.assertEqual(combos[1].currentData(), 0)
            self.assertEqual(details.raw_values.item(0, 1).text(), "4")
            self.assertFalse(flag.isHidden())
            flag.click()
            self.assertEqual(details.desired_configuration["nvs"][2], 8)
            numbers[1].setValue(3)
            self.assertEqual(details.desired_configuration["nvs"][1], 8)
            self.assertEqual(numbers[0].value(), 3)
            numbers[0].setValue(2)
            self.assertEqual(details.desired_configuration["nvs"][1], 4)
            self.assertEqual(numbers[1].value(), 2)
            details.mdf_values.raw_values.item(1, 1).setText("14")
            self.assertEqual(numbers[0].value(), 4.5)
            self.assertEqual(details.raw_values.item(1, 1).text(), "14")
            event = details.node_events.consumed_table.topLevelItem(0)
            event.setExpanded(True)
            ev_flag = details.node_events.consumed_table.itemWidget(
                event.child(0), 1
            ).findChild(QCheckBox)
            self.assertFalse(ev_flag.isHidden())
            details.raw_values.item(0, 1).setText("7")
            self.assertTrue(ev_flag.isHidden())
            self.assertTrue(flag.isHidden())
            details.raw_values.item(0, 1).setText("4")
            ev_flag.click()
            desired = deepcopy(details.desired_configuration)
            self.assertEqual(self.state.nv_values, {1: 7, 2: 8, 3: 9})
            if save:
                details.save_button.click()
                self.assertEqual(self.service.restore.backup, desired)
                self.run_node()
                self.assertTrue(self.results[-1][1])
                self.assertEqual(compare_live_node(self.state, desired), ([], False))
            else:
                details.cancel_editing()
                self.assertEqual(details.raw_values.item(0, 1).text(), "7")
                self.assertFalse(combos[0].isEnabled())
                self.assertEqual(self.connection.sent, [])

    def test_combined_editor_save_from_nv_tab(self):
        self.check_editor_save(events_tab=False)

    def test_combined_editor_save_from_events_tab(self):
        self.check_editor_save(events_tab=True)

    def test_combined_editor_save_failure_refreshes_both_views(self):
        details = self.editing_details()
        self.reject_nv = 1
        details.events_save_button.click()
        self.run_node()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[0][1])
        self.assertIn("Partial Save:", details.nv_result.text())
        self.assertEqual(details.nv_result.text(), details.events_result.text())
        self.assertEqual(details.raw_values.item(0, 1).text(), "7")
        event = details.node_events.consumed_table.topLevelItem(0)
        self.assertEqual(event.child(1).text(1), "")
        self.assertIsNone(details.desired_configuration)
        self.assertFalse(details.saving_configuration)
        self.assertTrue(details.variables.isEnabled())
        self.assertTrue(details.node_events.isEnabled())
        self.assertTrue(details.edit_button.isEnabled())
        self.assertTrue(details.events_edit_button.isEnabled())
        self.service.restore.check(258, node_backup(self.state))

    def test_failed_events_save_rediscovery_updates_raw_and_mdf_views(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem

        from workbench.node import Node

        details = NodeDetails({})
        self.addCleanup(details.close)
        details.connected = True
        details.cbus_service = self.service
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, Node(258, "Test", 2, "", True))
        details.show_node(item)
        from workbench.mdfs import Mdf
        from workbench.node_variables import PROTOTYPE_MDF

        mdf = Mdf(Path("test.json"), PROTOTYPE_MDF)
        details.show_live_state(self.state, mdf)
        self.service.restore.changed.connect(details.show_restore_progress)
        self.service.restore.finished.connect(details.finish_restore)
        self.service.node_state_updated.connect(
            lambda _n: details.show_live_state(self.state, mdf)
        )
        details.edit_button.click()
        details.raw_values.item(1, 1).setText("11")
        details.raw_values.item(2, 1).setText("10")
        self.assertEqual(details.desired_configuration["nvs"], [7, 11, 10])
        self.assertEqual(self.state.nv_values, {1: 7, 2: 8, 3: 9})
        self.change_earlier_nv = True
        details.node_events.consumed_table.topLevelItem(0).child(1).setText(1, "13")
        details.events_save_button.click()
        self.run_node()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[0][1])
        self.assertIn("NV verification", details.nv_result.text())
        self.assertEqual(details.nv_result.text(), details.events_result.text())
        self.assertEqual(self.state.nv_values, {1: 99, 2: 11, 3: 10})
        for table in (details.raw_values, details.mdf_values.raw_values):
            self.assertEqual(
                [table.item(i, 1).text() for i in range(3)], ["99", "11", "10"]
            )
        from PySide6.QtWidgets import QDoubleSpinBox

        form = details.mdf_values.pages.widget(1)
        self.assertEqual(form.findChild(QDoubleSpinBox).value(), 11)
        self.assertIsNone(details.desired_configuration)
        details.edit_button.click()
        self.assertEqual(details.nv_result.text(), "")
        self.assertEqual(details.events_result.text(), "")
        details.cancel_editing()

    def test_combined_editor_disconnect_reports_one_partial_result(self):
        details = self.editing_details()
        editing = []
        details.editing_changed.connect(editing.append)
        details.save_button.click()
        self.app.processEvents()
        self.assertTrue(self.service.nv_write.active)
        self.close_service()
        details.connected = False
        details.update_connection_details()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[0][1])
        self.assertEqual(editing, [False])
        self.assertIn("Connection ended", details.nv_result.text())
        self.assertTrue(
            any("last confirmed" in row[2] for row in self.report_rows(details))
        )
        self.addCleanup(details.failure_report.dialog.close)
        self.assertEqual(details.nv_result.text(), details.events_result.text())
        self.assertIsNone(details.desired_configuration)
        self.assertFalse(details.saving_configuration)
        self.assertFalse(details.edit_button.isEnabled())
        self.assertFalse(details.events_edit_button.isEnabled())

    def test_combined_editor_disconnect_during_reconstruction_keeps_final_result(self):
        details = self.editing_details()
        self.pause_removal_count = True
        details.events_save_button.click()
        self.run_node()  # Pause while the removed event is being rediscovered.
        self.assertFalse(self.results)
        self.assertFalse(details.variables.isEnabled())
        self.assertFalse(details.node_events.isEnabled())
        self.close_service()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[0][1])
        self.assertIn("Connection ended", details.nv_result.text())
        self.assertEqual(details.nv_result.text(), details.events_result.text())
        self.assertIsNone(details.desired_configuration)
        self.assertFalse(details.saving_configuration)

    def test_editor_save_revalidates_before_writing(self):
        details = self.editing_details()
        desired = deepcopy(details.desired_configuration)
        self.state.can_id = None
        details.save_button.click()
        self.assertEqual(self.connection.sent, [])
        self.assertFalse(self.results)
        self.assertFalse(details.saving_configuration)
        self.assertTrue(details.variables.isEnabled())
        self.assertTrue(details.node_events.isEnabled())
        self.assertEqual(details.desired_configuration, desired)
        self.assertEqual(details.nv_result.text(), details.events_result.text())
        self.assertIn("CAN ID", details.nv_result.text())
        details.events_cancel_button.click()
        self.assertIsNone(details.desired_configuration)

    def test_ui_restore_skips_compare_and_layout_warning_cancel_sends_nothing(self):
        self.backup["partOfLayoutBackup"] = True
        details = self.backup_details()
        messages = []

        def decline(dialog):
            messages.append(dialog.text())
            return QMessageBox.StandardButton.No

        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec") as compare,
            patch(
                "workbench.node_backup_workflow.QMessageBox.exec",
                decline,
            ),
        ):
            details.restore_backup()
        compare.assert_not_called()
        self.assertIn("part of a layout backup", messages[0])
        self.assertEqual(self.connection.sent, [])

    def test_ui_annotation_choice_does_not_change_hardware_restore(self):
        import tempfile

        from workbench.annotations import Annotations, load_annotations

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "workbench.annotations.application_directories",
                return_value={"Data": Path(directory)},
            ),
        ):
            self.backup["annotations"] = {"name": "Backup name"}
            details = self.backup_details()
            details.annotations = annotations = Annotations("test")
            details.node_events.annotations = annotations
            self.service.restore.changed.connect(details.show_restore_progress)
            self.service.restore.finished.connect(details.finish_restore)
            annotations.save({"name": "Existing"}, 258)
            for checked in (False, True):

                def confirm(dialog, checked=checked):
                    self.assertTrue(dialog.checkBox().isChecked())
                    dialog.checkBox().setChecked(checked)
                    return QMessageBox.StandardButton.Yes

                with patch("workbench.node_backup_workflow.QMessageBox.exec", confirm):
                    details.restore_backup()
                self.assertFalse(details.node_name.isEnabled())
                self.assertEqual(
                    load_annotations("test", 258)["name"],
                    "Backup name" if checked else "Existing",
                )
                self.run_node()
                self.assertTrue(self.results[-1][1], self.results)
                self.assertTrue(details.node_name.isEnabled())
                self.results.clear()

    def test_annotation_only_restore_skips_incomplete_hardware_and_checks_operation_choices(
        self,
    ):
        import tempfile

        from workbench.annotations import Annotations, load_annotations

        self.backup["annotations"] = {"name": "Local backup name"}
        self.state.nv_progress = DiscoveryProgress.INCOMPLETE
        details = self.backup_details()

        def choose_annotations(dialog):
            configuration = next(
                box
                for box in dialog.findChildren(QCheckBox)
                if box.text() == "Restore configuration"
            )
            annotations = dialog.checkBox()
            restore = dialog.button(QMessageBox.StandardButton.Yes)
            self.assertEqual(restore.text(), "Restore")
            self.assertTrue(configuration.isChecked())
            self.assertTrue(annotations.isChecked())
            self.assertTrue(restore.isEnabled())
            annotations.setChecked(False)
            self.assertTrue(restore.isEnabled())
            configuration.setChecked(False)
            self.assertFalse(restore.isEnabled())
            annotations.setChecked(True)
            self.assertTrue(restore.isEnabled())
            return QMessageBox.StandardButton.Yes

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "workbench.annotations.application_directories",
                return_value={"Data": Path(directory)},
            ),
            patch(
                "workbench.node_backup_workflow.QMessageBox.exec", choose_annotations
            ),
        ):
            details.annotations = Annotations("test")
            details.restore_backup()
            self.assertEqual(load_annotations("test", 258), self.backup["annotations"])
        self.assertEqual(self.connection.sent, [])
        self.assertEqual(self.results, [])
        self.assertEqual(self.state.nv_values, {1: 7, 2: 8, 3: 9})

    def test_ui_explicit_compare_opens_comparison_without_restoring(self):
        details = self.backup_details()
        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec") as compare,
            patch("workbench.node_backup_workflow.QMessageBox.exec") as question,
        ):
            details.backup_buttons["Compare"].click()
        compare.assert_called_once()
        question.assert_not_called()
        self.assertEqual(self.connection.sent, [])

    def test_restore_available_with_selected_backup_after_restore_and_later_saves(self):
        self.backup["nvs"][0] = 10  # Exercise NV writes as well as EV replacement.
        details = self.backup_details()
        self.assertTrue(details.backup_buttons["Restore"].isEnabled())
        self.service.restore.changed.connect(details.show_restore_progress)
        self.service.restore.finished.connect(details.finish_restore)
        self.service.node_state_updated.connect(
            lambda _n: details.show_live_state(self.state)
        )

        enabled_during_restore = []

        def observe_backup_actions(*_args):
            if self.service.restore.active:
                for action in ("New", "Compare", "Restore"):
                    if details.backup_buttons[action].isEnabled():
                        enabled_during_restore.append(action)

        # Check the visible contract after progress and live discovery updates,
        # including handoffs between writes, rediscovery and final verification.
        self.service.restore.changed.connect(observe_backup_actions)
        self.service.node_state_updated.connect(observe_backup_actions)
        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec") as compare,
            patch(
                "workbench.node_backup_workflow.QMessageBox.exec",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            details.restore_backup()
        compare.assert_not_called()
        self.assertFalse(details.edit_button.isEnabled())
        self.assertFalse(details.events_edit_button.isEnabled())
        self.assertFalse(details.backup_buttons["Restore"].isEnabled())
        self.run_node()
        self.assertEqual(enabled_during_restore, [])
        self.assertEqual(
            details.restore_result.text(),
            "Node 258: Configuration restored and fully verified.",
        )
        self.assertTrue(details.edit_button.isEnabled())
        self.assertTrue(details.events_edit_button.isEnabled())
        self.assertFalse(self.service.writes_busy())
        self.assertTrue(details.node_backups.selectedItems())
        self.assertTrue(details.backup_buttons["New"].isEnabled())
        self.assertTrue(details.backup_buttons["Compare"].isEnabled())
        self.assertTrue(details.backup_buttons["Restore"].isEnabled())

        # Keep the backup selected across subsequent unified editing sessions.
        selected = details.node_backups.currentItem()
        self.results.clear()
        details.events_edit_button.click()
        details.node_events.consumed_table.topLevelItem(0).child(1).setText(1, "14")
        details.events_save_button.click()
        self.assertTrue(self.service.writes_busy())
        with self.assertRaises(ValueError):
            self.service.restore.check(258, self.backup)
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertFalse(self.service.writes_busy())
        self.assertIs(details.node_backups.currentItem(), selected)
        self.assertTrue(details.backup_buttons["Compare"].isEnabled())
        self.assertTrue(details.backup_buttons["Restore"].isEnabled())

        self.results.clear()
        details.edit_button.click()
        details.raw_values.item(2, 1).setText("10")
        details.node_events.consumed_table.topLevelItem(0).child(1).setText(1, "15")
        details.events_save_button.click()
        self.assertTrue(self.service.writes_busy())
        self.run_node()
        self.assertFalse(self.service.writes_busy())
        self.assertIs(details.node_backups.currentItem(), selected)
        self.assertTrue(details.backup_buttons["Restore"].isEnabled())

    def test_incomplete_ui_warns_about_uncaptured_configuration_and_cancel_is_inert(
        self,
    ):
        self.backup["complete"] = False
        details = self.backup_details()
        messages = []

        def decline(dialog):
            messages.append(dialog.text())
            return QMessageBox.StandardButton.No

        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec"),
            patch(
                "workbench.node_backup_workflow.QMessageBox.exec",
                decline,
            ),
        ):
            details.restore_backup()
        self.assertIn("configuration that was not captured", messages[0])
        self.assertEqual(self.connection.sent, [])
        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec"),
            patch(
                "workbench.node_backup_workflow.QMessageBox.exec",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            details.restore_backup()
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertIn("full equivalence is not established", self.results[-1][2])

    def report_rows(self, details):
        from PySide6.QtWidgets import QTreeWidgetItemIterator

        iterator = QTreeWidgetItemIterator(details.failure_report.dialog.tree)
        rows = []
        while iterator.value():
            item = iterator.value()
            if item.childCount() == 0:
                rows.append(tuple(item.text(c) for c in range(3)))
            iterator += 1
        return rows

    def failed_save_report(self):
        details = self.editing_details()
        details.raw_values.item(2, 1).setText("10")
        self.change_earlier_nv = True
        details.save_button.click()
        self.run_node()
        self.results.clear()
        self.addCleanup(
            lambda: details.failure_report and details.failure_report.dialog.close()
        )
        return details, details.failure_report

    def test_retry_repeated_failure_then_success_keeps_original_request(self):
        details, report = self.failed_save_report()
        self.assertIn(("NV 1", "10", "99"), self.report_rows(details))
        self.assertFalse(any(row[0] == "NV 2" for row in self.report_rows(details)))
        self.assertEqual(
            [report.dialog.tree.headerItem().text(c) for c in (1, 2)],
            ["Requested", "Actual"],
        )
        original = report.dialog.message.text()
        self.nvs[3] = 9  # Force the firmware side effect again on the first Retry.
        report.dialog.retry_button.click()
        self.assertFalse(report.dialog.retry_button.isEnabled())
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("NV verification", report.dialog.message.text())
        self.assertIn("Partial Save:", report.dialog.message.text())
        self.assertIn(("NV 1", "10", "99"), self.report_rows(details))
        self.change_earlier_nv = False
        self.results.clear()
        report.dialog.retry_button.click()
        self.run_node()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.state.nv_values[1], 10)
        self.assertEqual(self.report_rows(details), [("No differences found", "", "")])
        self.assertFalse(report.dialog.retry_button.isEnabled())
        self.assertIn(original.splitlines()[0], report.dialog.message.text())
        self.assertIn(
            "Configuration saved and fully verified.", report.dialog.message.text()
        )

    def test_save_nv_failure_shows_confirmed_difference(self):
        details = self.editing_details()
        self.reject_nv = 1
        details.save_button.click()
        self.run_node()
        self.assertIn(("NV 1", "10", "7"), self.report_rows(details))
        self.assertIn("CMDERR", details.failure_report.dialog.message.text())
        message = details.failure_report.dialog.message.text()
        self.assertIn("Refresh Node", message)
        self.assertIn("does not retry failed writes", message)
        self.assertNotIn("Reconnect", message)
        self.assertTrue(details.failure_report.dialog.retry_button.isEnabled())
        self.addCleanup(details.failure_report.dialog.close)

    def test_restore_ev_failure_uses_the_same_report(self):
        details = self.editing_details()
        details.cancel_editing()
        self.reject_ev = True
        with patch(
            "workbench.node_backup_workflow.QMessageBox.exec",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            details.restore_backup()
        self.run_node()
        report = details.failure_report
        self.addCleanup(report.dialog.close)
        self.assertIn("EV", report.dialog.message.text())
        self.assertIn("Partial Restore:", report.dialog.message.text())
        self.assertIn("Layouts → Refresh", report.dialog.message.text())
        self.assertIn("does not retry failed writes", report.dialog.message.text())
        self.assertNotIn("Reconnect", report.dialog.message.text())
        self.assertTrue(report.dialog.retry_button.isEnabled())
        self.assertEqual(report.dialog.retry_status.text(), "")
        self.assertTrue(
            any(row[0].startswith("EV") for row in self.report_rows(details))
        )
        self.assertFalse(
            any(row[0].startswith("NV") for row in self.report_rows(details))
        )

    def test_failed_verification_and_disconnect_report_unknown_values(self):
        details = self.editing_details()
        self.withhold_final_read = True
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            details.save_button.click()
            self.run_node()
        report = details.failure_report
        self.addCleanup(report.dialog.close)
        self.assertTrue(any(row[2] == "Unknown" for row in self.report_rows(details)))
        self.assertIn("write may have succeeded", report.dialog.message.text())
        self.close_service()
        self.assertFalse(report.dialog.retry_button.isEnabled())

    def check_retry_stops_before_writes(self, outcome):
        details, report = self.failed_save_report()
        before = len(self.connection.sent)
        self.connection.fail_send = outcome == "send failure"
        self.withhold_final_read = outcome == "timeout"
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            report.dialog.retry_button.click()
            if outcome == "disconnect":
                self.close_service()
            elif outcome == "close":
                report.dialog.close()
            self.run_node(
                stop_when=lambda: (
                    self.connection.state != "Connected"
                    or (
                        not self.service.discovery_pending()
                        and not self.service.writes_busy()
                    )
                )
            )
        self.assertFalse(
            any(
                op in frame
                for frame in self.connection.sent[before:]
                for op in (b"N96", b"ND2", b"N95", b"N53")
            )
        )
        if outcome == "close":
            self.assertIsNone(details.failure_report)
        else:
            self.assertFalse(report.dialog.retry_button.isEnabled())
            self.assertNotEqual(report.dialog.retry_status.text(), "Retry in progress.")

    def test_retry_send_failure_does_not_write(self):
        self.check_retry_stops_before_writes("send failure")

    def test_retry_incomplete_discovery_does_not_write(self):
        self.check_retry_stops_before_writes("timeout")

    def test_disconnect_during_retry_does_not_write_or_hang(self):
        self.check_retry_stops_before_writes("disconnect")

    def test_close_during_retry_cancels_the_write_handoff(self):
        self.check_retry_stops_before_writes("close")

    def test_retry_rejects_busy_changed_identity_and_known_learn_mode(self):
        _details, report = self.failed_save_report()
        self.state.parameters[8] |= 0x20
        self.service.node_state_updated.emit(258)
        self.assertFalse(report.dialog.retry_button.isEnabled())
        self.state.parameters[8] &= ~0x20
        self.service.rediscover_node(258)
        before = list(self.connection.sent)
        report.retry()
        self.assertEqual(self.connection.sent, before)
        self.assertIn("discovery", report.dialog.retry_status.text())
        self.state.can_id = 3
        report.retry()
        self.assertIn("identity changed", report.dialog.message.text())
        self.assertEqual(self.connection.sent, before)

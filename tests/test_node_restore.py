"""Restore contracts through real writers and observable GridConnect exchanges."""

import unittest
from copy import deepcopy
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
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
        self.reject_nv = None
        self.reject_ev = False
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

    def run_node(self):
        """Answer transmitted requests as a small node with changing table slots."""
        for _ in range(600):
            self.app.processEvents()
            if self.withhold_final_read or self.drop_write_reply:
                QTest.qWait(1)
            if self.results:
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
                    2: 97,
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
                self.learn = False
            elif op == 0xD2:
                identity = (int.from_bytes(data[1:3]), int.from_bytes(data[3:5]))
                if self.reject_ev:
                    self.reply("6F010201")
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

    def test_complete_restore_skips_matching_nvs_then_matches_events_after_slot_change(
        self,
    ):
        self.service.restore.begin(258, self.backup)
        self.run_node()
        writes = [f for f in self.connection.sent if b"N96" in f]
        self.assertEqual(
            writes,
            [],
        )
        self.assertTrue(self.results[-1][1], self.results)
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))
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
            with self.assertRaisesRegex(ValueError, "restoration"):
                self.service.write_nvs(258, {2: 10})
        # Only the unanswered request needs the short timeout. Restore the
        # normal setting before its failure starts full-node rediscovery.
        # Retained matching values cannot substitute for fresh replies.
        QTest.qWait(30)
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

    def test_nv_side_effect_is_not_reconciled_and_prevents_ev_teaching(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.change_earlier_nv = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("NV verification", self.results[-1][2])
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))
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

    def test_nv_failure_stops_and_rediscover_partial_result(self):
        self.nvs = {1: 6, 2: 0, 3: 0}
        self.state.nv_values = dict(self.nvs)
        self.reject_nv = 2
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Partial restoration: 1 NV writes", self.results[-1][2])
        self.assertEqual(self.state.nv_values, self.nvs)
        self.assertFalse(any(b"N96010203" in f for f in self.connection.sent))

    def test_ev_failure_stops_exits_learn_mode_and_rediscover_partial_result(self):
        self.reject_ev = True
        self.service.restore.begin(258, self.backup)
        self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Partial restoration: 0 NV writes", self.results[-1][2])
        self.assertFalse(self.learn)
        self.assertEqual(self.state.nv_values, self.nvs)
        self.assertEqual(compare_live_node(self.state, self.backup)[0][0][1], "EV 2")

    def test_final_discovery_timeout_never_reports_success(self):
        self.withhold_final_read = True
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 5):
            self.service.restore.begin(258, self.backup)
            self.run_node()
        self.assertFalse(self.results[-1][1])
        self.assertIn("could not be completely verified", self.results[-1][2])
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
        self.assertFalse(any(b"ND2" in f for f in self.connection.sent))

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

    def test_ui_preview_and_layout_warning_cancel_send_nothing(self):
        self.backup["partOfLayoutBackup"] = True
        details = self.backup_details()
        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec"),
            patch(
                "workbench.node_backup_workflow.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as question,
        ):
            details.restore_backup()
        self.assertIn("part of a layout backup", question.call_args.args[2])
        self.assertEqual(self.connection.sent, [])

    def test_restore_available_with_selected_backup_after_restore_and_later_saves(self):
        details = self.backup_details()
        self.assertTrue(details.backup_buttons["Restore"].isEnabled())
        self.service.restore.changed.connect(details.show_restore_progress)
        self.service.restore.finished.connect(details.finish_restore)
        self.service.nv_write.finished.connect(details.finish_nv_save)
        self.service.nv_write.refresh_finished.connect(details.finish_nv_refresh)
        self.service.ev_write.finished.connect(details.finish_ev_save)
        self.service.node_state_updated.connect(
            lambda _n: details.show_live_state(self.state)
        )
        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec"),
            patch(
                "workbench.node_backup_workflow.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            details.restore_backup()
        self.assertFalse(details.edit_button.isEnabled())
        self.assertFalse(details.events_edit_button.isEnabled())
        self.assertFalse(details.backup_buttons["Restore"].isEnabled())
        self.run_node()
        self.assertIn("fully verified", details.restore_result.text())
        self.assertTrue(details.edit_button.isEnabled())
        self.assertTrue(details.events_edit_button.isEnabled())
        self.assertFalse(self.service.writes_busy())
        self.assertTrue(details.node_backups.selectedItems())
        self.assertTrue(details.backup_buttons["Compare"].isEnabled())
        self.assertTrue(details.backup_buttons["Restore"].isEnabled())

        # Keep the backup selected while editing the restored node. A Save's
        # final discovery update arrives before its writer releases the wire.
        selected = details.node_backups.currentItem()
        self.results.clear()
        self.service.ev_write.finished.connect(lambda *args: self.results.append(args))
        details.start_events_editing()
        event = details.node_events.consumed_table.topLevelItem(0)
        event.child(1).setText(1, "14")
        details.save_events_editing()
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
        self.service.nv_write.refresh_finished.connect(
            lambda *args: self.results.append(args)
        )
        details.start_editing()
        details.editing_values[3] = 10
        details.save_editing()
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
        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec"),
            patch(
                "workbench.node_backup_workflow.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as question,
        ):
            details.restore_backup()
        self.assertIn("configuration that was not captured", question.call_args.args[2])
        self.assertEqual(self.connection.sent, [])
        with (
            patch("workbench.node_backup_workflow.BackupCompare.exec"),
            patch(
                "workbench.node_backup_workflow.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            details.restore_backup()
        self.run_node()
        self.assertTrue(self.results[-1][1], self.results)
        self.assertIn("full equivalence is not established", self.results[-1][2])

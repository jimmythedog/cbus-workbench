"""Observable NV Save frames, confirmed state, and editor working copies."""

import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidgetItem

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.node import Node
from workbench.node_details import NodeDetails
from workbench.pnn import Pnn
from workbench.wrack import decode_wrack


class Connection(QObject):
    frame_received = Signal(bytes)
    state = "Connected"
    layout_name = "NV test"

    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail_send = False

    def send(self, frame):
        if self.fail_send:
            raise OSError("Connection lost")
        self.sent.append(frame)


class NvWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        self.identity = Pnn(258, 13, 34, 4)
        self.state = NodeState(
            self.identity,
            parameters={6: 2},
            nv_values={1: 7, 2: 8},
            nv_progress=DiscoveryProgress.COMPLETE,
        )
        self.service.node_states[258] = self.state
        self.results = []
        self.service.nv_write.finished.connect(lambda *args: self.results.append(args))
        self.addCleanup(lambda: self.service.close())

    def reply(self, payload):
        self.connection.frame_received.emit(f":SB040N{payload};".encode())

    def test_status_covers_post_save_nv_and_event_rediscovery(self):
        self.state.parameter_progress = DiscoveryProgress.COMPLETE
        self.state.event_progress = self.state.ev_progress = DiscoveryProgress.COMPLETE
        self.state.identity = Pnn(258, 13, 34, 5)
        self.service.write_nvs(258, {1: 9})
        self.reply("590102")
        self.reply("9701020109")
        self.app.processEvents()
        self.assertEqual(self.service.discovery_status, "Discovering configuration…")
        self.reply("9701020109")
        self.reply("9701020208")
        self.app.processEvents()
        self.assertEqual(self.service.discovery_status, "Discovering configuration…")
        self.reply("74010200")
        self.app.processEvents()
        self.assertEqual(self.service.discovery_status, "Configuration ready")

    def test_changed_only_serialised_acknowledgement_and_readback(self):
        self.service.write_nvs(258, {1: 7, 2: 0})
        self.assertEqual(self.connection.sent, [b":SBFC0N9601020200;"])
        self.assertEqual(self.state.nv_values, {1: 7, 2: 8})
        self.reply("9701020200")  # A readback before WRACK is not verification.
        self.reply("590103")  # Another node cannot acknowledge this write.
        self.reply("59010200")  # Malformed WRACK cannot acknowledge it either.
        self.assertFalse(self.results)
        self.assertEqual(self.state.nv_values[2], 8)
        self.reply("590102")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010202;")
        self.assertEqual(self.state.nv_values[2], 8)
        self.reply("9701020200")
        self.assertEqual(self.state.nv_values, {1: 7, 2: 0})
        self.assertTrue(self.results[-1][1])

    def test_refresh_failure_is_distinct_from_verified_writes(self):
        refresh_results = []
        self.service.nv_write.refresh_finished.connect(
            lambda *args: refresh_results.append(args)
        )
        with patch("workbench.cbus_service.AUTOMATIC_REQUEST_TIMEOUT_MS", 10):
            self.service.write_nvs(258, {1: 9})
            self.reply("590102")
            self.reply("9701020109")
            self.assertTrue(self.results[-1][1])
            self.assertIn("Saving changes…", self.results[-1][2])
            self.reply("9701020180")
            QTest.qWait(30)  # NV2 never responds during the full reread.
        self.assertEqual(self.state.nv_values, {1: 128, 2: 8})
        self.assertEqual(self.state.nv_progress, DiscoveryProgress.INCOMPLETE)
        self.assertIn("Changes saved, but", refresh_results[-1][1])
        self.assertIn("could not be refreshed", refresh_results[-1][1])
        self.assertNotIn("remaining edits were not confirmed", refresh_results[-1][1])

    def test_event_refresh_replaces_slots_and_values_in_state_and_view(self):
        self.state.identity = Pnn(258, 13, 34, 5)
        self.state.parameters[5] = 1
        self.state.event_identities = {
            i: (258, number) for i, number in enumerate((1, 102, 302, 202, 1000, 2), 1)
        }
        self.state.ev_values = {i: {1: 99} for i in range(1, 7)}
        self.state.stored_event_count = 6
        self.state.event_progress = self.state.ev_progress = DiscoveryProgress.COMPLETE
        from workbench.node_view import NodeView

        view = NodeView({})
        self.addCleanup(view.close)
        view.state_lookup = self.service.node_states.__getitem__
        view.show_identity(self.state.identity)
        self.service.node_state_updated.connect(view.refresh_state)
        details = view.details
        details.connected = True
        details.cbus_service = self.service
        self.service.nv_write.finished.connect(details.finish_nv_save)
        self.service.nv_write.refresh_finished.connect(details.finish_nv_refresh)
        results = []
        self.service.nv_write.refresh_finished.connect(
            lambda *args, results=results: results.append(args)
        )
        tree = details.node_events.consumed_table
        self.assertEqual(tree.topLevelItemCount(), 6)
        details.start_editing()
        details.raw_values.item(0, 1).setText("9")
        details.save_editing()
        self.reply("590102")
        self.reply("9701020109")
        self.reply("9701020109")
        self.reply("9701020208")
        self.assertEqual(details.nv_result.text(), "Saving changes…")
        self.assertEqual(tree.topLevelItemCount(), 0)
        self.assertEqual(self.state.ev_values, {})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580102;")
        self.reply("74010203")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N570102;")
        for slot, node, event in ((1, 258, 1), (2, 0, 1000), (3, 259, 77)):
            self.reply(f"F20102{node:04X}{event:04X}{slot:02X}")
        self.assertFalse(results)
        for slot in range(1, 4):
            self.assertEqual(details.nv_result.text(), "Saving changes…")
            self.reply(f"B50102{slot:02X}01{slot + 10:02X}")
        self.assertEqual(
            self.state.event_identities, {1: (258, 1), 2: (0, 1000), 3: (259, 77)}
        )
        self.assertEqual(self.state.ev_values, {1: {1: 11}, 2: {1: 12}, 3: {1: 13}})
        self.assertEqual(
            [tree.topLevelItem(i).text(0) for i in range(3)],
            ["258:1", "0:1000", "259:77"],
        )
        self.assertEqual(
            [tree.topLevelItem(i).child(0).text(1) for i in range(3)],
            ["11", "12", "13"],
        )
        self.assertEqual(results, [(258, "Changes saved successfully.")])
        self.assertEqual(
            details.nv_result.text(), "Node 258: Changes saved successfully."
        )

    def test_zero_events_and_incomplete_event_refresh(self):
        for outcome in (
            "zero",
            "count timeout",
            "identity timeout",
            "ev timeout",
            "send failure",
            "disconnect",
        ):
            with self.subTest(outcome=outcome):
                connection = Connection()
                service = CbusService(connection, 126)
                state = NodeState(
                    Pnn(258, 1, 1, 5),
                    parameters={6: 1, 5: 1},
                    nv_values={1: 7},
                    nv_progress=DiscoveryProgress.COMPLETE,
                    event_identities={1: (258, 99)},
                    ev_values={1: {1: 99}},
                )
                service.node_states[258] = state
                results = []
                service.nv_write.refresh_finished.connect(
                    lambda *args, results=results: results.append(args)
                )

                def reply(payload, connection=connection):
                    connection.frame_received.emit(f":SB040N{payload};".encode())

                with patch("workbench.cbus_service.AUTOMATIC_REQUEST_TIMEOUT_MS", 10):
                    service.write_nvs(258, {1: 9})
                    reply("590102")
                    reply("9701020109")
                    if outcome == "send failure":
                        connection.fail_send = True
                    reply("9701020109")
                    if outcome == "zero":
                        reply("74010200")
                    elif outcome in ("identity timeout", "ev timeout"):
                        reply("74010201")
                        if outcome == "ev timeout":
                            reply("F201020102000101")
                    if outcome == "disconnect":
                        service.close()
                    else:
                        QTest.qWait(30)
                        service.close()
                self.assertEqual(state.nv_values, {1: 9})
                self.assertEqual(len(results), 1)
                self.assertEqual(
                    results[0][1],
                    "Changes saved successfully."
                    if outcome == "zero"
                    else "Changes saved, but some values could not be refreshed.",
                )
                self.assertNotIn((258, 99), state.event_identities.values())

    def test_partial_failure_stops_remaining_writes_and_preserves_unverified(self):
        self.service.write_nvs(258, {1: 9, 2: 10})
        self.reply("590102")
        self.reply("9701020109")
        self.assertEqual(self.state.nv_values, {1: 9, 2: 8})
        self.reply("6F01020A")
        self.assertFalse(self.results[-1][1])
        self.assertIn("1 of 2 changes saved", self.results[-1][2])
        self.assertIn("CMDERR 10", self.results[-1][2])
        self.reply("970102020A")  # A late reply must not erase the failure.
        self.assertEqual(self.state.nv_values, {1: 9, 2: 8})
        with self.assertRaisesRegex(ValueError, "Reconnect"):
            self.service.write_nvs(258, {2: 10})

    def test_mismatch_does_not_confirm_requested_value(self):
        self.service.write_nvs(258, {1: 9, 2: 10})
        self.reply("590102")
        self.reply("9701020106")
        self.assertEqual(self.state.nv_values, {1: 7, 2: 8})
        self.assertFalse(self.results[-1][1])
        self.assertIn("readback was 6", self.results[-1][2])
        self.assertEqual(len(self.connection.sent), 2)

    def test_timeout_for_ack_or_readback_never_confirms_transmission(self):
        for acknowledge in (False, True):
            with (
                self.subTest(acknowledge=acknowledge),
                patch("workbench.nv_write.WRITE_TIMEOUT_MS", 10),
            ):
                self.service.write_nvs(258, {1: 9})
                if acknowledge:
                    self.reply("590102")
                QTest.qWait(30)
                self.assertFalse(self.results[-1][1])
                self.assertIn("timed out", self.results[-1][2])
                self.assertEqual(self.state.nv_values[1], 7)
                # A fresh service is the public rediscovery boundary after failure.
                self.service.close()
                self.service = CbusService(self.connection, 126)
                self.service.node_states[258] = self.state
                self.service.nv_write.finished.connect(
                    lambda *args: self.results.append(args)
                )

    def test_close_and_failed_send_report_failure(self):
        self.service.write_nvs(258, {1: 9})
        self.service.close()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Connection ended", self.results[-1][2])
        self.assertEqual(self.state.nv_values[1], 7)
        # Avoid closing the detached service twice in cleanup.
        self.service = CbusService(self.connection, 126)
        self.service.node_states[258] = self.state
        self.service.nv_write.finished.connect(lambda *args: self.results.append(args))
        self.connection.fail_send = True
        self.service.write_nvs(258, {1: 9})
        self.assertFalse(self.results[-1][1])
        self.assertEqual(self.state.nv_values[1], 7)

    def test_validation_and_unchanged_save_send_no_frames(self):
        for values in ({0: 1}, {256: 1}, {3: 1}, {1: -1}, {1: 256}, {1: True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.service.write_nvs(258, values)
        self.connection.state = "Disconnected"
        with self.assertRaises(ValueError):
            self.service.write_nvs(258, {1: 9})
        self.connection.state = "Connected"
        self.state.nv_progress = DiscoveryProgress.INCOMPLETE
        with self.assertRaises(ValueError):
            self.service.write_nvs(258, {1: 9})
        self.state.nv_progress = DiscoveryProgress.COMPLETE
        self.service.write_nvs(258, {1: 7, 2: 8})
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.connection.sent, [])

    def test_save_waits_for_existing_discovery_request_then_resumes_queue(self):
        self.reply("B601030D2200")  # Starts another node's parameter request.
        self.service.write_nvs(258, {1: 9})
        self.assertEqual(self.connection.sent, [b":SBFC0N73010300;"])
        self.reply("9B01030002")  # Queues parameter 2, yields to the pending Save.
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9601020109;")
        self.reply("590102")
        self.reply("9701020109")
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010302;")
        self.reply("9B01030201")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010201;")

    def test_live_raw_edit_and_disconnect_discard_without_transmission(self):
        details = NodeDetails({})
        self.addCleanup(details.close)
        details.connected = True
        details.cbus_service = self.service
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.identity)
        details.show_node(item)
        details.show_live_state(self.state)
        details.start_editing()
        details.raw_values.item(0, 1).setText("255")
        details.show_live_state(self.state)  # Background updates retain the edit.
        self.assertEqual(details.raw_values.item(0, 1).text(), "255")
        self.assertEqual(self.state.nv_values[1], 7)
        details.cancel_editing()
        self.assertEqual(details.raw_values.item(0, 1).text(), "7")
        details.start_editing()
        details.raw_values.item(0, 1).setText("9")
        details.connected = False
        details.update_connection_details()
        self.assertIsNone(details.editing_values)
        self.assertFalse(details.edit_button.isEnabled())
        self.assertIn("discarded", details.nv_result.text())
        self.assertEqual(self.connection.sent, [])

    def test_raw_and_mdf_share_working_copy_cancel_and_confirmed_result(self):
        details = NodeDetails({})
        self.addCleanup(details.close)
        details.connected = True
        details.cbus_service = self.service
        self.service.nv_write.finished.connect(details.finish_nv_save)
        self.service.nv_write.refresh_finished.connect(details.finish_nv_refresh)
        self.service.node_state_updated.connect(
            lambda _n: details.show_live_state(self.state)
        )
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, Node(258, "Test", 2, "", True))
        details.show_node(item)
        details.show_live_state(self.state)
        self.assertTrue(details.edit_button.isEnabled())
        details.start_editing()
        details.mdf_values.global_settings.startup_delay.setValue(9)
        self.assertEqual(self.state.nv_values[2], 8)
        details.cancel_editing()
        self.assertEqual(self.connection.sent, [])
        details.start_editing()
        details.raw_values.item(0, 1).setText("9")
        details.save_editing()
        self.assertFalse(details.cancel_button.isEnabled())
        self.assertEqual(self.state.nv_values[2], 8)
        self.reply("590102")
        self.reply("9701020109")
        self.assertEqual(details.raw_values.item(0, 1).text(), "9")
        self.assertEqual(details.mdf_values.global_settings.startup_delay.value(), 8)
        self.assertIn("Saving changes…", details.nv_result.text())
        self.reply("9701020109")
        self.reply("9701020280")  # Firmware changed an NV after verification.
        self.assertEqual(self.state.nv_values[2], 128)
        self.assertEqual(details.raw_values.item(1, 1).text(), "128")
        self.assertEqual(details.mdf_values.global_settings.startup_delay.value(), 128)
        self.assertEqual(
            details.nv_result.text(), "Node 258: Changes saved successfully."
        )


class WrackTests(unittest.TestCase):
    def test_decode_and_reject_malformed_acknowledgements(self):
        self.assertEqual(decode_wrack(b":SB040N590102;").node_number, 258)
        self.assertIsNone(decode_wrack(b":SB040N0D;"))
        with self.assertRaises(ValueError):
            decode_wrack(b":SB040N59010200;")

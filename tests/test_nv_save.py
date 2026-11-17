"""Targeted editing Save through confirmed, observable wire exchanges."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidgetItem, QPushButton
from test_nv_write import Connection

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.node_backup_files import node_backup
from workbench.node_view import NodeView
from workbench.pnn import Pnn


class NvSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        done = DiscoveryProgress.COMPLETE
        self.state = NodeState(
            Pnn(258, 13, 34, 4),
            parameters={6: 3},
            nv_values={1: 7, 2: 8, 3: 9},
            parameter_progress=done,
            nv_progress=done,
            event_progress=DiscoveryProgress.SKIPPED,
            ev_progress=DiscoveryProgress.SKIPPED,
            can_id=2,
        )
        self.service.nodes[258] = self.state.identity
        self.service.node_states[258] = self.state
        self.backup = node_backup(self.state)
        self.mdf = {
            "nodeVariables": [
                {"nodeVariableIndex": 1, "linkedVariables": {"NV": [2, 3]}},
                {"nodeVariableIndex": 2, "linkedVariables": {"NV": [3]}},
            ]
        }
        self.observed = []
        self.service.event_received.connect(self.observed.append)
        self.results = []
        self.service.nv_save.finished.connect(lambda *args: self.results.append(args))
        self.addCleanup(self.service.close)

    def reply(self, payload):
        self.connection.frame_received.emit(f":SB040N{payload};".encode())

    def save(self, values):
        self.backup["nvs"] = values
        self.service.nv_save.begin(258, self.backup, mdf=self.mdf)
        self.app.processEvents()

    def verified(self, index, value):
        self.reply("590102")
        self.reply(f"970102{index:02X}{value:02X}")

    def payloads(self):
        return [frame.decode().split("N")[1][:-1] for frame in self.connection.sent]

    def test_unchanged_values_send_nothing(self):
        self.save([7, 8, 9])
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.connection.sent, [])

    def test_linked_reads_accept_firmware_changes(self):
        self.save([10, 8, 9])
        self.verified(1, 10)
        self.reply("9701020280")
        self.reply("970102030B")
        self.app.processEvents()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.state.nv_values, {1: 10, 2: 128, 3: 11})
        self.assertEqual(
            self.payloads(), ["960102010A", "71010201", "71010202", "71010203"]
        )
        self.assertFalse(self.service.restore.active)
        self.assertEqual(self.backup["nvs"], [10, 8, 9])  # Caller owns its copy.

    def test_multiple_edits_keep_explicit_values_after_firmware_changes(self):
        self.save([10, 12, 9])
        self.verified(1, 10)
        self.reply("9701020280")
        self.reply("970102030B")
        self.app.processEvents()
        self.assertEqual(self.payloads()[-1], "960102020C")
        self.verified(2, 12)
        self.reply("970102030D")
        self.app.processEvents()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.state.nv_values, {1: 10, 2: 12, 3: 13})
        self.assertEqual(
            self.payloads(),
            [
                "960102010A",
                "71010201",
                "71010202",
                "71010203",
                "960102020C",
                "71010202",
                "71010203",
            ],
        )

    def test_explicit_edit_already_satisfied_by_firmware_is_not_written(self):
        self.save([10, 12, 9])
        self.verified(1, 10)
        self.reply("970102020C")
        self.reply("9701020309")
        self.app.processEvents()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(len(self.connection.sent), 4)

    def test_absent_and_empty_links_read_only_written_nv(self):
        for definition in (
            {},
            {"linkedVariables": {}},
            {"linkedVariables": {"NV": []}},
        ):
            with self.subTest(definition=definition):
                self.connection.sent.clear()
                self.state.nv_values[1] = 7
                self.mdf = {"nodeVariables": [{"nodeVariableIndex": 1, **definition}]}
                self.save([10, 8, 9])
                self.verified(1, 10)
                self.app.processEvents()
                self.assertTrue(self.results[-1][1])
                self.assertEqual(self.payloads(), ["960102010A", "71010201"])

    def test_link_can_refresh_a_lower_nv_without_reading_unrelated_nvs(self):
        self.mdf = {
            "nodeVariables": [
                {
                    "type": "NodeVariableTabs",
                    "tabPanels": [
                        {
                            "items": [
                                {
                                    "type": "NodeVariableGroup",
                                    "groupItems": [
                                        {
                                            "nodeVariableIndex": 3,
                                            "linkedVariables": {"NV": [1]},
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        self.save([7, 8, 10])
        self.verified(3, 10)
        self.reply("970102012A")
        self.app.processEvents()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.state.nv_values, {1: 42, 2: 8, 3: 10})
        self.assertEqual(self.payloads(), ["960102030A", "71010203", "71010201"])

    def consumer(self):
        self.state.identity = Pnn(258, 13, 34, 5)
        self.service.nodes[258] = self.state.identity
        self.state.parameters[5] = 1
        self.state.stored_event_count = 2
        self.state.event_identities = {1: (1, 2), 2: (3, 4)}
        self.state.ev_values = {1: {1: 5}, 2: {1: 6}}
        self.state.event_progress = self.state.ev_progress = DiscoveryProgress.COMPLETE
        self.backup = node_backup(self.state)
        self.mdf = {}

    def answer_events(self):
        self.assertEqual(self.payloads()[-1], "580102")
        self.reply("74010202")
        self.assertEqual(self.payloads()[-1], "570102")
        self.reply("F201020003000407")
        self.reply("F201020005000608")
        self.reply("B5010207012A")
        self.reply("B5010208012B")
        self.app.processEvents()
        self.assertEqual(self.state.event_identities, {7: (3, 4), 8: (5, 6)})
        self.assertEqual(self.state.ev_values, {7: {1: 42}, 8: {1: 43}})

    def test_nv_save_refreshes_added_removed_and_changed_events(self):
        self.consumer()
        view, _item = self.editing_view()
        details = view.details
        details.save_editing()
        self.app.processEvents()
        self.verified(1, 10)
        self.app.processEvents()
        self.assertFalse(self.results)
        self.answer_events()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.observed, [])
        tree = details.node_events.consumed_table
        self.assertEqual(tree.topLevelItemCount(), 2)
        self.assertEqual(
            [tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(2)],
            [(3, 4), (5, 6)],
        )
        self.assertEqual(
            self.payloads(),
            ["960102010A", "71010201", "580102", "570102", "9C01020701", "9C01020801"],
        )

    def test_partial_save_refreshes_events_after_resolved_failure(self):
        self.consumer()
        self.save([10, 12, 9])
        self.verified(1, 10)
        self.app.processEvents()
        self.reply("6F010201")
        self.answer_events()
        self.assertFalse(self.results[-1][1])
        self.assertIn("1 NV writes verified", self.results[-1][2])

    def test_linked_read_failure_still_refreshes_events_after_verified_write(self):
        self.consumer()
        self.mdf = {
            "nodeVariables": [{"nodeVariableIndex": 1, "linkedVariables": {"NV": [2]}}]
        }
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 50):
            self.save([10, 8, 12])
            self.verified(1, 10)
            for _ in range(30):
                if self.payloads()[-1] == "580102":
                    break
                QTest.qWait(10)
            self.answer_events()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Linked NV reads incomplete", self.results[-1][2])
        self.assertNotIn("960102030C", self.payloads())

    def test_partial_save_with_uncertain_write_does_not_start_discovery(self):
        self.consumer()
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.save([10, 12, 9])
            self.verified(1, 10)
            self.app.processEvents()
            self.wait_for_result()
        self.assertFalse(self.results[-1][1])
        self.assertNotIn("580102", self.payloads())

    def test_unchanged_consumer_does_not_refresh_events(self):
        self.consumer()
        self.save([7, 8, 9])
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.connection.sent, [])

    def test_consumer_with_events_not_yet_loaded_saves_nvs_without_event_reads(self):
        # Events never loaded on this connection hold nothing that could be stale.
        self.state.identity = Pnn(258, 13, 34, 5)
        self.service.nodes[258] = self.state.identity
        self.state.event_progress = self.state.ev_progress = (
            DiscoveryProgress.NOT_STARTED
        )
        self.mdf = {}
        self.save([10, 8, 9])
        self.verified(1, 10)
        self.app.processEvents()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.payloads(), ["960102010A", "71010201"])
        self.assertEqual(self.state.event_progress, DiscoveryProgress.NOT_STARTED)

    def test_event_refresh_failure_reports_partial_save(self):
        self.consumer()
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.save([10, 8, 9])
            self.verified(1, 10)
            self.wait_for_result()
        self.assertFalse(self.results[-1][1])
        self.assertIn("event", self.results[-1][2].lower())
        self.assertEqual(self.state.event_progress, DiscoveryProgress.INCOMPLETE)

    def test_last_nv_edit_has_no_follow_on_discovery(self):
        self.save([7, 8, 10])
        self.verified(3, 10)
        self.app.processEvents()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.payloads(), ["960102030A", "71010203"])

    def test_verification_mismatch_stops_later_writes_and_records_actual_value(self):
        self.save([10, 12, 9])
        self.reply("590102")
        self.reply("9701020106")
        self.assertFalse(self.results[-1][1])
        self.assertIn("readback was 6", self.results[-1][2])
        self.assertEqual(self.state.nv_values, {1: 6, 2: 8, 3: 9})
        self.assertEqual(self.payloads(), ["960102010A", "71010201"])

    def test_rejected_write_stops_without_discovery(self):
        self.save([10, 12, 9])
        self.reply("6F010201")
        self.assertFalse(self.results[-1][1])
        self.assertIn("CMDERR", self.results[-1][2])
        self.assertEqual(self.payloads(), ["960102010A"])

    def wait_for_result(self):
        for _ in range(50):
            if self.results:
                return
            QTest.qWait(10)
        self.fail("Save did not finish")

    def test_verification_timeout_keeps_safety_block_and_ignores_late_readback(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.save([10, 12, 9])
            self.reply("590102")
            self.wait_for_result()
        self.assertFalse(self.results[-1][1])
        self.reply("970102010A")
        self.assertEqual(self.state.nv_values[1], 7)
        self.assertEqual(self.payloads(), ["960102010A", "71010201", "71010201"])
        with self.assertRaisesRegex(ValueError, "Protocol safety unresolved"):
            self.service.nv_save.begin(258, self.backup)

    def test_linked_nv_read_timeout_prevents_remaining_edits(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.save([10, 8, 12])
            self.verified(1, 10)
            self.reply("9701020280")
            self.wait_for_result()
        self.assertFalse(self.results[-1][1])
        self.assertIn("Linked NV reads incomplete", self.results[-1][2])
        self.assertIn("1 NV writes verified", self.results[-1][2])
        self.assertEqual(self.state.nv_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(self.state.nv_values[2], 128)
        self.assertEqual(self.state.nv_values[3], 9)  # Unread cache is retained.
        # Only NV2's reply is fresh. Its firmware change is accepted; the
        # explicit NV3 request remains pending despite the cached value.
        self.assertEqual(self.service.nv_save.backup["nvs"], [10, 128, 12])
        self.assertEqual(
            self.payloads(),
            ["960102010A", "71010201", "71010202", "71010203", "71010203"],
        )

    def test_missing_acknowledgement_never_confirms_a_write(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.save([10, 8, 9])
            self.wait_for_result()
        self.assertFalse(self.results[-1][1])
        self.assertIn("WRACK", self.results[-1][2])
        self.assertEqual(self.state.nv_values[1], 7)
        self.assertEqual(self.payloads(), ["960102010A"])

    def test_disconnect_reports_one_result_and_no_follow_on_requests(self):
        self.save([10, 8, 9])
        self.service.close()
        self.assertEqual(len(self.results), 1)
        self.assertFalse(self.results[0][1])
        self.assertIn("Connection ended", self.results[0][2])
        self.assertEqual(self.state.nv_values[1], 7)
        self.assertEqual(self.payloads(), ["960102010A"])

    def test_operation_ownership_excludes_other_writes_and_refresh(self):
        self.save([10, 8, 9])
        for action in (
            lambda: self.service.nv_save.begin(258, self.backup),
            lambda: self.service.restore.begin(258, self.backup),
            lambda: self.service.refresh_node(258),
            lambda: self.service.write_nvs(258, {2: 12}),
        ):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.payloads(), ["960102010A"])

    def editing_view(self):
        view = NodeView({})
        self.addCleanup(view.close)
        details = view.details
        details.connected = True
        details.cbus_service = self.service
        view.state_lookup = lambda number: self.service.node_states.get(number)
        self.service.node_state_updated.connect(view.refresh_state)
        self.service.discovery_status_changed.connect(view.discovery_status_changed)
        self.service.nv_save.changed.connect(details.show_restore_progress)
        self.service.nv_save.finished.connect(details.finish_restore)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.state.identity)
        view.node_list.addItem(item)
        view.node_list.setCurrentItem(item)
        details.live_mdf = SimpleNamespace(data=self.mdf)
        details.start_editing()
        details.raw_values.item(0, 1).setText("10")
        return view, item

    def retry_after_refresh(self, report, values):
        """Answer Retry's explicit read-only refresh, stopping at its first write."""
        cursor = len(self.connection.sent)
        report.dialog.retry_button.click()
        parameters = {0: 8, 1: 13, 2: 97, 3: 34, 4: 0, 5: 0, 6: 3, 7: 1, 8: 4}
        for _ in range(100):
            self.app.processEvents()
            if cursor == len(self.connection.sent):
                QTest.qWait(1)
                continue
            payload = self.payloads()[cursor]
            cursor += 1
            opcode = payload[:2]
            if opcode == "96":
                return
            index = int(payload[6:8], 16)
            if opcode == "73":
                self.reply(f"9B0102{index:02X}{parameters[index]:02X}")
            else:
                self.assertEqual(opcode, "71")
                self.reply(f"970102{index:02X}{values[index - 1]:02X}")
        self.fail(
            f"Retry did not reach its first write: {report.dialog.message.text()}"
        )

    def test_repeated_retry_preserves_explicit_edits_and_accepts_untouched_firmware_values(
        self,
    ):
        view, _item = self.editing_view()
        details = view.details
        details.raw_values.item(1, 1).setText("12")
        details.save_button.click()
        self.app.processEvents()
        self.verified(1, 6)  # Confirmed mismatch permits an explicit Retry.
        report = details.failure_report
        self.addCleanup(report.dialog.close)

        # NV2 already matches the explicit edit during each refresh. It must
        # still retain that intention if writing NV1 subsequently resets it.
        self.retry_after_refresh(report, [6, 12, 42])
        self.verified(1, 5)  # A second failure must not replace the original set.
        self.assertFalse(self.results[-1][1])
        self.retry_after_refresh(report, [5, 12, 43])
        retry_start = len(self.connection.sent) - 1
        self.verified(1, 10)
        self.reply("9701020280")
        self.reply("970102032C")
        self.app.processEvents()
        self.assertEqual(self.payloads()[-1], "960102020C")
        self.verified(2, 12)
        self.reply("970102032D")
        self.app.processEvents()
        self.assertTrue(self.results[-1][1])
        self.assertEqual(self.state.nv_values, {1: 10, 2: 12, 3: 45})
        self.assertEqual(report.requested["nvs"], [10, 12, 45])
        self.assertEqual(
            self.payloads()[retry_start:],
            [
                "960102010A",
                "71010201",
                "71010202",
                "71010203",
                "960102020C",
                "71010202",
                "71010203",
            ],
        )

    def test_ui_keeps_selection_and_shows_confirmed_values_on_completion(self):
        view, item = self.editing_view()
        details = view.details
        details.save_button.click()
        self.app.processEvents()
        self.assertIs(view.node_list.currentItem(), item)
        self.assertFalse(details.save_button.isEnabled())
        self.verified(1, 10)
        self.reply("9701020280")
        self.reply("9701020309")
        self.app.processEvents()
        self.assertIs(view.node_list.currentItem(), item)
        self.assertEqual(details.raw_values.item(1, 1).text(), "128")
        self.assertTrue(details.edit_button.isEnabled())
        self.assertIsNone(details.desired_configuration)
        self.assertIn("saved successfully", details.nv_result.text())

    def test_ui_failure_reports_requested_and_actual_without_automatic_discovery(self):
        view, _item = self.editing_view()
        details = view.details
        details.save_button.click()
        self.app.processEvents()
        self.reply("590102")
        self.reply("9701020106")
        self.app.processEvents()
        report = details.failure_report
        self.addCleanup(report.dialog.close)
        self.assertIn("readback was 6", report.dialog.message.text())
        self.assertTrue(report.dialog.retry_button.isEnabled())
        self.assertEqual(details.raw_values.item(0, 1).text(), "6")
        self.assertTrue(details.variables.isEnabled())
        self.assertIsNone(details.desired_configuration)
        self.assertEqual(self.payloads(), ["960102010A", "71010201"])
        # A later Restore owns a new request; the old NV report cannot retry it.
        self.service.restore.begin(258, node_backup(self.state))
        self.assertFalse(report.dialog.retry_button.isEnabled())
        self.assertIn("replaced this request", report.dialog.retry_status.text())

    def output_view(self):
        """Edit session with ordinary NV1 = 10 and MDF outputOnWrite NV3."""
        self.mdf = {
            "nodeVariables": [
                {
                    "type": "NodeVariableSlider",
                    "nodeVariableIndex": 3,
                    "displayTitle": "Servo",
                    "outputOnWrite": True,
                }
            ]
        }
        view, _item = self.editing_view()
        return view.details

    def test_output_nv_writes_immediately_and_save_writes_only_ordinary_nvs(self):
        self.consumer()
        details = self.output_view()
        details.raw_values.item(2, 1).setText("20")
        self.app.processEvents()
        self.assertEqual(self.payloads(), ["9601020314"])
        self.verified(3, 20)
        self.app.processEvents()
        # Driving the output does not refresh stored events.
        self.assertEqual(self.payloads(), ["9601020314", "71010203"])
        self.assertEqual(details.editing_session, "nvs")
        self.assertIn("NV 3 written", details.nv_result.text())
        details.save_button.click()
        self.app.processEvents()
        self.verified(1, 10)
        self.app.processEvents()
        self.answer_events()  # Normal Save still refreshes them.
        self.assertEqual(
            self.payloads()[:4], ["9601020314", "71010203", "960102010A", "71010201"]
        )
        self.assertIsNone(details.desired_configuration)
        self.assertIn("saved successfully", details.nv_result.text())
        self.assertEqual(self.state.nv_values, {1: 10, 2: 8, 3: 20})

    def test_cancel_restores_written_output_nv_and_discards_ordinary_edits(self):
        details = self.output_view()
        details.raw_values.item(2, 1).setText("20")
        self.app.processEvents()
        self.verified(3, 20)
        self.app.processEvents()
        details.cancel_button.click()
        self.app.processEvents()
        self.assertEqual(self.payloads()[-1], "9601020309")
        self.assertEqual(details.editing_session, "nvs")  # until verified
        self.verified(3, 9)
        self.app.processEvents()
        self.assertIsNone(details.desired_configuration)
        self.assertIn("Original NV 3 value restored", details.nv_result.text())
        self.assertEqual(self.state.nv_values, {1: 7, 2: 8, 3: 9})
        self.assertNotIn("960102010A", self.payloads())

    def test_test_button_rewrites_confirmed_value_in_view_and_edit_modes(self):
        details = self.output_view()
        details.cancel_button.click()  # No output NV changed: nothing to write.
        self.assertEqual(self.payloads(), [])
        details.mdf_values.set_definition(self.mdf)
        details.show_nv_values()
        (test,) = [
            button
            for button in details.mdf_values.findChildren(QPushButton)
            if button.text() == "Test"
        ]
        for start_editing in (False, True):
            if start_editing:
                details.start_editing()
            self.assertTrue(test.isEnabled())
            test.click()
            self.app.processEvents()
            self.assertEqual(self.payloads()[-1], "9601020309")
            self.verified(3, 9)
            self.app.processEvents()
            self.assertIn("NV 3 tested", details.nv_result.text())
        self.assertEqual(details.editing_session, "nvs")
        self.assertEqual(self.state.nv_values, {1: 7, 2: 8, 3: 9})

    def test_failed_output_write_is_reported_and_shows_actual_value(self):
        details = self.output_view()
        details.raw_values.item(2, 1).setText("20")
        self.app.processEvents()
        self.verified(3, 11)
        self.app.processEvents()
        self.assertIn("NV 3 could not be written", details.nv_result.text())
        self.assertNotIn("Partial Save", details.nv_result.text())
        self.assertIn("readback was 11", details.nv_result.text())
        self.assertEqual(details.editing_session, "nvs")
        self.assertEqual(details.desired_configuration["nvs"], [10, 8, 11])
        self.assertEqual(details.raw_values.item(2, 1).text(), "11")

    def test_failed_cancel_restore_is_reported(self):
        details = self.output_view()
        details.raw_values.item(2, 1).setText("20")
        self.app.processEvents()
        self.verified(3, 20)
        self.app.processEvents()
        details.cancel_button.click()
        self.app.processEvents()
        self.verified(3, 20)
        self.app.processEvents()
        self.assertIsNone(details.desired_configuration)
        self.assertIn(
            "Cancel could not restore the original NV 3 value",
            details.nv_result.text(),
        )
        self.assertEqual(self.state.nv_values[3], 20)

    def test_test_is_refused_during_events_editing(self):
        details = self.output_view()
        details.cancel_button.click()
        details.mdf_values.set_definition(self.mdf)
        details.show_nv_values()
        details.start_events_editing()
        (test,) = [
            button
            for button in details.mdf_values.findChildren(QPushButton)
            if button.text() == "Test"
        ]
        test.click()
        self.app.processEvents()
        self.assertEqual(self.payloads(), [])
        self.assertIn("Test is unavailable", details.nv_result.text())
        self.assertEqual(details.editing_session, "events")

    def test_disconnect_reports_output_nv_left_at_edited_value(self):
        details = self.output_view()
        details.raw_values.item(2, 1).setText("20")
        self.app.processEvents()
        self.verified(3, 20)
        self.app.processEvents()
        details.connected = False
        details.update_connection_details()
        self.assertIsNone(details.desired_configuration)
        self.assertIn(
            "NV 3 had already been written and still holds the edited value",
            details.nv_result.text(),
        )


if __name__ == "__main__":
    unittest.main()

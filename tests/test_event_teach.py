"""Adding consumed events through Events Edit/Save, and deleting them."""

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QListWidgetItem,
    QRadioButton,
    QSpinBox,
)
from test_nv_write import Connection

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.event_teach import TeachEventDialog, teach_targets
from workbench.layout_view import LayoutView
from workbench.node_backup_files import node_backup
from workbench.pnn import Pnn


class EventTeachTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        done = DiscoveryProgress.COMPLETE
        # A fully discovered legacy FLiM consumer without parameter 8, so the
        # standard teaching sequence is used.
        self.state = NodeState(
            Pnn(258, 13, 34, 5),
            parameters={5: 3, 6: 1},
            nv_values={1: 0},
            event_identities={1: (1, 2)},
            ev_values={1: {1: 5, 2: 6, 3: 7}},
            stored_event_count=1,
            parameter_progress=done,
            nv_progress=done,
            event_progress=done,
            ev_progress=done,
            can_id=2,
        )
        self.service.nodes[258] = self.state.identity
        self.service.node_states[258] = self.state
        self.saves = []
        self.service.event_save.finished.connect(lambda *a: self.saves.append(a))
        self.deletes = []
        self.service.event_save.delete_finished.connect(
            lambda *a: self.deletes.append(a)
        )
        self.addCleanup(lambda: self.service.close())

    def reply(self, payload):
        self.connection.frame_received.emit(f":SB040N{payload};".encode())

    def payloads(self):
        return [frame.decode().split("N")[1][:-1] for frame in self.connection.sent]

    def rediscover(self, events):
        """Answer RQEVN/NERD/REVAL with the given {(nn, en): [EVs]}."""
        self.reply(f"740102{len(events):02X}")
        for slot, (nn, en) in enumerate(events, 1):
            self.reply(f"F20102{nn:04X}{en:04X}{slot:02X}")
        for slot, values in enumerate(events.values(), 1):
            for ev, value in enumerate(values, 1):
                self.reply(f"B50102{slot:02X}{ev:02X}{value:02X}")
        self.app.processEvents()

    def save_new_event(self, values):
        """Events Save of the live configuration plus one new event 0:1000."""
        original = node_backup(self.state)
        desired = node_backup(self.state)
        desired["events"].append(
            {"nodeNumber": 0, "eventNumber": 1000, "eventVariables": values}
        )
        self.service.event_save.begin(258, desired, original=original)
        self.app.processEvents()

    # New events: the ordinary Events Save teaches and verifies them.

    def test_new_event_is_taught_nonzero_first_and_verified_by_rediscovery(self):
        self.save_new_event([0, 9])
        # Nonzero EV2 creates the event before the explicit zero EV1.
        self.assertEqual(self.payloads(), ["530102", "D2000003E80209"])
        self.reply("590102")
        self.reply("D3000003E80209")
        self.assertEqual(self.payloads()[-1], "D2000003E80100")
        self.reply("590102")
        self.reply("D3000003E80100")
        self.assertEqual(self.payloads()[-2:], ["540102", "580102"])
        # Unconfigured EV3 keeps the node's own default (here 4).
        self.rediscover({(1, 2): [5, 6, 7], (0, 1000): [0, 9, 4]})
        self.assertTrue(self.saves[-1][1], self.saves)
        self.assertIn((0, 1000), self.state.event_identities.values())

    def test_new_event_without_nonzero_ev_is_rejected_without_sending(self):
        for values in ([], [0], [0, None, 0]):
            with self.assertRaisesRegex(ValueError, "needs at least one nonzero EV"):
                self.save_new_event(values)
        self.assertEqual(self.connection.sent, [])
        self.assertFalse(self.service.writes_busy())

    def test_new_event_fails_when_rediscovery_does_not_show_it(self):
        self.save_new_event([3])
        self.reply("590102")
        self.reply("D3000003E80103")
        self.rediscover({(1, 2): [5, 6, 7]})
        self.assertFalse(self.saves[-1][1])

    def test_acknowledged_new_event_rejected_on_readback_fails_and_exits(self):
        # Hardware case: WRACK, then REQEV (still in learn mode) -> CMDERR 7.
        self.save_new_event([1])
        self.reply("590102")
        self.assertEqual(self.payloads()[-1], "B2000003E801")
        self.reply("6F010207")
        self.app.processEvents()
        self.assertFalse(self.saves[-1][1])
        self.assertEqual(self.payloads()[-1], "540102")
        self.assertNotIn((0, 1000), self.state.event_identities.values())

    def test_disconnect_while_teaching_new_event_reports_failure(self):
        self.save_new_event([1])
        self.reply("590102")
        self.service.close()
        self.assertFalse(self.saves[-1][1])
        self.assertIn("Connection ended", self.saves[-1][2])
        self.assertEqual(self.payloads()[-1], "540102")
        self.assertTrue(self.service.ev_write.blocked)
        # Avoid closing the detached service twice in cleanup.
        self.service = CbusService(self.connection, 126)

    def test_readback_timeout_fails_exits_learn_mode_and_keeps_safety_block(self):
        with patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 10):
            self.save_new_event([1])
            self.reply("590102")
            QTest.qWait(30)
        self.assertFalse(self.saves[-1][1])
        self.assertIn("Timed out waiting for EV readback", self.saves[-1][2])
        self.assertIn("540102", self.payloads())
        self.assertNotIn("580102", self.payloads())  # No rediscovery after doubt.
        with self.assertRaisesRegex(ValueError, "Protocol safety"):
            self.service.event_save.delete_event(258, (1, 2))

    # Delete Event: immediate, verified by rediscovered absence.

    def test_delete_is_verified_by_rediscovered_absence(self):
        self.service.event_save.delete_event(258, (1, 2))
        self.assertEqual(self.payloads()[:3], ["530102", "9500010002", "540102"])
        self.rediscover({})
        self.assertTrue(self.deletes[-1][1], self.deletes)
        self.assertIn("Event 1:2 deleted from node 258", self.deletes[-1][2])
        self.assertEqual(self.state.event_identities, {})
        self.assertEqual(self.saves, [])  # Not reported as an editor Save.

    def test_delete_fails_when_event_is_still_present(self):
        self.service.event_save.delete_event(258, (1, 2))
        self.rediscover({(1, 2): [5, 6, 7]})
        self.assertFalse(self.deletes[-1][1])
        self.assertIn("Could not delete event 1:2", self.deletes[-1][2])

    def test_delete_requires_consumed_event_and_complete_discovery(self):
        with self.assertRaisesRegex(ValueError, "does not consume"):
            self.service.event_save.delete_event(258, (0, 9))
        self.state.ev_values[1].pop(2)  # One EV position still unread.
        with self.assertRaisesRegex(ValueError, "Complete discovery"):
            self.service.event_save.delete_event(258, (1, 2))
        self.assertEqual(self.connection.sent, [])

    # Dialogs and editor workflow.

    def test_teach_to_node_lists_only_editable_online_nodes(self):
        self.service.presence[258] = True
        producer = NodeState(Pnn(300, 165, 2, 4), can_id=3)
        incomplete = NodeState(Pnn(301, 13, 34, 5), can_id=4)  # Not discovered.
        for state in (producer, incomplete):
            self.service.nodes[state.identity.node_number] = state.identity
            self.service.node_states[state.identity.node_number] = state
            self.service.presence[state.identity.node_number] = True
        self.assertEqual([t[0] for t in teach_targets(self.service, None)], [258])
        self.service.presence[258] = False
        self.assertEqual(teach_targets(self.service, None), [])

    def test_teach_to_node_dialog_chooses_only_the_target(self):
        self.service.presence[258] = True
        targets = teach_targets(self.service, None)
        dialog = TeachEventDialog(None, "Teach to Node", (1, 2), targets=targets)
        self.assertEqual(dialog.findChildren(QSpinBox), [])
        self.assertEqual(dialog.findChildren(QRadioButton), [])
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(ok.isEnabled())  # Node 258 already consumes 1:2.
        dialog.deleteLater()
        dialog = TeachEventDialog(None, "Teach to Node", (0, 7), targets=targets)
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertTrue(ok.isEnabled())
        self.assertEqual((dialog.identity(), dialog.target_number()), ((0, 7), 258))
        dialog.deleteLater()

    def test_new_event_dialog_edits_long_and_short_identities(self):
        dialog = TeachEventDialog(None, "New Event", consumed={(1, 2)})
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        dialog.node_number.setValue(1)
        dialog.event_number.setValue(2)
        self.assertFalse(ok.isEnabled())
        dialog.event_number.setValue(3)
        self.assertEqual(dialog.identity(), (1, 3))
        dialog.short_radio.setChecked(True)
        self.assertEqual(dialog.identity(), (0, 3))
        self.assertTrue(ok.isEnabled())
        dialog.deleteLater()

    def layout_view(self):
        """A connected layout showing node 258 on its Events tab."""
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        node_view = view.node_view
        details = node_view.details
        details.connected = True
        details.cbus_service = self.service
        node_view.state_lookup = lambda number: self.service.node_states.get(number)
        self.service.node_state_updated.connect(node_view.refresh_state)
        self.service.event_save.finished.connect(details.finish_restore)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.state.identity)
        node_view.node_list.addItem(item)
        view.tabs.setCurrentWidget(view.layout_events)
        return view

    def pending_row(self, details):
        tree = details.node_events.consumed_table
        rows = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        return next(
            (r for r in rows if r.data(0, Qt.ItemDataRole.UserRole) == (0, 1000)),
            None,
        )

    def test_teach_to_node_opens_target_editor_and_cancel_discards(self):
        view = self.layout_view()
        details = view.node_view.details
        view.layout_events.teach_requested.emit(258, (0, 1000))
        self.assertIs(view.tabs.currentWidget(), view.node_view)
        self.assertIs(details.tabs.currentWidget(), details.consumed_events_page)
        self.assertEqual(details.editing_session, "events")
        row = self.pending_row(details)
        self.assertIsNotNone(row)
        self.assertTrue(row.isExpanded())
        self.assertIs(details.node_events.consumed_table.currentItem(), row)
        details.events_cancel_button.click()
        self.assertIsNone(self.pending_row(details))
        self.assertIsNone(details.desired_configuration)
        self.assertEqual(self.connection.sent, [])

    def test_saving_new_event_without_nonzero_ev_keeps_editing(self):
        view = self.layout_view()
        details = view.node_view.details
        view.node_view.node_list.setCurrentRow(0)
        details.start_new_event(258, (0, 1000))
        # Only the new event's EV1 starts at 0; later EVs stay undefined.
        new = details.desired_configuration["events"][-1]
        self.assertEqual(new["eventVariables"], [0])
        row = self.pending_row(details)
        self.assertEqual([row.child(i).text(1) for i in range(3)], ["0", "", ""])
        self.assertEqual(
            details.desired_configuration["events"][0]["eventVariables"], [5, 6, 7]
        )
        details.events_save_button.click()
        self.assertIn("needs at least one nonzero EV", details.events_result.text())
        self.assertEqual(details.editing_session, "events")
        self.assertIsNotNone(self.pending_row(details))
        self.assertEqual(self.connection.sent, [])

    def test_saving_configured_new_event_teaches_it_and_shows_it(self):
        view = self.layout_view()
        details = view.node_view.details
        view.node_view.node_list.setCurrentRow(0)
        details.start_new_event(258, (0, 1000))
        self.pending_row(details).child(1).setText(1, "9")  # Raw EV2 row.
        details.events_save_button.click()
        self.app.processEvents()
        self.assertEqual(self.payloads()[:2], ["530102", "D2000003E80209"])
        self.reply("590102")
        self.reply("D3000003E80209")
        # The initial EV1 = 0 is taught after the nonzero EV created the event.
        self.assertEqual(self.payloads()[-1], "D2000003E80100")
        self.reply("590102")
        self.reply("D3000003E80100")
        self.rediscover({(1, 2): [5, 6, 7], (0, 1000): [0, 9, 0]})
        self.assertTrue(self.saves[-1][1], self.saves)
        self.assertIsNone(details.desired_configuration)
        self.assertIn("saved", details.events_result.text())
        self.assertIsNotNone(self.pending_row(details))  # Now a live row.


if __name__ == "__main__":
    unittest.main()

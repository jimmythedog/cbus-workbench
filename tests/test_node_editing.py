"""One complete backup-format working copy across both configuration tabs."""

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidgetItem
from test_nv_write import Connection

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.node_backup_files import load_node_backup, node_backup, validate_backup
from workbench.node_details import NodeDetails
from workbench.pnn import Pnn


class NodeEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        self.addCleanup(self.service.close)
        done = DiscoveryProgress.COMPLETE
        self.state = NodeState(
            Pnn(258, 13, 34, 5),
            parameters={5: 4, 6: 2},
            nv_values={1: 7, 2: 8},
            stored_event_count=2,
            event_identities={9: (0, 1000), 2: (259, 45)},
            ev_values={
                9: {1: 3, 2: 12, 3: 0, 4: None},
                2: {1: 5, 2: None, 3: None, 4: None},
            },
            parameter_progress=done,
            nv_progress=done,
            event_progress=done,
            ev_progress=done,
            can_id=2,
        )
        self.service.node_states[258] = self.state
        self.service.nodes[258] = self.state.identity
        self.details = NodeDetails({})
        self.addCleanup(self.details.close)
        self.details.connected = True
        self.details.cbus_service = self.service
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.state.identity)
        self.details.show_node(item)
        self.details.show_live_state(self.state)

    def event(self, address="0:1000"):
        tree = self.details.node_events.consumed_table
        return next(
            tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).text(0) == address
        )

    def test_combined_edit_matches_yaml_loaded_configuration(self):
        self.details.edit_button.click()
        self.details.raw_values.item(0, 1).setText("99")
        self.event().child(0).setText(1, "4")
        self.event().child(1).setText(1, "")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "node.yaml"
            path.write_text(
                "format_version: 1\ncomplete: true\npartOfLayoutBackup: false\n"
                "node: 258\nnvs: [99, 8]\nevents:\n"
                "  - nodeNumber: 0\n    eventNumber: 1000\n"
                "    eventVariables: [4, null, 0]\n"
                "  - nodeNumber: 259\n    eventNumber: 45\n"
                "    eventVariables: [5]\n",
                encoding="utf-8",
            )
            loaded = load_node_backup(path)
        validate_backup(self.details.desired_configuration)
        self.assertEqual(self.details.desired_configuration, loaded)
        values = self.details.desired_configuration["events"][0]["eventVariables"]
        self.assertIsNone(values[1])
        self.assertIs(type(values[2]), int)

    def test_either_edit_and_cancel_button_controls_both_tabs(self):
        details = self.details
        original = node_backup(self.state)
        for edit, cancel in (
            (details.edit_button, details.events_cancel_button),
            (details.events_edit_button, details.cancel_button),
        ):
            with self.subTest(edit=edit):
                edit.click()
                for page in (details.variables_page, details.events_page):
                    self.assertTrue(
                        details.tabs.isTabEnabled(details.tabs.indexOf(page))
                    )
                    details.tabs.setCurrentWidget(page)
                details.raw_values.item(0, 1).setText("99")
                self.event().child(1).setText(1, "13")
                expected = deepcopy(original)
                expected["nvs"][0] = 99
                expected["events"][0]["eventVariables"][1] = 13
                self.assertEqual(details.desired_configuration, expected)
                self.assertEqual(details.original_configuration, original)
                details.show_live_state(self.state)
                self.assertEqual(details.desired_configuration, expected)
                self.assertEqual(details.raw_values.item(0, 1).text(), "99")
                self.assertEqual(self.event().child(1).text(1), "13")
                validate_backup(details.desired_configuration)
                self.assertEqual(node_backup(self.state), original)
                cancel.click()
                self.assertIsNone(details.desired_configuration)
                self.assertIsNone(details.original_configuration)
                self.assertEqual(details.raw_values.item(0, 1).text(), "7")
                self.assertEqual(self.event().child(1).text(1), "12")
                self.assertEqual(details.buttons.currentIndex(), 0)
                self.assertEqual(details.events_buttons.currentIndex(), 0)
                self.assertEqual(self.connection.sent, [])

    def test_clearing_and_zero_preserve_backup_schema_and_other_configuration(self):
        self.details.events_edit_button.click()
        expected = node_backup(self.state)
        self.event().child(1).setText(1, "")
        expected["events"][0]["eventVariables"][1] = None
        self.assertEqual(self.details.desired_configuration, expected)
        self.event().child(3).setText(1, "0")
        expected["events"][0]["eventVariables"].append(0)
        self.assertEqual(self.details.desired_configuration, expected)
        self.event().child(3).setText(1, "")
        expected["events"][0]["eventVariables"].pop()
        self.assertEqual(self.details.desired_configuration, expected)
        validate_backup(self.details.desired_configuration)

    def test_blank_cell_editor_does_not_invent_zero(self):
        details = self.details
        details.show()
        details.events_edit_button.click()
        details.tabs.setCurrentWidget(details.events_page)
        event = self.event()
        event.setExpanded(True)
        tree = details.node_events.consumed_table
        original = deepcopy(details.desired_configuration)
        tree.editItem(event.child(3), 1)
        self.app.processEvents()
        editor = next(c for c in tree.findChildren(QLineEdit) if c.isVisible())
        self.assertEqual(editor.text(), "")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(1)
        self.assertEqual(details.desired_configuration, original)

    def test_incomplete_discovery_prevents_both_edit_entry_points(self):
        for change in ("progress", "unknown_ev", "membership"):
            with self.subTest(change=change):
                self.state.ev_progress = DiscoveryProgress.COMPLETE
                self.state.ev_values[9][4] = None
                self.state.stored_event_count = 2
                if change == "progress":
                    self.state.nv_progress = DiscoveryProgress.INCOMPLETE
                elif change == "unknown_ev":
                    self.state.nv_progress = DiscoveryProgress.COMPLETE
                    del self.state.ev_values[9][4]
                else:
                    self.state.stored_event_count = 3
                self.details.show_live_state(self.state)
                self.assertFalse(self.details.edit_button.isEnabled())
                self.assertFalse(self.details.events_edit_button.isEnabled())
                self.details.start_editing()
                self.details.start_events_editing()
                self.assertIsNone(self.details.desired_configuration)
                self.assertEqual(self.connection.sent, [])

    def test_disconnect_discards_the_entire_session(self):
        self.details.events_edit_button.click()
        self.details.raw_values.item(0, 1).setText("99")
        self.event().child(1).setText(1, "13")
        self.details.connected = False
        self.details.update_connection_details()
        self.assertIsNone(self.details.desired_configuration)
        self.assertEqual(self.event().child(1).text(1), "12")
        self.assertFalse(self.details.edit_button.isEnabled())
        self.assertFalse(self.details.events_edit_button.isEnabled())
        self.assertEqual(self.connection.sent, [])

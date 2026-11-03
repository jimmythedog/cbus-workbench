"""The details form keeps node display and name editing in the existing tab."""

import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem

from workbench.cbus_service import NodeState
from workbench.node import Node
from workbench.node_details import NodeDetails
from workbench.node_details_form import NodeDetailsForm
from workbench.pnn import Pnn


class NodeDetailsFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.details = NodeDetails({})
        self.addCleanup(self.details.close)

    def select(self, node):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, node)
        self.details.show_node(item)
        return item

    def test_form_is_the_details_page_and_labels_remain_accessible(self):
        details = self.details
        self.assertIsInstance(details.details_page, NodeDetailsForm)
        self.assertIs(details.tabs.widget(0), details.details_page)
        self.assertIs(details.node_number, details.details_page.node_number)
        self.assertIs(details.node_name, details.details_page.node_name)
        self.assertEqual(details.node_number.text(), "-")
        self.assertEqual(details.summary.title(), "Node details")

    def test_hide_zero_evs_filters_configured_events_without_changing_values(self):
        node = Node(42, "Configured", 12, "1a", False)
        node.consumed_events = {"42:10": "Signal"}
        node.ev_values = {"42:10": {1: 0, 2: 7}}
        self.select(node)
        events = self.details.node_events
        event = events.consumed_table.topLevelItem(0)
        event.setExpanded(True)

        events.hide_zero_evs.setChecked(True)
        self.assertFalse(event.isHidden())
        self.assertTrue(event.isExpanded())
        self.assertTrue(event.child(0).isHidden())
        self.assertFalse(event.child(1).isHidden())

        events.hide_zero_evs.setChecked(False)
        self.assertFalse(event.child(0).isHidden())
        self.assertEqual(node.ev_values["42:10"], {1: 0, 2: 7})

    def test_details_stay_grouped_at_top_when_switching_node_types(self):
        details = self.details
        details.resize(850, 950)
        details.show()

        for node in (
            Node(42, "Configured", 12, "1a", False),
            Pnn(258, 13, 34, 0x03),
            Node(43, "Other", 13, "1b", False),
        ):
            with self.subTest(node=node):
                self.select(node)
                self.app.processEvents()
                name_bottom = details.node_name_stack.mapTo(
                    details.details_page, details.node_name_stack.rect().bottomLeft()
                ).y()
                number_top = details.node_number.mapTo(
                    details.details_page, details.node_number.rect().topLeft()
                ).y()
                self.assertLess(number_top - name_bottom, 20)

        details.start_name_editing()
        self.app.processEvents()
        editor_bottom = details.node_name_editor.mapTo(
            details.details_page, details.node_name_editor.rect().bottomLeft()
        ).y()
        number_top = details.node_number.mapTo(
            details.details_page, details.node_number.rect().topLeft()
        ).y()
        self.assertLess(number_top - editor_bottom, 20)
        details.cancel_name_editing()
        self.app.processEvents()

        button_corner = details.details_edit_button.mapTo(
            details, details.details_edit_button.rect().bottomRight()
        )
        self.assertLess(details.width() - button_corner.x(), 50)
        self.assertLess(details.height() - button_corner.y(), 50)

    def test_configured_name_editing_updates_header_and_restores_tabs(self):
        node = Node(42, "Test module", 12, "1a", False)
        item = self.select(node)
        details = self.details
        self.assertEqual(details.node_number.text(), "42")
        self.assertEqual(details.summary.title(), "Node 42 — Test module")

        details.start_name_editing()
        self.assertIs(details.node_name_stack.currentWidget(), details.node_name_editor)
        for page in (details.variables_page, details.events_page, details.node_backups):
            self.assertFalse(details.tabs.isTabEnabled(details.tabs.indexOf(page)))

        details.node_name_editor.setText("  Garden  ")
        details.save_name_editing()
        self.assertEqual(node.name, "Garden")
        self.assertEqual(details.node_name.text(), "Garden")
        self.assertEqual(details.summary.title(), "Node 42 — Test module — Garden")
        self.assertEqual(item.text(), "42 - Test module — Garden")
        for page in (details.variables_page, details.events_page, details.node_backups):
            self.assertTrue(details.tabs.isTabEnabled(details.tabs.indexOf(page)))

    def test_switching_to_live_identity_and_no_node_updates_tabs_and_header(self):
        details = self.details
        self.select(Node(42, "Test module", 12, "1a", False))
        self.select(Pnn(258, 13, 34, 0x03))
        self.assertEqual(details.node_number.text(), "258")
        self.assertEqual(details.summary.title(), "Node 258 — 34")
        self.assertTrue(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.variables_page))
        )
        self.assertIs(details.variables.currentWidget(), details.raw_values)
        self.assertIs(details.tabs.currentWidget(), details.details_page)

        details.show_node(None)
        self.assertEqual(details.node_number.text(), "-")
        self.assertEqual(details.summary.title(), "Node details")
        self.assertTrue(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.variables_page))
        )

    def test_configured_raw_values_remain_editable(self):
        node = Node(42, "Test module", 12, "1a", False, nv_values={1: 7})
        self.select(node)
        details = self.details

        details.start_editing()
        self.assertNotEqual(
            details.raw_values.editTriggers(),
            details.raw_values.EditTrigger.NoEditTriggers,
        )
        details.raw_values.item(0, 1).setText("0")
        details.save_editing()

        self.assertEqual(node.nv_values, {1: 0})
        self.assertEqual(details.raw_values.item(0, 1).text(), "0")

    def test_live_configured_live_transition_restores_value_editability(self):
        details = self.details
        identity = Pnn(258, 13, 34, 0x03)
        state = NodeState(identity, parameters={6: 1}, nv_values={1: 0})
        configured = Node(42, "Test module", 12, "1a", False, nv_values={1: 7})

        self.select(identity)
        details.show_live_state(state)
        table = details.raw_values
        self.assertEqual(table.item(0, 1).text(), "0")
        self.assertFalse(table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(table.editTriggers(), table.EditTrigger.NoEditTriggers)

        self.select(configured)
        self.assertEqual(table.item(0, 1).text(), "7")
        details.start_editing()
        self.assertTrue(table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertNotEqual(table.editTriggers(), table.EditTrigger.NoEditTriggers)
        details.cancel_editing()

        self.select(identity)
        details.show_live_state(state)
        self.assertEqual(table.item(0, 1).text(), "0")
        self.assertFalse(table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(table.editTriggers(), table.EditTrigger.NoEditTriggers)

    def test_available_tabs_survive_configured_node_changes(self):
        details = self.details
        first = Node(42, "First", 12, "1a", False)
        second = Node(43, "Second", 13, "1b", False)
        self.select(first)

        for page in (
            details.details_page,
            details.variables_page,
            details.events_page,
            details.node_backups,
        ):
            with self.subTest(tab=details.tabs.tabText(details.tabs.indexOf(page))):
                details.tabs.setCurrentWidget(page)
                self.select(second)
                self.assertIs(details.tabs.currentWidget(), page)
                self.select(first)

    def test_node_variables_tab_survives_live_and_configured_changes(self):
        details = self.details
        self.select(Node(42, "Configured", 12, "1a", False))
        details.tabs.setCurrentWidget(details.variables_page)

        self.select(Pnn(258, 13, 34, 0x03))
        self.assertIs(details.tabs.currentWidget(), details.variables_page)
        self.select(Pnn(259, 13, 35, 0x03))
        self.assertIs(details.tabs.currentWidget(), details.variables_page)
        self.select(Node(43, "Other", 13, "1b", False))
        self.assertIs(details.tabs.currentWidget(), details.variables_page)

    def test_unavailable_live_backup_tab_falls_back_to_node_details(self):
        details = self.details
        configured = Node(42, "Configured", 12, "1a", False)
        live = Pnn(258, 13, 34, 0x03)
        self.select(configured)

        self.assertTrue(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.events_page))
        )

        details.tabs.setCurrentWidget(details.node_backups)
        self.select(live)
        self.assertFalse(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.node_backups))
        )
        self.assertIs(details.tabs.currentWidget(), details.details_page)
        self.select(configured)

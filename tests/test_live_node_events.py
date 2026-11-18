"""Visible contracts for the live node event tabs."""

import os
import unittest
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem

from workbench.cbus_service import NodeState
from workbench.layout_view import LayoutView
from workbench.node_view import NodeView
from workbench.pnn import Pnn


class LiveNodeEventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = NodeView({258: {45: {"description": "Signal cleared"}}})
        self.addCleanup(self.view.close)
        self.states = {}
        self.view.state_lookup = self.states.get

    def test_full_discovery_restores_selection_and_displays_final_state(self):
        for status in ("Configuration ready", "Discovery incomplete"):
            with self.subTest(status=status):
                node = Pnn(258, 13, 34, 0x03)
                self.states[258] = NodeState(node, parameters={5: 1})
                other = Pnn(100, 13, 34, 0x03)
                self.states[100] = NodeState(other)
                self.view.show_identity(other)
                self.view.show_identity(node)
                self.view.node_list.setCurrentRow(1)
                self.view.begin_discovery()
                self.assertIsNone(self.view.node_list.currentItem())
                self.assertFalse(self.view.node_list.isEnabled())
                tree = self.view.details.node_events.consumed_table
                for value in (10, 20, 30):
                    self.states[258].event_identities[1] = (258, value)
                    self.view.show_identity(node)
                    self.view.refresh_state(258)
                    self.assertEqual(self.view.details.node, node)
                    self.assertEqual(tree.topLevelItemCount(), 0)
                self.view.finish_discovery(status)
                self.assertTrue(self.view.node_list.isEnabled())
                self.assertEqual(self.view.details.node, node)
                self.assertEqual(tree.topLevelItem(0).text(0), "258:30")

    def test_full_discovery_defers_first_selection_and_falls_back_if_missing(self):
        for remembered in (None, 999):
            with self.subTest(remembered=remembered):
                self.view.clear_identities()
                if remembered is not None:
                    # A saved offline node may not respond to discovery.
                    item = QListWidgetItem("999 (offline)")
                    item.setData(Qt.ItemDataRole.UserRole, remembered)
                    self.view.node_list.addItem(item)
                    self.view.node_list.setCurrentItem(item)
                self.view.state_lookup = self.states.get
                self.view.begin_discovery()
                node = Pnn(258, 13, 34, 0x03)
                self.states[258] = NodeState(node)
                self.view.show_identity(node)
                self.view.finish_discovery("Discovering configuration…")
                self.assertIsNone(self.view.node_list.currentItem())
                self.view.finish_discovery("Configuration ready")
                self.assertEqual(self.view.details.node, node)

    def test_disconnect_during_discovery_releases_list_without_live_selection(self):
        node = Pnn(258, 13, 34, 0x03)
        self.states[258] = NodeState(node)
        self.view.show_identity(node)
        self.view.begin_discovery()
        self.view.finish_discovery("Disconnected")
        self.view.clear_identities()
        self.states.clear()
        self.assertTrue(self.view.node_list.isEnabled())
        self.assertIsNone(self.view.node_list.currentItem())
        self.assertIsNone(self.view.details.node)
        # Subsequent use retains normal first-node selection.
        self.view.state_lookup = self.states.get
        self.states[258] = NodeState(node)
        self.view.show_identity(node)
        self.assertEqual(self.view.details.node, node)

    def test_consecutive_discovery_statuses_preserve_selection_and_editing_lock(self):
        node = Pnn(258, 13, 34, 0x03)
        self.states[258] = NodeState(node)
        self.view.show_identity(node)
        self.view.details.editing_changed.emit(True)
        for _ in range(2):
            self.view.discovery_status_changed("Discovering configuration…")
            self.view.discovery_status_changed("Discovering configuration…")
            self.view.details.editing_changed.emit(False)
            self.assertFalse(self.view.node_list.isEnabled())
            self.view.details.editing_changed.emit(True)
            self.view.discovery_status_changed("Configuration ready")
            self.assertFalse(self.view.node_list.isEnabled())
            self.assertEqual(self.view.details.node, node)
            self.assertEqual(
                self.view.node_list.currentItem().data(Qt.ItemDataRole.UserRole), node
            )
        self.view.details.editing_changed.emit(False)
        self.assertTrue(self.view.node_list.isEnabled())

    def test_live_event_tabs_use_full_width_and_preserve_event_state(self):
        node = Pnn(258, 13, 34, 0x03)
        self.states[258] = NodeState(
            node,
            parameters={5: 2},
            event_identities={2: (258, 45), 1: (0, 44)},
            ev_values={1: {1: 0, 2: 7}, 2: {1: 8, 2: 0}},
        )
        self.view.show_identity(node)
        details = self.view.details
        events = details.node_events
        details.tabs.setCurrentWidget(events)

        self.assertEqual(
            [details.tabs.tabText(i) for i in range(details.tabs.count())],
            [
                "Node Details",
                "Node Variables",
                "Consumed Events",
                "Produced Events",
                "Backups",
            ],
        )
        self.view.resize(1200, 700)
        self.view.show()
        self.app.processEvents()
        tree = events.consumed_table
        tree.topLevelItem(0).setExpanded(True)
        tree.setCurrentItem(tree.topLevelItem(0).child(1))
        self.assertGreater(tree.width(), details.tabs.width() * 0.9)
        details.tabs.setCurrentWidget(details.produced_events_page)
        self.app.processEvents()
        self.assertGreater(events.produced_table.width(), details.tabs.width() * 0.9)
        self.assertFalse(details.events_edit_button.isVisible())
        events.produced_table.setCurrentItem(events.produced_table.topLevelItem(0))
        details.tabs.setCurrentWidget(details.consumed_events_page)
        self.app.processEvents()
        self.assertTrue(tree.topLevelItem(0).isExpanded())
        self.assertIs(tree.currentItem(), tree.topLevelItem(0).child(1))
        self.assertTrue(events.produced_table.topLevelItem(0).isSelected())
        self.assertTrue(details.events_edit_button.isVisible())
        details.tabs.setCurrentWidget(details.node_backups)
        self.assertTrue(details.backup_buttons["New"].isVisible())
        details.tabs.setCurrentWidget(details.consumed_events_page)
        self.assertEqual(events.produced_table.topLevelItem(0).text(0), "258:45")
        self.assertEqual(
            events.produced_table.topLevelItem(0).text(1), "Signal cleared"
        )
        first = events.consumed_table.topLevelItem(0)
        second = events.consumed_table.topLevelItem(1)
        self.assertEqual((first.text(0), first.text(1)), ("0:44", ""))
        self.assertEqual((second.text(0), second.text(1)), ("258:45", "Signal cleared"))
        self.assertEqual(
            [(first.child(row).text(0), first.child(row).text(1)) for row in range(2)],
            [("EV 1", "0"), ("EV 2", "7")],
        )
        self.assertEqual(
            [
                (second.child(row).text(0), second.child(row).text(1))
                for row in range(2)
            ],
            [("EV 1", "8"), ("EV 2", "0")],
        )

    def test_consumed_events_sort_numerically_and_keep_evs_when_editing(self):
        node = Pnn(258, 13, 34, 0x03)
        identities = {1: (10, 1), 4: (2, 10), 7: (0, 100), 9: (2, 2)}
        values = {1: {1: 11}, 4: {1: 44}, 7: {1: 77}, 9: {1: 99}}
        state = NodeState(
            node,
            parameters={5: 1},
            event_identities=deepcopy(identities),
            ev_values=deepcopy(values),
        )
        self.states[258] = state
        self.view.details.node_events.events.update({2: {10: {"description": "Route"}}})
        self.view.show_identity(node)
        events = self.view.details.node_events
        tree = events.consumed_table
        self.assertEqual(
            [
                (
                    tree.topLevelItem(i).text(0),
                    tree.topLevelItem(i).text(1),
                    tree.topLevelItem(i).child(0).text(1),
                )
                for i in range(4)
            ],
            [
                ("0:100", "", "77"),
                ("2:2", "", "99"),
                ("2:10", "Route", "44"),
                ("10:1", "", "11"),
            ],
        )
        desired = {
            "nvs": [],
            "events": [
                {
                    "nodeNumber": nn,
                    "eventNumber": en,
                    "eventVariables": [values[slot][1]],
                }
                for slot, (nn, en) in identities.items()
            ],
        }
        events.begin_configuration_edit(desired)
        tree.topLevelItem(2).child(0).setText(1, "45")
        self.assertEqual(
            [event["eventVariables"] for event in desired["events"]],
            [[11], [45], [77], [99]],
        )
        self.assertEqual(state.event_identities, identities)
        self.assertEqual(state.ev_values, values)

    def test_discovery_refresh_and_node_change_replace_visible_events(self):
        first = Pnn(258, 13, 34, 0x03)
        second = Pnn(259, 13, 35, 0x03)
        self.states[258] = NodeState(first, parameters={5: 1})
        self.states[259] = NodeState(
            second, parameters={5: 1}, event_identities={3: (259, 20)}
        )
        self.view.show_identity(first)
        self.view.show_identity(second)
        tree = self.view.details.node_events.consumed_table
        self.assertEqual(tree.topLevelItemCount(), 0)

        self.states[258].event_identities[1] = (258, 10)
        self.view.refresh_state(258)
        self.assertEqual(tree.topLevelItem(0).text(0), "258:10")

        self.states[258].ev_values[1] = {1: 9}
        self.view.refresh_state(258)
        self.assertEqual(tree.topLevelItem(0).child(0).text(1), "9")

        self.view.node_list.setCurrentRow(1)
        self.assertEqual(tree.topLevelItemCount(), 1)
        self.assertEqual(tree.topLevelItem(0).text(0), "259:20")
        self.view.node_list.setCurrentRow(0)
        self.assertEqual(tree.topLevelItem(0).text(0), "258:10")

        self.view.clear_identities()
        self.assertEqual(tree.topLevelItemCount(), 0)

    def test_returning_from_layout_events_keeps_selected_live_events(self):
        layout = LayoutView(empty=True)
        self.addCleanup(layout.close)
        node = Pnn(258, 13, 34, 0x03)
        state = NodeState(node, event_identities={1: (258, 10)})
        layout.node_view.state_lookup = lambda _number: state
        layout.node_view.show_identity(node)

        layout.tabs.setCurrentWidget(layout.layout_events)
        layout.tabs.setCurrentWidget(layout.node_view)

        tree = layout.node_view.details.node_events.consumed_table
        self.assertEqual(tree.topLevelItem(0).text(0), "258:10")

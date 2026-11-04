"""Visible contracts for the live node Events tab."""

import os
import unittest

from PySide6.QtWidgets import QApplication

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
        self.view.state_lookup = self.states.__getitem__

    def test_live_events_use_original_panels_and_expand_to_matching_evs(self):
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

        self.assertEqual(events.widget(0).title(), "Known produced events")
        self.assertEqual(events.widget(1).title(), "Consumed events")
        self.assertEqual(events.produced_table.item(0, 0).text(), "258:45")
        self.assertEqual(events.produced_table.item(0, 1).text(), "Signal cleared")
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

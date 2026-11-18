"""Event dependencies (#87): configured consumers shown below event rows."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel

from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.layout_view import LayoutView
from workbench.mdfs import MdfRepository
from workbench.node_metadata import save_metadata
from workbench.observed_events import EventIdentity, ObservedEvents
from workbench.pnn import Pnn

COMPLETE = DiscoveryProgress.COMPLETE


class Connection(QObject):
    frame_received = Signal(bytes)

    def __init__(self):
        super().__init__()
        self.layout_name = "test"
        self.state = "Connected"
        self.sent = []

    def send(self, frame):
        self.sent.append(frame)


def consumer(number, events, *, ev_count=2, progress=COMPLETE, flags=0x01):
    """A live node whose consumed events were read; events maps identity -> EVs."""
    return NodeState(
        Pnn(number, 165, 32, flags),
        parameters={1: 165, 3: 32, 5: ev_count},
        event_identities={slot: identity for slot, identity in enumerate(events, 1)},
        ev_values={slot: evs for slot, evs in enumerate(events.values(), 1)},
        event_progress=progress,
        ev_progress=progress,
    )


def rows(item):
    """Child rows as text, with consumer EVs nested: comparable across views."""
    return [
        (child.text(0), child.text(1), [(ev.text(0), ev.text(1)) for ev in children])
        for child in (item.child(i) for i in range(item.childCount()))
        for children in [[child.child(j) for j in range(child.childCount())]]
    ]


def presentation(tree, event):
    """What an event's visible EV rows and their MDF control rows show."""
    shown = []
    for ev in (event.child(i) for i in range(event.childCount())):
        if ev.isHidden():
            continue
        form = tree.itemWidget(ev, 1)
        controls = []
        for row in (ev.child(i) for i in range(ev.childCount())):
            control = tree.itemWidget(row, 1).findChild(QComboBox) or tree.itemWidget(
                row, 1
            ).findChild(QCheckBox)
            value = (
                control.currentText()
                if isinstance(control, QComboBox)
                else control.isChecked()
            )
            label = tree.itemWidget(row, 0).findChild(QLabel).text()
            controls.append((label, value, row.isHidden(), control.isEnabled()))
        raw = (form.raw_value.text(), form.raw_value.isReadOnly()) if form else None
        shown.append((ev.text(0), raw, controls))
    return shown


def event_row(table, label):
    return next(
        table.topLevelItem(row)
        for row in range(table.topLevelItemCount())
        if table.topLevelItem(row).text(0) == label
    )


class EventConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for module in ("annotations", "observed_events", "node_backup_files"):
            patcher = patch(
                f"workbench.{module}.application_directories",
                return_value={"Data": self.root},
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        observations = ObservedEvents("test")
        for identity in ((258, 102), (0, 5), (258, 7)):
            observations.observe(EventIdentity(*identity))
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        self.addCleanup(self.service.close)
        self.view = LayoutView(empty=True)
        self.addCleanup(self.view.close)
        self.view.set_observed_events(observations)
        self.view.show_live_layout("test", list)
        self.view.node_view.details.cbus_service = self.service
        self.view.layout_events.cbus_service = self.service
        self.view.node_view.state_lookup = self.service.node_states.get

    def add_live(self, state):
        self.service.node_states[state.identity.node_number] = state
        self.service.presence[state.identity.node_number] = True
        self.view.node_view.show_identity(state.identity)

    def layout_event(self, label):
        item = event_row(self.view.layout_events.table, label)
        item.setExpanded(True)
        return item

    def produced_event(self, node, label):
        events = self.view.node_view.details.node_events
        events.show_produced_events(node)
        item = event_row(events.produced_table, label)
        item.setExpanded(True)
        return item

    def test_both_views_list_every_consumer_with_raw_evs_by_identity(self):
        # Slots differ per node; only the (NN, EN) identity selects the EVs.
        self.add_live(consumer(260, {(1, 1): {1: 9}, (258, 102): {1: 4, 2: 1}}))
        self.add_live(consumer(261, {(258, 102): {1: 2, 2: None}}))
        # Unread EV values stay unknown rather than defaulting.
        self.add_live(consumer(262, {(258, 102): {1: 3}}, ev_count=2))
        self.add_live(consumer(263, {(258, 7): {1: 1}}))
        self.add_live(consumer(258, {}, flags=0x02, progress=DiscoveryProgress.SKIPPED))
        sent = len(self.connection.sent)

        expected = [
            ("Node 260 - CANMIO", "", [("EV 1", "4"), ("EV 2", "1")]),
            ("Node 261 - CANMIO", "", [("EV 1", "2")]),
            ("Node 262 - CANMIO", "", [("EV 1", "3"), ("EV 2", "Unknown")]),
        ]
        self.assertEqual(rows(self.layout_event("258:102")), expected)
        self.assertEqual(rows(self.produced_event(258, "258:102")), expected)
        # Expansion reads only discovered state; it never interrogates hardware.
        self.assertEqual(self.connection.sent[sent:], [])

    def test_short_and_long_identities_match_exactly(self):
        # A short event is (0, EN); a long event with the same EN is distinct.
        self.add_live(consumer(260, {(0, 5): {1: 1, 2: None}}))
        self.add_live(consumer(261, {(258, 5): {1: 2}}))

        self.assertEqual(
            rows(self.layout_event("0:5")),
            [("Node 260 - CANMIO", "", [("EV 1", "1")])],
        )
        # Short events are never attributed to a node's Produced Events.
        events = self.view.node_view.details.node_events
        events.show_produced_events(0)
        self.assertEqual(events.produced_table.topLevelItemCount(), 0)

    def test_undetermined_nodes_are_not_reported_as_no_consumers(self):
        self.add_live(consumer(260, {(258, 102): {1: 4, 2: None}}))
        self.add_live(consumer(261, {}))
        none = [("No configured consumers", "", [])]

        def unread(*nodes):
            return ("Not determined", "Right-click to load unread nodes", list(nodes))

        def unknown(*nodes):
            return ("Not determined", "Use Layouts → Refresh", list(nodes))

        confirmed = ("Node 260 - CANMIO", "", [("EV 1", "4")])
        self.assertEqual(rows(self.layout_event("258:7")), none)

        # Unread, reading, failed (even with partial results) and Offline nodes
        # might consume the event, so neither list is presented as complete.
        undetermined = {
            "not loaded": consumer(262, {}, progress=DiscoveryProgress.NOT_STARTED),
            "loading": consumer(262, {}, progress=DiscoveryProgress.IN_PROGRESS),
            "discovery incomplete": consumer(
                262, {(258, 7): {1: 6}}, progress=DiscoveryProgress.INCOMPLETE
            ),
            "Offline": consumer(262, {(258, 7): {1: 8}}),
        }
        for reason, state in undetermined.items():
            with self.subTest(reason=reason):
                self.add_live(state)
                self.service.presence[262] = reason != "Offline"
                self.view.refresh_consumers()
                # Only unread nodes can be loaded without Layouts → Refresh.
                # Each undetermined node is listed with its reason.
                node = ("Node 262", reason)
                hint = unread(node) if reason == "not loaded" else unknown(node)
                self.assertEqual(rows(self.layout_event("258:7")), [hint])
                self.assertEqual(rows(self.layout_event("258:102")), [confirmed, hint])

        self.add_live(consumer(262, {}))
        self.view.refresh_consumers()
        self.assertEqual(rows(self.layout_event("258:7")), none)

        # Without a connection nothing is confirmed, even previously read nodes.
        self.connection.state = "Disconnected"
        self.view.refresh_consumers()
        # Refresh needs a connection, so the hint is to connect first.
        self.assertEqual(
            rows(self.layout_event("258:102")),
            [
                (
                    "Not determined",
                    "Use Layouts → Connect",
                    [(f"Node {n}", "disconnected") for n in (260, 261, 262)],
                )
            ],
        )
        self.connection.state = "Connected"

        # A saved-only node's metadata is not confirmed live configuration.
        save_metadata("test", consumer(265, {(258, 7): {1: 1}}))
        self.view.node_view.show_saved_nodes("test")
        self.view.refresh_consumers()
        self.assertEqual(
            rows(self.layout_event("258:7")), [unknown(("Node 265", "Offline"))]
        )

    def test_configuration_changes_refresh_while_keeping_expansion(self):
        state = consumer(260, {(258, 102): {1: 4}})
        self.add_live(state)
        self.add_live(consumer(261, {}))
        event = self.layout_event("258:102")
        event.child(0).setExpanded(True)
        self.view.layout_events.table.setCurrentItem(event.child(0).child(0))

        # E.g. Save or Refresh rereads both nodes' consumed events.
        state.ev_values[1] = {1: 5}
        self.service.node_states[261] = consumer(261, {(258, 102): {1: 2}})
        self.view.refresh_consumers()

        table = self.view.layout_events.table
        event = event_row(table, "258:102")
        self.assertTrue(event.isExpanded())
        self.assertEqual(
            rows(event),
            [
                ("Node 260 - CANMIO", "", [("EV 1", "5"), ("EV 2", "Unknown")]),
                ("Node 261 - CANMIO", "", [("EV 1", "2"), ("EV 2", "Unknown")]),
            ],
        )
        self.assertTrue(event.child(0).isExpanded())
        self.assertIs(table.currentItem(), event.child(0).child(0))

    def test_consumer_evs_show_its_consumed_events_mdf_presentation_read_only(self):
        # One presentation in two places: group labels, token renames, values
        # and NV-dependent labels come from the same MDF code (#168/#169).
        mdf = json.loads(
            (Path(__file__).parent / "fixtures/mdfs/canmio-3d-ev2.json").read_text()
        )
        mdf |= {"moduleName": "CANMIO", "nodeVariables": []}
        system = self.root / "mdfs"
        system.mkdir()
        (system / "CANMIO-A520-3d.json").write_text(json.dumps(mdf))
        self.view.node_view.mdf_repository = MdfRepository(system, self.root / "user")
        self.view.annotations.save({"tokens": {"channel": {"1": "Points"}}}, 260)
        details = self.view.node_view.details
        table = self.view.layout_events.table

        # Load Unread Nodes reads no NVs: their labels stay unknown, not guessed.
        for nvs, action in (
            ({}, "Unknown label (NV 16 unread)"),
            ({16: 1}, "Points - ON"),
        ):
            with self.subTest(nvs=nvs):
                state = consumer(260, {(258, 102): {1: 0, 2: 137}})
                state.parameters |= {2: ord("d"), 7: 3}
                state.nv_values |= nvs
                self.add_live(state)
                self.view.refresh_consumers()
                node = self.layout_event("258:102").child(0)
                node.setExpanded(True)
                shown = presentation(table, node)

                self.view.select_node(260)
                consumed = event_row(details.node_events.consumed_table, "258:102")
                consumed.setExpanded(True)
                self.assertEqual(
                    shown, presentation(details.node_events.consumed_table, consumed)
                )
                ev2 = shown[1]
                self.assertEqual(ev2[1], ("137", True))
                self.assertEqual(ev2[2][0][:2], ("Action:", action))
                self.assertFalse(any(enabled for *_, enabled in ev2[2]))

        # Renaming a token updates an already expanded consumer.
        self.view.annotations.save({"tokens": {"channel": {"1": "Junction"}}}, 260)
        node = event_row(table, "258:102").child(0)
        self.assertEqual(presentation(table, node)[1][2][0][1], "Junction - ON")

    def test_consumer_opens_that_nodes_consumed_event(self):
        self.add_live(consumer(258, {}, flags=0x02, progress=DiscoveryProgress.SKIPPED))
        self.add_live(consumer(260, {(1, 1): {1: 9}, (258, 102): {1: 4}}))
        self.view.show()
        details = self.view.node_view.details

        for open_from in (
            self.layout_event,
            lambda label: self.produced_event(258, label),
        ):
            with self.subTest(open_from=open_from):
                self.view.select_node(258)
                event = open_from("258:102")
                event.treeWidget().itemDoubleClicked.emit(event.child(0), 0)
                self.app.processEvents()

                self.assertIs(self.view.tabs.currentWidget(), self.view.node_view)
                self.assertEqual(details.annotation_number(), 260)
                self.assertIs(
                    details.tabs.currentWidget(), details.consumed_events_page
                )
                self.assertEqual(details.node_events.selected_identity(), (258, 102))

    def test_load_unread_nodes_reads_only_unread_consumers_events_and_nvs(self):
        # 260's events were read, but not the NVs its MDF labels may need.
        read = consumer(260, {(258, 102): {1: 4, 2: None}})
        read.parameters[6] = 1
        self.add_live(read)
        unread = consumer(261, {}, progress=DiscoveryProgress.NOT_STARTED)
        unread.parameters[6] = 2
        self.add_live(unread)
        self.add_live(
            consumer(262, {}, flags=0x02, progress=DiscoveryProgress.NOT_STARTED)
        )
        self.add_live(consumer(263, {}, progress=DiscoveryProgress.NOT_STARTED))
        self.service.presence[263] = False
        event = self.layout_event("258:102")
        sent = len(self.connection.sent)

        for consumers in self.view.consumer_trees():
            action = consumers.load_action(self.service)
            self.assertEqual(action.text(), "Load Unread Nodes")
            self.assertTrue(action.isEnabled())
        self.view.layout_events.consumers.load_action(self.service).trigger()

        # Answer each request in turn: NVRD with NVANS, RQEVN with NUMEV 0.
        requests = []
        while len(self.connection.sent) > sent:
            frame = self.connection.sent[sent].decode()
            sent += 1
            opcode, node = frame[7:9], frame[9:13]
            requests.append((opcode, int(node, 16), frame[13:-1]))
            reply = {"71": f"97{node}{frame[13:15]}00", "58": f"74{node}00"}[opcode]
            self.connection.frame_received.emit(f":SB040N{reply};".encode())
        self.view.refresh_consumers()

        # Only Online possible consumers: 260's NV, 261's NVs and stored events
        # (0x0104 = 260, 0x0105 = 261). Non-consumer 262 and Offline 263 are not read.
        self.assertCountEqual(
            requests,
            [("71", 260, "01"), ("71", 261, "01"), ("71", 261, "02"), ("58", 261, "")],
        )

        # Offline 263 still needs Layouts → Refresh; nothing is left to load.
        self.assertEqual(
            rows(event),
            [
                ("Node 260 - CANMIO", "", [("EV 1", "4")]),
                ("Not determined", "Use Layouts → Refresh", [("Node 263", "Offline")]),
            ],
        )
        self.assertFalse(
            self.view.layout_events.consumers.load_action(self.service).isEnabled()
        )


if __name__ == "__main__":
    unittest.main()

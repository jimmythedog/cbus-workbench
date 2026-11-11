"""Observed event reception, durable identities and shared view contracts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from workbench.cbus_service import CbusService, NodeState
from workbench.layout_view import LayoutView
from workbench.observed_events import EventIdentity, ObservedEvents
from workbench.pnn import Pnn


class Connection(QObject):
    frame_received = Signal(bytes)

    def __init__(self, name):
        super().__init__()
        self.layout_name = name


class ObservedEventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.services = []
        self.addCleanup(lambda: [service.close() for service in self.services])
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patcher = patch(
            "workbench.observed_events.application_directories",
            return_value={"Data": self.root},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self, observations):
        connection = Connection(observations.logical_layout)
        service = CbusService(connection, 126)
        service.event_received.connect(observations.observe)
        self.services.append(service)
        return connection, service

    def test_received_events_persist_immediately_and_repeats_do_not_rewrite(self):
        observations = ObservedEvents("a")
        connection, _ = self.connect(observations)
        connection.frame_received.emit(b":SB040N900102002D;")
        identity = EventIdentity(258, 45)
        self.assertEqual(
            yaml.safe_load(observations.path.read_text()),
            [{"nodeNumber": 258, "eventNumber": 45}],
        )
        # File metadata is an observable check that repeated sightings do not write.
        before = observations.path.stat().st_mtime_ns
        connection.frame_received.emit(b":SB040N910102002D;")
        self.assertEqual(observations.path.stat().st_mtime_ns, before)
        self.assertEqual(len(observations.events), 1)
        restored = ObservedEvents("a")
        self.assertEqual(restored.events, {identity})

    def test_long_short_response_and_data_variants_have_correct_identities(self):
        observations = ObservedEvents("a")
        connection, _ = self.connect(observations)
        frames = [
            b":SB040N980102002D;",
            b":SB040N990103002D;",
            b":SB040N900000002D;",
            b":SB040N930102002D;",
            b":SB040NB40102002DAA;",
            b":SB040ND40102002DAABB;",
            b":SB040ND50102002DAABB;",
            b":SB040ND80102002DAABB;",
            b":SB040NFE0102002DAABBCC;",
        ]
        # Short senders normalise to zero; a long NN=0 shares that identity.
        for frame in frames:
            connection.frame_received.emit(frame)
        expected = {
            EventIdentity(0, 45),
            EventIdentity(258, 45),
        }
        self.assertEqual(observations.events, expected)
        # Requests, malformed lengths, remote and extended frames add nothing.
        for frame in (
            b":SB040N920102002E;",
            b":SB040N900102002EAA;",
            b":SB040N980102;",
            b":SB040ND30102002E020D;",
            b":SB040R900102002E;",
            b":X0000B040N900102002E;",
        ):
            connection.frame_received.emit(frame)
        self.assertEqual(observations.events, expected)

    def test_layouts_reconnect_and_both_views_use_same_collection(self):
        a, b = ObservedEvents("a"), ObservedEvents("b")
        first, service = self.connect(a)
        second, _ = self.connect(b)
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        view.set_observed_events(a)
        first.frame_received.emit(b":SB040N900102002D;")
        second.frame_received.emit(b":SB040N900103002E;")
        self.assertEqual(len(a.events), 1)
        self.assertEqual(len(b.events), 1)
        self.assertNotEqual(a.path.read_text(), b.path.read_text())
        events = view.node_view.details.node_events
        state = NodeState(Pnn(258, 1, 1, 0))
        view.node_view.state_lookup = lambda number: state
        view.node_view.show_identity(state.identity)
        self.assertEqual(events.produced_table.item(0, 0).text(), "258:45")
        self.assertEqual(view.layout_events.table.topLevelItemCount(), 1)
        # Removing the old service stops observations; reconnect retains identities.
        service.close()
        self.services.remove(service)
        first.frame_received.emit(b":SB040N900102002E;")
        self.assertEqual(a.events, {EventIdentity(258, 45)})
        reconnect, _ = self.connect(a)
        reconnect.frame_received.emit(b":SB040N910102002D;")
        self.assertEqual(a.events, {EventIdentity(258, 45)})
        table = view.layout_events.table
        self.assertEqual(table.columnCount(), 2)
        self.assertEqual(
            [table.headerItem().text(column) for column in range(2)],
            ["Event", "Description"],
        )
        self.assertEqual(table.topLevelItem(0).text(1), "")
        restored_view = LayoutView(empty=True)
        self.addCleanup(restored_view.close)
        restored_view.set_observed_events(ObservedEvents("a"))
        restored_events = restored_view.node_view.details.node_events
        restored_events.show_produced_events(258)
        self.assertEqual(restored_events.produced_table.rowCount(), 1)
        restored_events.show_produced_events(259)
        self.assertEqual(restored_events.produced_table.rowCount(), 0)
        # Short events do not get attributed to their sender's node pane.
        reconnect.frame_received.emit(b":SB040N980102002D;")
        events.show_produced_events(258)
        self.assertEqual(events.produced_table.rowCount(), 1)
        events.show_produced_events(0)
        self.assertEqual(events.produced_table.item(0, 0).text(), "0:45")
        self.assertEqual(view.layout_events.table.topLevelItem(0).text(0), "0:45")
        view.set_observed_events(b)
        self.assertEqual(view.layout_events.table.topLevelItem(0).text(0), "259:46")

    def test_failed_save_preserves_existing_file_and_allows_next_reception_to_retry(
        self,
    ):
        observations = ObservedEvents("a")
        first, second = EventIdentity(1, 2), EventIdentity(1, 3)
        observations.observe(first)
        saved = observations.path.read_bytes()
        with (
            patch.object(Path, "replace", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            observations.observe(second)
        self.assertEqual(observations.path.read_bytes(), saved)
        self.assertNotIn(second, observations.events)
        observations.observe(second)
        self.assertEqual(set(ObservedEvents("a").events), {first, second})

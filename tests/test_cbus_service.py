"""CBUS node state and requests over the existing connection contract."""

import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from workbench import cbus_service
from workbench.cbus_service import CbusService, DiscoveryProgress, NodeState
from workbench.pnn import Pnn


class ConnectionStub(QObject):
    frame_received = Signal(bytes)

    def __init__(self, layout_name: str):
        super().__init__()
        self.layout_name = layout_name
        self.sent: list[bytes] = []
        self.send_error: Exception | None = None

    def send(self, frame: bytes) -> None:
        if self.send_error:
            raise self.send_error
        self.sent.append(frame)


class CbusServiceTests(unittest.TestCase):
    def setUp(self):
        self.connection = ConnectionStub("Test Layout")
        self.service = CbusService(self.connection, can_id=126)
        self.discovered = []
        self.updated = []
        self.parameter_updates = []
        self.state_updates = []
        self.service.node_discovered.connect(self.discovered.append)
        self.service.node_updated.connect(self.updated.append)
        self.service.parameter_updated.connect(
            lambda node_number, index, value: self.parameter_updates.append(
                (node_number, index, value)
            )
        )
        self.service.node_state_updated.connect(self.state_updates.append)

    def start_nv_reads(self, nv_count: int) -> None:
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020006;")
        for index in (2, 4, 5):
            self.connection.frame_received.emit(f":SB040N9B0102{index:02X}00;".encode())
        self.connection.frame_received.emit(f":SB040N9B010206{nv_count:02X};".encode())

    def finish_short_parameter_pass(self, node_number: int = 258) -> None:
        """Complete a one-request parameter pass for a discovered node."""
        self.connection.frame_received.emit(f":SB040N9B{node_number:04X}0000;".encode())

    def start_ev_reads(self, ev_count: int, indices: tuple[int, ...] = (7,)) -> None:
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(f":SB040N9B010205{ev_count:02X};".encode())
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(
            f":SB040N740102{len(indices):02X};".encode()
        )
        for index in indices:
            self.connection.frame_received.emit(
                f":SB040NF20102000A0014{index:02X};".encode()
            )

    def test_reval_frame_uses_node_event_and_ev_indices(self):
        self.service.request_ev(0x1234, 7, 2)
        self.service.request_ev(0x1234, 0, 1)
        self.assertEqual(
            self.connection.sent,
            [b":SBFC0N9C12340702;", b":SBFC0N9C12340001;"],
        )

    def test_ev_reads_use_confirmed_nonsequential_indices_and_parameter_5_range(self):
        self.start_ev_reads(2, (7, 2))
        state = self.service.node_states[258]
        self.assertEqual(state.event_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.ev_progress, DiscoveryProgress.IN_PROGRESS)
        self.assertEqual(state.ev_values, {})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9C01020201;")

        for event_index, ev_index, value, next_frame in (
            (2, 1, 0, b":SBFC0N9C01020202;"),
            (2, 2, 9, b":SBFC0N9C01020701;"),
            (7, 1, 3, b":SBFC0N9C01020702;"),
            (7, 2, 4, None),
        ):
            self.connection.frame_received.emit(
                f":SB040NB50102{event_index:02X}{ev_index:02X}{value:02X};".encode()
            )
            if next_frame is not None:
                self.assertEqual(self.connection.sent[-1], next_frame)
                self.assertEqual(state.ev_progress, DiscoveryProgress.IN_PROGRESS)
        self.assertEqual(state.ev_values, {2: {1: 0, 2: 9}, 7: {1: 3, 2: 4}})
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)

    def test_unrelated_malformed_and_late_neval_do_not_confirm_values(self):
        self.start_ev_reads(1)
        state = self.service.node_states[258]
        sent = self.connection.sent.copy()
        for frame in (
            b":SB040NB50103070109;",  # Another node.
            b":SB040NB50102080109;",  # Another event index.
            b":SB040NB50102070209;",  # Another EV index.
            b":SB040NB501020701;",  # Missing value.
        ):
            self.connection.frame_received.emit(frame)
        self.assertEqual(state.ev_values, {})
        self.assertEqual(self.connection.sent, sent)
        self.connection.frame_received.emit(b":SB040NB50102070105;")
        self.assertEqual(state.ev_values, {7: {1: 5}})
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)
        self.connection.frame_received.emit(b":SB040NB50102070109;")
        self.assertEqual(state.ev_values, {7: {1: 5}})

    def test_ev_timeout_retains_partial_values_and_continues_other_node(self):
        self.start_ev_reads(2)
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040NB50102070108;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9C01020702;")
        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        first = self.service.node_states[258]
        self.assertEqual(first.event_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(first.ev_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(first.ev_values, {7: {1: 8}})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        self.connection.frame_received.emit(b":SB040NB50102070209;")
        self.assertEqual(first.ev_values, {7: {1: 8}})
        self.finish_short_parameter_pass(259)
        self.connection.frame_received.emit(b":SB040N74010300;")
        self.assertEqual(
            self.service.node_states[259].event_progress, DiscoveryProgress.COMPLETE
        )

    def test_cmderr_5_leaves_value_unconfirmed_and_continues_later_ev(self):
        self.start_ev_reads(3)
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040NB50102070105;")
        self.connection.frame_received.emit(b":SB040N6F010305;")
        self.connection.frame_received.emit(b":SB040N6F010206;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9C01020702;")
        with self.assertLogs("workbench.cbus", level="DEBUG") as captured:
            self.connection.frame_received.emit(b":SB040N6F010205;")
        self.assertIn("with REVAL outstanding", captured.records[0].getMessage())
        first = self.service.node_states[258]
        self.assertEqual(first.ev_values, {7: {1: 5}})
        self.assertEqual(first.ev_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9C01020703;")
        self.connection.frame_received.emit(b":SB040NB50102070309;")
        self.assertEqual(first.ev_values, {7: {1: 5, 3: 9}})
        self.assertEqual(first.ev_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        self.connection.frame_received.emit(b":SB040NB50102070209;")
        self.assertEqual(first.ev_values, {7: {1: 5, 3: 9}})

    def test_multiple_cmderr_5_responses_leave_ev_pass_incomplete(self):
        self.start_ev_reads(3)
        state = self.service.node_states[258]
        for ev_index in (1, 2, 3):
            self.assertEqual(
                self.connection.sent[-1],
                f":SBFC0N9C010207{ev_index:02X};".encode(),
            )
            with self.assertLogs("workbench.cbus", level="DEBUG"):
                self.connection.frame_received.emit(b":SB040N6F010205;")
            if ev_index < 3:
                self.assertEqual(state.ev_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(state.ev_values, {})
        self.assertEqual(state.ev_progress, DiscoveryProgress.INCOMPLETE)

    def test_ev_send_failure_retains_confirmed_value(self):
        self.start_ev_reads(2)
        self.connection.send_error = ConnectionError("not connected")
        with self.assertLogs("workbench.cbus", level="ERROR"):
            self.connection.frame_received.emit(b":SB040NB50102070105;")
        state = self.service.node_states[258]
        self.assertEqual(state.ev_values, {7: {1: 5}})
        self.assertEqual(state.ev_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9C01020701;")

    def test_ev_zero_and_unknown_counts_do_not_invent_values(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010200;")
        self.assertEqual(
            self.service.node_states[258].ev_progress, DiscoveryProgress.COMPLETE
        )
        self.assertFalse(any(b"N9C" in frame for frame in self.connection.sent))

        other = ConnectionStub("Unknown EV Count")
        service = CbusService(other, can_id=127)
        other.frame_received.emit(b":SB040NB601020D2203;")
        other.frame_received.emit(b":SB040N9B01020000;")
        other.frame_received.emit(b":SB040N74010201;")
        other.frame_received.emit(b":SB040NF20102000A001407;")
        state = service.node_states[258]
        self.assertEqual(state.ev_progress, DiscoveryProgress.NOT_STARTED)
        self.assertEqual(state.ev_values, {})
        self.assertFalse(any(b"N9C" in frame for frame in other.sent))
        other.frame_received.emit(b":SB040N9B01020500;")
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)
        self.assertFalse(any(b"N9C" in frame for frame in other.sent))

    def test_late_parameter_5_starts_ev_reads_after_enumeration(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010201;")
        self.connection.frame_received.emit(b":SB040NF20102000A001407;")
        state = self.service.node_states[258]
        self.assertEqual(state.ev_progress, DiscoveryProgress.NOT_STARTED)
        self.connection.frame_received.emit(b":SB040N9B01020501;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N9C01020701;")
        self.assertEqual(state.ev_progress, DiscoveryProgress.IN_PROGRESS)
        self.connection.frame_received.emit(b":SB040NB50102070109;")
        self.assertEqual(state.ev_values, {7: {1: 9}})
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)

    def test_incomplete_event_enumeration_never_starts_ev_reads(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020502;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010202;")
        self.connection.frame_received.emit(b":SB040NF20102000A001407;")
        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        state = self.service.node_states[258]
        self.assertEqual(state.event_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(state.ev_progress, DiscoveryProgress.NOT_STARTED)
        self.assertEqual(state.ev_values, {})
        self.assertFalse(any(b"N9C" in frame for frame in self.connection.sent))

    def test_event_count_starts_after_parameter_pass_and_zero_is_confirmed(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        state = self.service.node_states[258]
        self.assertIsNone(state.stored_event_count)
        self.finish_short_parameter_pass()
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580102;")
        self.assertEqual(state.event_progress, DiscoveryProgress.IN_PROGRESS)
        before = len(self.state_updates)
        self.connection.frame_received.emit(b":SB040N74010200;")
        self.assertEqual(state.stored_event_count, 0)
        self.assertEqual(state.event_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.ev_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(len(self.state_updates) - before, 3)

    def test_producer_only_node_skips_event_discovery(self):
        self.connection.frame_received.emit(b":SB040NB601020D2202;")
        state = self.service.node_states[258]
        before = len(self.state_updates)

        with self.assertLogs("workbench.cbus", level="TRACE") as captured:
            self.finish_short_parameter_pass()

        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])
        self.assertEqual(state.parameter_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.event_progress, DiscoveryProgress.SKIPPED)
        self.assertEqual(state.ev_progress, DiscoveryProgress.SKIPPED)
        self.assertIsNone(state.stored_event_count)
        self.assertGreater(len(self.state_updates), before)
        self.assertTrue(
            any("not a consumer" in record.getMessage() for record in captured.records)
        )

    def test_producer_only_node_skips_events_after_parameter_timeout(self):
        self.connection.frame_received.emit(b":SB040NB601020D2202;")

        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()

        state = self.service.node_states[258]
        self.assertEqual(state.parameter_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(state.event_progress, DiscoveryProgress.SKIPPED)
        self.assertIsNone(state.stored_event_count)
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])

    def test_consumer_and_non_consumer_nodes_share_discovery_queue(self):
        self.connection.frame_received.emit(b":SB040NB601020D2202;")
        self.connection.frame_received.emit(b":SB040NB601030D2201;")
        self.finish_short_parameter_pass(258)

        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        self.finish_short_parameter_pass(259)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580103;")
        self.connection.frame_received.emit(b":SB040N74010300;")

        self.assertEqual(
            self.connection.sent,
            [b":SBFC0N73010200;", b":SBFC0N73010300;", b":SBFC0N580103;"],
        )
        self.assertEqual(
            self.service.node_states[258].event_progress, DiscoveryProgress.SKIPPED
        )
        self.assertIsNone(self.service.node_states[258].stored_event_count)
        self.assertEqual(
            self.service.node_states[259].event_progress, DiscoveryProgress.COMPLETE
        )
        self.assertEqual(self.service.node_states[259].stored_event_count, 0)

    def test_unknown_consumer_capability_still_requests_event_count(self):
        self.connection.frame_received.emit(b":SB040NB601020D2202;")
        with patch.object(Pnn, "is_consumer", None):
            self.finish_short_parameter_pass()

        self.assertEqual(self.connection.sent[-1], b":SBFC0N580102;")
        self.assertEqual(
            self.service.node_states[258].event_progress,
            DiscoveryProgress.IN_PROGRESS,
        )

    def test_positive_count_queues_nerd_and_distinct_nonsequential_indices_complete(
        self,
    ):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010202;")
        state = self.service.node_states[258]
        self.assertEqual(state.stored_event_count, 2)
        self.assertEqual(state.event_progress, DiscoveryProgress.IN_PROGRESS)
        self.assertEqual(
            self.connection.sent,
            [b":SBFC0N73010200;", b":SBFC0N580102;", b":SBFC0N570102;"],
        )
        self.connection.frame_received.emit(b":SB040NF20102000A001407;")
        self.assertEqual(state.event_identities, {7: (10, 20)})
        self.assertEqual(state.event_progress, DiscoveryProgress.IN_PROGRESS)
        self.connection.frame_received.emit(b":SB040NF20102000000FF02;")
        self.assertEqual(state.event_identities, {7: (10, 20), 2: (0, 255)})
        self.assertEqual(state.event_progress, DiscoveryProgress.COMPLETE)

    def test_duplicate_unrelated_and_malformed_enrsp_do_not_advance_queue(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010202;")
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        sent = self.connection.sent.copy()
        self.connection.frame_received.emit(b":SB040NF20103000A001407;")
        self.connection.frame_received.emit(b":SB040NF20102000A0014;")
        self.assertEqual(self.connection.sent, sent)
        self.connection.frame_received.emit(b":SB040NF20102000A001407;")
        self.connection.frame_received.emit(b":SB040NF20102000A001407;")
        self.assertEqual(self.service.node_states[258].event_identities, {7: (10, 20)})
        self.assertEqual(self.service.node_states[259].event_identities, {})
        self.assertEqual(self.connection.sent, sent)
        self.assertEqual(
            self.service.node_states[258].event_progress,
            DiscoveryProgress.IN_PROGRESS,
        )
        self.connection.frame_received.emit(b":SB040NF20102000A001409;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")

    def test_conflicting_enrsp_stops_enumeration_and_continues_other_node(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020502;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010202;")
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040NF20102000A001407;")

        with self.assertLogs("workbench.cbus", level="WARNING") as captured:
            self.connection.frame_received.emit(b":SB040NF20102000A009907;")

        first = self.service.node_states[258]
        self.assertEqual(first.event_identities, {7: (10, 20)})
        self.assertEqual(first.event_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(first.ev_progress, DiscoveryProgress.NOT_STARTED)
        self.assertFalse(any(b"N9C" in frame for frame in self.connection.sent))
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        self.assertEqual(captured.records[0].fields["confirmed_identity"], (10, 20))
        self.connection.frame_received.emit(b":SB040NF20102000A001409;")
        self.assertEqual(first.event_identities, {7: (10, 20)})

        self.finish_short_parameter_pass(259)
        self.connection.frame_received.emit(b":SB040N74010301;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N570103;")
        self.connection.frame_received.emit(b":SB040NF20103000B001501;")
        self.assertEqual(self.service.node_states[259].event_identities, {1: (11, 21)})
        self.assertEqual(
            self.service.node_states[259].event_progress, DiscoveryProgress.COMPLETE
        )
        self.assertEqual(first.event_progress, DiscoveryProgress.INCOMPLETE)

    def test_nerd_timeout_keeps_partial_results_and_late_reply_is_ignored(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010202;")
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040NF20102000A001407;")
        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        first = self.service.node_states[258]
        self.assertEqual(first.event_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(first.event_identities, {7: (10, 20)})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        self.connection.frame_received.emit(b":SB040NF20102000A001409;")
        self.assertEqual(first.event_identities, {7: (10, 20)})
        self.finish_short_parameter_pass(259)
        self.connection.frame_received.emit(b":SB040N74010301;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N570103;")
        self.connection.frame_received.emit(b":SB040NF20102000A001409;")
        self.connection.frame_received.emit(b":SB040NF20103000B001501;")
        self.assertEqual(first.event_identities, {7: (10, 20)})
        self.assertEqual(self.service.node_states[259].event_identities, {1: (11, 21)})
        self.assertEqual(
            self.service.node_states[259].event_progress, DiscoveryProgress.COMPLETE
        )

    def test_unrelated_and_late_numev_do_not_confirm_count(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N74010209;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040N74010309;")
        self.assertIsNone(self.service.node_states[258].stored_event_count)
        self.connection.frame_received.emit(b":SB040N74010202;")
        self.connection.frame_received.emit(b":SB040N74010203;")
        self.assertEqual(self.service.node_states[258].stored_event_count, 2)

    def test_event_count_timeout_keeps_unknown_and_continues_other_node(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        self.assertIsNone(self.service.node_states[258].stored_event_count)
        self.assertEqual(
            self.service.node_states[258].event_progress, DiscoveryProgress.INCOMPLETE
        )
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        self.connection.frame_received.emit(b":SB040N74010207;")
        self.assertIsNone(self.service.node_states[258].stored_event_count)
        self.finish_short_parameter_pass(259)
        self.connection.frame_received.emit(b":SB040N74010300;")
        self.assertEqual(self.service.node_states[259].stored_event_count, 0)

    def test_late_numev_cannot_complete_another_nodes_outstanding_request(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.finish_short_parameter_pass()
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        self.finish_short_parameter_pass(259)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580103;")

        self.connection.frame_received.emit(b":SB040N74010205;")
        first = self.service.node_states[258]
        second = self.service.node_states[259]
        self.assertIsNone(first.stored_event_count)
        self.assertEqual(first.event_progress, DiscoveryProgress.INCOMPLETE)
        self.assertIsNone(second.stored_event_count)
        self.assertEqual(second.event_progress, DiscoveryProgress.IN_PROGRESS)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580103;")

        self.connection.frame_received.emit(b":SB040N74010300;")
        self.assertEqual(second.stored_event_count, 0)
        self.assertEqual(second.event_progress, DiscoveryProgress.COMPLETE)

    def test_event_count_send_failure_keeps_unknown(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.send_error = ConnectionError("not connected")
        with self.assertLogs("workbench.cbus", level="ERROR"):
            self.finish_short_parameter_pass()
        state = self.service.node_states[258]
        self.assertIsNone(state.stored_event_count)
        self.assertEqual(state.event_progress, DiscoveryProgress.INCOMPLETE)

    def test_parameter_timeout_still_starts_event_count_discovery(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        state = self.service.node_states[258]
        self.assertEqual(state.parameter_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(state.event_progress, DiscoveryProgress.IN_PROGRESS)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580102;")

    def test_multiple_nodes_share_queue_and_preserve_nv_discovery(self):
        self.start_nv_reads(1)
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010201;")
        self.connection.frame_received.emit(b":SB040N9701020109;")
        self.assertEqual(self.service.node_states[258].nv_values, {1: 9})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580102;")
        self.connection.frame_received.emit(b":SB040N74010200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        self.finish_short_parameter_pass(259)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580103;")
        self.connection.frame_received.emit(b":SB040N74010303;")
        self.assertEqual(self.service.node_states[259].stored_event_count, 3)

    def test_discovers_node_without_a_prior_query(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")

        node = Pnn(258, 13, 34, 3)
        self.assertEqual(self.service.nodes, {258: node})
        self.assertEqual(
            self.service.node_states,
            {258: NodeState(node, parameter_progress=DiscoveryProgress.IN_PROGRESS)},
        )
        self.assertEqual(self.service.node_states[258].nv_values, {})
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.NOT_STARTED
        )
        self.assertEqual(
            self.service.node_states[258].event_progress, DiscoveryProgress.NOT_STARTED
        )
        self.assertEqual(self.discovered, [node])
        self.assertEqual(self.updated, [])
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])

    def test_request_parameter_encodes_node_and_index(self):
        with self.assertLogs("workbench.cbus", level="TRACE") as captured:
            self.service.request_parameter(0x1234, 0xAB)

        self.assertEqual(self.connection.sent, [b":SBFC0N731234AB;"])
        self.assertEqual(
            captured.records[0].fields,
            {"layout": "Test Layout", "node_number": 0x1234, "parameter_index": 0xAB},
        )

    def test_manual_request_does_not_join_automatic_queue(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.service.request_parameter(259, 7)
        self.assertEqual(
            self.connection.sent,
            [b":SBFC0N73010200;", b":SBFC0N73010307;"],
        )
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040N9B01030705;")
        self.assertEqual(self.service.node_states[259].parameters, {7: 5})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010307;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")

    def test_request_parameter_validates_arguments_before_sending(self):
        for node_number, index in (
            (0, 0),
            (-1, 0),
            (0x10000, 0),
            (True, 0),
            (1.5, 0),
            (1, -1),
            (1, 0x100),
            (1, True),
            (1, "7"),
        ):
            with (
                self.subTest(node_number=node_number, index=index),
                self.assertRaises(ValueError),
            ):
                self.service.request_parameter(node_number, index)
        self.assertEqual(self.connection.sent, [])

    def test_request_parameter_send_failure_is_reported(self):
        self.connection.send_error = ConnectionError("not connected")

        with (
            self.assertLogs("workbench.cbus", level="ERROR") as captured,
            self.assertRaisesRegex(ConnectionError, "not connected"),
        ):
            self.service.request_parameter(258, 0)
        self.assertEqual(self.connection.sent, [])
        self.assertIsNotNone(captured.records[0].exc_info)

    def test_failed_automatic_request_keeps_discovered_node(self):
        self.connection.send_error = ConnectionError("not connected")

        with self.assertLogs("workbench.cbus", level="ERROR"):
            self.connection.frame_received.emit(b":SB040NB601020D2203;")

        self.assertEqual(self.service.nodes, {258: Pnn(258, 13, 34, 3)})
        self.assertEqual(self.connection.sent, [])
        self.assertEqual(
            self.service.node_states[258].parameter_progress,
            DiscoveryProgress.INCOMPLETE,
        )

    def test_paran_first_changed_duplicate_and_zero_values(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        before = len(self.state_updates)
        self.connection.frame_received.emit(b":SB040N9B01020700;")
        self.connection.frame_received.emit(b":SB040N9B01020700;")
        self.connection.frame_received.emit(b":SB040N9B01020702;")
        self.connection.frame_received.emit(b":SB040N9B01020600;")

        self.assertEqual(self.service.node_states[258].parameters, {7: 2, 6: 0})
        self.assertEqual(
            self.parameter_updates, [(258, 7, 0), (258, 7, 2), (258, 6, 0)]
        )
        self.assertEqual(self.updated, [])
        self.assertEqual(len(self.state_updates) - before, 4)
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.COMPLETE
        )

    def test_nv_values_are_sparse_and_notify_only_on_change(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        before = len(self.state_updates)

        self.service.record_nv(258, 2, 0)
        self.service.record_nv(258, 2, 0)
        self.service.record_nv(258, 2, 9)

        state = self.service.node_states[258]
        self.assertEqual(state.nv_values, {2: 9})
        self.assertNotIn(1, state.nv_values)
        self.assertEqual(state.nv_progress, DiscoveryProgress.NOT_STARTED)
        self.assertEqual(state.event_progress, DiscoveryProgress.NOT_STARTED)
        self.assertEqual(len(self.state_updates) - before, 2)
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])

    def test_request_nv_uses_nvrd_frame(self):
        self.service.request_nv(0x1234, 2)
        self.assertEqual(self.connection.sent, [b":SBFC0N71123402;"])
        for index in (0, 256):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.service.request_nv(0x1234, index)
        self.assertEqual(self.connection.sent, [b":SBFC0N71123402;"])

    def test_nv_count_starts_automatic_reads_after_parameters(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020006;")
        progress_updates = []

        def record_nv_progress(node_number):
            progress = self.service.node_states[node_number].nv_progress
            if not progress_updates or progress_updates[-1] != progress:
                progress_updates.append(progress)

        self.service.node_state_updated.connect(record_nv_progress)
        for index in (2, 4, 5):
            self.connection.frame_received.emit(f":SB040N9B0102{index:02X}00;".encode())
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.NOT_STARTED
        )
        self.connection.frame_received.emit(b":SB040N9B01020602;")

        self.assertEqual(
            self.connection.sent,
            [f":SBFC0N730102{index:02X};".encode() for index in (0, 2, 4, 5, 6)]
            + [b":SBFC0N71010201;"],
        )
        state = self.service.node_states[258]
        self.assertEqual(state.parameter_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.nv_progress, DiscoveryProgress.IN_PROGRESS)
        self.connection.frame_received.emit(b":SB040N9B01020602;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010201;")
        self.connection.frame_received.emit(b":SB040N9701020100;")
        self.assertEqual(state.nv_values, {1: 0})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010202;")
        self.connection.frame_received.emit(b":SB040N9701020207;")
        self.assertEqual(state.nv_values, {1: 0, 2: 7})
        self.assertEqual(state.nv_progress, DiscoveryProgress.COMPLETE)
        self.assertIn(DiscoveryProgress.IN_PROGRESS, progress_updates)
        self.assertEqual(progress_updates.count(DiscoveryProgress.COMPLETE), 1)

    def test_zero_and_unknown_nv_counts_do_not_send_nvrd(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        state = self.service.node_states[258]
        self.assertEqual(state.nv_progress, DiscoveryProgress.NOT_STARTED)
        self.connection.frame_received.emit(b":SB040N9701020109;")
        self.assertEqual(state.nv_values, {1: 9})
        self.assertEqual(state.nv_progress, DiscoveryProgress.NOT_STARTED)
        self.connection.frame_received.emit(b":SB040N9B01020600;")
        self.assertEqual(state.nv_progress, DiscoveryProgress.COMPLETE)
        self.assertFalse(any(b"N71" in frame for frame in self.connection.sent))

    def test_unavailable_nv_count_leaves_discovery_not_started(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        for index in (2, 4):
            self.connection.frame_received.emit(f":SB040N9B0102{index:02X}00;".encode())
        state = self.service.node_states[258]
        self.assertNotIn(6, state.parameters)
        self.assertEqual(state.nv_progress, DiscoveryProgress.NOT_STARTED)
        self.assertFalse(any(b"N71" in frame for frame in self.connection.sent))

    def test_nv_requests_wait_for_outstanding_parameter_request(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020006;")
        self.connection.frame_received.emit(b":SB040N9B01020601;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010202;")
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.NOT_STARTED
        )
        for index in (2, 4, 5, 6):
            value = 1 if index == 6 else 0
            self.connection.frame_received.emit(
                f":SB040N9B0102{index:02X}{value:02X};".encode()
            )
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010201;")
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.IN_PROGRESS
        )

    def test_changed_late_nv_count_cannot_complete_old_discovery(self):
        self.start_nv_reads(2)
        state = self.service.node_states[258]
        sent = self.connection.sent.copy()

        self.connection.frame_received.emit(b":SB040N9B01020603;")
        self.assertEqual(self.connection.sent, sent)
        self.assertEqual(state.parameters[6], 3)
        self.assertEqual(state.parameter_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.nv_progress, DiscoveryProgress.INCOMPLETE)

        self.connection.frame_received.emit(b":SB040N9701020105;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010202;")
        self.connection.frame_received.emit(b":SB040N9701020206;")
        self.assertEqual(state.nv_values, {1: 5, 2: 6})
        self.assertEqual(state.nv_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(self.connection.sent.count(b":SBFC0N71010201;"), 1)

    def test_late_nv_count_after_completion_does_not_restart_requests(self):
        self.start_nv_reads(1)
        self.connection.frame_received.emit(b":SB040N9701020105;")
        state = self.service.node_states[258]
        self.assertEqual(state.nv_progress, DiscoveryProgress.COMPLETE)
        sent = self.connection.sent.copy()

        self.connection.frame_received.emit(b":SB040N9B01020601;")
        self.assertEqual(state.nv_progress, DiscoveryProgress.COMPLETE)
        self.connection.frame_received.emit(b":SB040N9B01020602;")
        self.assertEqual(state.nv_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(state.parameter_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(self.connection.sent, sent)

    def test_unrelated_and_duplicate_nvans_do_not_advance(self):
        self.start_nv_reads(2)
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        before = self.connection.sent.copy()
        self.connection.frame_received.emit(b":SB040N9701030108;")
        self.connection.frame_received.emit(b":SB040N9701020209;")
        self.connection.frame_received.emit(b":SB040N9701020209;")
        self.assertEqual(self.connection.sent, before)
        self.assertEqual(self.service.node_states[258].nv_values, {2: 9})
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.IN_PROGRESS
        )

        self.connection.frame_received.emit(b":SB040N9701020101;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010202;")
        self.connection.frame_received.emit(b":SB040N9701020101;")
        self.assertEqual(self.connection.sent.count(b":SBFC0N71010202;"), 1)
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.IN_PROGRESS
        )
        self.connection.frame_received.emit(b":SB040N9701020209;")
        self.assertEqual(
            self.service.node_states[258].nv_progress, DiscoveryProgress.COMPLETE
        )

    def test_nv_timeout_keeps_partial_values_and_continues_next_node(self):
        self.start_nv_reads(2)
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040N9B01030601;")
        self.connection.frame_received.emit(b":SB040N9701020105;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010202;")

        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        first = self.service.node_states[258]
        second = self.service.node_states[259]
        self.assertEqual(first.nv_values, {1: 5})
        self.assertEqual(first.nv_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580102;")
        self.connection.frame_received.emit(b":SB040N74010200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")
        sent = self.connection.sent.copy()
        self.connection.frame_received.emit(b":SB040N9B01020602;")
        self.assertEqual(self.connection.sent, sent)
        self.assertEqual(first.nv_progress, DiscoveryProgress.INCOMPLETE)
        self.connection.frame_received.emit(b":SB040N9B01030006;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010301;")
        self.connection.frame_received.emit(b":SB040N9701030107;")
        self.assertEqual(second.nv_values, {1: 7})
        self.assertEqual(second.nv_progress, DiscoveryProgress.COMPLETE)

    def test_failed_nv_request_preserves_confirmed_value(self):
        self.start_nv_reads(2)
        self.connection.send_error = ConnectionError("not connected")
        with self.assertLogs("workbench.cbus", level="ERROR"):
            self.connection.frame_received.emit(b":SB040N9701020105;")

        state = self.service.node_states[258]
        self.assertEqual(state.nv_values, {1: 5})
        self.assertEqual(state.nv_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N71010201;")

    def test_nv_discovery_is_fresh_after_disconnect(self):
        self.start_nv_reads(1)
        self.connection.frame_received.emit(b":SB040N9701020105;")
        self.service.close()
        self.connection.frame_received.emit(b":SB040N9701020109;")
        self.assertEqual(self.service.node_states[258].nv_values, {1: 5})

        new_service = CbusService(self.connection, can_id=126)
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.assertEqual(new_service.node_states[258].nv_values, {})
        self.assertEqual(
            new_service.node_states[258].nv_progress, DiscoveryProgress.NOT_STARTED
        )

    def test_automatic_nv_state_is_separate_between_layouts(self):
        self.start_nv_reads(1)
        other_connection = ConnectionStub("Other Layout")
        other_service = CbusService(other_connection, can_id=127)
        other_connection.frame_received.emit(b":SB040NB601020D2203;")
        other_connection.frame_received.emit(b":SB040N9B01020006;")
        for index in (2, 4, 5):
            other_connection.frame_received.emit(
                f":SB040N9B0102{index:02X}00;".encode()
            )
        other_connection.frame_received.emit(b":SB040N9B01020601;")

        self.connection.frame_received.emit(b":SB040N9701020105;")
        self.assertEqual(other_service.node_states[258].nv_values, {})
        self.assertEqual(
            other_service.node_states[258].nv_progress, DiscoveryProgress.IN_PROGRESS
        )
        other_connection.frame_received.emit(b":SB040N9701020107;")
        self.assertEqual(self.service.node_states[258].nv_values, {1: 5})
        self.assertEqual(other_service.node_states[258].nv_values, {1: 7})
        self.assertEqual(
            other_service.node_states[258].nv_progress, DiscoveryProgress.COMPLETE
        )

    def test_discovery_progress_is_independent_for_each_category(self):
        state = NodeState(
            Pnn(258, 13, 34, 3),
            parameter_progress=DiscoveryProgress.COMPLETE,
            nv_progress=DiscoveryProgress.IN_PROGRESS,
            event_progress=DiscoveryProgress.INCOMPLETE,
        )

        self.assertEqual(state.parameter_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(state.nv_progress, DiscoveryProgress.IN_PROGRESS)
        self.assertEqual(state.event_progress, DiscoveryProgress.INCOMPLETE)

    def test_parameter_progress_finishes_or_records_timeout_independently(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020000;")

        first = self.service.node_states[258]
        second = self.service.node_states[259]
        self.assertEqual(first.parameter_progress, DiscoveryProgress.COMPLETE)
        self.assertEqual(second.parameter_progress, DiscoveryProgress.IN_PROGRESS)
        self.assertEqual(first.nv_progress, DiscoveryProgress.NOT_STARTED)
        self.assertEqual(first.event_progress, DiscoveryProgress.NOT_STARTED)

        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        self.assertEqual(second.parameter_progress, DiscoveryProgress.INCOMPLETE)
        self.assertEqual(first.parameter_progress, DiscoveryProgress.COMPLETE)

    def test_paran_parameter_count_updates_state_after_discovery(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020014;")

        self.assertEqual(self.service.node_states[258].parameters, {0: 20})
        self.assertEqual(self.parameter_updates, [(258, 0, 20)])
        self.assertEqual(
            self.connection.sent,
            [b":SBFC0N73010200;", b":SBFC0N73010202;"],
        )

    def test_automatic_requests_advance_only_on_matching_replies(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020014;")
        progress_updates = []

        def record_parameter_progress(node_number):
            progress = self.service.node_states[node_number].parameter_progress
            if not progress_updates or progress_updates[-1] != progress:
                progress_updates.append(progress)

        self.service.node_state_updated.connect(record_parameter_progress)

        values = {2: 0, 4: 0, 5: 0, 6: 0, 7: 0, 10: 1, 20: 1, 19: 1, 9: 13}
        expected_indices = (0, 2, 4, 5, 6, 7, 10, 20, 19, 9)
        for index in expected_indices[1:]:
            with self.subTest(index=index):
                self.connection.frame_received.emit(
                    f":SB040N9B0102{index:02X}{values[index]:02X};".encode()
                )
                sent_count = expected_indices.index(index) + 2
                self.assertEqual(
                    self.connection.sent,
                    [
                        f":SBFC0N730102{requested:02X};".encode()
                        for requested in expected_indices[:sent_count]
                    ]
                    + ([b":SBFC0N580102;"] if index == expected_indices[-1] else []),
                )
                self.assertEqual(
                    self.service.node_states[258].parameter_progress,
                    DiscoveryProgress.COMPLETE
                    if index == expected_indices[-1]
                    else DiscoveryProgress.IN_PROGRESS,
                )

        self.assertEqual(
            self.service.node_states[258].parameters,
            {0: 20, **values},
        )
        self.assertEqual(progress_updates.count(DiscoveryProgress.COMPLETE), 1)

    def test_count_below_twenty_skips_beta_but_requests_later_indices(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020013;")

        expected_indices = (0, 2, 4, 5, 6, 7, 10, 19, 9)
        for index in expected_indices[1:]:
            self.connection.frame_received.emit(f":SB040N9B0102{index:02X}00;".encode())

        self.assertEqual(
            self.connection.sent,
            [f":SBFC0N730102{index:02X};".encode() for index in expected_indices]
            + [b":SBFC0N580102;"],
        )
        self.assertEqual(self.service.node_states[258].parameters[19], 0)
        self.assertNotIn(20, self.service.node_states[258].parameters)

    def test_unrelated_and_duplicate_replies_do_not_advance(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])
        # Node 259's count is unsolicited while node 258 owns the request.
        self.connection.frame_received.emit(b":SB040N9B01030004;")
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])
        self.assertEqual(
            self.service.node_states[259].parameter_progress,
            DiscoveryProgress.NOT_STARTED,
        )
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.connection.frame_received.emit(b":SB040N9B01030004;")
        self.connection.frame_received.emit(b":SB040N9B01020409;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.assertEqual(
            self.connection.sent,
            [
                b":SBFC0N73010200;",
                b":SBFC0N73010300;",
                b":SBFC0N73010202;",
            ],
        )
        self.assertEqual(self.service.node_states[258].parameters[4], 9)
        self.assertEqual(
            self.service.node_states[258].parameter_progress,
            DiscoveryProgress.IN_PROGRESS,
        )

        self.connection.frame_received.emit(b":SB040N9B01020200;")
        self.connection.frame_received.emit(b":SB040N9B01020200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010204;")
        self.assertEqual(self.connection.sent.count(b":SBFC0N73010204;"), 1)
        # The earlier unsolicited value does not prevent the matching reply
        # from completing this node's sequence.
        self.connection.frame_received.emit(b":SB040N9B01020409;")
        self.assertEqual(self.connection.sent.count(b":SBFC0N73010204;"), 1)
        self.assertEqual(self.connection.sent.count(b":SBFC0N73010304;"), 0)
        self.assertEqual(
            self.service.node_states[258].parameter_progress,
            DiscoveryProgress.COMPLETE,
        )

    def test_parameter_count_limits_automatic_requests(self):
        for count, expected_indices in ((0, ()), (4, (2, 4)), (6, (2, 4, 5, 6))):
            with self.subTest(count=count):
                connection = ConnectionStub("Other Layout")
                service = CbusService(connection, can_id=127)
                connection.frame_received.emit(b":SB040NB601020D2203;")
                connection.frame_received.emit(f":SB040N9B010200{count:02X};".encode())

                expected = [b":SBFE0N73010200;"]
                if expected_indices:
                    expected.append(b":SBFE0N73010202;")
                else:
                    expected.append(b":SBFE0N580102;")
                self.assertEqual(connection.sent, expected)
                self.assertEqual(service.node_states[258].parameters, {0: count})
                self.assertEqual(
                    service.node_states[258].parameter_progress,
                    DiscoveryProgress.IN_PROGRESS
                    if expected_indices
                    else DiscoveryProgress.COMPLETE,
                )
                for index in expected_indices:
                    connection.frame_received.emit(
                        f":SB040N9B0102{index:02X}00;".encode()
                    )
                    self.assertEqual(
                        service.node_states[258].parameter_progress,
                        DiscoveryProgress.COMPLETE
                        if index == expected_indices[-1]
                        else DiscoveryProgress.IN_PROGRESS,
                    )

    def test_unchanged_count_does_not_repeat_requests(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")

        self.assertEqual(
            self.connection.sent,
            [b":SBFC0N73010200;", b":SBFC0N73010202;"],
        )
        self.assertEqual(self.parameter_updates, [(258, 0, 4)])

    def test_changed_count_does_not_restart_active_sequence(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020002;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.connection.frame_received.emit(b":SB040N9B01020200;")

        self.assertEqual(
            self.connection.sent,
            [
                b":SBFC0N73010200;",
                b":SBFC0N73010202;",
                b":SBFC0N580102;",
            ],
        )
        self.assertEqual(
            self.parameter_updates, [(258, 0, 2), (258, 0, 4), (258, 2, 0)]
        )

    def test_count_requests_stay_with_their_layout(self):
        other_connection = ConnectionStub("Other Layout")
        other_service = CbusService(other_connection, can_id=127)
        pnn = b":SB040NB601020D2203;"
        self.connection.frame_received.emit(pnn)
        other_connection.frame_received.emit(pnn)

        self.connection.frame_received.emit(b":SB040N9B01020002;")
        other_connection.frame_received.emit(b":SB040N9B01020004;")

        self.assertEqual(
            self.connection.sent, [b":SBFC0N73010200;", b":SBFC0N73010202;"]
        )
        self.assertEqual(
            other_connection.sent,
            [b":SBFE0N73010200;", b":SBFE0N73010202;"],
        )
        self.assertEqual(self.service.node_states[258].parameters, {0: 2})
        self.assertEqual(other_service.node_states[258].parameters, {0: 4})

        self.connection.frame_received.emit(b":SB040N9B01020200;")
        other_connection.frame_received.emit(b":SB040N9B01020200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N580102;")
        self.assertEqual(other_connection.sent[-1], b":SBFE0N73010204;")

    def test_several_nodes_share_one_fifo_of_automatic_requests(self):
        for node in (258, 259, 260):
            self.connection.frame_received.emit(f":SB040NB6{node:04X}0D2203;".encode())
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])

        for node, next_node in ((258, 259), (259, 260), (260, 258)):
            self.connection.frame_received.emit(f":SB040N9B{node:04X}0004;".encode())
            self.assertEqual(
                self.connection.sent[-1],
                f":SBFC0N73{next_node:04X}{0 if next_node != 258 else 2:02X};".encode(),
            )

        self.connection.frame_received.emit(b":SB040N9B01020200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010204;")
        self.connection.frame_received.emit(b":SB040N9B01020400;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010302;")
        self.assertEqual(
            self.service.node_states[258].parameter_progress,
            DiscoveryProgress.COMPLETE,
        )
        self.assertEqual(
            self.service.node_states[259].parameter_progress,
            DiscoveryProgress.IN_PROGRESS,
        )

    def test_timeout_abandons_one_node_and_late_reply_does_not_restart_it(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")

        with self.assertLogs("workbench.cbus", level="WARNING") as captured:
            self.service._request_timer.timeout.emit()
        self.assertEqual(captured.records[0].fields["node_number"], 259)
        self.assertEqual(captured.records[0].fields["parameter_index"], 0)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010202;")

        self.connection.frame_received.emit(b":SB040N9B01030004;")
        self.assertEqual(self.service.node_states[259].parameters, {0: 4})
        self.assertEqual(
            self.service.node_states[259].parameter_progress,
            DiscoveryProgress.INCOMPLETE,
        )
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010202;")
        self.connection.frame_received.emit(b":SB040N9B01020200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010204;")

    def test_timeout_discards_remaining_requests_for_node(self):
        for node in (258, 259):
            self.connection.frame_received.emit(f":SB040NB6{node:04X}0D2203;".encode())
        for node in (258, 259):
            self.connection.frame_received.emit(f":SB040N9B{node:04X}0004;".encode())
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010202;")

        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010302;")
        self.connection.frame_received.emit(b":SB040N9B01020200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010302;")
        self.connection.frame_received.emit(b":SB040N9B01030200;")
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010304;")

    def test_qt_event_loop_fires_request_timeout(self):
        app = QApplication.instance() or QApplication([])
        with patch.object(cbus_service, "AUTOMATIC_REQUEST_TIMEOUT_MS", 0):
            self.connection.frame_received.emit(b":SB040NB601020D2203;")
            self.connection.frame_received.emit(b":SB040NB601030D2203;")
            with self.assertLogs("workbench.cbus", level="WARNING") as captured:
                app.processEvents()
        self.assertEqual(captured.records[0].fields["node_number"], 258)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010300;")

    def test_timeout_on_one_connection_does_not_advance_another(self):
        other_connection = ConnectionStub("Other Layout")
        other_service = CbusService(other_connection, can_id=127)
        pnn = b":SB040NB601020D2203;"
        self.connection.frame_received.emit(pnn)
        other_connection.frame_received.emit(pnn)

        with self.assertLogs("workbench.cbus", level="WARNING"):
            self.service._request_timer.timeout.emit()
        self.assertEqual(other_connection.sent, [b":SBFE0N73010200;"])
        other_connection.frame_received.emit(b":SB040N9B01020004;")
        self.assertEqual(other_connection.sent[-1], b":SBFE0N73010202;")
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;", b":SBFC0N580102;"])
        self.assertEqual(other_service.node_states[258].parameters, {0: 4})

    def test_failed_parameter_requests_keep_confirmed_count(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.send_error = ConnectionError("not connected")

        with self.assertLogs("workbench.cbus", level="ERROR"):
            self.connection.frame_received.emit(b":SB040N9B01020007;")

        self.assertEqual(self.service.node_states[258].parameters, {0: 7})
        self.assertEqual(
            self.service.node_states[258].parameter_progress,
            DiscoveryProgress.INCOMPLETE,
        )
        self.assertEqual(self.parameter_updates, [(258, 0, 7)])
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])

    def test_failed_next_request_stops_sequence_and_preserves_reply(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.connection.send_error = ConnectionError("not connected")

        with self.assertLogs("workbench.cbus", level="ERROR") as captured:
            self.connection.frame_received.emit(b":SB040N9B01020200;")

        self.assertEqual(self.service.node_states[258].parameters, {0: 4, 2: 0})
        self.assertEqual(
            self.service.node_states[258].parameter_progress,
            DiscoveryProgress.INCOMPLETE,
        )
        self.assertEqual(
            self.connection.sent, [b":SBFC0N73010200;", b":SBFC0N73010202;"]
        )
        self.assertTrue(
            any(
                record.fields.get("parameter_index") == 4 for record in captured.records
            )
        )
        self.connection.send_error = None
        self.connection.frame_received.emit(b":SB040N9B01020403;")
        self.assertEqual(len(self.connection.sent), 2)

    def test_close_clears_sequence_and_new_service_starts_fresh(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040NB601030D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.service.close()
        self.connection.frame_received.emit(b":SB040N9B01020200;")
        self.assertEqual(len(self.connection.sent), 2)
        self.assertFalse(self.service._request_timer.isActive())
        self.service._request_timer.timeout.emit()
        self.assertEqual(len(self.connection.sent), 2)

        new_service = CbusService(self.connection, can_id=126)
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020004;")
        self.assertEqual(
            self.connection.sent[-2:], [b":SBFC0N73010200;", b":SBFC0N73010202;"]
        )
        self.assertEqual(new_service.node_states[258].parameters, {0: 4})
        self.assertEqual(new_service.node_states[258].nv_values, {})

    def test_paran_for_undiscovered_node_is_ignored(self):
        self.connection.frame_received.emit(b":SB040N9B01020702;")

        self.assertEqual(self.service.nodes, {})
        self.assertEqual(self.service.node_states, {})
        self.assertEqual(self.parameter_updates, [])

    def test_pnn_identity_change_preserves_parameters(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB040N9B01020702;")
        self.connection.frame_received.emit(b":SB040NB601020D2303;")

        self.assertEqual(
            self.service.node_states[258],
            NodeState(
                Pnn(258, 13, 35, 3),
                {7: 2},
                parameter_progress=DiscoveryProgress.IN_PROGRESS,
            ),
        )
        self.assertEqual(self.updated, [Pnn(258, 13, 35, 3)])
        self.assertEqual(self.parameter_updates, [(258, 7, 2)])

    def test_repeated_pnn_is_silent_and_changed_identity_emits_update(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB060NB601020D2203;")
        self.connection.frame_received.emit(b":SB040NB601020D2303;")

        self.assertEqual(self.discovered, [Pnn(258, 13, 34, 3)])
        self.assertEqual(self.updated, [Pnn(258, 13, 35, 3)])
        self.assertEqual(self.service.nodes[258], Pnn(258, 13, 35, 3))
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])

    def test_malformed_frames_do_not_block_later_pnn(self):
        self.connection.frame_received.emit(b":SB040NB60102;")
        self.connection.frame_received.emit(b":SB040NB601020D22G3;")
        self.connection.frame_received.emit(b":SB040N0D;")
        self.connection.frame_received.emit(b":SB040NB601020D2203;")

        self.assertEqual(self.discovered, [Pnn(258, 13, 34, 3)])
        self.assertEqual(self.updated, [])

    def test_qnn_uses_assigned_can_id_and_transport_send(self):
        self.service.discover_nodes()

        self.assertEqual(self.connection.sent, [b":SBFC0N0D;"])
        self.assertEqual(self.service.nodes, {})

    def test_qnn_send_failure_is_reported(self):
        self.connection.send_error = ConnectionError("not connected")

        with (
            self.assertLogs("workbench.cbus", level="ERROR") as captured,
            self.assertRaisesRegex(ConnectionError, "not connected"),
        ):
            self.service.discover_nodes()
        self.assertEqual(self.connection.sent, [])
        self.assertEqual(len(captured.records), 1)
        self.assertIsNotNone(captured.records[0].exc_info)

    def test_services_keep_layout_state_separate(self):
        other_connection = ConnectionStub("Other Layout")
        other_service = CbusService(other_connection, can_id=127)

        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.assertEqual(other_service.nodes, {})
        other_connection.frame_received.emit(b":SB040NB601030D2203;")
        self.assertEqual(self.service.nodes, {258: Pnn(258, 13, 34, 3)})
        self.assertEqual(other_service.nodes, {259: Pnn(259, 13, 34, 3)})
        self.assertEqual(self.connection.sent, [b":SBFC0N73010200;"])
        self.assertEqual(other_connection.sent, [b":SBFE0N73010300;"])

    def test_services_keep_parameters_separate_for_same_node_number(self):
        other_connection = ConnectionStub("Other Layout")
        other_service = CbusService(other_connection, can_id=127)
        pnn_frame = b":SB040NB601020D2203;"
        self.connection.frame_received.emit(pnn_frame)
        other_connection.frame_received.emit(pnn_frame)

        self.connection.frame_received.emit(b":SB040N9B01020702;")
        other_connection.frame_received.emit(b":SB040N9B01020703;")

        self.assertEqual(self.service.node_states[258].parameters, {7: 2})
        self.assertEqual(other_service.node_states[258].parameters, {7: 3})
        self.assertEqual(self.parameter_updates, [(258, 7, 2)])
        self.service.record_nv(258, 1, 0)
        other_service.record_nv(258, 2, 7)
        self.assertEqual(self.service.node_states[258].nv_values, {1: 0})
        self.assertEqual(other_service.node_states[258].nv_values, {2: 7})

    def test_rejects_can_ids_outside_pc_range(self):
        for can_id in (0, 99, 128):
            with self.subTest(can_id=can_id), self.assertRaises(ValueError):
                CbusService(ConnectionStub("Test Layout"), can_id)


if __name__ == "__main__":
    unittest.main()

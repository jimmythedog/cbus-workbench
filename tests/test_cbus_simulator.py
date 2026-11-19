"""Frame-level contract of the simulated CBUS nodes, independent of Qt and the GUI.

Replies are decoded with Workbench's own decoders, so these tests also show
that the simulator speaks the frames the CBUS service understands.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from workbench.cbus_simulator import (
    CbusSimulator,
    load_simulated_nodes,
    node_from_metadata,
)
from workbench.cmderr import decode_cmderr
from workbench.enrsp import decode_enrsp
from workbench.neval import decode_neval
from workbench.node_backup_files import backup_directory
from workbench.numev import decode_numev
from workbench.nvans import decode_nvans
from workbench.paran import decode_paran
from workbench.pnn import decode_pnn
from workbench.wrack import decode_wrack

# CANMIO-like saved parameters: 20 parameters, 255 events, 20 EVs, 127 NVs,
# flags 0x1F. Values are taken from metadata as CW saves it, not invented.
PARAMETERS = [20, 165, 100, 32, 255, 20, 127, 3, 31, 13, 1, 0, 8, 0, 0, 134, 97]


def request(opcode: int, *data: int) -> bytes:
    """A frame as Workbench sends it, from PC CAN ID 126."""
    return f":SBFC0N{bytes((opcode, *data)).hex().upper()};".encode()


def sender_can_id(frame: bytes) -> int:
    return (int(frame[2:6], 16) >> 5) & 0x7F


def node(number=256, can_id=4, parameters=PARAMETERS):
    result = node_from_metadata(number, {"canId": can_id, "parameters": parameters})
    assert not isinstance(result, str), result
    return result


class CbusSimulatorTests(unittest.TestCase):
    def test_qnn_reports_each_node_with_saved_identity_and_can_id(self):
        # Saved flags are preserved, including the VLCB bit (0x40).
        vlcb = [5, 165, 2, 113, 32, 2, 9, 2, 0x4F]
        simulator = CbusSimulator([node(300, 7, vlcb), node(256, 4)])

        replies = simulator.handle(request(0x0D))

        self.assertEqual(
            [decode_pnn(reply) for reply in replies],
            [
                decode_pnn(b":SB080NB60100A5201F;"),
                decode_pnn(b":SB0E0NB6012CA5714F;"),
            ],
        )
        self.assertEqual([sender_can_id(reply) for reply in replies], [4, 7])

    def test_rqnpn_returns_saved_parameters_and_rejects_indices_beyond_count(self):
        simulator = CbusSimulator([node()])

        for index in (0, 1, 6, 8, 16):
            with self.subTest(index=index):
                (reply,) = simulator.handle(request(0x73, 0x01, 0x00, index))
                paran = decode_paran(reply)
                self.assertEqual(
                    (paran.node_number, paran.parameter_index, paran.parameter_value),
                    (256, index, PARAMETERS[index]),
                )
                self.assertEqual(sender_can_id(reply), 4)
        (reply,) = simulator.handle(request(0x73, 0x01, 0x00, 21))
        self.assertEqual(decode_cmderr(reply).code, 9)

    def test_unknown_saved_parameters_are_not_answered(self):
        # Within the count but not saved: a reply would invent a value.
        partial = [20, 165, None, 32, None, None, None, None, 31]
        simulator = CbusSimulator([node(parameters=partial)])

        for index in (2, 4, 9, 20):
            with self.subTest(index=index):
                self.assertEqual(simulator.handle(request(0x73, 1, 0, index)), [])
        # Unknown count: indices beyond the saved list stay unknown too.
        simulator = CbusSimulator([node(parameters=[None, 165, 1, 32, 2, 3, 4, 5, 31])])
        self.assertEqual(simulator.handle(request(0x73, 1, 0, 0)), [])
        self.assertEqual(simulator.handle(request(0x73, 1, 0, 30)), [])

    def test_nvs_start_at_zero_for_the_confirmed_count(self):
        simulator = CbusSimulator([node()])

        for index in (1, 127):
            with self.subTest(index=index):
                (reply,) = simulator.handle(request(0x71, 0x01, 0x00, index))
                nvans = decode_nvans(reply)
                self.assertEqual(
                    (nvans.node_number, nvans.nv_index, nvans.nv_value),
                    (256, index, 0),
                )
        for index in (0, 128):
            with self.subTest(index=index):
                (reply,) = simulator.handle(request(0x71, 0x01, 0x00, index))
                self.assertEqual(decode_cmderr(reply).code, 10)

    def read_nv(self, simulator, node_high, node_low, index):
        (reply,) = simulator.handle(request(0x71, node_high, node_low, index))
        return decode_nvans(reply).nv_value

    def test_nvset_acknowledges_and_changes_only_that_node_and_nv(self):
        simulator = CbusSimulator([node(256, 4), node(257, 5)])

        (reply,) = simulator.handle(request(0x96, 0x01, 0x00, 3, 0xA5))

        self.assertEqual(decode_wrack(reply).node_number, 256)
        self.assertEqual(sender_can_id(reply), 4)
        self.assertEqual(self.read_nv(simulator, 0x01, 0x00, 3), 0xA5)
        self.assertEqual(self.read_nv(simulator, 0x01, 0x00, 2), 0)
        self.assertEqual(self.read_nv(simulator, 0x01, 0x01, 3), 0)
        # Any byte is accepted; value validation is module-specific firmware.
        simulator.handle(request(0x96, 0x01, 0x00, 127, 0xFF))
        self.assertEqual(self.read_nv(simulator, 0x01, 0x00, 127), 0xFF)

    def test_nvset_rejects_invalid_indices_without_changing_nvs(self):
        simulator = CbusSimulator([node()])

        for index in (0, 128):
            with self.subTest(index=index):
                (reply,) = simulator.handle(request(0x96, 0x01, 0x00, index, 7))
                self.assertEqual(decode_cmderr(reply).code, 10)
        self.assertEqual(
            {self.read_nv(simulator, 0x01, 0x00, index) for index in range(1, 128)},
            {0},
        )

    def test_nv_requests_without_a_saved_nv_count_are_not_answered(self):
        without_nv_count = [20, 165, 100, 32, 255, 20, None, 3, 31]
        simulator = CbusSimulator([node(parameters=without_nv_count)])

        self.assertEqual(simulator.handle(request(0x71, 0x01, 0x00, 1)), [])
        self.assertEqual(simulator.handle(request(0x96, 0x01, 0x00, 1, 5)), [])
        # The node itself is still identified and its known parameters read.
        self.assertEqual(len(simulator.handle(request(0x0D))), 1)
        self.assertIsNotNone(decode_paran(simulator.handle(request(0x73, 1, 0, 1))[0]))

    def test_other_traffic_is_ignored(self):
        simulator = CbusSimulator([node()])

        for frame in (
            request(0x73, 0x01, 0x01, 1),  # Another node number.
            request(0x71, 0x01, 0x00),  # Too short for NVRD.
            request(0x96, 0x01, 0x01, 1, 5),  # NVSET for another node number.
            request(0xB6, 0x01, 0x00, 165, 32, 31),  # A reply, not a request.
            request(0x90, 0x01, 0x00, 0x00, 0x01),  # ACON event.
            request(0x10),  # RQNP: simulated nodes are never in setup mode.
            request(0x0C),  # Not an opcode Workbench recognises.
            b":X00080004N0D;",  # Extended frame.
            b":SBFC0R;",  # No data.
            b"not a frame",
        ):
            with self.subTest(frame=frame):
                self.assertEqual(simulator.handle(frame), [])


def nn(number):
    return tuple(number.to_bytes(2))


def learn(number):
    return request(0x53, *nn(number))


def unlearn(number):
    return request(0x54, *nn(number))


def teach(event_node, event_number, ev_index, value):
    return request(0xD2, *nn(event_node), *nn(event_number), ev_index, value)


def evans(reply):
    """(event NN, event number, EV index, value) from an EVANS reply."""
    payload = bytes.fromhex(reply.decode()[7:-1])
    assert payload[0] == 0xD3, reply
    return (int.from_bytes(payload[1:3]), int.from_bytes(payload[3:5]), *payload[5:])


class EventTableTests(unittest.TestCase):
    def setUp(self):
        self.simulator = CbusSimulator([node(256, 4), node(257, 5)])

    def handle(self, frame):
        return self.simulator.handle(frame)

    def reqev(self, event_node, event_number, ev_index):
        (reply,) = self.handle(
            request(0xB2, *nn(event_node), *nn(event_number), ev_index)
        )
        return evans(reply) if reply[7:9] == b"D3" else decode_cmderr(reply).code

    def reval(self, number, slot, ev_index):
        (reply,) = self.handle(request(0x9C, *nn(number), slot, ev_index))
        neval = decode_neval(reply)
        return neval.value if neval else decode_cmderr(reply).code

    def stored(self, number):
        (count,) = self.handle(request(0x58, *nn(number)))
        events = self.handle(request(0x57, *nn(number)))
        return decode_numev(count).stored_event_count, [
            (enrsp.event_index, enrsp.event_node_number, enrsp.event_number)
            for enrsp in map(decode_enrsp, events)
        ]

    def test_vlcb_nodes_report_learn_mode_in_parameter_8(self):
        # Saved flags include bit 5 to show the saved value does not decide it.
        vlcb = [8, 165, 1, 32, 4, 2, 0, 3, 0x7F]
        legacy = [8, 165, 1, 32, 4, 2, 0, 3, 0x3F]
        simulator = CbusSimulator([node(256, 4, vlcb), node(257, 5, legacy)])

        def flags():
            return [
                decode_paran(
                    simulator.handle(request(0x73, *nn(number), 8))[0]
                ).parameter_value
                for number in (256, 257)
            ]

        self.assertEqual(flags(), [0x5F, 0x3F])
        simulator.handle(learn(256))
        self.assertEqual(flags(), [0x7F, 0x3F])
        simulator.handle(learn(257))
        self.assertEqual(flags(), [0x5F, 0x3F])
        simulator.handle(learn(256))
        simulator.handle(unlearn(256))
        self.assertEqual(flags(), [0x5F, 0x3F])

    def test_teaching_needs_learn_mode_and_fills_ev_gaps_with_zero(self):
        self.assertEqual(self.handle(teach(300, 5, 2, 7)), [])
        self.assertEqual(self.stored(256), (0, []))

        self.assertEqual(self.handle(learn(256)), [])
        (reply,) = self.handle(teach(300, 5, 2, 7))
        self.assertEqual(decode_wrack(reply).node_number, 256)
        self.assertEqual(sender_can_id(reply), 4)
        # EVANS names the event (VLCB Opcode specification), not the consumer.
        self.assertEqual(self.reqev(300, 5, 2), (300, 5, 2, 7))
        self.assertEqual(self.reqev(300, 5, 1), (300, 5, 1, 0))
        self.assertEqual(self.reqev(300, 5, 3), 5)  # Above the highest taught EV.
        self.assertEqual(self.reqev(300, 5, 0), (300, 5, 0, 2))  # Number of EVs.
        self.assertEqual(self.reqev(300, 5, 21), 6)
        self.assertEqual(self.reqev(300, 6, 1), 7)
        self.assertEqual(self.handle(unlearn(256)), [])
        self.assertEqual(
            self.handle(request(0xB2, *nn(300), *nn(5), 2)), []
        )  # REQEV is answered only in learn mode.

        # Discovery reads work in normal mode, with 1-based slots.
        self.assertEqual(self.stored(256), (1, [(1, 300, 5)]))
        self.assertEqual([self.reval(256, 1, ev) for ev in (1, 2, 3, 21)], [0, 7, 5, 6])
        self.assertEqual(self.reval(256, 2, 1), 7)
        # EV 0 is the number of EVs (CBUSlib); CW's decoder never requests it.
        self.assertEqual(
            self.handle(request(0x9C, *nn(256), 1, 0)), [b":SB080NB50100010002;"]
        )
        self.assertEqual(self.stored(257), (0, []))

    def test_events_change_and_unlearn_by_identity_including_short_events(self):
        self.handle(learn(256))
        self.handle(teach(300, 5, 1, 1))
        self.handle(teach(0, 5, 1, 2))  # Short event 5: a distinct identity.
        self.handle(teach(300, 5, 1, 9))  # Changes the existing event.
        self.assertEqual(self.reqev(0, 5, 1), (0, 5, 1, 2))
        self.assertEqual(self.reqev(300, 5, 1), (300, 5, 1, 9))

        self.assertEqual(self.handle(request(0x95, *nn(300), *nn(5))), [])
        self.assertEqual(self.handle(request(0x95, *nn(300), *nn(99))), [])
        self.assertEqual(self.reqev(300, 5, 1), 7)
        # The freed slot is reused, so slots identify table positions only.
        self.handle(teach(400, 1, 1, 3))
        self.handle(unlearn(256))
        self.assertEqual(self.stored(256), (2, [(1, 400, 1), (2, 0, 5)]))

    def test_invalid_teaching_changes_nothing(self):
        small = CbusSimulator([node(parameters=[8, 165, 1, 32, 1, 2, 0, 3, 31])])
        small.handle(learn(256))

        for ev_index in (0, 3):
            with self.subTest(ev_index=ev_index):
                (reply,) = small.handle(teach(300, 5, ev_index, 1))
                self.assertEqual(decode_cmderr(reply).code, 6)
        small.handle(teach(300, 5, 1, 1))
        (reply,) = small.handle(teach(300, 6, 1, 1))
        self.assertEqual(decode_cmderr(reply).code, 4)  # One-event table is full.
        (count,) = small.handle(request(0x58, *nn(256)))
        self.assertEqual(decode_numev(count).stored_event_count, 1)

    def test_nnlrn_for_another_node_ends_learn_mode(self):
        self.handle(learn(256))
        self.handle(learn(257))  # CBUSlib: node 256 leaves learn mode.
        replies = self.handle(teach(300, 5, 1, 1))
        self.assertEqual([decode_wrack(reply).node_number for reply in replies], [257])

        self.handle(unlearn(256))  # Addressed to another node: 257 keeps learning.
        self.assertEqual(len(self.handle(teach(300, 5, 1, 2))), 1)
        self.handle(learn(999))  # Not simulated, but still ends 257's learn mode.
        self.assertEqual(self.handle(teach(300, 5, 1, 3)), [])
        self.assertEqual(self.stored(256), (0, []))

    def test_unknown_event_capacity_leaves_only_event_requests_unanswered(self):
        no_ev_count = CbusSimulator(
            [node(parameters=[8, 165, 1, 32, 4, None, 0, 3, 31])]
        )
        no_ev_count.handle(learn(256))
        self.assertEqual(no_ev_count.handle(teach(300, 5, 1, 1)), [])
        self.assertEqual(no_ev_count.handle(request(0x9C, 1, 0, 1, 1)), [])

        no_table_size = CbusSimulator(
            [node(parameters=[8, 165, 1, 32, None, 2, 0, 3, 31])]
        )
        no_table_size.handle(learn(256))
        self.assertEqual(no_table_size.handle(teach(300, 5, 1, 1)), [])
        (count,) = no_table_size.handle(request(0x58, 1, 0))
        self.assertEqual(decode_numev(count).stored_event_count, 0)


class LoadSimulatedNodesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        paths = patch(
            "workbench.node_backup_files.application_directories",
            return_value={"Data": Path(temp.name)},
        )
        paths.start()
        self.addCleanup(paths.stop)

    def save(self, number, metadata):
        path = backup_directory("yard", number).parent / "metadata.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump(metadata))

    def test_only_metadata_that_identifies_a_node_is_simulated(self):
        self.save(256, {"canId": 4, "parameters": PARAMETERS})
        # Identification needs only CAN ID and parameters 1, 3 and 8.
        self.save(
            257, {"canId": 5, "parameters": [None, 165, None, 32] + [None] * 4 + [31]}
        )
        self.save(258, {"parameters": PARAMETERS})
        self.save(259, {"canId": 6, "parameters": PARAMETERS[:8]})
        self.save(261, ["not", "a", "mapping"])
        backup = backup_directory("yard", 260)
        backup.mkdir(parents=True)
        (backup / "2026-01-01_00-00-00-000000.yaml").write_text("node: 260\n")

        nodes, skipped = load_simulated_nodes("yard")

        self.assertEqual([simulated.node_number for simulated in nodes], [256, 257])
        self.assertEqual(
            skipped,
            {
                258: "no saved CAN ID",
                259: "missing flags",
                260: "no saved CAN ID",
                261: "unreadable metadata",
            },
        )


if __name__ == "__main__":
    unittest.main()

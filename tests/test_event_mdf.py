"""Visible EV interpretation and preservation of the raw editing contract."""

import json
import os
import unittest
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workbench.cbus_service import NodeState
from workbench.node_events import NodeEvents
from workbench.pnn import Pnn


class EventMdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.events = NodeEvents()
        self.addCleanup(self.events.close)
        self.state = NodeState(
            Pnn(258, 165, 32, 0),
            parameters={5: 3},
            event_identities={1: (0, 45)},
            ev_values={1: {1: 0, 2: 137}},
            nv_values={16: 1},
        )
        self.mdf = json.loads(
            (Path(__file__).parent / "fixtures/mdfs/canmio-3d-ev2.json").read_text()
        )

    def show(self, mdf=None, *, expand=True):
        self.events.show_live_state(self.state, self.mdf if mdf is None else mdf)
        event = self.events.consumed_table.topLevelItem(0)
        if expand:
            event.setExpanded(True)
        return event

    def test_collapsed_events_build_once_on_expansion_and_retain_on_refresh(self):
        event = self.show(expand=False)
        tree = self.events.consumed_table
        self.assertEqual(event.childCount(), 3)
        self.assertEqual(event.child(1).text(1), "137")
        self.assertIsNone(tree.itemWidget(event.child(1), 1))
        event.setExpanded(True)
        form = tree.itemWidget(event.child(1), 1)
        self.assertIsNotNone(form)
        event.setExpanded(False)
        event.setExpanded(True)
        self.assertIs(tree.itemWidget(event.child(1), 1), form)
        self.show()
        self.assertIs(tree.itemWidget(event.child(1), 1), form)
        # A changed MDF context must take effect even on the same MDF object.
        self.mdf["eventVariables"][0]["groupItems"][0]["displayTitle"] = "New action"
        event = self.show(expand=False)
        self.assertTrue(event.isExpanded())
        self.assertIn(
            "New action:",
            [
                label.text()
                for label in tree.itemWidget(event.child(1), 1).findChildren(QLabel)
            ],
        )

    def test_expand_during_edit_preserves_unread_raw_values(self):
        self.state.ev_values[1].pop(2)
        event = self.show(expand=False)
        desired = {
            "nvs": [None] * 15 + [1],
            "events": [{"nodeNumber": 0, "eventNumber": 45, "eventVariables": [0]}],
        }
        self.events.begin_configuration_edit(desired)
        event.setExpanded(True)
        row = event.child(1)
        form = self.events.consumed_table.itemWidget(row, 1)
        self.assertFalse(row.isHidden())
        self.assertEqual(form.raw_value.text(), "")
        self.assertFalse(form.raw_value.isReadOnly())
        self.assertFalse(self.control(row, QComboBox).isEnabled())
        form.raw_value.setText("255")
        form.update_raw_value()
        self.assertEqual(desired["events"][0]["eventVariables"], [0, 255])
        self.events.cancel_edit()
        row = self.events.consumed_table.topLevelItem(0).child(1)
        self.assertEqual(row.text(1), "")
        self.assertTrue(row.isHidden())

    def test_collapsed_refresh_uses_latest_values_and_visibility_on_expansion(self):
        group = self.mdf["eventVariables"][0]
        group["visibilityLogic"] = {"nv": 16, "equals": 1}
        self.show(expand=False)
        self.state.nv_values[16] = 0
        self.state.ev_values[1][2] = 138
        event = self.show(expand=False)
        self.assertFalse(event.isExpanded())
        self.assertEqual(event.child(1).text(1), "138")
        self.assertIsNone(self.events.consumed_table.itemWidget(event.child(1), 1))
        event.setExpanded(True)
        self.assertTrue(self.control(event.child(1), QComboBox).isHidden())
        self.state.nv_values[16] = 1
        event = self.show(expand=False)
        self.assertTrue(event.isExpanded())
        self.assertEqual(self.control(event.child(1), QComboBox).currentData(), 10)

    def test_desired_edits_sync_duplicates_bits_visibility_and_lazy_expansion(self):
        number = {
            "type": "EventVariableNumber",
            "eventVariableIndex": 2,
            "displayTitle": "Low bits",
            "startBit": 0,
            "endBit": 3,
        }
        bit = {
            "type": "EventVariableBitSingle",
            "eventVariableIndex": 2,
            "displayTitle": "Flag",
            "bit": 7,
            "visibilityLogic": {"nv": 16, "equals": 1},
        }
        mdf = {"eventVariables": [number, dict(number), bit]}
        event = self.show(mdf, expand=False)
        desired = {
            "nvs": [0] * 16,
            "events": [
                {"nodeNumber": 0, "eventNumber": 45, "eventVariables": [0, 137]}
            ],
        }
        self.events.begin_configuration_edit(desired)
        event.child(1).setText(1, "138")
        self.assertIsNone(self.events.consumed_table.itemWidget(event.child(1), 1))
        event.setExpanded(True)
        form = self.events.consumed_table.itemWidget(event.child(1), 1)
        numbers = form.findChildren(QDoubleSpinBox)
        self.assertEqual([n.value() for n in numbers], [10, 10])
        flag = form.findChild(QCheckBox)
        self.assertTrue(flag.isHidden())
        desired["nvs"][15] = 1
        self.events.refresh_configuration_controls()
        self.assertFalse(flag.isHidden())
        flag.click()
        self.assertEqual(desired["events"][0]["eventVariables"][1], 10)
        numbers[0].setValue(3)
        self.assertEqual(numbers[1].value(), 3)
        self.assertEqual(event.child(1).text(1), "3")
        self.assertEqual(self.state.ev_values[1][2], 137)
        self.events.cancel_edit()
        event = self.events.consumed_table.topLevelItem(0)
        self.assertEqual(event.child(1).text(1), "137")
        self.assertFalse(self.control(event.child(1), QDoubleSpinBox).isEnabled())

    def control(self, ev, kind):
        widget = self.events.consumed_table.itemWidget(ev, 1)
        return widget.findChild(kind)

    def test_canmio_multiple_controls_mask_bits_and_unknown_labels(self):
        ev = self.show().child(1)
        self.assertEqual((ev.text(0), ev.text(1)), ("EV 2", "137"))
        self.assertEqual(
            [
                label.text()
                for label in self.events.consumed_table.itemWidget(ev, 1).findChildren(
                    QLabel
                )
            ],
            ["Action:", "Simultaneous:"],
        )
        action = self.control(ev, QComboBox)
        simultaneous = self.control(ev, QCheckBox)
        self.assertEqual(action.currentData(), 9)  # 137 & 127, without shifting
        self.assertIn("ON", action.currentText())
        self.assertTrue(simultaneous.isChecked())
        self.assertFalse(action.isEnabled())
        self.assertFalse(simultaneous.isEnabled())
        self.assertEqual(ev.childCount(), 0)
        parent = ev.parent()
        parent.setExpanded(True)
        self.events.resize(1100, 500)
        self.events.show()
        self.app.processEvents()
        container = self.events.consumed_table.itemWidget(ev, 1)
        self.assertGreaterEqual(
            self.events.consumed_table.visualItemRect(ev).height(),
            container.sizeHint().height(),
        )
        self.assertLess(
            container.raw_value.geometry().right(), action.geometry().left()
        )
        self.assertLess(action.geometry().right(), simultaneous.geometry().left())
        for control in (action, simultaneous):
            self.assertAlmostEqual(
                container.raw_value.geometry().center().y(),
                control.geometry().center().y(),
                delta=1,
            )
        self.assertLessEqual(
            container.height(),
            max(container.raw_value.sizeHint().height(), action.sizeHint().height()),
        )
        for label in container.findChildren(QLabel):
            self.assertGreaterEqual(
                label.width(), label.fontMetrics().horizontalAdvance(label.text())
            )
        self.assertGreaterEqual(action.width(), action.minimumSizeHint().width())
        self.state.nv_values.clear()
        ev = self.show().child(1)
        self.assertIn("Unknown label", self.control(ev, QComboBox).currentText())
        self.state.ev_values[1][2] = 6  # Not a defined action
        ev = self.show().child(1)
        self.assertEqual(self.control(ev, QComboBox).currentIndex(), -1)
        self.assertEqual(self.control(ev, QComboBox).placeholderText(), "6")

    def test_visibility_per_definition_including_groups_and_tab_panels(self):
        number = {
            "type": "EventVariableNumber",
            "eventVariableIndex": 2,
            "displayTitle": "Output",
        }
        bit = {
            "type": "EventVariableBitSingle",
            "eventVariableIndex": 2,
            "displayTitle": "Simultaneous",
            "bit": 7,
            "visibilityLogic": {"evBit": {"index": 2, "bit": 7}, "equals": 1},
        }
        mdf = {
            "eventVariables": [
                {
                    "type": "EventVariableTabs",
                    "visibilityLogic": {"nv": 16, "equals": 1},
                    "tabPanels": [
                        {
                            "displayTitle": "Mode",
                            "visibilityLogic": {"ev": 1, "equals": 0},
                            "items": [
                                {
                                    "type": "EventVariableGroup",
                                    "displayTitle": "Actions",
                                    "visibilityLogic": {"ev": 3, "equals": 1},
                                    "groupItems": [number, bit],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        ev = self.show(mdf).child(1)
        self.assertEqual(ev.childCount(), 0)
        self.assertIsNotNone(self.control(ev, QCheckBox))  # Unknown stays visible.
        self.assertIn("Visibility unknown", self.control(ev, QDoubleSpinBox).toolTip())
        self.state.ev_values[1][3] = 1
        self.state.ev_values[1][2] = 9
        ev = self.show(mdf).child(1)
        self.assertTrue(self.control(ev, QCheckBox).isHidden())
        self.assertEqual(self.control(ev, QDoubleSpinBox).value(), 9)
        self.state.nv_values[16] = 0
        self.assertTrue(
            self.control(self.show(mdf).child(1), QDoubleSpinBox).isHidden()
        )

    def test_numeric_bits_array_and_unread_values(self):
        mdf = {
            "eventVariables": [
                {
                    "type": "EventVariableSlider",
                    "eventVariableIndex": 2,
                    "displayTitle": "Delay",
                    "startBit": 0,
                    "endBit": 3,
                    "displayScale": 0.5,
                    "displayOffset": 1,
                    "displayUnits": "s",
                },
                {
                    "type": "EventVariableBitArray",
                    "eventVariableIndex": 3,
                    "displayTitle": "Flags",
                    "bitCollection": [
                        {"bitPosition": 0, "label": "Active"},
                        {"bitPosition": 7, "label": "Invert"},
                    ],
                },
                {
                    "type": "EventVariableNumber",
                    "eventVariableIndex": 3,
                    "displayTitle": "Unknown number",
                },
            ]
        }
        parent = self.show(mdf)
        self.assertEqual(self.control(parent.child(1), QDoubleSpinBox).value(), 5.5)
        self.events.set_editing(True)
        unread = parent.child(2)
        self.assertEqual(unread.text(1), "")
        widget = self.events.consumed_table.itemWidget(unread, 1)
        bits = widget.findChildren(QCheckBox)
        self.assertEqual(
            [b.checkState() for b in bits], [Qt.CheckState.PartiallyChecked] * 2
        )
        self.assertEqual(self.control(unread, QDoubleSpinBox).text(), "")
        parent.setExpanded(True)
        self.events.resize(1100, 500)
        self.events.show()
        self.app.processEvents()
        self.assertEqual(unread.childCount(), 0)
        # Two BitArray checkboxes plus the number are three actual controls,
        # so the raw value, array and number retain separate lines.
        number = self.control(unread, QDoubleSpinBox)
        self.assertLess(
            widget.raw_value.geometry().bottom(),
            bits[0].mapTo(widget, bits[0].rect().topLeft()).y(),
        )
        self.assertLess(
            bits[1].mapTo(widget, bits[1].rect().bottomLeft()).y(),
            number.mapTo(widget, number.rect().topLeft()).y(),
        )
        self.assertGreaterEqual(
            self.events.consumed_table.visualItemRect(unread).height(),
            widget.sizeHint().height(),
        )
        self.state.ev_values[1][3] = 128
        unread = self.show(mdf).child(2)
        widget = self.events.consumed_table.itemWidget(unread, 1)
        self.assertEqual(
            [b.isChecked() for b in widget.findChildren(QCheckBox)], [False, True]
        )
        # A BitArray alone with two checkboxes uses the same compact rule.
        mdf["eventVariables"].pop()
        unread = self.show(mdf).child(2)
        self.app.processEvents()
        widget = self.events.consumed_table.itemWidget(unread, 1)
        for bit in widget.findChildren(QCheckBox):
            self.assertAlmostEqual(
                widget.raw_value.geometry().center().y(),
                bit.geometry().center().y(),
                delta=1,
            )

    def test_raw_editing_refresh_selection_and_expansion(self):
        parent = self.show()
        ev = parent.child(1)
        parent.setExpanded(True)
        self.events.consumed_table.setCurrentItem(ev)
        # Rediscovery changes the slot, but event identity and EV number persist.
        self.state.event_identities = {4: (0, 45)}
        self.state.ev_values = {4: {1: 0, 2: 138}}
        parent = self.show()
        ev = parent.child(1)
        self.assertTrue(parent.isExpanded())
        self.assertEqual(ev.childCount(), 0)
        self.assertIs(self.events.consumed_table.currentItem(), ev)
        desired = {
            "nvs": [None] * 15 + [1],
            "events": [
                {"nodeNumber": 0, "eventNumber": 45, "eventVariables": [0, 138]}
            ],
        }
        self.events.begin_configuration_edit(desired)
        raw = self.events.consumed_table.itemWidget(ev, 1).raw_value
        self.events.resize(1000, 500)
        self.events.show()
        self.app.processEvents()
        QTest.mouseClick(raw, Qt.MouseButton.LeftButton)
        raw.selectAll()
        QTest.keyClicks(raw, "255")
        QTest.keyClick(raw, Qt.Key.Key_Tab)
        self.assertEqual(desired["events"][0]["eventVariables"], [0, 255])
        self.assertTrue(self.control(ev, QComboBox).isEnabled())
        self.assertEqual(self.control(ev, QComboBox).currentIndex(), -1)
        self.assertIs(self.events.consumed_table.currentItem(), ev)
        self.assertEqual(ev.text(1), "255")
        action = self.control(ev, QComboBox)
        action.setCurrentIndex(action.findData(10))
        self.assertEqual(desired["events"][0]["eventVariables"], [0, 138])
        self.assertEqual(raw.text(), "138")
        self.assertTrue(self.control(ev, QCheckBox).isChecked())
        QTest.mouseClick(raw, Qt.MouseButton.LeftButton)
        raw.selectAll()
        QTest.keyClick(raw, Qt.Key.Key_Backspace)
        QTest.keyClick(raw, Qt.Key.Key_Tab)
        self.assertEqual(desired["events"][0]["eventVariables"], [0])
        QTest.mouseClick(raw, Qt.MouseButton.LeftButton)
        QTest.keyClicks(raw, "0")
        QTest.keyClick(raw, Qt.Key.Key_Tab)
        self.assertEqual(desired["events"][0]["eventVariables"], [0, 0])
        QTest.mouseClick(raw, Qt.MouseButton.LeftButton)
        raw.selectAll()
        QTest.keyClicks(raw, "256")
        QTest.keyClick(raw, Qt.Key.Key_Tab)
        self.assertEqual(raw.text(), "256")
        self.assertEqual(desired["events"][0]["eventVariables"], [0, 0])
        # Incoming values do not replace an active raw editor or its MDF controls.
        self.state.ev_values[4][2] = 139
        self.events.show_live_state(self.state, self.mdf)
        self.assertEqual(raw.text(), "256")
        window = QWidget()
        self.addCleanup(window.close)
        self.addCleanup(self.events.setParent, None)
        layout = QVBoxLayout(window)
        layout.addWidget(self.events)
        save = QPushButton("Save")
        layout.addWidget(save)
        submitted = []
        save.clicked.connect(lambda: submitted.append(deepcopy(desired)))
        window.resize(1100, 500)
        window.show()
        self.app.processEvents()
        QTest.mouseClick(raw, Qt.MouseButton.LeftButton)
        raw.selectAll()
        QTest.keyClicks(raw, "254")
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)
        self.assertEqual(submitted[0]["events"][0]["eventVariables"], [0, 254])
        self.events.cancel_edit()
        self.assertEqual(
            self.events.consumed_table.topLevelItem(0).child(1).text(1), "139"
        )

    def test_unsupported_definitions_and_sparse_indices_keep_raw_rows(self):
        mdf = {
            "eventVariables": [
                {
                    "type": "EventVariableDual",
                    "eventVariableIndexHigh": 1,
                    "eventVariableIndexLow": 2,
                    "displayTitle": "Dual",
                },
                {
                    "type": "EventVariableCollectionSelect",
                    "eventVariableCollection": [1, 2],
                },
                {"type": "FutureControl", "eventVariableIndex": 1},
                {
                    "type": "EventVariableNumber",
                    "eventVariableIndex": 3,
                    "displayTitle": "Third",
                },
            ]
        }
        parent = self.show(mdf)
        self.assertEqual([parent.child(i).childCount() for i in range(3)], [0, 0, 0])
        self.assertIsNone(self.events.consumed_table.itemWidget(parent.child(0), 1))
        self.assertIsNone(self.events.consumed_table.itemWidget(parent.child(1), 1))
        self.assertEqual(parent.child(1).text(1), "137")
        self.state.parameters.clear()
        self.state.ev_values[1] = {3: 42}
        parent = self.show(mdf)
        self.assertEqual(parent.childCount(), 1)
        self.assertEqual(parent.child(0).text(0), "EV 3")
        self.assertEqual(self.control(parent.child(0), QDoubleSpinBox).value(), 42)

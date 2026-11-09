"""Observable contracts for the first, read-only MDF form slice."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
)

from workbench.node import Node
from workbench.node_variables import MdfNodeVariables


class MdfFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.node = Node(256, "Prototype", 126, "", True)
        self.values = [0, 12, 129, 0, 23, 45, 128, 67, 89, 90]
        self.view = MdfNodeVariables()
        self.addCleanup(self.view.close)
        self.view.show_node(self.node, self.values)

    def test_real_dual_values_missing_bytes_and_shared_raw_edits(self):
        definition = json.loads(
            Path("tests/fixtures/mdfs/mmctest-dual.json").read_text()
        )
        view = MdfNodeVariables(definition)
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        controls = view.pages.currentWidget().findChildren(QDoubleSpinBox)
        values = {40: 1, 41: 2, 42: 0xAB, 43: 0xCD}
        view.show_live_values(43, values)
        self.assertEqual(
            [c.value() for c in controls],
            [258, 258, 4398.1, 439.81, 44081, 3021, 2748],
        )
        self.assertTrue(all(not c.isEnabled() for c in controls))
        self.assertEqual(controls[0].suffix(), " mS")
        self.assertIn("outside MDF range", controls[1].toolTip())
        for missing in (40, 41):
            view.show_live_values(43, {k: v for k, v in values.items() if k != missing})
            self.assertEqual(controls[0].text(), "")
        working = [0] * 43
        view.show_node(self.node, working)
        view.set_editing(True)
        view.raw_values.item(39, 1).setText("255")
        view.raw_values.item(40, 1).setText("255")
        view.navigation.setCurrentRow(0)
        view.navigation.setCurrentRow(1)
        self.assertEqual(controls[0].value(), 65535)
        self.assertEqual(working[39:41], [255, 255])
        self.assertTrue(all(not c.isEnabled() for c in controls))

    def test_dual_visibility_and_invalid_indices_or_bits(self):
        definition = json.loads(
            Path("tests/fixtures/mdfs/mmctest-dual.json").read_text()
        )
        dual = definition["nodeVariables"][0]
        dual["visibilityLogic"] = {"nv": 1, "equals": 2}
        view = MdfNodeVariables({"nodeVariables": [dual]})
        self.addCleanup(view.close)
        form = view.pages.widget(1)
        control = form.findChild(QDoubleSpinBox)
        for values, visible in [({1: 0}, False), ({1: 2}, True), ({}, True)]:
            view.show_live_values(43, values)
            self.assertEqual(not control.isHidden(), visible)
        self.assertIn("Visibility unknown", control.toolTip())
        for properties in (
            {"nodeVariableIndexHigh": 0},
            {"nodeVariableIndexLow": 256},
            {"endBit": 16},
            {"startBit": 12, "endBit": 4},
        ):
            with self.subTest(properties=properties), self.assertRaises(ValueError):
                view.set_definition({"nodeVariables": [{**dual, **properties}]})

    def slider_view(self, **attributes):
        slider = {
            "type": "NodeVariableSlider",
            "nodeVariableIndex": 2,
            "displayTitle": "Delay",
            **attributes,
        }
        view = MdfNodeVariables(
            {
                "nodeVariables": [
                    {
                        "type": "NodeVariableTabs",
                        "tabPanels": [{"displayTitle": "Timing", "items": [slider]}],
                    }
                ]
            }
        )
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        return view, view.pages.currentWidget().findChild(QDoubleSpinBox)

    def test_bit_array_order_states_unknowns_and_group_visibility(self):
        bits = {
            "type": "NodeVariableBitArray",
            "nodeVariableIndex": 2,
            "displayTitle": "Flags",
            "bitCollection": [
                {"bitPosition": bit, "label": label}
                for bit, label in [(7, "High"), (0, "Low"), (4, "Middle")]
            ],
        }
        view = MdfNodeVariables(
            {
                "nodeVariables": [
                    {
                        "type": "NodeVariableGroup",
                        "displayTitle": "Group",
                        "visibilityLogic": {"nv": 1, "equals": 1},
                        "groupItems": [bits],
                    }
                ]
            }
        )
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        form = view.pages.currentWidget()
        checks = form.findChildren(QCheckBox)
        self.assertEqual([c.text() for c in checks], ["High", "Low", "Middle"])
        for values, states in [
            ({1: 1, 2: 129}, [2, 2, 0]),
            ({1: 1, 2: 16}, [0, 0, 2]),
            ({1: 1}, [1, 1, 1]),
            ({1: 1, 2: 0}, [0, 0, 0]),
        ]:
            view.show_live_values(2, values)
            self.assertEqual([c.checkState().value for c in checks], states)
            self.assertTrue(all(not c.isEnabled() for c in checks))
            self.assertTrue(all(not c.isHidden() for c in checks))
        view.show_live_values(2, {1: 0, 2: 255})
        self.assertTrue(all(c.isHidden() for c in checks))
        self.assertTrue(form.findChild(QGroupBox).isHidden())
        view.show_live_values(2, {})
        self.assertTrue(all(not c.isHidden() for c in checks))
        self.assertTrue(all("Visibility unknown" in c.toolTip() for c in checks))
        self.assertEqual(view.navigation.item(0).text(), "Raw Values")

    def test_bit_array_literal_labels_and_invalid_definitions(self):
        base = {
            "type": "NodeVariableBitArray",
            "nodeVariableIndex": 1,
            "displayTitle": "Flags",
        }
        view = MdfNodeVariables(
            {
                "nodeVariables": [
                    {
                        **base,
                        "displaySubTitle": "Note",
                        "bitCollection": [
                            {"bitPosition": 0, "label": ""},
                            {"bitPosition": 7, "label": "${channel1}"},
                        ],
                    }
                ]
            }
        )
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        view.show_live_values(1, {})
        self.assertEqual(
            [
                c.text()
                for c in view.pages.currentWidget().findChildren(QCheckBox)
                if not c.isHidden()
            ],
            ["${channel1}"],
        )
        for collection in (
            {},
            [None],
            [{"bitPosition": 8, "label": "Bad"}],
            [{"bitPosition": True, "label": "Bad"}],
            [{"bitPosition": 0, "label": 3}],
            [{"label": "Missing"}],
            [{"bitPosition": 0, "overload": []}],
            [{"bitPosition": 0, "overload": {"nv": 0, "labels": []}}],
            [
                {
                    "bitPosition": 0,
                    "overload": {"nv": 1, "labels": [{"value": 0, "label": 3}]},
                }
            ],
        ):
            with self.subTest(collection=collection):
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    view.set_definition(
                        {"nodeVariables": [{**base, "bitCollection": collection}]}
                    )
                self.assertEqual(view.navigation.count(), 1)

    def test_real_canmio_overloads_modes_unknowns_and_group_visibility(self):
        definition = json.loads(
            (Path(__file__).parent / "fixtures/mdfs/canmio-3d-flags.json").read_text()
        )
        definition["nodeVariables"] = [
            {
                "type": "NodeVariableGroup",
                "displayTitle": "Channel",
                "visibilityLogic": {"nv": 1, "equals": 1},
                "groupItems": definition["nodeVariables"],
            }
        ]
        view = MdfNodeVariables(definition)
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        form = view.pages.currentWidget()
        checks = form.findChildren(QCheckBox)

        def visible():
            return [c for c in checks if not c.isHidden()]

        values = {1: 1, 16: 2, 17: 85}  # Bits 0, 2, 4, 6 set.
        view.show_live_values(17, values)
        self.assertEqual(
            [c.text() for c in visible()],
            [
                "TRIGGER_INVERTED",
                "CUTOFF",
                "STARTUP",
                "PULLUP",
                "ACTION_INVERTED",
                "EVENT_INVERTED",
            ],
        )
        self.assertEqual(
            [c.isChecked() for c in visible()], [True, False, True, True, False, True]
        )
        values[16] = 0
        view.show_live_values(17, values)
        self.assertEqual(
            [c.text() for c in visible()],
            [
                "TRIGGER_INVERTED",
                "DISABLE_OFF",
                "TOGGLE",
                "INPUT_DISABLE_SOD_RESPONSE",
                "EVENT_INVERTED",
            ],
        )
        self.assertEqual(
            [c.isChecked() for c in visible()], [True, False, True, False, True]
        )
        del values[16]
        view.show_live_values(17, values)
        self.assertEqual(len(visible()), 8)
        self.assertEqual(checks[0].text(), "Bit 0: label unknown")
        self.assertIn("NV 16", checks[0].toolTip())
        self.assertTrue(checks[0].isChecked())
        values[16] = 2
        del values[17]
        view.show_live_values(17, values)
        self.assertEqual(len(visible()), 6)
        self.assertTrue(
            all(c.checkState() == Qt.CheckState.PartiallyChecked for c in checks)
        )
        values[16] = 99  # Known non-match: only the static bit survives.
        view.show_live_values(17, values)
        self.assertEqual([c.text() for c in visible()], ["EVENT_INVERTED"])
        labels = form.findChildren(QLabel)
        self.assertIn("Flags:", [l.text() for l in labels if not l.isHidden()])
        values[1] = 0
        view.show_live_values(17, values)
        self.assertEqual(visible(), [])
        self.assertTrue(all(l.isHidden() for l in labels))
        self.assertTrue(all(not c.isEnabled() for c in checks))

    def test_slider_uses_mmc_scale_offset_precision_and_bit_selection(self):
        for attributes, raw, expected in [
            ({}, 255, 255),
            ({"displayScale": 0.1, "displayOffset": 2}, 12, 3.2),
            ({"displayScale": 0.0196}, 7, 0.14),
            ({"displayScale": 0.001}, 123, 0.123),
            ({"displayScale": 16.13}, 2, 32.26),
            ({"startBit": 4, "endBit": 7}, 176, 11),
        ]:
            with self.subTest(attributes=attributes):
                view, control = self.slider_view(**attributes, displayUnits="seconds")
                view.show_live_values(2, {2: raw})
                self.assertAlmostEqual(control.value(), expected)
                self.assertTrue(control.text().endswith(" seconds"))
                self.assertFalse(control.isEnabled())

    def test_slider_limits_do_not_replace_observed_outliers(self):
        view, control = self.slider_view(
            min=10, max=20, displayScale=0.5, displayOffset=2
        )
        for raw, expected, outside in [
            (10, 7, False),
            (20, 12, False),
            (3, 3.5, True),
            (25, 14.5, True),
        ]:
            with self.subTest(raw=raw):
                values = {2: raw}
                view.show_live_values(2, values)
                self.assertAlmostEqual(control.value(), expected)
                self.assertEqual(bool(control.toolTip()), outside)
                self.assertEqual(values, {2: raw})
        view.show_live_values(2, {2: 15})
        self.assertEqual((control.minimum(), control.maximum()), (7, 12))

    def test_slider_unknown_is_blank_and_distinct_from_zero(self):
        view, control = self.slider_view(
            displayScale=0.1, displayOffset=2, displayUnits="seconds"
        )
        for values in ({2: 0}, {}, {2: 0}, {}):
            view.show_live_values(2, values)
            self.assertEqual(control.text(), "2.0 seconds" if values else "")
            self.assertEqual(view.raw_values.item(1, 1).text(), "0" if values else "-")

    def test_real_mdf_number_transforms_limits_and_unknowns(self):
        definition = json.loads(
            (Path(__file__).parent / "fixtures/mdfs/nv-value-controls.json").read_text()
        )
        view = MdfNodeVariables(definition)
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        form = view.pages.currentWidget()
        values = {10: 3, 11: 1, 12: 5, 13: 123, 14: 165, 15: 224}
        view.show_live_values(15, values)
        controls = form.findChildren(QDoubleSpinBox)
        self.assertEqual(
            [c.value() for c in controls], [3, 1, 105, 12300, 12.3, 1.23, 5, 6, 80]
        )
        self.assertEqual(
            [c.maximum() for c in controls], [255, 12, 355, 25500, 25.5, 2.55, 7, 8, 80]
        )
        self.assertEqual(controls[2].text(), "105 mS")
        self.assertIn("outside MDF range", controls[1].toolTip())
        values[11] = 20
        view.show_live_values(15, values)
        self.assertEqual(controls[1].value(), 20)
        self.assertIn("outside MDF range", controls[1].toolTip())
        values[11] = 6
        view.show_live_values(15, values)
        self.assertEqual((controls[1].minimum(), controls[1].maximum()), (2, 12))
        view.show_live_values(15, {})
        self.assertTrue(all(c.text() == "" for c in controls))
        view.show_live_values(15, {12: 0})
        self.assertEqual(controls[2].text(), "100 mS")
        self.assertEqual(values, {10: 3, 11: 6, 12: 5, 13: 123, 14: 165, 15: 224})

    def test_number_and_slider_keep_their_distinct_mmc_precision_rules(self):
        view = MdfNodeVariables(
            {
                "nodeVariables": [
                    {
                        "type": kind,
                        "nodeVariableIndex": 1,
                        "displayTitle": kind,
                        "displayScale": 16.13,
                    }
                    for kind in ("NodeVariableNumber", "NodeVariableSlider")
                ]
            }
        )
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        view.show_live_values(1, {1: 2})
        self.assertEqual(
            [
                c.value()
                for c in view.pages.currentWidget().findChildren(QDoubleSpinBox)
            ],
            [32, 32.26],
        )

    def test_select_masks_match_without_shifting_or_inventing_options(self):
        definition = json.loads(
            (Path(__file__).parent / "fixtures/mdfs/nv-value-controls.json").read_text()
        )
        masked = definition["nodeVariables"][-1]
        complete = {k: v for k, v in masked.items() if k != "bitMask"}
        # A nonzero low bit proves that masks retain the option's bit positions.
        high = {
            **masked,
            "bitMask": 128,
            "options": [{"label": "High", "value": 128}, {"label": "Low", "value": 0}],
        }
        view = MdfNodeVariables({"nodeVariables": [masked, complete, high]})
        self.addCleanup(view.close)
        view.navigation.setCurrentRow(1)
        combos = view.pages.currentWidget().findChildren(QComboBox)
        for raw, masked_option, whole_option in [
            (130, 2, None),
            (128, 0, None),
            (1, 1, 1),
            (255, None, None),
            (None, None, None),
        ]:
            with self.subTest(raw=raw):
                view.show_live_values(1, {} if raw is None else {1: raw})
                self.assertEqual(combos[0].currentData(), masked_option)
                self.assertEqual(combos[1].currentData(), whole_option)
                self.assertEqual(
                    combos[2].currentData(), None if raw is None else raw & 128
                )
                if masked_option is None:
                    self.assertEqual(combos[0].currentIndex(), -1)
        self.assertEqual(
            [combos[0].itemText(i) for i in range(combos[0].count())],
            [option["label"] for option in masked["options"]],
        )
        self.assertTrue(all(not c.isEnabled() for c in combos))

    def test_navigation_comes_from_panels_with_raw_first(self):
        definition = {
            "nodeVariables": [
                {
                    "type": "NodeVariableTabs",
                    "tabPanels": [
                        {
                            "displayTitle": "Other settings",
                            "items": [
                                {
                                    "type": "NodeVariableNumber",
                                    "nodeVariableIndex": 1,
                                    "displayTitle": "Value",
                                }
                            ],
                        },
                    ],
                }
            ]
        }
        view = MdfNodeVariables(definition)
        self.addCleanup(view.close)
        self.assertEqual(
            [view.navigation.item(i).text() for i in range(2)],
            ["Raw Values", "Other settings"],
        )
        view.navigation.setCurrentRow(1)
        self.assertEqual(view.pages.currentIndex(), 1)

    def test_partial_forms_still_reject_malformed_and_invalid_supported_definitions(
        self,
    ):
        for items in (
            {},
            [None],
            [{"type": ""}],
            [{"type": "NodeVariableNumber", "displayTitle": "Missing NV"}],
            [
                {
                    "type": "NodeVariableNumber",
                    "displayTitle": "Bad NV",
                    "nodeVariableIndex": 0,
                }
            ],
            [
                {
                    "type": "NodeVariableSlider",
                    "displayTitle": "Bad range",
                    "nodeVariableIndex": 1,
                    "min": 20,
                    "max": 10,
                }
            ],
        ):
            with self.subTest(items=items):
                definition = {
                    "nodeVariables": [
                        {
                            "type": "NodeVariableTabs",
                            "tabPanels": [{"displayTitle": "Invalid", "items": items}],
                        }
                    ]
                }
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    self.view.set_definition(definition)
                self.assertEqual(self.view.navigation.count(), 1)

    def test_real_cancmd_bit_visibility_and_working_copy(self):
        definition = json.loads(
            Path("tests/fixtures/mdfs/CANCMD-A50A-4d.json").read_text()
        )
        self.view.set_definition(definition)
        form = self.view.pages.widget(1)
        fields = {
            c.parentWidget().layout().labelForField(c).text(): c
            for c in form.findChildren(QDoubleSpinBox)
        }
        sod, honk = fields["SoD Delay:"], fields["Honk Interval:"]
        for flags in (0, 63, 64, 127, 128, 191, 192, 255):
            with self.subTest(flags=flags):
                self.view.show_live_values(16, {2: flags, 14: 10, 15: 20})
                self.assertEqual(not sod.isHidden(), bool(flags & 64))
                self.assertEqual(not honk.isHidden(), bool(flags & 128))
        self.assertEqual(sod.value(), 7)  # NV14 * 0.5 + 2.
        self.assertEqual(honk.value(), 20)
        self.view.show_live_values(16, {14: 10, 15: 20})
        for control in (sod, honk):
            self.assertFalse(control.isHidden())
            self.assertFalse(control.isEnabled())
            self.assertIn("Visibility unknown: NV 2", control.toolTip())
        working = [0] * 16
        self.view.show_node(self.node, working)
        self.view.set_editing(True)
        self.view.raw_values.item(1, 1).setText("64")
        self.view.navigation.setCurrentRow(1)
        self.assertFalse(sod.isHidden())
        self.assertTrue(honk.isHidden())
        self.assertEqual(working[1], 64)
        # Cancel's existing presentation contract: return to confirmed values.
        self.view.set_editing(False)
        self.view.show_live_values(16, {2: 128})
        self.assertTrue(sod.isHidden())
        self.assertFalse(honk.isHidden())
        self.assertEqual(self.view.raw_values.item(1, 1).text(), "128")

    def test_real_canlever_jll_conditions_and_unknown_values(self):
        group = json.loads(
            Path("tests/fixtures/mdfs/canlever-io-type.json").read_text()
        )
        self.view.set_definition({"nodeVariables": [group]})
        form = self.view.pages.widget(1)
        choices = form.findChildren(QComboBox)
        checks = {c.text(): c for c in form.findChildren(QCheckBox)}
        servo = checks["Primary - Start Event (7xx)"]
        input_event = checks["Primary - Input Event (0xx)"]
        for values, visible in (
            ({19: 1, 72: 18}, (True, False, True, False)),
            ({19: 2, 72: 18}, (False, True, False, False)),
            ({19: 1, 72: 16}, (True, False, False, True)),
            ({19: 1}, (True, False, True, True)),
            ({72: 18}, (True, True, True, False)),
            ({19: 2}, (False, True, False, True)),
        ):
            with self.subTest(values=values):
                self.view.show_live_values(80, values)
                self.assertEqual(
                    tuple(not c.isHidden() for c in (*choices, servo, input_event)),
                    visible,
                )
        self.view.show_live_values(80, {19: 1})
        self.assertIn("Visibility unknown", servo.toolTip())
        self.assertFalse(servo.isEnabled())
        self.view.show_live_values(80, {19: 1, 72: 18})
        self.assertEqual(servo.toolTip(), "")
        self.assertTrue(servo.isChecked())

        # A false ancestor still hides a JLL child whose value is unread.
        group = deepcopy(group)
        group["visibilityLogic"] = {"nv": 1, "equals": 1}
        self.view.set_definition({"nodeVariables": [group]})
        form = self.view.pages.widget(1)
        box = form.findChild(QGroupBox)
        self.view.show_live_values(80, {1: 0})
        self.assertTrue(box.isHidden())
        self.view.show_live_values(80, {1: 1})
        self.assertFalse(box.isHidden())
        self.assertTrue(all(not c.isHidden() for c in form.findChildren(QComboBox)))

    def test_real_canace8c_eight_channel_groups(self):
        definition = json.loads(
            Path("tests/fixtures/mdfs/CANACE8C-A505-2q.json").read_text()
        )
        self.view.set_definition(definition)
        self.view.show_live_values(8, {index: 85 for index in range(1, 9)})
        form = self.view.pages.widget(1)
        groups = form.findChildren(QGroupBox)
        # Channel templates stay literal: this prototype does not change MDF interpretation.
        self.assertEqual(
            [group.title() for group in groups],
            ["General"] + [f"${{channel {index}}}" for index in range(1, 9)],
        )
        for index, group in enumerate(groups[1:]):
            checks = group.findChildren(QCheckBox)
            self.assertEqual(len(checks), 6)
            self.assertTrue(
                all(c.isChecked() == bool(85 & (1 << index)) for c in checks)
            )
            self.assertTrue(all(not c.isEnabled() for c in checks))
        self.assertTrue(all(not group.isHidden() for group in groups))

    def test_malformed_bit_conditions_skip_only_the_affected_entry(self):
        number = {
            "type": "NodeVariableNumber",
            "displayTitle": "Value",
            "nodeVariableIndex": 1,
        }
        conditions = (
            [None, [], {"nvBit": {"index": 2, "bit": 6}}]
            + [
                {"nvBit": selector, "equals": 1}
                for selector in (
                    None,
                    {},
                    {"index": 2},
                    {"index": 2, "bit": 0, "extra": 1},
                    *({"index": n, "bit": 0} for n in (0, 256, True, "2")),
                    *({"index": 2, "bit": b} for b in (-1, 8, True, "6")),
                )
            ]
            + [
                {"nvBit": {"index": 2, "bit": 6}, "equals": value}
                for value in (-1, 2, True, "1", None)
            ]
        )
        for condition in conditions:
            with self.subTest(condition=condition):
                self.view.set_definition(
                    {
                        "nodeVariables": [
                            {**number, "visibilityLogic": condition},
                            number,
                        ]
                    }
                )
                self.view.show_live_values(2, {1: 42, 2: 255})
                self.assertEqual(
                    [
                        c.value()
                        for c in self.view.pages.widget(1).findChildren(QDoubleSpinBox)
                    ],
                    [42],
                )

    def test_false_visibility_overrides_unknown_tooltips_in_either_order(self):
        conditions = (
            {"nv": 2, "equals": 1},
            {"nvBit": {"index": 2, "bit": 0}, "equals": 1},
            {"JLL": {"==": [{"NV": 2}, 1]}},
        )
        for condition in conditions:
            for false_first in (True, False):
                with self.subTest(condition=condition, false_first=false_first):
                    unknown = {"nv": 3, "equals": 1}
                    parent, child = (
                        (condition, unknown) if false_first else (unknown, condition)
                    )
                    self.view.set_definition(
                        {
                            "nodeVariables": [
                                {
                                    "type": "NodeVariableGroup",
                                    "displayTitle": "Conditional group",
                                    "visibilityLogic": parent,
                                    "groupItems": [
                                        {
                                            "type": "NodeVariableNumber",
                                            "displayTitle": "Value",
                                            "nodeVariableIndex": 1,
                                            "visibilityLogic": child,
                                        }
                                    ],
                                }
                            ]
                        }
                    )
                    control = self.view.pages.widget(1).findChild(QDoubleSpinBox)
                    self.view.show_live_values(3, {1: 42})
                    self.assertFalse(control.isHidden())
                    first_explanation = control.toolTip()
                    self.assertIn("Visibility unknown", first_explanation)
                    if false_first:
                        self.assertNotIn("NV 3", first_explanation)
                    else:
                        self.assertIn("NV 3", first_explanation)
                    self.view.show_live_values(3, {1: 42, 2: 0})
                    self.assertTrue(control.isHidden())
                    self.assertEqual(control.toolTip(), "")
                    self.view.show_live_values(3, {1: 42})
                    self.assertFalse(control.isHidden())
                    self.assertEqual(control.toolTip(), first_explanation)

    def test_unsupported_visibility_omits_entry_in_flat_groups_and_tabs(self):
        number = {
            "type": "NodeVariableNumber",
            "displayTitle": "Visible",
            "nodeVariableIndex": 1,
        }
        hidden = {
            **number,
            "displayTitle": "Unsupported",
            "visibilityLogic": {
                "any": [{"nv": 2, "equals": 128}],
            },
        }
        group = {
            "type": "NodeVariableGroup",
            "displayTitle": "Group",
            "groupItems": [number, hidden],
        }
        conditional_group = {**group, "visibilityLogic": hidden["visibilityLogic"]}
        for items in ([number, hidden, conditional_group], [group]):
            for definitions in (
                items,
                [
                    {
                        "type": "NodeVariableTabs",
                        "tabPanels": [
                            {"displayTitle": "Panel", "items": items},
                        ],
                    }
                ],
            ):
                with self.subTest(definitions=definitions):
                    self.view.set_definition({"nodeVariables": definitions})
                    self.view.show_live_values(2, {1: 42, 2: 128})
                    form = self.view.pages.widget(1)
                    self.assertEqual(
                        [c.value() for c in form.findChildren(QDoubleSpinBox)], [42]
                    )
                    self.assertNotIn(
                        "Unsupported:", [c.text() for c in form.findChildren(QLabel)]
                    )

    def test_nested_group_boxes_keep_order_visibility_and_live_updates(self):
        def number(index, title):
            return {
                "type": "NodeVariableNumber",
                "nodeVariableIndex": index,
                "displayTitle": title,
            }

        definitions = [
            number(1, "Before"),
            {
                "type": "NodeVariableGroup",
                "displayTitle": "Outputs",
                "visibilityLogic": {"nvBit": {"index": 4, "bit": 0}, "equals": 1},
                "groupItems": [
                    number(2, "First"),
                    {"type": "NodeVariableUnknown"},
                    {
                        "type": "NodeVariableGroup",
                        "displayTitle": "Nested",
                        "visibilityLogic": {
                            "nvBit": {"index": 5, "bit": 0},
                            "equals": 1,
                        },
                        "groupItems": [number(3, "Second")],
                    },
                    {
                        "type": "NodeVariableGroup",
                        "displayTitle": "Unsupported only",
                        "groupItems": [{"type": "NodeVariableUnknown"}],
                    },
                ],
            },
            number(6, "After"),
        ]
        view = MdfNodeVariables({"nodeVariables": definitions})
        self.addCleanup(view.close)
        self.assertEqual(
            [view.navigation.item(i).text() for i in range(2)],
            ["Raw Values", "Settings"],
        )
        view.navigation.setCurrentRow(1)
        form = view.pages.currentWidget()
        labels = form.findChildren(QLabel)
        self.assertEqual(
            [label.text() for label in labels],
            ["Before:", "First:", "Second:", "After:"],
        )
        groups = form.findChildren(QGroupBox)
        self.assertEqual([group.title() for group in groups], ["Outputs", "Nested"])
        self.assertIs(groups[1].parentWidget(), groups[0])
        values = {1: 10, 2: 20, 3: 30, 4: 1, 5: 1, 6: 60}
        view.show_live_values(6, values)
        self.assertTrue(all(not label.isHidden() for label in labels))
        self.assertEqual(
            [spin.value() for spin in form.findChildren(QDoubleSpinBox)],
            [10, 20, 30, 60],
        )
        values[2] = 21
        values[5] = 0
        view.show_live_values(6, values)
        self.assertEqual(
            [label.text() for label in labels if not label.isHidden()],
            ["Before:", "First:", "After:"],
        )
        self.assertEqual(form.findChildren(QDoubleSpinBox)[1].value(), 21)
        self.assertFalse(groups[0].isHidden())
        self.assertTrue(groups[1].isHidden())
        values[4] = 0
        view.show_live_values(6, values)
        self.assertEqual(
            [label.text() for label in labels if not label.isHidden()],
            ["Before:", "After:"],
        )
        self.assertTrue(all(group.isHidden() for group in groups))
        del values[4]
        del values[5]
        view.show_live_values(6, values)
        self.assertTrue(all(not label.isHidden() for label in labels))
        self.assertTrue(all(not group.isHidden() for group in groups))
        self.assertFalse(form.findChildren(QDoubleSpinBox)[1].isEnabled())
        view.navigation.setCurrentRow(0)
        self.assertEqual(view.raw_values.item(1, 1).text(), "21")

    def test_groups_inside_tabs_and_mixed_flat_runs_keep_navigation_order(self):
        number = {
            "type": "NodeVariableNumber",
            "nodeVariableIndex": 1,
            "displayTitle": "Value",
        }
        group = {
            "type": "NodeVariableGroup",
            "displayTitle": "Group",
            "groupItems": [
                {
                    "type": "NodeVariableGroup",
                    "displayTitle": "Inner",
                    "visibilityLogic": {"nvBit": {"index": 255, "bit": 7}, "equals": 0},
                    "groupItems": [number],
                }
            ],
        }
        view = MdfNodeVariables(
            {
                "nodeVariables": [
                    number,
                    {
                        "type": "NodeVariableTabs",
                        "tabPanels": [
                            {"displayTitle": "Panel", "items": [group]},
                            {
                                "displayTitle": "Empty",
                                "items": [
                                    {
                                        "type": "NodeVariableGroup",
                                        "displayTitle": "Empty group",
                                        "groupItems": [],
                                    }
                                ],
                            },
                        ],
                    },
                    number,
                ]
            }
        )
        self.addCleanup(view.close)
        self.assertEqual(
            [view.navigation.item(i).text() for i in range(view.navigation.count())],
            ["Raw Values", "Settings", "Panel", "Settings 2"],
        )
        view.show_node(self.node, self.values)
        view.set_editing(True)
        view.navigation.setCurrentRow(0)
        view.raw_values.item(0, 1).setText("42")
        view.navigation.setCurrentRow(2)
        form = view.pages.currentWidget()
        self.assertEqual(
            [label.text() for label in form.findChildren(QLabel)],
            ["Value:"],
        )
        self.assertEqual(form.findChild(QDoubleSpinBox).value(), 42)
        view.navigation.setCurrentRow(3)
        self.assertEqual(
            view.pages.currentWidget().findChild(QDoubleSpinBox).value(), 42
        )

        view.show_live_values(255, {1: 42, 255: 128})
        self.assertTrue(form.findChild(QDoubleSpinBox).isHidden())
        view.show_live_values(255, {1: 42, 255: 127})
        self.assertFalse(form.findChild(QDoubleSpinBox).isHidden())
        view.show_live_values(255, {1: 42})
        control = form.findChild(QDoubleSpinBox)
        self.assertFalse(control.isHidden())
        self.assertIn("Visibility unknown", control.toolTip())

    def test_invalid_group_structures_and_nested_tabs_remain_errors(self):
        for group in [
            {"type": "NodeVariableGroup", "displayTitle": "Missing items"},
            {
                "type": "NodeVariableGroup",
                "displayTitle": "Bad items",
                "groupItems": {},
            },
            {
                "type": "NodeVariableGroup",
                "displayTitle": "Bad child",
                "groupItems": [None],
            },
            {
                "type": "NodeVariableGroup",
                "displayTitle": "Nested tabs",
                "groupItems": [{"type": "NodeVariableTabs", "tabPanels": []}],
            },
        ]:
            with self.subTest(group=group):
                with self.assertRaises((KeyError, TypeError, ValueError)):
                    self.view.set_definition({"nodeVariables": [group]})
                self.assertEqual(self.view.navigation.count(), 1)

    def test_values_are_editable_and_refresh_from_raw_working_copy(self):
        self.view.set_editing(True)
        self.view.raw_values.item(1, 1).setText("31")
        self.view.navigation.setCurrentRow(1)
        form = self.view.pages.currentWidget()
        self.assertEqual(form.findChild(QDoubleSpinBox).value(), 31)
        self.assertEqual(form.findChild(QComboBox).currentData(), 0)
        self.assertTrue(form.findChild(QCheckBox).isChecked())
        for kind in (QDoubleSpinBox, QComboBox, QCheckBox):
            self.assertTrue(form.findChild(kind).isEnabled())
        self.assertEqual(self.values[1], 31)
        self.assertEqual(self.node.nv_values, {})

    def test_conditions_follow_raw_nv_values_and_hide_labels_too(self):
        for mode, labels in [
            (0, ["I/O type:", "ON delay:", "OFF delay:"]),
            (1, ["I/O type:", "Invert output:", "Pulse duration:"]),
            (2, ["I/O type:", "ON position:", "OFF position:"]),
        ]:
            self.view.navigation.setCurrentRow(0)
            self.view.raw_values.item(3, 1).setText(str(mode))
            self.view.navigation.setCurrentRow(2)
            form = self.view.pages.currentWidget()
            layout = form.widget().layout()
            visible = [
                layout.itemAt(row, layout.ItemRole.LabelRole).widget().text()
                for row in range(layout.rowCount())
                if layout.isRowVisible(row)
            ]
            self.assertEqual(visible, labels)

    def test_unknown_values_are_preserved_without_defaults(self):
        for values in ({1: 77}, [77, None]):
            original = deepcopy(values)
            self.view.show_node(self.node, values)
            self.view.navigation.setCurrentRow(1)
            form = self.view.pages.currentWidget()
            self.assertEqual(form.findChild(QComboBox).currentIndex(), -1)
            self.assertEqual(form.findChild(QComboBox).placeholderText(), "77")
            self.assertEqual(form.findChild(QDoubleSpinBox).text(), "")
            self.view.set_editing(True)
            self.assertFalse(form.findChild(QDoubleSpinBox).isEnabled())
            self.assertFalse(form.findChild(QCheckBox).isEnabled())
            self.assertEqual(
                form.findChild(QCheckBox).checkState(), Qt.CheckState.PartiallyChecked
            )
            self.view.navigation.setCurrentRow(2)
            layout = self.view.pages.currentWidget().widget().layout()
            self.assertTrue(layout.isRowVisible(0))
            self.assertTrue(
                all(layout.isRowVisible(i) for i in range(1, layout.rowCount()))
            )
            self.assertEqual(values, original)

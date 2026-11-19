import logging
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QWidget,
)

from . import mdf_visibility
from .logging_config import trace

logger = logging.getLogger("workbench.node_variables")


class RawNodeVariables(QTableWidget):
    value_changed = Signal()

    def __init__(self):
        super().__init__(0, 2)

        self.setHorizontalHeaderLabels(["NV", "Value"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.values = None
        self.itemChanged.connect(self.update_value)

    def show_node(self, node, values=None):
        """Edit a positional backup NV list or the prototype indexed values."""
        self.values = values if values is not None else node.nv_values
        self.setRowCount(len(self.values))

        # setItem() emits itemChanged; rows must be complete before update_value runs.
        self.blockSignals(True)
        entries = (
            enumerate(self.values, 1)
            if isinstance(self.values, list)
            else sorted(self.values.items())
        )
        for row, (number, value) in enumerate(entries):
            number_item = QTableWidgetItem(str(number))
            number_item.setFlags(number_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 0, number_item)
            self.setItem(row, 1, QTableWidgetItem(str(value)))
        self.blockSignals(False)

    def show_live_values(self, count: int | None, values: dict[int, int]) -> None:
        """Show confirmed live NVs; absent values within a known count stay unknown."""
        self.set_editing(False)
        self.values = None  # Live state must never be changed through this table.
        indices = range(1, count + 1) if count is not None else sorted(values)
        current = [self.item(row, 0).text() for row in range(self.rowCount())]
        rebuild = current != [str(index) for index in indices]

        self.blockSignals(True)
        if rebuild:
            self.setRowCount(len(indices))
        for row, index in enumerate(indices):
            if rebuild:
                number_item = QTableWidgetItem(str(index))
                number_item.setFlags(number_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.setItem(row, 0, number_item)
            value = str(values[index]) if index in values else "-"
            item = self.item(row, 1)
            if item is None or item.text() != value:
                item = QTableWidgetItem(value)
                self.setItem(row, 1, item)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.blockSignals(False)

    def refresh_values(self):
        if self.values is None:
            return
        blocked = self.blockSignals(True)
        for row in range(self.rowCount()):
            value = nv_value(self.values, int(self.item(row, 0).text()))
            self.item(row, 1).setText("" if value is None else str(value))
        self.blockSignals(blocked)

    def set_editing(self, editing):
        triggers = (
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            if editing
            else QTableWidget.EditTrigger.NoEditTriggers
        )
        self.setEditTriggers(triggers)

    def update_value(self, item):
        if self.values is None:
            return

        number = int(self.item(item.row(), 0).text())

        if item.column() == 1:
            try:
                value = int(item.text())
            except ValueError:
                value = -1

            index = number - 1 if isinstance(self.values, list) else number
            if 0 <= value <= 255:
                trace(
                    logger,
                    "Raw NV edit index=%s old=%s new=%s",
                    number,
                    self.values[index],
                    value,
                )
                self.values[index] = value
                self.value_changed.emit()
            else:
                item.setText(str(self.values[index]))


# Representative presentation data only: these indices are not module definitions.
# Live MDF lookup is deliberately not connected in this visual-review slice.
PROTOTYPE_MDF = {
    "nodeVariables": [
        {
            "type": "NodeVariableTabs",
            "tabPanels": [
                {
                    "displayTitle": "Globals",
                    "items": [
                        {
                            "type": "NodeVariableSelect",
                            "nodeVariableIndex": 1,
                            "displayTitle": "Module mode",
                            "options": [
                                {"label": "Normal", "value": 0},
                                {"label": "Advanced", "value": 1},
                                {"label": "Diagnostic", "value": 2},
                            ],
                        },
                        {
                            "type": "NodeVariableNumber",
                            "nodeVariableIndex": 2,
                            "displayTitle": "Startup delay",
                            "displayUnits": "seconds",
                        },
                        {
                            "type": "NodeVariableBitSingle",
                            "nodeVariableIndex": 3,
                            "displayTitle": "Enable diagnostics",
                            "bit": 0,
                        },
                    ],
                },
                {
                    "displayTitle": "Channel 1",
                    "items": [
                        {
                            "type": "NodeVariableSelect",
                            "nodeVariableIndex": 4,
                            "displayTitle": "I/O type",
                            "options": [
                                {"label": "Input", "value": 0},
                                {"label": "Output", "value": 1},
                                {"label": "Servo", "value": 2},
                            ],
                        },
                        {
                            "type": "NodeVariableNumber",
                            "nodeVariableIndex": 5,
                            "displayTitle": "ON delay",
                            "displayUnits": "ms",
                            "visibilityLogic": {"nv": 4, "equals": 0},
                        },
                        {
                            "type": "NodeVariableNumber",
                            "nodeVariableIndex": 6,
                            "displayTitle": "OFF delay",
                            "displayUnits": "ms",
                            "visibilityLogic": {"nv": 4, "equals": 0},
                        },
                        {
                            "type": "NodeVariableBitSingle",
                            "nodeVariableIndex": 7,
                            "displayTitle": "Invert output",
                            "bit": 0,
                            "visibilityLogic": {"nv": 4, "equals": 1},
                        },
                        {
                            "type": "NodeVariableNumber",
                            "nodeVariableIndex": 8,
                            "displayTitle": "Pulse duration",
                            "displayUnits": "ms",
                            "visibilityLogic": {"nv": 4, "equals": 1},
                        },
                        {
                            "type": "NodeVariableNumber",
                            "nodeVariableIndex": 9,
                            "displayTitle": "ON position",
                            "visibilityLogic": {"nv": 4, "equals": 2},
                        },
                        {
                            "type": "NodeVariableNumber",
                            "nodeVariableIndex": 10,
                            "displayTitle": "OFF position",
                            "visibilityLogic": {"nv": 4, "equals": 2},
                        },
                    ],
                },
                {"displayTitle": "Channel 2", "items": []},
            ],
        }
    ],
}


def nv_value(values, number):
    """Read one-based NV indices without inventing values for absent bytes."""
    if isinstance(values, list):
        return values[number - 1] if 1 <= number <= len(values) else None
    return values.get(number)


class MdfNumericValue(QDoubleSpinBox):
    """Number/Slider/Dual display using MMC v0.23.2 interpretation."""

    def __init__(self, definition):
        super().__init__()
        self.definition = definition
        self.raw_min = definition.get("min", 0)
        self.last_bit = 15 if definition["type"] == "NodeVariableDual" else 7
        self.raw_max = definition.get("max", (1 << (self.last_bit + 1)) - 1)
        start, end = (
            definition.get("startBit", 0),
            definition.get("endBit", self.last_bit),
        )
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start <= end <= self.last_bit
        ):
            raise ValueError(
                f"MDF numeric bits must satisfy 0 <= startBit <= endBit <= {self.last_bit}"
            )
        is_number = definition["type"] in ("NodeVariableNumber", "NodeVariableDual")
        # Number caps its raw maximum to the selected bit width; Slider uses
        # the supplied max directly. Source: MMC v0.23.2 bundled client, module 641.
        if is_number:
            self.raw_max = min(self.raw_max, (1 << (end - start + 1)) - 1)
        if self.raw_min > self.raw_max:
            raise ValueError("MDF numeric minimum exceeds maximum")
        self.scale = definition.get("displayScale", 1)
        self.offset = definition.get("displayOffset", 0)
        # The bundled MMC client rounds sub-unit scales to 1, 2 or 3 places.
        # Slider retains fractional parts at larger scales (e.g. 16.13).
        if is_number and self.scale >= 1:
            # Number's getDisplayValue() always uses toFixed(0) at these scales.
            decimals = 0
        elif self.scale >= 1:
            decimals = max(
                0,
                -Decimal(str(self.scale)).as_tuple().exponent,
                -Decimal(str(self.offset)).as_tuple().exponent,
            )
        elif self.scale >= 0.1:
            decimals = 1
        elif self.scale >= 0.01:
            decimals = 2
        else:
            decimals = 3
        self.setDecimals(decimals)
        self.setSingleStep(abs(self.scale))

    def show_value(self, value):
        """Display the observed value, including values outside descriptor limits."""
        definition = self.definition
        start = definition.get("startBit", 0)
        end = definition.get("endBit", self.last_bit)
        raw = (
            None if value is None else (value >> start) & ((1 << (end - start + 1)) - 1)
        )
        limits = sorted(
            (
                self.raw_min * self.scale + self.offset,
                self.raw_max * self.scale + self.offset,
            )
        )
        displayed = None if raw is None else raw * self.scale + self.offset
        # A spin box clamps setValue() to its range. Extend the display range for
        # outliers so the confirmed hardware value is never replaced by a limit.
        self.setRange(
            min(limits[0], displayed) if displayed is not None else limits[0],
            max(limits[1], displayed) if displayed is not None else limits[1],
        )
        units = definition.get("displayUnits", "")
        self.setSuffix(f" {units}" if units and raw is not None else "")
        if displayed is None:
            self.clear()
        else:
            self.setValue(displayed)
        outside = raw is not None and not self.raw_min <= raw <= self.raw_max
        message = (
            f"Value {raw} is outside MDF range {self.raw_min}–{self.raw_max}."
            if outside
            else ""
        )
        if outside:
            logger.warning(
                "MDF numeric NV %s: %s",
                definition.get(
                    "nodeVariableIndex", definition.get("nodeVariableIndexHigh")
                ),
                message,
            )
        return message


def validate_bit_label(bit):
    """Accept the NV label lookup used by MMC v0.23.2 bit arrays."""
    if "overload" not in bit:
        if not isinstance(bit["label"], str):
            raise TypeError("MDF bit label must be text")
        return
    overload = bit["overload"]
    if not isinstance(overload, dict) or set(overload) != {"nv", "labels"}:
        raise ValueError("Unsupported MDF bit overload format")
    index = overload["nv"]
    if type(index) is not int or not 1 <= index <= 255:
        raise ValueError("MDF overload NV index must be an integer from 1 to 255")
    if not isinstance(overload["labels"], list):
        raise TypeError("MDF overload labels must be a list")
    for entry in overload["labels"]:
        if not isinstance(entry, dict) or set(entry) != {"value", "label"}:
            raise ValueError("MDF overload labels need value and label")
        if (
            type(entry["value"]) is not int
            or not 0 <= entry["value"] <= 255
            or not isinstance(entry["label"], str)
        ):
            raise ValueError("MDF overload labels need a byte value and text label")


def resolve_bit_label(bit, values):
    """Return label and explanation; an unread selector is not a non-match."""
    if "overload" not in bit:
        return bit["label"], ""
    overload = bit["overload"]
    value = nv_value(values, overload["nv"])
    if value is None:
        return (
            f"Bit {bit['bitPosition']}: label unknown",
            f"Label unknown: NV {overload['nv']} has not been read.",
        )
    label = ""
    # MMC retains the last matching entry; the flags NV and bit never change.
    for entry in overload["labels"]:
        if entry["value"] == value:
            label = entry["label"]
    return label, ""


def mdf_form_layout(parent):
    """Use the same compact native form layout for pages and group boxes."""
    layout = QFormLayout(parent)
    layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
    layout.setLabelAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    return layout


class MdfSettings(QScrollArea):
    """Interpret raw bytes and emit edits; never own desired configuration."""

    value_edited = Signal(int, int)
    test_requested = Signal(int)

    def __init__(
        self,
        definitions,
        panel_title,
        panel_number,
        *,
        parent_conditions=(),
        source_definitions=None,
        token_editor=None,
        allow_undefined: bool = False,
    ):
        super().__init__()
        self.rows = []
        self.page = f"{panel_title} ({panel_number})"
        # Set by the owner so refresh summaries identify the node being shown.
        self.node_number = None
        self.token_editor = token_editor
        self.editing = False
        self.allow_undefined = allow_undefined
        self.values = None
        self.labels = {}
        contents = QWidget()
        layout = mdf_form_layout(contents)
        # Keep the form's minimum height inside the viewport, not the main window.
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidget(contents)
        self.group_rows = []
        self.tab_pages = []
        self.bit_arrays = []
        self.test_buttons = {}
        self.add_items(
            definitions,
            self.page,
            layout,
            parent_conditions,
            source_definitions,
        )
        self.bind_controls()

    def bind_controls(self):
        for definition, control, _ in self.rows:
            signal = (
                control.currentIndexChanged
                if isinstance(control, QComboBox)
                else control.valueChanged
                if isinstance(control, MdfNumericValue)
                else control.checkStateChanged
            )
            signal.connect(
                lambda _value, d=definition, c=control: self.edit_value(d, c)
            )

    def edit_value(self, definition, control):
        if not self.editing or not control.isEnabled():
            return
        index = definition["nodeVariableIndex"]
        current = nv_value(self.values, index)
        if current is None:
            if not self.allow_undefined:
                return  # NV edits still require the original byte.
            # An explicit first EV edit establishes a byte. There are no known
            # bits to preserve yet; subsequent masked edits preserve that byte.
            current = 0
        if isinstance(control, QComboBox):
            replacement = control.currentData()
            if replacement is None:
                return
            mask = definition.get("bitMask", 255)
        elif isinstance(control, MdfNumericValue):
            if not control.scale:
                return
            raw = round((control.value() - control.offset) / control.scale)
            start = definition.get("startBit", 0)
            end = definition.get("endBit", 7)
            if (
                not control.raw_min <= raw <= control.raw_max
                or raw > (1 << (end - start + 1)) - 1
            ):
                self.show_values(
                    self.values, nv_values=self.nv_values, ev_values=self.ev_values
                )
                return
            mask = ((1 << (end - start + 1)) - 1) << start
            replacement = raw << start
        else:
            mask = 1 << definition["bit"]
            replacement = mask if control.isChecked() else 0
        value = (current & ~mask) | (replacement & mask)
        trace(
            logger,
            "MDF edit index=%s old=%s new=%s mask=%s",
            index,
            current,
            value,
            mask,
        )
        self.value_edited.emit(index, value)

    def set_editing(self, editing):
        if self.editing == editing:
            return
        self.editing = editing
        if self.values is not None:
            self.show_values(
                self.values, nv_values=self.nv_values, ev_values=self.ev_values
            )

    def set_row_visible(self, control, visible):
        if control in self.test_buttons:
            # The form row holds the control beside its Test button. Group
            # visibility still reads the control's own hidden state.
            control.setVisible(visible)
            control = control.parentWidget()
        layout = control.parentWidget().layout()
        if isinstance(layout, QFormLayout):
            layout.setRowVisible(control, visible)
        else:
            control.setVisible(visible)
            label = self.labels.get(control)
            if label is not None:
                label.setVisible(visible)

    def add_items(
        self,
        definitions,
        location,
        layout,
        parent_conditions=(),
        source_definitions=None,
    ):
        """Append controls, nested group boxes and nested tabs in MDF order."""
        if not isinstance(definitions, list):
            raise TypeError("MDF panel/group items must be a list")
        for item_number, definition in enumerate(definitions, 1):
            source = (
                source_definitions[item_number - 1]
                if source_definitions is not None
                else definition
            )
            item_location = f"{location}/item {item_number}"
            if (
                not isinstance(definition, dict)
                or not isinstance(definition.get("type"), str)
                or not definition["type"].strip()
            ):
                raise ValueError(f"MDF item needs a nonempty type: {item_location}")
            kind = definition["type"]
            if kind not in (
                "NodeVariableTabs",
                "NodeVariableGroup",
                "NodeVariableSelect",
                "NodeVariableSlider",
                "NodeVariableNumber",
                "NodeVariableDual",
                "NodeVariableBitSingle",
                "NodeVariableBitArray",
            ):
                logger.warning(
                    "Skipping unsupported MDF control type=%s location=%s",
                    kind,
                    item_location,
                )
                continue
            condition = definition.get("visibilityLogic")
            if "visibilityLogic" in definition:
                try:
                    # Empty values validate syntax without inventing unread NVs.
                    mdf_visibility.evaluate_visibility(condition, {}, {})
                except mdf_visibility.MdfVisibilityError:
                    logger.warning(
                        "Skipping MDF entry with unsupported visibility condition "
                        "type=%s location=%s condition=%s",
                        kind,
                        item_location,
                        condition,
                    )
                    continue
            conditions = parent_conditions + (
                (condition,) if condition is not None else ()
            )
            if kind == "NodeVariableTabs":
                # Tabs have no displayTitle of their own; only panels are titled.
                self.add_tabs(definition, item_location, layout, conditions, source)
                continue
            title = definition["displayTitle"]
            if not isinstance(title, str):
                raise TypeError("MDF displayTitle must be text")
            if kind == "NodeVariableGroup":
                group = QGroupBox(title)
                if self.token_editor:
                    self.token_editor.bind(group, source["displayTitle"])
                group_layout = mdf_form_layout(group)
                layout.addRow(group)
                first_child = len(self.rows)
                self.add_items(
                    definition["groupItems"],
                    item_location + "/groupItems",
                    group_layout,
                    conditions,
                    source.get("groupItems"),
                )
                children = [control for _, control, _ in self.rows[first_child:]]
                if children:
                    self.group_rows.append((group, children))
                else:
                    layout.removeRow(group)
            elif kind == "NodeVariableBitArray":
                self.add_bit_array(
                    definition, item_location, layout, conditions, source
                )
            else:
                control = self.make_control(definition)
                control.setEnabled(False)
                label = QLabel(title + ":")
                if self.token_editor:
                    self.token_editor.bind(label, source["displayTitle"])
                    if isinstance(control, QComboBox):
                        self.token_editor.bind_choices(
                            control, source.get("options", [])
                        )
                field = control
                if output_on_write(definition):
                    field = QWidget()
                    field_layout = QHBoxLayout(field)
                    field_layout.setContentsMargins(0, 0, 0, 0)
                    field_layout.addWidget(control, 1)
                    test = QPushButton("Test")
                    test.setToolTip("Write the current value to the node again.")
                    test.clicked.connect(
                        lambda _checked, i=definition["nodeVariableIndex"]: (
                            self.test_requested.emit(i)
                        )
                    )
                    field_layout.addWidget(test)
                    self.test_buttons[control] = test
                layout.addRow(label, field)
                self.rows.append((definition, control, conditions))

    def add_tabs(self, definition, location, layout, conditions, source):
        """Nested tabs keep the MDF presentation as a native tab widget.

        Root tabs never reach here: settings_panels() makes them navigation pages.
        """
        panels = definition["tabPanels"]
        if not isinstance(panels, list):
            raise TypeError("MDF tabPanels must be a list")
        tabs = QTabWidget()
        layout.addRow(tabs)
        templates = []
        all_children = []
        for number, panel in enumerate(panels, 1):
            title = panel["displayTitle"]
            if not isinstance(title, str):
                raise TypeError("MDF panel title must be text")
            source_panel = source["tabPanels"][number - 1]
            page = QWidget()
            first_child = len(self.rows)
            self.add_items(
                panel["items"],
                f"{location}/panel {number}",
                mdf_form_layout(page),
                conditions,
                source_panel["items"],
            )
            children = [control for _, control, _ in self.rows[first_child:]]
            if not children:
                # As for root panels and groups, omit panels with no controls.
                page.deleteLater()
                continue
            self.tab_pages.append((tabs, tabs.addTab(page, title), children))
            templates.append(source_panel["displayTitle"])
            all_children += children
        trace(
            logger,
            "Construct nested MDF tabs page=%s location=%s tabs=%s",
            self.page,
            location,
            [tabs.tabText(index) for index in range(tabs.count())],
        )
        if not all_children:
            layout.removeRow(tabs)
            return
        # The whole tab widget hides like a group once no tab has a visible row.
        self.group_rows.append((tabs, all_children))
        if self.token_editor:
            self.token_editor.bind_tabs(tabs, templates)

    def add_bit_array(self, definition, location, layout, conditions, source):
        """MMC v0.23.2 uses ordered, zero-based bitPosition entries on one NV."""
        index = definition["nodeVariableIndex"]
        if type(index) is not int or not 1 <= index <= 255:
            raise ValueError("MDF NV index must be an integer from 1 to 255")
        collection = definition["bitCollection"]
        if not isinstance(collection, list):
            raise TypeError("MDF bitCollection must be a list")
        for property_name in definition.keys() - {
            "type",
            "nodeVariableIndex",
            "displayTitle",
            "visibilityLogic",
            "bitCollection",
        }:
            logger.warning(
                "Skipping unsupported MDF property=%s location=%s",
                property_name,
                location,
            )
        controls = []
        for number, bit in enumerate(collection, 1):
            if not isinstance(bit, dict):
                raise TypeError("MDF bitCollection entries must be objects")
            position = bit["bitPosition"]
            if type(position) is not int or not 0 <= position <= 7:
                raise ValueError("MDF bitPosition must be an integer from 0 to 7")
            for property_name in bit.keys() - {"bitPosition", "label", "overload"}:
                logger.warning(
                    "Skipping unsupported MDF bit property=%s location=%s/bit %s",
                    property_name,
                    location,
                    number,
                )
            validate_bit_label(bit)
            control = QCheckBox(resolve_bit_label(bit, {})[0])
            if self.token_editor:
                self.token_editor.bind(
                    control, source["bitCollection"][number - 1].get("label")
                )
            control.setEnabled(False)
            layout.addRow(QLabel(""), control)
            self.rows.append(
                ({**definition, "bit": position, "bitLabel": bit}, control, conditions)
            )
            controls.append(control)
        self.bit_arrays.append((definition["displayTitle"], controls))

    def make_control(self, definition):
        """Construct existing leaf widgets; invalid supported definitions are errors."""
        kind = definition["type"]
        # Missing/invalid supported fields are descriptor errors, never skips.
        indices = (
            [definition["nodeVariableIndexHigh"], definition["nodeVariableIndexLow"]]
            if kind == "NodeVariableDual"
            else [definition["nodeVariableIndex"]]
        )
        for index in indices:
            if type(index) is not int or not 1 <= index <= 255:
                raise ValueError("MDF NV index must be an integer from 1 to 255")
        if kind == "NodeVariableDual":
            for name in definition.keys() - {
                "type",
                "displayTitle",
                "visibilityLogic",
                "nodeVariableIndexHigh",
                "nodeVariableIndexLow",
                "min",
                "max",
                "startBit",
                "endBit",
                "displayScale",
                "displayOffset",
                "displayUnits",
            }:
                logger.warning(
                    "Skipping unsupported MDF Dual property=%s NVs=%s", name, indices
                )
        if kind == "NodeVariableBitSingle" and (
            type(definition["bit"]) is not int or not 0 <= definition["bit"] <= 7
        ):
            raise ValueError("MDF bit must be an integer from 0 to 7")
        if kind == "NodeVariableSelect":
            mask = definition.get("bitMask", 255)
            if type(mask) is not int or not 0 <= mask <= 255:
                raise ValueError("MDF select bitMask must be a byte")
            if not isinstance(definition["options"], list):
                raise TypeError("MDF select options must be a list")
            control = QComboBox()
            for option in definition["options"]:
                if (
                    not isinstance(option["label"], str)
                    or type(option["value"]) is not int
                    or not 0 <= option["value"] <= 255
                ):
                    raise ValueError(
                        "MDF select options need a text label and byte value"
                    )
                control.addItem(option["label"], option["value"])
        elif kind in ("NodeVariableSlider", "NodeVariableNumber", "NodeVariableDual"):
            control = MdfNumericValue(definition)
            # Each change is written to the node immediately, so report only
            # finished entries (Enter, focus loss, arrows), not every digit typed.
            control.setKeyboardTracking(not output_on_write(definition))
        elif kind == "NodeVariableBitSingle":
            control = QCheckBox()
        return control

    def show_values(self, values, *, nv_values=None, ev_values=None):
        """Refresh from raw bytes; EV forms supply the node and event contexts."""
        if nv_values is None:
            nv_values = (
                dict(enumerate(values, 1)) if isinstance(values, list) else values
            )
        if ev_values is None:
            ev_values = {}
        self.values = values
        self.nv_values = nv_values
        self.ev_values = ev_values
        counts = {"visible": 0, "hidden": 0, "unknown": 0}
        for definition, control, conditions in self.rows:
            blocked = control.blockSignals(True)
            if definition["type"] == "NodeVariableDual":
                high = nv_value(values, definition["nodeVariableIndexHigh"])
                low = nv_value(values, definition["nodeVariableIndexLow"])
                # Both confirmed bytes are needed; never invent a missing half.
                value = None if high is None or low is None else (high << 8) + low
            else:
                value = nv_value(values, definition["nodeVariableIndex"])
            value_message = ""
            # Unknown values stay blank/indeterminate, never substituted with zero.
            if isinstance(control, QComboBox):
                if "labelOptions" in definition:
                    control.clear()
                    for option in definition["labelOptions"]:
                        label, reason = resolve_bit_label(
                            {**option, "bitPosition": option["value"]}, nv_values
                        )
                        if reason:
                            label = (
                                f"Unknown label (NV {option['overload']['nv']} unread)"
                            )
                        if label:
                            control.addItem(label, option["value"])
                # MMC masks in place: option values are not shifted down to bit 0.
                selected = (
                    None if value is None else value & definition.get("bitMask", 255)
                )
                control.setPlaceholderText(
                    "Unknown" if selected is None else str(selected)
                )
                control.setCurrentIndex(
                    control.findData(selected) if selected is not None else -1
                )
            elif isinstance(control, MdfNumericValue):
                value_message = control.show_value(value)
            else:
                control.setTristate(value is None)
                control.setCheckState(
                    Qt.CheckState.PartiallyChecked
                    if value is None
                    else Qt.CheckState.Checked
                    if value & (1 << definition["bit"])
                    else Qt.CheckState.Unchecked
                )
            # A known-false ancestor hides its subtree. Unknown conditions retain
            # the existing visible, read-only presentation with an explanatory tooltip.
            visible = True
            if "bitLabel" in definition:
                label, value_message = resolve_bit_label(
                    definition["bitLabel"], nv_values
                )
                control.setText(label)
                visible = bool(label)
            visibility_message = ""
            for condition in conditions:
                result = mdf_visibility.evaluate_visibility(
                    condition, nv_values, ev_values
                )
                if result is None and not visibility_message:
                    # Keep the existing byte/bit explanation; JLL may reference
                    # several values, so describe its unknown result as a whole.
                    index = condition.get("nv")
                    if "nvBit" in condition:
                        index = condition["nvBit"]["index"]
                    visibility_message = (
                        f"Visibility unknown: NV {index} has not been read."
                        if index is not None
                        else "Visibility unknown: a referenced value has not been read."
                    )
                elif result is False:
                    visible = False
            control.setToolTip((visibility_message if visible else "") or value_message)
            self.set_row_visible(control, visible)
            control.setEnabled(
                self.editing
                and (value is not None or self.allow_undefined)
                and not visibility_message
                and definition["type"] != "NodeVariableDual"
                and (not isinstance(control, MdfNumericValue) or bool(control.scale))
            )
            test = self.test_buttons.get(control)
            if test is not None:
                # Test rewrites the confirmed value, so it works outside Edit too.
                test.setEnabled(value is not None and not visibility_message)
            control.blockSignals(blocked)
            if not visible:
                counts["hidden"] += 1
            elif visibility_message:
                counts["unknown"] += 1
            else:
                counts["visible"] += 1

        # Keep the array title beside its first visible bit as modes change.
        for title, controls in self.bit_arrays:
            first = True
            for control in controls:
                layout = control.parentWidget().layout()
                visible = not control.isHidden()
                label = (
                    layout.labelForField(control)
                    if isinstance(layout, QFormLayout)
                    else self.labels.get(control)
                )
                label.setText(title + ":" if first and visible else "")
                if visible:
                    first = False

        # Leaf rows already include ancestor conditions. Use their explicit hidden
        # state so a previously hidden group can reappear when conditions change.
        for group, children in self.group_rows:
            visible = any(not child.isHidden() for child in children)
            group.parentWidget().layout().setRowVisible(group, visible)
        for tabs, index, children in self.tab_pages:
            tabs.setTabVisible(index, any(not child.isHidden() for child in children))
        # One summary per refresh: per-row detail would flood TRACE (#149).
        trace(
            logger,
            "MDF page refreshed node=%s page=%s visible=%s hidden=%s unknown_visibility=%s",
            self.node_number,
            self.page,
            counts["visible"],
            counts["hidden"],
            counts["unknown"],
        )


class PlainSplitterHandle(QSplitterHandle):
    """Retain native splitter dragging without Fusion's dotted grip decoration."""

    def paintEvent(self, event):
        pass


def output_on_write(definition) -> bool:
    """MDF outputOnWrite NVs drive their output whenever they are written."""
    return (
        definition.get("outputOnWrite") is True
        and type(definition.get("nodeVariableIndex")) is int
    )


def output_on_write_nvs(definition) -> set[int]:
    """Collect outputOnWrite NV indices from the nested MDF presentation."""
    result = set()

    def visit(value):
        if isinstance(value, dict):
            if output_on_write(value):
                result.add(value["nodeVariableIndex"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(definition.get("nodeVariables", []) if definition else [])
    return result


def settings_panels(definitions):
    """Root tabs supply navigation; consecutive flat items share a Settings page."""
    if not isinstance(definitions, list):
        raise TypeError("MDF nodeVariables must be a list")
    flat_items = []
    flat_page = 0
    for entry in definitions:
        if not isinstance(entry, dict) or "type" not in entry:
            raise ValueError("MDF nodeVariables entries need a type")
        if entry["type"] != "NodeVariableTabs":
            flat_items.append(entry)
            continue
        if flat_items:
            flat_page += 1
            yield "Settings" if flat_page == 1 else f"Settings {flat_page}", flat_items
            flat_items = []
        if not isinstance(entry["tabPanels"], list):
            raise TypeError("MDF tabPanels must be a list")
        for panel in entry["tabPanels"]:
            title = panel["displayTitle"]
            if not isinstance(title, str):
                raise TypeError("MDF panel title must be text")
            yield title, panel["items"]
    if flat_items:
        flat_page += 1
        yield "Settings" if flat_page == 1 else f"Settings {flat_page}", flat_items


class MdfNodeVariables(QSplitter):
    value_changed = Signal()
    test_requested = Signal(int)

    def __init__(self, definition=None):
        super().__init__(Qt.Orientation.Horizontal)
        self.node = None
        self.node_number = None
        self.values = None
        self.navigation = QListWidget()
        self.pages = QStackedWidget()
        self.raw_values = RawNodeVariables()
        self.raw_values.value_changed.connect(self.value_changed)
        self.navigation.addItem("Raw Values")
        self.pages.addWidget(self.raw_values)
        self.definition = None
        self.token_editor = None
        self.navigation.itemDoubleClicked.connect(self.edit_page_tokens)
        self.live_mode = False
        self.live_count = None
        # Last live values drawn; the service mutates its dictionary in place.
        self.live_shown = None
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self.refresh_raw_values)
        self.addWidget(self.navigation)
        self.addWidget(self.pages)
        self.setSizes([200, 800])
        self.set_definition(PROTOTYPE_MDF if definition is None else definition)

    def createHandle(self):
        return PlainSplitterHandle(self.orientation(), self)

    def edit_page_tokens(self, item):
        template = item.data(Qt.ItemDataRole.UserRole)
        if self.token_editor and template:
            self.token_editor.edit(template, item.text())

    def set_definition(self, definition, *, source=None, token_editor=None):
        """Replace presentation only; unsupported definitions remain explicit errors."""
        if definition == self.definition and token_editor is self.token_editor:
            return
        self.token_editor = token_editor
        self.definition = None
        self.live_shown = None
        self.navigation.setCurrentRow(0)
        while self.pages.count() > 1:
            page = self.pages.widget(1)
            self.pages.removeWidget(page)
            page.deleteLater()
            self.navigation.takeItem(1)
        if definition is None:
            return
        # Construct off-stack so a rejected MDF cannot leave partial navigation.
        forms = []
        try:
            source_panels = list(
                settings_panels((source or definition)["nodeVariables"])
            )
            for panel_index, (title, items) in enumerate(
                settings_panels(definition["nodeVariables"])
            ):
                source_title, source_items = source_panels[panel_index]
                form = MdfSettings(
                    items,
                    title,
                    len(forms) + 1,
                    source_definitions=source_items,
                    token_editor=token_editor,
                )
                if form.rows:
                    forms.append((title, source_title, form))
                else:
                    form.deleteLater()
        except ValueError, KeyError, TypeError:
            for _, _, form in forms:
                form.deleteLater()
            raise
        for title, source_title, form in forms:
            self.navigation.addItem(title)
            if token_editor:
                token_editor.bind_page(
                    self.navigation.item(self.navigation.count() - 1), source_title
                )
            self.pages.addWidget(form)
            form.value_edited.connect(self.update_value)
            form.test_requested.connect(self.test_requested)
        self.definition = definition

    def show_live_values(self, count, values, node_number=None):
        """Read the service's confirmed dictionary directly, including absent NVs."""
        self.set_editing(False)
        # Every CBUS reply for the selected node arrives here (#151); most leave
        # the NVs unchanged, so skip redrawing when nothing visible would differ.
        shown = (node_number, count, dict(values))
        if self.live_mode and shown == self.live_shown:
            trace(logger, "Retain unchanged MDF NV pages node=%s", node_number)
            return
        self.live_shown = shown
        self.values = values
        self.node_number = node_number
        self.live_mode = True
        self.live_count = count
        self.raw_values.show_live_values(count, values)
        self.show_pages()

    def show_node(self, node, values=None):
        self.live_mode = False
        self.live_shown = None
        self.node = node
        self.node_number = node.number
        self.values = values if values is not None else node.nv_values
        self.raw_values.show_node(node, self.values)
        self.show_pages()
        trace(logger, "Displayed prototype MDF node=%s", node.number)

    def refresh_raw_values(self, index):
        if self.values is None:
            return
        trace(logger, "Selected NV page page=%s live=%s", index, self.live_mode)
        if index == 0:
            if self.live_mode:
                self.raw_values.show_live_values(self.live_count, self.values)
            else:
                self.raw_values.show_node(self.node, self.values)
        else:
            self.show_page(index)

    def update_value(self, index, value):
        if self.live_mode:
            return
        self.values[index - 1 if isinstance(self.values, list) else index] = value
        self.value_changed.emit()

    def refresh_values(self):
        if self.values is None or self.live_mode:
            return
        self.raw_values.refresh_values()
        self.show_pages()

    def show_pages(self):
        # Only the selected page is drawn; refresh_raw_values draws any other
        # page when it is selected, before it is painted (#151).
        index = self.navigation.currentRow()
        if index > 0:
            self.show_page(index)

    def show_page(self, index):
        page = self.pages.widget(index)
        page.node_number = self.node_number
        page.show_values(self.values)

    def set_editing(self, editing):
        self.raw_values.set_editing(editing)
        for index in range(1, self.pages.count()):
            self.pages.widget(index).set_editing(editing)

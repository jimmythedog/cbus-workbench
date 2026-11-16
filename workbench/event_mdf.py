"""Inline raw and MDF editors of the same desired EV bytes."""

import logging

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIntValidator, QValidator
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from .logging_config import trace
from .mdf_visibility import evaluate_visibility
from .node_variables import MdfSettings, resolve_bit_label, validate_bit_label

logger = logging.getLogger(__name__)
_SUPPORTED = {
    "EventVariableSelect",
    "EventVariableNumber",
    "EventVariableSlider",
    "EventVariableBitSingle",
    "EventVariableBitArray",
}


class EvValueValidator(QIntValidator):
    """Allow a blank EV cell as well as a byte value."""

    def validate(self, text, position):
        if not text:
            return QValidator.State.Acceptable, text, position
        return super().validate(text, position)


class EvContainer(QWidget):
    """Keep the raw editor on the existing tree-item/save path."""

    def __init__(self, tree, item, *, compact):
        super().__init__()
        self.settings = []
        self.tree = tree
        self.item = item
        self.setAutoFillBackground(True)
        layout = QHBoxLayout(self) if compact else QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(8 if compact else 2)
        self.raw_value = QLineEdit(item.text(1))
        self.raw_value.setAccessibleName(f"{item.text(0)} raw value")
        self.raw_value.setFixedWidth(52)
        self.raw_value.setValidator(EvValueValidator(0, 255, self.raw_value))
        self.raw_value.editingFinished.connect(self.update_raw_value)
        self.raw_value.installEventFilter(self)
        layout.addWidget(self.raw_value)
        self.set_editing(False)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
            self.tree.setCurrentItem(self.item, 1)
        return super().eventFilter(watched, event)

    def update_raw_value(self):
        # Match the delegate: commit complete bytes (or blank) on focus loss.
        # Never save a valid prefix while the user is still typing a byte.
        if not self.raw_value.isReadOnly() and self.raw_value.hasAcceptableInput():
            self.item.setText(1, self.raw_value.text())

    def set_editing(self, editing):
        self.raw_value.setReadOnly(not editing)
        self.raw_value.setFrame(editing)
        for settings in self.settings:
            settings.set_editing(editing)


def ev_definitions(items, conditions=()):
    """Flatten containers only; preserve duplicate indices and ancestor conditions."""
    for definition in items:
        try:
            inherited = conditions
            if "visibilityLogic" in definition:
                condition = definition["visibilityLogic"]
                evaluate_visibility(condition, {}, {})
                inherited += (condition,)
            kind = definition["type"]
            if kind == "EventVariableGroup":
                yield from ev_definitions(definition["groupItems"], inherited)
            elif kind == "EventVariableTabs":
                for panel in definition["tabPanels"]:
                    # Panels may carry a condition independently of their tabs.
                    yield from ev_definitions(
                        [
                            {
                                **panel,
                                "type": "EventVariableGroup",
                                "groupItems": panel["items"],
                            }
                        ],
                        inherited,
                    )
            elif kind in _SUPPORTED:
                index = definition["eventVariableIndex"]
                if type(index) is not int or not 1 <= index <= 255:
                    raise ValueError("EV index must be an integer from 1 to 255")
                yield index, definition, inherited
            else:
                trace(logger, "Skip unsupported EV MDF type=%s", kind)
        except ValueError, KeyError, TypeError:
            logger.exception("Skipping invalid EV MDF definition=%s", definition)


def add_ev_controls(
    tree,
    event,
    ev_rows,
    definitions,
    nv_values,
    ev_values,
    node_number,
    *,
    source_definitions=None,
    token_editor=None,
):
    """Construct forms on expansion; retain them so editing can change visibility."""
    forms = {}
    for position, (index, definition, conditions) in enumerate(definitions):
        source = (
            source_definitions[position][1]
            if source_definitions is not None
            else definition
        )
        if index not in ev_rows:
            continue
        settings = None
        try:
            # Reuse existing byte widgets, not the NV navigation or editing path.
            normalized = {
                **definition,
                "type": definition["type"].replace("EventVariable", "NodeVariable"),
                "nodeVariableIndex": index,
            }
            normalized.pop("eventVariableIndex")
            normalized.pop("visibilityLogic", None)
            # Immediate output writes and Test are NV behaviour only (#139).
            normalized.pop("outputOnWrite", None)
            if definition["type"] == "EventVariableSelect":
                options = []
                for option in definition["options"]:
                    validate_bit_label(option)
                    label, reason = resolve_bit_label(
                        {**option, "bitPosition": option["value"]}, nv_values
                    )
                    if reason:
                        label = f"Unknown label (NV {option['overload']['nv']} unread)"
                    # An unmatched overload is not a known option label.
                    options.append({"value": option["value"], "label": label})
                normalized["options"] = options
                normalized["labelOptions"] = definition["options"]
            settings = MdfSettings(
                [normalized],
                "EV",
                index,
                parent_conditions=conditions,
                source_definitions=[source],
                token_editor=token_editor,
                allow_undefined=True,
            )
            contents = settings.takeWidget()
            # Keep full form labels inside the value column, beside their controls.
            layout = contents.layout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setVerticalSpacing(2)
            controls = [control for _, control, _ in settings.rows]

            trace(
                logger,
                "Construct EV MDF control node=%s event=%s ev=%s type=%s value=%s controls=%s conditions=%s",
                node_number,
                event.text(0),
                index,
                definition["type"],
                ev_values.get(index),
                len(controls),
                conditions,
            )
            forms.setdefault(index, []).append((contents, controls, settings))
            settings = None  # Ownership transfers to the inline container below.

        except ValueError, KeyError, TypeError:
            logger.exception(
                "Skipping invalid EV control node=%s event=%s ev=%s definition=%s",
                node_number,
                event.text(0),
                index,
                definition,
            )
        finally:
            if settings is not None:
                settings.deleteLater()

    for index, entries in forms.items():
        item = ev_rows[index]
        count = sum(len(controls) for _, controls, _ in entries)
        compact = count <= 2
        container = EvContainer(tree, item, compact=compact)
        for contents, controls, settings in entries:
            settings.setParent(container)
            settings.hide()
            container.settings.append(settings)
            settings.value_edited.connect(
                lambda _index, value, row=item: row.setText(1, str(value))
            )
            if compact:
                # Transfer the existing labels/widgets; a two-bit array must also
                # occupy one line. Qt layouts reparent the transferred widgets.
                for control in controls:
                    row = contents.layout().takeRow(control)
                    label = row.labelItem.widget() if row.labelItem else None
                    settings.labels[control] = label
                    if label is not None:
                        container.layout().addWidget(label)
                    container.layout().addWidget(control)
                contents.deleteLater()
            else:
                container.layout().addWidget(contents)
            settings.show_values(ev_values, nv_values=nv_values, ev_values=ev_values)
        if compact:
            container.layout().addStretch()
        tree.setItemWidget(item, 1, container)
        item.setSizeHint(1, container.sizeHint())
        alignment = (
            Qt.AlignmentFlag.AlignVCenter if compact else Qt.AlignmentFlag.AlignTop
        )
        item.setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | alignment)
        # Reserve enough width for the complete labels and native controls.
        tree.setColumnWidth(1, max(tree.columnWidth(1), container.sizeHint().width()))
        trace(
            logger,
            "EV layout node=%s event=%s ev=%s controls=%s compact=%s",
            node_number,
            event.text(0),
            index,
            count,
            compact,
        )

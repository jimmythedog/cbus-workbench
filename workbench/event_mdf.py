"""Inline raw and MDF editors of the same desired EV bytes."""

import logging
from collections import Counter

from PySide6.QtCore import QEvent
from PySide6.QtGui import QIntValidator, QValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QTreeWidgetItem,
    QWidget,
)

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


class NoHoverDelegate(QStyledItemDelegate):
    """No hover highlight on MDF control rows, whose labels are cell widgets."""

    def paint(self, painter, option, index):
        if index.parent().isValid() and not index.siblingAtColumn(0).data():
            option.state &= ~QStyle.StateFlag.State_MouseOver

        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        if index.column() == 0:
            return None

        return super().createEditor(parent, option, index)


class EvValueValidator(QIntValidator):
    """Allow a blank EV cell as well as a byte value."""

    def validate(self, text, position):
        if not text:
            return QValidator.State.Acceptable, text, position
        return super().validate(text, position)


class EvContainer(QWidget):
    """Keep the raw editor on the existing tree-item/save path.

    Each MDF control has its own child row of the EV row (#168): one tall row
    holding a whole form made Qt draw branch connectors halfway down it.
    """

    def __init__(self, tree, item):
        super().__init__()
        self.settings = []
        # (child tree item, control) for every control of this EV's forms.
        self.rows = []
        self.tree = tree
        self.item = item
        self.setAutoFillBackground(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        self.raw_value = QLineEdit(item.text(1))
        self.raw_value.setAccessibleName(f"{item.text(0)} raw value")
        self.raw_value.setFixedWidth(52)
        self.raw_value.setValidator(EvValueValidator(0, 255, self.raw_value))
        self.raw_value.editingFinished.connect(self.update_raw_value)
        self.raw_value.installEventFilter(self)
        layout.addWidget(self.raw_value)
        layout.addStretch()
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
        self.show_rows()

    def show_rows(self):
        """Hide the rows of controls MdfSettings hid (visibility, blank labels)."""
        for row, control in self.rows:
            row.setHidden(control.isHidden())


def row_cell(widget):
    """Wrap a control for a tree cell.

    The tree shows and hides cell widgets itself, so MdfSettings must hide the
    wrapped control, never the cell, for its visibility state to stay reliable.
    """
    cell = QWidget()
    layout = QHBoxLayout(cell)
    layout.setContentsMargins(2, 0, 2, 0)
    layout.addWidget(widget)
    layout.addStretch()
    return cell


def ev_definitions(items, conditions=(), group=""):
    """Flatten containers only; preserve duplicate indices and ancestor conditions.

    Each control also carries its nearest nonblank group (or tab panel) title.
    """
    for definition in items:
        try:
            inherited = conditions
            if "visibilityLogic" in definition:
                condition = definition["visibilityLogic"]
                evaluate_visibility(condition, {}, {})
                inherited += (condition,)
            kind = definition["type"]
            if kind == "EventVariableGroup":
                title = definition.get("displayTitle")
                nearest = title if isinstance(title, str) and title.strip() else group
                yield from ev_definitions(definition["groupItems"], inherited, nearest)
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
                        group,
                    )
            elif kind in _SUPPORTED:
                index = definition["eventVariableIndex"]
                if type(index) is not int or not 1 <= index <= 255:
                    raise ValueError("EV index must be an integer from 1 to 255")
                yield index, definition, inherited, group
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
    # Titles repeated within one EV (e.g. a bit or mask per output) are told
    # apart by their group (#169); unique titles stay as the MDF gives them.
    titles = Counter(
        (index, definition.get("displayTitle"))
        for index, definition, _, _ in definitions
        if isinstance(definition.get("displayTitle"), str)
    )
    for position, (index, definition, conditions, group) in enumerate(definitions):
        if source_definitions is not None:
            _, source, _, source_group = source_definitions[position]
        else:
            source, source_group = definition, group
        if index not in ev_rows:
            continue
        title = definition.get("displayTitle")
        if group and titles[index, title] > 1:
            definition = {**definition, "displayTitle": f"{group} — {title}"}
            # The source keeps its tokens so double-click can edit the group name.
            source = {
                **source,
                "displayTitle": f"{source_group} — {source['displayTitle']}",
            }
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
            settings.node_number = node_number
            # Several events can share an EV index, so name the event too.
            settings.page = f"event {event.text(0)} EV {index}"
            contents = settings.takeWidget()
            # Keep full form labels inside the value column, beside their controls.
            layout = contents.layout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setVerticalSpacing(2)
            controls = [control for _, control, _ in settings.rows]

            trace(
                logger,
                "Construct EV MDF control node=%s event=%s ev=%s type=%s title=%r value=%s controls=%s conditions=%s",
                node_number,
                event.text(0),
                index,
                definition["type"],
                definition["displayTitle"],
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
        # Control rows sit one level below the EV row; top-level rows are
        # indented too because the trees decorate their roots.
        depth = 1
        ancestor = item
        while ancestor is not None:
            depth += 1
            ancestor = ancestor.parent()
        container = EvContainer(tree, item)
        for contents, controls, settings in entries:
            settings.setParent(container)
            settings.hide()
            container.settings.append(settings)
            settings.value_edited.connect(
                lambda _index, value, row=item: row.setText(1, str(value))
            )
            for control in controls:
                # Move each form row into a child row. MdfSettings finds a
                # moved row's label in labels, as for any non-form layout.
                row = contents.layout().takeRow(control)
                label = row.labelItem.widget() if row.labelItem else None
                settings.labels[control] = label
                child = QTreeWidgetItem(item)
                if label is not None:
                    label_cell = row_cell(label)
                    tree.setItemWidget(child, 0, label_cell)
                    # Labels sit inside the item text rect, whose margins Qt
                    # derives from this metric.
                    margins = 2 * (
                        tree.style().pixelMetric(
                            QStyle.PixelMetric.PM_FocusFrameHMargin, None, tree
                        )
                        + 1
                    )
                    tree.setColumnWidth(
                        0,
                        max(
                            tree.columnWidth(0),
                            depth * tree.indentation()
                            + margins
                            + label_cell.sizeHint().width(),
                        ),
                    )
                control_cell = row_cell(control)
                tree.setItemWidget(child, 1, control_cell)
                child.setSizeHint(1, control_cell.sizeHint())
                tree.setColumnWidth(
                    1, max(tree.columnWidth(1), control_cell.sizeHint().width())
                )
                container.rows.append((child, control))
            contents.deleteLater()
            settings.show_values(ev_values, nv_values=nv_values, ev_values=ev_values)
        tree.setItemWidget(item, 1, container)
        container.show_rows()
        item.setExpanded(True)
        trace(
            logger,
            "EV layout node=%s event=%s ev=%s control_rows=%s",
            node_number,
            event.text(0),
            index,
            len(container.rows),
        )

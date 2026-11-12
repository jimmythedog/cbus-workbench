"""Plan and save a bounded annotation import using CW's existing YAML APIs."""

import logging
import shutil
from copy import deepcopy
from dataclasses import dataclass, field

from .annotations import annotation_path, load_annotations, save_annotations
from .app_settings import load_settings, save_settings, validate_settings
from .logging_config import trace
from .mmc_layouts import MmcLayout
from .observed_events import EventIdentity, ObservedEvents

logger = logging.getLogger("workbench.mmc_import")


@dataclass
class ImportTarget:
    source: MmcLayout
    name: str
    logical_layout: str
    new: bool
    # Each entry holds node number (None = layout), original and merged annotations.
    changes: list[tuple[int | None, dict, dict]] = field(default_factory=list)
    counts: dict[str, int] = field(
        default_factory=lambda: {"added": 0, "replaced": 0, "preserved": 0}
    )


@dataclass
class ImportPlan:
    settings: dict
    targets: list[ImportTarget]


def merge_annotations(
    existing: dict, imported: dict, overwrite: bool, counts: dict
) -> dict:
    """Apply the same leaf-value rule to names, events and token overrides."""
    result = deepcopy(existing)
    for key, value in imported.items():
        if isinstance(value, dict):
            result[key] = merge_annotations(
                result.get(key, {}), value, overwrite, counts
            )
        elif key in result and not overwrite:
            counts["preserved"] += 1
        else:
            counts["replaced" if key in result else "added"] += 1
            result[key] = value
    return result


def plan_import(
    selections: list[tuple[MmcLayout, str]],
    overwrite: bool,
    confirmed_layouts: dict | None = None,
) -> ImportPlan:
    """Preview destinations, or use confirmed Layout Settings values.

    A new destination has no logical ID until its settings have been reviewed.
    Such a preview cannot be saved through save_import.
    """
    if not selections:
        raise ValueError("Select at least one layout")
    settings = load_settings()
    by_name = {name.casefold(): name for name in settings["layouts"]}
    targets = []
    destinations = set()
    for source, entered in selections:
        entered = entered.strip()
        if not entered:
            raise ValueError("Each selected layout needs a CW layout name")
        name = by_name.get(entered.casefold(), entered)
        new = name not in settings["layouts"]
        if confirmed_layouts is not None:
            saved = dict(confirmed_layouts[entered])
            if new:
                saved["auto_connect"] = False
            saved = validate_settings(
                {"default_layout": name, "layouts": {name: saved}}
            )["layouts"][name]
            settings["layouts"][name] = saved
        elif new:
            settings["layouts"][name] = {
                "logical_layout": "",
                "auto_connect": False,
                "connection": dict(source.connection),
            }
        logical_layout = settings["layouts"][name]["logical_layout"]
        by_name[name.casefold()] = name
        # Shared logical layouts address the same files, regardless of display name.
        destination = (
            ("logical", logical_layout.casefold())
            if logical_layout
            else ("new", name.casefold())
        )
        if destination in destinations:
            raise ValueError(
                "Choose distinct destination layouts for the selected MMC layouts"
            )
        destinations.add(destination)
        target = ImportTarget(source, name, logical_layout, new)
        for number, imported in [(None, source.annotations), *source.nodes.items()]:
            existing = (
                load_annotations(logical_layout, number) if logical_layout else {}
            )
            merged = merge_annotations(existing, imported, overwrite, target.counts)
            # Empty node files deliberately retain unnamed, unverified offline nodes.
            if merged != existing or (
                number is not None
                and (
                    not logical_layout
                    or not annotation_path(logical_layout, number).exists()
                )
            ):
                target.changes.append((number, existing, merged))
        trace(
            logger,
            "Planned MMC import source=%s layout=%s id=%s new=%s overwrite=%s counts=%s",
            source.path,
            name,
            logical_layout,
            new,
            overwrite,
            target.counts,
        )
        targets.append(target)
    if settings["default_layout"] is None:
        settings["default_layout"] = targets[0].name
    if confirmed_layouts is not None or not any(target.new for target in targets):
        settings = validate_settings(settings)
    return ImportPlan(settings, targets)


def save_import(plan: ImportPlan) -> None:
    """Publish settings last; undo local data saves on ordinary failure.

    This is deliberately a local rollback, not a new persistence framework.
    A process crash can leave unpublished new directories. Hardware configuration
    and backups are never part of the write set.
    """
    # Reject an unreviewed preview before it can write into any directory.
    validate_settings(plan.settings)
    created = []
    completed = []
    observation_files = []
    try:
        for target in plan.targets:
            directory = annotation_path(target.logical_layout).parent
            if not directory.exists():
                directory.parent.mkdir(parents=True, exist_ok=True)
                directory.mkdir()
                created.append(directory)
            for number, previous, merged in target.changes:
                path = annotation_path(target.logical_layout, number)
                existed = path.exists()
                parent_existed = path.parent.exists()
                try:
                    save_annotations(target.logical_layout, merged, number)
                except OSError:
                    path.with_suffix(".yaml.tmp").unlink(missing_ok=True)
                    if not parent_existed and path.parent.exists():
                        path.parent.rmdir()
                    raise
                completed.append(
                    (target.logical_layout, number, previous, existed, parent_existed)
                )
            # MMC names identify catalogue entries even without new network traffic.
            # Use observe() so imports share normal identity deduplication and format.
            observations = ObservedEvents(target.logical_layout)
            path = observations.path
            observation_files.append(
                (path, path.read_bytes() if path.exists() else None)
            )
            for key in target.source.annotations.get("events", {}):
                observations.observe(EventIdentity(*map(int, key.split(":"))))
        if plan.settings != load_settings():
            save_settings(plan.settings)
    except Exception:
        logger.exception("MMC import failed; restoring local data saves")
        rollback_errors = []
        for path, previous in reversed(observation_files):
            try:
                path.with_suffix(".yaml.tmp").unlink(missing_ok=True)
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(previous)
            except OSError as error:
                logger.exception("Cannot undo imported observations path=%s", path)
                rollback_errors.append(str(error))
        for logical_layout, number, previous, existed, parent_existed in reversed(
            completed
        ):
            try:
                if existed:
                    save_annotations(logical_layout, previous, number)
                else:
                    path = annotation_path(logical_layout, number)
                    path.unlink()
                    if not parent_existed:
                        path.parent.rmdir()
            except OSError as error:
                logger.exception(
                    "Cannot undo import layout=%s node=%s", logical_layout, number
                )
                rollback_errors.append(str(error))
        for directory in reversed(created):
            try:
                shutil.rmtree(directory)
            except OSError as error:
                logger.exception(
                    "Cannot remove unpublished import directory=%s", directory
                )
                rollback_errors.append(str(error))
        if rollback_errors:
            raise OSError(
                "Import failed and cleanup was incomplete: "
                + "; ".join(rollback_errors)
            )
        raise
    for target in plan.targets:
        logger.info(
            "Imported MMC layout source=%s destination=%s id=%s counts=%s",
            target.source.path,
            target.name,
            target.logical_layout,
            target.counts,
        )

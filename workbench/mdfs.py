"""Locate MMC JSON descriptors independently of editors and configuration writes."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .logging_config import trace
from .paths import system_mdf_directory, user_mdf_directory
from .pnn import Pnn

logger = logging.getLogger("workbench.mdfs")
# Repositories are per navigator, but this installation warning is per process.
_missing_system_directory_warned = False

# MMC v0.23.2 stores identity in filenames, not in the descriptor JSON.
# Names can contain hyphens; the final segments carry the identity and version.
# Source: MMC-SERVER VLCB-server/configuration.js and config/modules/.
_FILENAME = re.compile(
    r".+-(?P<module>[0-9A-Fa-f]{4})-(?P<major>\d+)(?P<minor>[A-Za-z])"
    r"(?:--[Pp](?P<processor>\d+))?\.json"
)


class MdfError(ValueError):
    """A matching descriptor cannot be used; callers should report this error."""


@dataclass(frozen=True)
class Mdf:
    path: Path
    data: dict


class MdfRepository:
    """Look up current files on each request; user edits need no cache refresh."""

    def __init__(
        self, system_directory: Path | None = None, user_directory: Path | None = None
    ):
        self.system_directory = (
            system_directory if system_directory is not None else system_mdf_directory()
        )
        self.user_directory = (
            user_directory if user_directory is not None else user_mdf_directory()
        )

    def lookup(self, identity: Pnn | None, parameters: dict[int, int]) -> Mdf | None:
        """Select from confirmed PNN/PARAN data, never display labels or saved guesses.

        Firmware must match with case-insensitive letters. Like MMC-SERVER,
        selection uses major/minor firmware, without checking beta parameter 20.
        """
        global _missing_system_directory_warned
        if not _missing_system_directory_warned and not self.system_directory.exists():
            logger.warning(
                "System MDF directory is missing: %s", self.system_directory.absolute()
            )
            _missing_system_directory_warned = True
        trace(logger, "MDF lookup identity=%s parameters=%s", identity, parameters)
        if identity is None or 2 not in parameters or 7 not in parameters:
            trace(logger, "No MDF: identity or firmware is incomplete")
            return None
        if any(
            index in parameters and parameters[index] != value
            for index, value in (
                (1, identity.manufacturer),
                (3, identity.module_type),
            )
        ):
            trace(logger, "No MDF: PNN and PARAN identity disagree")
            return None
        module = f"{identity.manufacturer:02X}{identity.module_type:02X}"
        version = f"{parameters[7]}{chr(parameters[2])}"
        for directory in (self.user_directory, self.system_directory):
            path = self._matching_path(directory, module, version, parameters.get(9))
            if path is not None:
                return self._load(path, identity.node_number)
        trace(
            logger,
            "No compatible MDF for node=%s module=%s version=%s",
            identity.node_number,
            module,
            version,
        )
        return None

    def _matching_path(
        self, directory: Path, module: str, version: str, processor: int | None
    ) -> Path | None:
        try:
            files = sorted(directory.iterdir())
        except FileNotFoundError:
            trace(logger, "MDF directory is absent: %s", directory)
            return None
        except OSError as error:
            logger.exception("Cannot read MDF directory %s", directory)
            raise MdfError(f"Cannot read MDF directory {directory}: {error}") from error

        generic = []
        specific = []
        for path in files:
            match = _FILENAME.fullmatch(path.name)
            if match is None:
                continue
            if (
                match["module"].upper() != module
                or (match["major"] + match["minor"]).casefold() != version.casefold()
            ):
                continue
            restriction = match["processor"]
            if restriction is None:
                generic.append(path)
            elif processor is not None and int(restriction) == processor:
                specific.append(path)
        candidates = specific or generic
        if len(candidates) > 1:
            message = (
                f"Ambiguous MDFs for {module}-{version} in {directory}: {candidates}"
            )
            logger.error(message)
            raise MdfError(message)
        trace(
            logger,
            "MDF candidates directory=%s module=%s version=%s processor=%s selected=%s",
            directory,
            module,
            version,
            processor,
            candidates,
        )
        return candidates[0] if candidates else None

    def _load(self, path: Path, node_number: int) -> Mdf:
        try:
            with path.open(encoding="utf-8") as source:
                data = json.load(source)
            # Validate the discovery contract only. Interpretation of individual
            # control types and constraints belongs to the later editor adapter.
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("moduleName"), str)
                or not data["moduleName"].strip()
            ):
                raise ValueError("Expected an object with a nonempty moduleName")
            if not isinstance(data.get("nodeVariables"), list):
                raise TypeError("Expected a nodeVariables list")
            if "eventVariables" in data and not isinstance(
                data["eventVariables"], list
            ):
                raise ValueError("Expected an eventVariables list")
            for key in ("nodeVariables", "eventVariables"):
                if any(
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("type"), str)
                    or not entry["type"].strip()
                    for entry in data.get(key, [])
                ):
                    raise ValueError(f"Expected objects with a nonempty type in {key}")
        except (OSError, ValueError, TypeError) as error:
            logger.exception("Invalid MDF for node=%s path=%s", node_number, path)
            raise MdfError(f"Invalid MDF {path}: {error}") from error
        logger.info("Selected MDF for node=%s path=%s", node_number, path)
        return Mdf(path, data)

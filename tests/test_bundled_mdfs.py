"""Source and frozen MDF resource layout and packaging contracts."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_bundled_mdfs import check_bundled_mdfs
from workbench.mdfs import MdfRepository
from workbench.paths import system_mdf_directory
from workbench.pnn import Pnn

FIXTURES = Path(__file__).parent / "fixtures" / "mdfs"
ACE = "CANACE3-A504-2g.json"


class BundledMdfTests(unittest.TestCase):
    def test_source_resource_path(self):
        with patch.dict(sys.__dict__):
            sys.__dict__.pop("_MEIPASS", None)
            self.assertEqual(
                system_mdf_directory(),
                Path(__file__).resolve().parents[1] / "resources" / "mdfs",
            )

    def test_frozen_layout_lookup_and_user_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            shutil.copy(FIXTURES / ACE, source)
            user = root / "user"
            user.mkdir()
            # macOS relocates data into Resources; other onedir builds use _internal.
            for layout in ("_internal", "App.app/Contents/Resources"):
                with self.subTest(layout=layout):
                    bundle = root / layout
                    destination = bundle / "resources" / "mdfs"
                    destination.mkdir(parents=True)
                    shutil.copy(source / ACE, destination)
                    self.assertEqual(check_bundled_mdfs(source, bundle), 1)
                    with patch.object(sys, "_MEIPASS", str(bundle), create=True):
                        repository = MdfRepository(user_directory=user)
                        identity = Pnn(42, 0xA5, 4, 0)
                        parameters = {2: ord("g"), 7: 2}
                        self.assertEqual(
                            repository.lookup(identity, parameters).path,
                            destination / ACE,
                        )
                        override = Path(shutil.copy(source / ACE, user))
                        self.assertEqual(
                            repository.lookup(identity, parameters).path, override
                        )
                        override.unlink()

    def test_packaging_rejects_missing_empty_incomplete_or_changed_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            bundle = root / "bundle"
            with self.assertRaises(ValueError):
                check_bundled_mdfs(source, bundle)
            source.mkdir()
            with self.assertRaises(ValueError):
                check_bundled_mdfs(source, bundle)
            shutil.copy(FIXTURES / ACE, source)
            with self.assertRaises(ValueError):
                check_bundled_mdfs(source, bundle)
            destination = bundle / "resources" / "mdfs"
            destination.mkdir(parents=True)
            (destination / ACE).write_text("{}")
            with self.assertRaises(ValueError):
                check_bundled_mdfs(source, bundle)

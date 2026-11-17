"""Offline user guide build, packaging and runtime resource layout."""

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_user_guide import ONLINE_DOCS, SOURCE, build_user_guide
from scripts.check_bundled_user_guide import check_bundled_user_guide
from workbench.paths import user_guide_path

GUIDE = """# User guide

See the [installation guide](installation.md) and [backups](#backup-storage).

![Main window](images/main%20window.png)

| Column | Meaning |
| ------ | ------- |
| Node   | Number  |

### Backup storage

Stored under the data directory.
"""


class UserGuideBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docs = self.root / "docs"
        (self.docs / "images").mkdir(parents=True)
        self.source = self.docs / "user-guide.md"
        self.source.write_text(GUIDE, encoding="utf-8")
        (self.docs / "images" / "main window.png").write_bytes(b"png")
        self.destination = self.root / "resources" / "user-guide"

    def test_page_is_self_contained_with_images_anchors_and_online_links(self):
        page = build_user_guide(self.source, self.destination)
        html = page.read_text(encoding="utf-8")
        self.assertEqual(page, self.destination / "user-guide.html")
        self.assertEqual(
            (self.destination / "images" / "main window.png").read_bytes(), b"png"
        )
        self.assertIn('href="#backup-storage"', html)
        self.assertIn('id="backup-storage"', html)
        self.assertIn(f'href="{ONLINE_DOCS}installation.md"', html)
        self.assertIn("<table>", html)

    def test_rebuild_removes_stale_files(self):
        stale = self.destination / "images" / "old.png"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"old")
        build_user_guide(self.source, self.destination)
        self.assertFalse(stale.exists())

    def test_missing_or_external_image_is_rejected(self):
        for image in ("images/missing.png", "../secret.png"):
            with self.subTest(image=image):
                (self.root / "secret.png").write_bytes(b"x")
                self.source.write_text(f"![x]({image})\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    build_user_guide(self.source, self.destination)

    def test_real_guide_internal_links_have_targets(self):
        html = build_user_guide(SOURCE, self.destination).read_text(encoding="utf-8")
        targets = set(re.findall(r'id="([^"]+)"', html))
        links = set(re.findall(r'href="#([^"]+)"', html))
        self.assertTrue(links)
        self.assertEqual(links - targets, set())


class BundledUserGuideTests(unittest.TestCase):
    def test_frozen_layouts_resolve_checked_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "built"
            (source / "images").mkdir(parents=True)
            (source / "user-guide.html").write_text("guide", encoding="utf-8")
            (source / "images" / "a.png").write_bytes(b"png")
            # Data lives in Contents/Resources in a macOS app (reached through
            # links from _MEIPASS) and in _internal in other onedir builds.
            for layout in ("_internal", "App.app/Contents/Resources"):
                with self.subTest(layout=layout):
                    bundle = root / layout
                    destination = bundle / "resources" / "user-guide"
                    (destination / "images").mkdir(parents=True)
                    (destination / "user-guide.html").write_text("guide")
                    (destination / "images" / "a.png").write_bytes(b"png")
                    self.assertEqual(check_bundled_user_guide(source, bundle), 2)
                    with patch.object(sys, "_MEIPASS", str(bundle), create=True):
                        self.assertEqual(
                            user_guide_path(), destination / "user-guide.html"
                        )

    def test_packaging_rejects_missing_incomplete_or_changed_guide(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "built"
            bundle = root / "_internal"
            destination = bundle / "resources" / "user-guide"
            with self.assertRaises(ValueError):
                check_bundled_user_guide(source, bundle)

            (source / "images").mkdir(parents=True)
            (source / "user-guide.html").write_text("guide", encoding="utf-8")
            (source / "images" / "a.png").write_bytes(b"png")
            destination.mkdir(parents=True)
            (destination / "user-guide.html").write_text("guide", encoding="utf-8")
            with self.assertRaises(ValueError):
                check_bundled_user_guide(source, bundle)

            (destination / "images").mkdir()
            (destination / "images" / "a.png").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                check_bundled_user_guide(source, bundle)


if __name__ == "__main__":
    unittest.main()

"""Build the offline HTML User Guide from docs/user-guide.md.

The Markdown file stays the only source. The generated page and the images it
uses go to resources/user-guide (git-ignored), which PyInstaller bundles.
"""

import argparse
import html
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

import markdown

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "user-guide.md"
DESTINATION = ROOT / "resources" / "user-guide"
# Other documents are not bundled; relative links to them open the online copy.
ONLINE_DOCS = "https://github.com/jimmythedog/cbus-workbench/blob/main/docs/"

# Python-Markdown writes attributes with double quotes; a link is relative
# when it has no URL scheme and is not an in-page or root-relative reference.
# Literal href="…" or src="…" text in a code span would also match; the guide
# has none, so a full HTML parser is not worth it.
RELATIVE_LINK = re.compile(r'href="(?![a-z][a-z0-9+.-]*:|#|/)([^"]+)"', re.IGNORECASE)
RELATIVE_IMAGE = re.compile(r'src="(?![a-z][a-z0-9+.-]*:|/)([^"]+)"', re.IGNORECASE)

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ max-width: 52rem; margin: 0 auto; padding: 1rem 1.5rem 4rem;
  font: 16px/1.55 system-ui, sans-serif; }}
img {{ max-width: 100%; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #8888; padding: 0.3rem 0.6rem; text-align: left; }}
code {{ font-size: 0.9em; }}
pre {{ overflow-x: auto; padding: 0.6rem; background: #8882; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def build_user_guide(source: Path, destination: Path) -> Path:
    """Replace destination with the guide page and its local images."""
    converter = markdown.Markdown(extensions=["tables", "fenced_code", "toc"])
    # For plain headings the toc extension's ids match GitHub's, so the guide's
    # "#section" links work in both; the real-guide test catches any divergence.
    body = converter.convert(source.read_text(encoding="utf-8"))
    body = RELATIVE_LINK.sub(lambda m: f'href="{ONLINE_DOCS}{m[1]}"', body)
    # src stays URL-encoded for the browser; the file names are decoded.
    images = [unquote(html.unescape(path)) for path in RELATIVE_IMAGE.findall(body)]

    docs = source.parent.resolve()
    for image in images:
        path = (docs / image).resolve()
        if not path.is_relative_to(docs) or not path.is_file():
            raise ValueError(f"User guide image is missing or outside docs: {image}")

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for image in images:
        target = destination / image
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(docs / image, target)
    page = destination / "user-guide.html"
    page.write_text(
        TEMPLATE.format(title="CBUS Workbench User Guide", body=body),
        encoding="utf-8",
    )
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    page = build_user_guide(SOURCE, DESTINATION)
    print(f"Built {page}")


if __name__ == "__main__":
    main()

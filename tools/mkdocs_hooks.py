# tools/mkdocs_hooks.py
"""MkDocs hook for the project site (mkdocs.yml → hooks).

The site states the current version and release date — on the home page and
in the schema.org data search engines read. Both come from app/version.py, the
single source tools/release.py writes, so a release never has to touch the
site. The file is read as text: importing the app package would pull in Qt.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_version(root: str = ROOT) -> dict:
    with open(os.path.join(root, "app", "version.py"), encoding="utf-8") as f:
        text = f.read()

    def field(name):
        m = re.search(rf'^{name} = "([^"]*)"', text, re.M)
        return m.group(1) if m else ""
    return {"app_version": field("APP_VERSION"),
            "release_date": field("RELEASE_DATE")}


def on_config(config, **_kwargs):
    config.extra.update(read_version())
    return config


def on_page_markdown(markdown, config, **_kwargs):
    """``{{ app_version }}`` in a page → the current version."""
    return markdown.replace("{{ app_version }}", config.extra["app_version"])

"""Shared test setup: headless Qt, project imports, and a guard that no test
can ever write the real app_settings.json."""
import os
import sys

# Headless BEFORE any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Tests live in tests/; the project modules live in the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    """One QApplication for the whole session + block settings writes."""
    app = QApplication.instance() or QApplication([])

    # No test may touch the real app_settings.json — nor READ it: a window
    # built from the developer's own settings loads their last map and
    # project, which made results depend on whose machine ran the suite.
    import tempfile
    from app import settings_manager
    from app import app_context
    from gui import main_window as gui_main
    settings_manager.SETTINGS_FILE = os.path.join(
        tempfile.mkdtemp(prefix="mbr-tests-"), "app_settings.json")
    # Nor the real Projects folder: every window puts the demo's copy there
    # once (gui/main_window._seed_projects) — from the sources that is the
    # developer's own Documents/ModbusReader.
    from app import projects
    projects._cache["dir"] = tempfile.mkdtemp(prefix="mbr-projects-")
    # Keep the real implementation reachable under another name: a test that
    # wants to exercise saving itself (atomic write, backup path) must point
    # SETTINGS_FILE at a tmp_path first and call this explicitly.
    settings_manager.real_save_settings = settings_manager.save_settings
    settings_manager.save_settings = lambda d: None
    app_context.save_settings = lambda d: None
    gui_main.save_settings = lambda d: None

    yield app

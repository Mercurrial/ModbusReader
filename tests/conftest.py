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
    import settings_manager, app_context, gui_main
    settings_manager.SETTINGS_FILE = os.path.join(
        tempfile.mkdtemp(prefix="mbr-tests-"), "app_settings.json")
    # Keep the real implementation reachable under another name: a test that
    # wants to exercise saving itself (atomic write, backup path) must point
    # SETTINGS_FILE at a tmp_path first and call this explicitly.
    settings_manager.real_save_settings = settings_manager.save_settings
    settings_manager.save_settings = lambda d: None
    app_context.save_settings = lambda d: None
    gui_main.save_settings = lambda d: None

    yield app

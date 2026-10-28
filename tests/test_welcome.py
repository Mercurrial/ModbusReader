"""First launch: the «make it yours» card (gui/welcome.py) — every pick
applies to the live window at once, then the tour or not."""
import copy

import pytest
from PyQt6.QtWidgets import QApplication

from app.settings_manager import DEFAULT_SETTINGS


@pytest.fixture()
def first_run(monkeypatch, tmp_path):
    from app import settings_manager
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(tmp_path / "s.json"),
                        raising=False)
    base = copy.deepcopy(DEFAULT_SETTINGS)
    base.update(guide_seen_main=False, lang="ru")
    monkeypatch.setattr(gui_main, "load_settings", lambda: copy.deepcopy(base))
    w = gui_main.ModernScadaApp()
    w.resize(1280, 800)
    yield w
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _pump(n=5):
    for _ in range(n):
        QApplication.processEvents()


def test_first_launch_opens_the_card_before_the_tour(first_run):
    from gui.welcome import WelcomeSetup
    w = first_run
    w._maybe_show_onboarding()
    assert isinstance(w._guide, WelcomeSetup)
    assert w.settings["guide_seen_main"] is True        # never again unprompted
    w._show_help()                                      # F1 does not stack a tour on it
    assert isinstance(w._guide, WelcomeSetup)


def test_picks_apply_to_the_window_at_once(first_run):
    from gui.theme_manager import schemes_for
    from gui.welcome import font_choices
    w = first_run
    w._maybe_show_onboarding()
    card = w._guide
    card.seg_theme.setValue("Light")
    assert w.settings["theme"] == "Light"
    assert w.settings["scheme"] in schemes_for("Light")    # no dark scheme on light
    card.swatches.setValue("teal")
    assert w.settings["accent"] == "teal"
    card.rail_tiles.setValue("top")
    assert w.settings["rail_position"] == "top" and w.nav_rail.position == "top"
    assert w._shell.indexOf(w.nav_rail) == 0
    card.seg_size.setValue(11)
    assert w.settings["font_size"] == 11
    fams = font_choices()
    if len(fams) > 1:                       # a machine with a font database
        card.font_tiles.setValue(fams[1])
        assert fams[1] in w.settings["font_family"]
    card.seg_lang.setValue("en")
    assert w.lang == "en"
    assert card.lbl_title.text() == w.t("welcomeTitle")
    assert card.seg_theme._buttons["Light"].text() == "Light"
    assert w._guide is card and card.isVisibleTo(w)      # still on top


def test_next_starts_the_tour_and_skip_does_not(first_run):
    from gui.onboarding import OnboardingGuide
    w = first_run
    w.show()
    w._maybe_show_onboarding()
    w._guide._finish(True)
    _pump()
    assert isinstance(w._guide, OnboardingGuide)
    w._guide._finish()
    _pump()
    assert w._guide is None
    w._show_welcome()
    w._guide._finish(False)
    _pump()
    assert w._guide is None


def test_font_tiles_are_installed_faces_with_the_current_one():
    from PyQt6.QtGui import QFontDatabase
    from app import fonts
    from gui.welcome import font_choices, FONT_TILES
    installed = set(QFontDatabase.families())
    picks = font_choices()
    assert len(picks) <= FONT_TILES
    assert all(f in installed and not fonts.is_symbol_font(f) for f in picks)
    usable = [f for f in installed if not fonts.is_symbol_font(f)]
    if usable:
        odd = sorted(usable)[-1]
        assert font_choices(odd)[0] == odd


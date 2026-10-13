"""Font choices must never be able to make the UI unreadable.

Picking a symbol family (Wingdings, the Segoe icon fonts) used to turn every
label into dingbats — including the settings page you would fix it from. The
list is filtered and the saved value is validated on the way in.
"""
from PyQt6.QtGui import QFontDatabase

import fonts


def test_symbol_fonts_are_rejected(monkeypatch):
    ws = QFontDatabase.WritingSystem
    monkeypatch.setattr(fonts, "_cache", {})
    monkeypatch.setattr(QFontDatabase, "writingSystems",
                        staticmethod(lambda fam: {
                            "Wingdings": [ws.Symbol],
                            "Segoe Fluent Icons": [ws.Other],
                            "Segoe UI": [ws.Latin, ws.Cyrillic, ws.Greek],
                            "Consolas": [ws.Latin],
                        }.get(fam, [])))
    assert fonts.is_symbol_font("Wingdings")
    assert fonts.is_symbol_font("Segoe Fluent Icons")
    assert not fonts.is_symbol_font("Segoe UI")
    assert not fonts.is_symbol_font("Consolas")
    # Unknown to Qt -> treated as unsafe rather than gambling on it
    assert fonts.is_symbol_font("Nonesuch")


def test_cyrillic_detection(monkeypatch):
    ws = QFontDatabase.WritingSystem
    monkeypatch.setattr(fonts, "_cache", {})
    monkeypatch.setattr(QFontDatabase, "writingSystems",
                        staticmethod(lambda fam: {
                            "Segoe UI": [ws.Latin, ws.Cyrillic],
                            "Consolas": [ws.Latin],
                        }.get(fam, [])))
    assert fonts.has_cyrillic("Segoe UI")
    assert not fonts.has_cyrillic("Consolas")


def _fake_db(monkeypatch, installed, systems):
    monkeypatch.setattr(fonts, "_cache", {})
    monkeypatch.setattr(QFontDatabase, "families",
                        staticmethod(lambda *a, **k: list(installed)))
    monkeypatch.setattr(QFontDatabase, "writingSystems",
                        staticmethod(lambda fam: systems.get(fam, [])))


def test_ui_families_drops_the_symbol_fonts(monkeypatch):
    ws = QFontDatabase.WritingSystem
    _fake_db(monkeypatch, ["Segoe UI", "Wingdings", "Arial", "Marlett"],
             {"Segoe UI": [ws.Latin, ws.Cyrillic], "Arial": [ws.Latin],
              "Wingdings": [ws.Symbol], "Marlett": [ws.Symbol]})
    assert fonts.ui_families() == ["Segoe UI", "Arial"]


def test_safe_family_keeps_a_good_choice(monkeypatch):
    ws = QFontDatabase.WritingSystem
    _fake_db(monkeypatch, ["Segoe UI", "Consolas"],
             {"Segoe UI": [ws.Latin, ws.Cyrillic], "Consolas": [ws.Latin]})
    assert fonts.safe_family("Consolas") == "Consolas"


def test_safe_family_rescues_a_symbol_or_missing_font(monkeypatch):
    ws = QFontDatabase.WritingSystem
    _fake_db(monkeypatch, ["Segoe UI", "Wingdings"],
             {"Segoe UI": [ws.Latin, ws.Cyrillic], "Wingdings": [ws.Symbol]})
    assert fonts.safe_family("Wingdings") == "Segoe UI"   # unreadable choice
    assert fonts.safe_family("FontFromAnotherPC") == "Segoe UI"
    assert fonts.safe_family("") == "Segoe UI"


def test_empty_font_database_does_not_rewrite_the_users_choice(monkeypatch):
    """Headless/offscreen has no fonts at all; it must not "fix" a valid
    setting into the default and silently lose the user's preference."""
    _fake_db(monkeypatch, [], {})
    assert fonts.safe_family("IBM Plex Sans") == "IBM Plex Sans"


def test_schema_validates_the_family_it_writes(monkeypatch):
    """The derived font_family stack is what QSS actually uses — a symbol font
    must never reach it."""
    ws = QFontDatabase.WritingSystem
    _fake_db(monkeypatch, ["Segoe UI", "Wingdings"],
             {"Segoe UI": [ws.Latin, ws.Cyrillic], "Wingdings": [ws.Symbol]})
    import settings_schema as ss
    derived = ss._derive_font_family("Wingdings")
    assert "Wingdings" not in derived["font_family"]
    assert "Segoe UI" in derived["font_family"]

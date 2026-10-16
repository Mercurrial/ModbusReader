"""Colour schemes, contrast levels and theme-aware accents.

Pure palette maths — no Qt needed. The point of these tests is that a user can
pick ANY combination from the Appearance page and still be able to read the
screen: text on its surface, and the accent's own label on the accent.
"""
import pytest

from gui import theme_manager as tm


def _contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def L(h):
        r, g, bl = (lin(v) for v in tm._rgb(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
    la, lb = L(a), L(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ── colour maths ────────────────────────────────────────────────────────
def test_mix_endpoints_and_midpoint():
    assert tm._mix("#000000", "#ffffff", 0.0) == "#000000"
    assert tm._mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert tm._mix("#000000", "#ffffff", 0.5) == "#808080"


def test_short_hex_is_expanded():
    assert tm._rgb("#fff") == (255, 255, 255)


def test_luma_orders_black_below_white():
    assert tm._luma("#000000") < tm._luma("#808080") < tm._luma("#ffffff")


# ── schemes ─────────────────────────────────────────────────────────────
def test_every_scheme_declares_a_real_base():
    for key, s in tm.SCHEMES.items():
        assert s["base"] in tm.THEMES, f"{key}: unknown base {s['base']}"


def test_schemes_for_only_offers_the_matching_family():
    dark, light = tm.schemes_for("Dark"), tm.schemes_for("Light")
    assert "graphite" in dark and "carbon" in dark
    assert "paper" in light and "snow" in light
    assert not set(dark) & set(light)


def test_default_schemes_reproduce_the_original_look():
    """graphite/paper must be pure pass-throughs — an existing install that
    gains a `scheme` key must not change appearance."""
    for theme, scheme in (("Dark", "graphite"), ("Light", "paper")):
        plain = tm.get_theme(theme, "neutral", scheme=None, contrast="soft")
        named = tm.get_theme(theme, "neutral", scheme=scheme, contrast="soft")
        assert plain == named


def test_scheme_actually_changes_the_surfaces():
    a = tm.get_theme("Dark", "neutral", scheme="graphite", contrast="soft")
    b = tm.get_theme("Dark", "neutral", scheme="midnight", contrast="soft")
    assert a["bg_0"] != b["bg_0"] and a["bg_2"] != b["bg_2"]
    # …but the semantic colours are shared, so "error" still means the same red
    assert a["error"] == b["error"] and a["ok"] == b["ok"]


def test_scheme_from_the_wrong_family_is_ignored():
    """A light scheme on a dark base would be unreadable."""
    dark = tm.get_theme("Dark", "neutral", scheme="graphite", contrast="soft")
    mixed = tm.get_theme("Dark", "neutral", scheme="snow", contrast="soft")
    assert mixed["bg_0"] == dark["bg_0"]


def test_scheme_aliases_follow_their_source_token():
    p = tm.get_theme("Dark", "neutral", scheme="carbon", contrast="soft")
    assert p["bg_card"] == p["bg_2"]
    assert p["bg_input"] == p["bg_0"] == p["plot_bg"]
    assert p["border"] == p["line"] == p["plot_axis"]


# ── contrast ────────────────────────────────────────────────────────────
def test_soft_contrast_is_a_no_op():
    base = tm.get_theme("Dark", "neutral", scheme="graphite", contrast="soft")
    assert base["bg_0"] == tm.THEMES["dark"]["bg_0"]


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_higher_contrast_really_separates_text_from_surface(theme):
    ratios = []
    for level in tm.CONTRAST_LEVELS:
        p = tm.get_theme(theme, "neutral", contrast=level)
        ratios.append(_contrast_ratio(p["text_3"], p["bg_1"]))
    assert ratios[0] < ratios[1] < ratios[2], ratios


@pytest.mark.parametrize("theme", ["Dark", "Light"])
@pytest.mark.parametrize("level", tm.CONTRAST_LEVELS)
def test_body_text_clears_wcag_aa_everywhere(theme, level):
    """Every scheme × contrast must keep secondary text legible (4.5:1)."""
    for scheme in tm.schemes_for(theme):
        p = tm.get_theme(theme, "neutral", scheme=scheme, contrast=level)
        for surface in ("bg_0", "bg_1", "bg_2"):
            r = _contrast_ratio(p["text_3"], p[surface])
            assert r >= 4.5, f"{theme}/{scheme}/{level}: text_3 on {surface} = {r:.2f}"
            r1 = _contrast_ratio(p["text_1"], p[surface])
            assert r1 >= 7.0, f"{theme}/{scheme}/{level}: text_1 on {surface} = {r1:.2f}"


# ── accents ─────────────────────────────────────────────────────────────
def test_every_accent_has_both_surface_variants():
    for key, entry in tm.ACCENT_PALETTES.items():
        assert set(entry) == {"dark", "light"}, key


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_accent_label_is_readable_on_the_accent(theme):
    """accent_fg is derived from luminance; a bright accent must not end up
    with white text on it (that was possible when fg was a stored constant)."""
    for key in tm.ACCENT_PALETTES:
        p = tm.get_theme(theme, key)
        r = _contrast_ratio(p["accent_fg"], p["accent"])
        assert r >= 4.5, f"{theme}/{key}: {r:.2f}"


def test_accent_swatches_match_the_registry():
    from app.settings_schema import ACCENT_SWATCHES
    keys = {k for k, _ in ACCENT_SWATCHES}
    assert keys == set(tm.ACCENT_PALETTES), "swatch row and accents disagree"


def test_scheme_labels_cover_every_scheme():
    from app.settings_schema import SCHEME_LABELS
    from app import i18n
    assert {v for v, _ in SCHEME_LABELS} == set(tm.SCHEMES)
    for _, key in SCHEME_LABELS:
        assert key in i18n.STRINGS["ru"] and key in i18n.STRINGS["en"]


# ── the module-level "what am I wearing" state ──────────────────────────
def test_active_appearance_is_used_when_the_caller_only_knows_the_theme():
    """Dialogs call get_theme("Dark") with nothing else; they must still get
    the scheme and contrast the rest of the window is using."""
    before = tm.active()
    try:
        tm.set_active(scheme="midnight", contrast="high", accent="blue")
        implicit = tm.get_theme("Dark")
        explicit = tm.get_theme("Dark", "blue", scheme="midnight", contrast="high")
        assert implicit == explicit
    finally:
        tm.set_active(**before)


# ── the startup path ────────────────────────────────────────────────────
def test_startup_publishes_the_saved_appearance():
    """Regression: main.py built the global stylesheet BEFORE anything called
    set_active, so the whole window started in the DEFAULT scheme while dialogs
    created later used the saved one. Symptom: choosing a scheme appeared to
    change nothing but one dialog's background."""
    import inspect
    import main
    src = inspect.getsource(main.main)
    set_at = src.find("set_active(")
    qss_at = src.find("setStyleSheet(")
    assert set_at != -1, "main() must publish the saved appearance"
    assert set_at < qss_at, "set_active() must run BEFORE the stylesheet is built"


def test_saved_scheme_changes_the_stylesheet():
    """A scheme that produces the same QSS as the default is invisible."""
    from gui.styles import get_stylesheet
    before = tm.active()
    try:
        tm.set_active(scheme="graphite", contrast="soft", accent="neutral")
        plain = get_stylesheet("Dark", "Segoe UI", 9, "neutral")
        for scheme in ("carbon", "midnight", "slate"):
            tm.set_active(scheme=scheme, contrast="soft", accent="neutral")
            assert get_stylesheet("Dark", "Segoe UI", 9, "neutral") != plain, scheme
        for level in ("normal", "high"):
            tm.set_active(scheme="graphite", contrast=level, accent="neutral")
            assert get_stylesheet("Dark", "Segoe UI", 9, "neutral") != plain, level
    finally:
        tm.set_active(**before)


def test_contrast_lifts_secondary_text_a_lot():
    """"Dull" lives in secondary text. High contrast must nearly double its
    readability, not nudge it by a few RGB steps."""
    for theme in ("Dark", "Light"):
        soft = tm.get_theme(theme, "neutral", contrast="soft")
        high = tm.get_theme(theme, "neutral", contrast="high")
        r_soft = _contrast_ratio(soft["text_3"], soft["bg_1"])
        r_high = _contrast_ratio(high["text_3"], high["bg_1"])
        assert r_high > r_soft * 1.6, f"{theme}: {r_soft:.2f} -> {r_high:.2f}"


def test_every_scheme_is_visibly_distinct_from_the_others():
    """Two schemes whose ramps sit a few RGB steps apart are indistinguishable
    on screen — the first attempt shipped three such pairs."""
    for family in ("Dark", "Light"):
        seen = {}
        for scheme in tm.schemes_for(family):
            p = tm.get_theme(family, "neutral", scheme=scheme, contrast="soft")
            seen[scheme] = tuple(p[t] for t in ("bg_0", "bg_1", "bg_2", "text_3"))
        keys = list(seen)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                worst = max(
                    max(abs(x - y) for x, y in zip(tm._rgb(ca), tm._rgb(cb)))
                    for ca, cb in zip(seen[a], seen[b]))
                assert worst >= 14, f"{family}: {a} vs {b} differ by only {worst}"

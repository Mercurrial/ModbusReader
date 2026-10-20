# gui/styles.py

from gui import icons
from gui.theme_manager import get_theme, _mix
from app.fonts import MONO_CSS

def get_stylesheet(theme_name: str = "Dark", font_family: str = "Inter, Segoe UI, system-ui, sans-serif", font_size: int = 9, accent: str | None = None) -> str:
    """Returns the complete QSS stylesheet based on the current theme and settings."""
    c = get_theme(theme_name, accent)
    
    # Base sizes
    fs = f"{font_size}pt"
    fs_small = f"{max(7, font_size - 1)}pt"
    fs_h1 = f"{font_size + 5}pt"
    fs_h2 = f"{font_size + 1}pt"
    fs_h3 = f"{font_size + 3}pt"
    # Hover of a filled accent button: a step toward the text colour, not a
    # jump to it (the old hover flashed a white slab on a coloured button).
    accent_hover = _mix(c["accent"], c["text_1"], 0.16)
    # Focus ring: neutral, not the accent. With a red-family accent (rose,
    # coral) an accent ring around a freshly focused field read as a
    # validation error. Neutral text_4 is still plainly visible on every
    # scheme and contrast level.
    focus_ring = c["text_4"]

    return f"""

/* ─── FOUNDATION ─────────────────────────────────────────────────── */
QWidget {{
    background: {c["bg_1"]};
    color: {c["text_1"]};
    font-size: {fs};
    font-family: {font_family};
    border: none;
}}

QMainWindow {{
    background: {c["bg_0"]};
}}

/* Labels are transparent by default so text always sits on whatever panel
   it's on — the global QWidget rule above would otherwise paint a bg_1 box
   behind every label, mismatching darker (bg_0) or lighter (bg_2) backdrops.
   Labels that intentionally look like pills/badges re-set their own
   background via #id selectors below (higher specificity wins). */
QLabel {{
    background: transparent;
    /* A label with any QSS padding / border gets Qt's automatic indent
       (half an "x") on its aligned edge — section titles, hints and badges
       sat ~5 px in from the labels they line up with. Text starts at the
       padding edge, as in CSS. */
    qproperty-indent: 0;
}}

/* ─── FRAME: rail | header / page ────────────────────────────────── */
/* Chrome (rail, header, status bar) is bg_1; data surfaces are bg_0. The
   rail and the header meet in one L-shaped frame; a whisper line (line_soft,
   which the contrast layer keeps dim) marks where the page begins, because
   the tool pages below are bg_1 too and a pure tonal step does not exist
   there. */
QWidget#workArea {{
    background: {c["bg_1"]};
}}
QWidget#topBar {{
    background: {c["bg_1"]};
    border-bottom: 1px solid {c["line_soft"]};
    min-height: 52px;
    max-height: 52px;
}}
QLabel#hdrTitle {{
    color: {c["text_1"]};
    font-size: {fs_h2};
    font-weight: 600;
    padding-left: 2px;
}}
QLabel#hdrSep {{
    color: {c["text_4"]};
    font-size: {fs_h2};
    padding: 0 6px;
}}
/* What the app talks to — "COM3 · 115200 · 8N1 · ID 10". */
QPushButton#linkChip {{
    background: transparent;
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 0 12px 0 10px;
    color: {c["text_3"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
    min-height: 30px;
    max-height: 30px;
}}
QPushButton#linkChip:hover {{
    background: {c["bg_2"]};
    color: {c["text_1"]};
    border-color: {c["line_strong"]};
}}
QPushButton#linkChip[connected="true"] {{
    color: {c["text_1"]};
    border-color: {c["ok_soft"]};
}}
/* THE primary action of the window. */
QPushButton#btnConnect {{
    background: {c["accent"]};
    color: {c["accent_fg"]};
    border: none;
    border-radius: 6px;
    padding: 0 16px 0 12px;
    font-weight: 600;
    min-height: 30px;
    max-height: 30px;
}}
QPushButton#btnConnect:hover {{
    background: {accent_hover};
}}
QPushButton#btnConnect[connected="true"] {{
    background: {c["ok_tint"]};
    color: {c["ok"]};
    border: 1px solid {c["ok_soft"]};
}}
QPushButton#btnConnect[connected="true"]:hover {{
    background: {c["ok_soft"]};
    color: {c["text_1"]};
}}

/* ─── NAVIGATION RAIL ────────────────────────────────────────────── */
QWidget#navRail {{
    background: {c["bg_1"]};
    border-right: 1px solid {c["line_soft"]};
}}
QWidget#railBrand {{
    background: transparent;
    border-radius: 8px;
}}
QWidget#railBrand:hover {{
    background: {c["bg_2"]};
}}
QLabel#railCaption {{
    color: {c["text_4"]};
    font-size: {fs_small};
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 8px 10px 4px 10px;
}}
QLabel#railCaption[collapsed="true"] {{
    padding: 0;
    min-height: 8px;
    max-height: 8px;
}}
QPushButton#railBtn {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0 10px;
    text-align: left;
    color: {c["text_2"]};
    font-size: {fs};
    min-height: 34px;
    max-height: 34px;
}}
QPushButton#railBtn:hover {{
    background: {c["bg_2"]};
    color: {c["text_1"]};
}}
QPushButton#railBtn:pressed {{
    background: {c["bg_3"]};
}}
QPushButton#railBtn[active="true"] {{
    background: {c["bg_3"]};
    color: {c["text_1"]};
    font-weight: 600;
}}
QPushButton#railBtn[collapsed="true"] {{
    padding: 0;
    text-align: center;
}}

QPushButton#tbBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0 10px;
    color: {c["text_2"]};
    font-size: {fs};
    font-weight: 500;
    text-align: left;
    min-height: 32px;
    max-height: 32px;
}}
QPushButton#tbBtn:hover {{
    background: {c["bg_3"]};
    color: {c["text_1"]};
}}
QPushButton#tbBtn:pressed {{
    background: {c["bg_4"]};
}}
QPushButton#tbBtn:disabled {{
    color: {c["text_4"]};
    background: transparent;
}}

QPushButton#iconBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {c["text_3"]};
}}
QPushButton#iconBtn:hover {{
    background: {c["bg_3"]};
    color: {c["text_1"]};
}}
QPushButton#iconBtn:pressed {{
    background: {c["bg_4"]};
}}

QWidget#brandPanel {{
    background: transparent;
    border-radius: 8px;
}}
QWidget#brandPanel:hover {{
    background: {c["bg_2"]};
}}

QLabel#brandMark {{
    background: {c["accent"]};
    color: {c["accent_fg"]};
    font-weight: 700;
    font-size: {fs_h2};
    border-radius: 6px;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    qproperty-alignment: AlignCenter;
}}
QLabel#brandIcon {{
    background: transparent;
}}
QLabel#brandName {{
    color: {c["text_1"]};
    font-size: {fs_h2};
    font-weight: 700;
}}
QLabel#brandVer {{
    color: {c["text_4"]};
    font-size: {fs_small};
}}

/* The RU/EN pill carries no outline: the filled bg_2 capsule is the shape,
   and the ring around it was one of the stacked greys in the top-right
   corner. Same reasoning as the removed toolbar dividers. */
QWidget#langSeg {{
    background: {c["bg_2"]};
    border: none;
    border-radius: 13px;
}}
QPushButton#segBtn {{
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 0 9px;
    color: {c["text_3"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
    letter-spacing: 1px;
    min-height: 20px;
    max-height: 20px;
}}
QPushButton#segBtn[active="true"] {{
    background: {c["accent"]};
    color: {c["accent_fg"]};
}}
QPushButton#segBtn:hover {{
    color: {c["text_2"]};
}}

/* ─── STATUS BAR ─────────────────────────────────────────────────── */
QStatusBar {{
    background: {c["bg_1"]};
    border-top: 1px solid {c["line_soft"]};
    color: {c["text_3"]};
    font-size: {fs_small};
    max-height: 26px;
    min-height: 26px;
}}
QStatusBar::item {{
    border: none;
}}
QPushButton#sbTermBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 1px 10px;
    color: {c["text_2"]};
    font-size: {fs_small};
    min-height: 18px;
}}
QPushButton#sbTermBtn:hover {{
    background: {c["bg_3"]};
    color: {c["text_1"]};
    border-color: {c["line_strong"]};
}}
QLabel#sbItem {{
    color: {c["text_3"]};
    font-size: {fs_small};
    padding: 0 4px;
}}
QLabel#sbVal {{
    color: {c["text_2"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
    padding: 0 4px;
}}
QWidget#sbStats {{
    background: transparent;
    border-radius: 6px;
    min-height: 20px;
}}
QWidget#sbStats:hover {{
    background: {c["bg_3"]};
}}
/* Log errors: the count is coloured, the chip is not a red alarm box. */
QPushButton#sbTermBtn[state="error"] {{
    color: {c["error"]};
    background: {c["error_tint"]};
}}
QFrame#statsCard {{
    background: {c["bg_2"]};
    border: 1px solid {c["line_strong"]};
    border-radius: 10px;
}}
QLabel#statsTitle {{
    color: {c["text_1"]};
    font-size: {fs_h2};
    font-weight: 600;
    padding-bottom: 4px;
}}
QLabel#statsKey {{
    color: {c["text_3"]};
    font-size: {fs_small};
}}
QLabel#statsVal {{
    color: {c["text_1"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}
QLabel#statsVal[state="error"] {{
    color: {c["error"]};
    font-weight: 600;
}}
QLabel#statsVal[state="warn"] {{
    color: {c["warn"]};
}}
QLabel#statsHint {{
    color: {c["text_4"]};
    font-size: {fs_small};
    padding-top: 6px;
}}
QLabel#sbVal[state="idle"] {{
    color: {c["text_4"]};
}}
QLabel#sbVal[state="error"] {{
    color: {c["error"]};
    font-weight: 600;
}}
QFrame#sbSep {{
    background: {c["line"]};
    min-width: 1px;
    max-width: 1px;
    min-height: 14px;
    max-height: 14px;
    margin: 0 4px;
}}
QWidget#sbIdEdit {{
    border-radius: 4px;
}}
QWidget#sbIdEdit:hover {{
    background: {c["bg_3"]};
}}
QLineEdit#sbIdInput {{
    background: {c["bg_3"]};
    border: 1px solid {c["accent"]};
    border-radius: 4px;
    color: {c["text_1"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
    padding: 0 4px;
    max-width: 40px;
    max-height: 20px;
    selection-background-color: {c["accent_soft"]};
}}

/* ─── SPLITTERS ──────────────────────────────────────────────────── */
QSplitter::handle {{
    background: {c["line_soft"]};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

/* ─── REGISTER-MAP HEAD BAR ──────────────────────────────────────── */
QWidget#registerArea {{
    background: {c["bg_0"]};
}}
/* Also unruled — see #topBar. The table's own header row starts on bg_1
   immediately below, which is the boundary. */
QWidget#mainHead {{
    background: {c["bg_1"]};
}}
QLabel#mhTitle {{
    color: {c["text_1"]};
    font-size: {fs};
    font-weight: 600;
}}
QLabel#mhCrumb {{
    color: {c["text_3"]};
    font-size: {fs_small};
}}
/* Status lines under the tool views: an error is a colour, not an emoji. */
QLabel#mhCrumb[state="error"] {{
    color: {c["error"]};
    font-weight: 600;
}}
QLabel#mhCrumb[state="ok"] {{
    color: {c["ok"]};
}}
QLabel#mhBadge {{
    color: {c["text_3"]};
    background: transparent;
    border: none;
    padding: 3px 4px;
    font-size: {fs_small};
}}
QWidget#searchBox {{
    background: {c["bg_0"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    min-height: 30px;
    max-height: 30px;
}}
QWidget#searchBox:focus-within {{
    border: 1px solid {focus_ring};
    background: {c["bg_0"]};
}}
/* Project dropdown — the first crumb of the header ("plant ▾ / Сканер"). */
QPushButton#mhProfile {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0 26px 0 8px;
    color: {c["text_2"]};
    font-size: {fs_h2};
    font-weight: 500;
    min-height: 32px;
    max-height: 32px;
}}
QPushButton#mhProfile:hover {{
    background: {c["bg_2"]};
    color: {c["text_1"]};
}}
QLabel#searchIcon {{
    background: transparent;
}}
QLineEdit#searchInput {{
    background: transparent;
    border: none;
    color: {c["text_1"]};
    font-size: {fs};
}}

/* ─── REGISTER TABLE ─────────────────────────────────────────────── */
/* No grid at all: even a transparent one reserves a pixel between cells, and
   on a zebra stripe that pixel showed through as a dark seam per column. */
QTableView {{
    qproperty-showGrid: 0;
}}
QTableWidget {{
    background: {c["bg_0"]};
    alternate-background-color: {c["bg_1"]};
    gridline-color: transparent;
    border: none;
    selection-background-color: {c["bg_3"]};
    selection-color: {c["text_1"]};
    font-size: {fs};
    outline: none;
}}
QTableWidget::item {{
    padding: 4px 8px;
    border-bottom: 1px solid {c["line_soft"]};
}}
/* Stripes OR row lines — never both (RegisterTable sets [zebra]). */
QTableWidget[zebra="true"]::item {{
    border-bottom: none;
}}
QTableWidget::item:selected {{
    background: {c["bg_3"]};
    color: {c["text_1"]};
}}
/* One header band, one colour. The row-number gutter and the top-left corner
   used to sit on bg_0 while the column headers sat on bg_1, so the header
   arrived on screen in two shades with a visible seam down the left — that
   is the "some cells one colour, some another" effect. Header, gutter and
   corner are all chrome, so they all get bg_1; the data area keeps bg_0.
   The column dividers stay (they are the resize handle — without them
   nobody discovers that columns can be dragged) but they are line_soft,
   which the contrast fix in theme_manager put back to a whisper. */
QHeaderView {{
    background: {c["bg_1"]};
    border: none;
}}
QHeaderView::section {{
    background: {c["bg_1"]};
    color: {c["text_3"]};
    border: none;
    border-bottom: 1px solid {c["line"]};
    padding: 7px 8px;
    font-size: {fs_small};
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}
/* No vertical dividers in the header: each one stopped dead at the header's
   lower edge — a line leading nowhere over the data. Columns still resize by
   dragging the gap between titles (the cursor shows it). */
QHeaderView::section:horizontal {{
    border-right: none;
}}
/* Row numbers sit ON the grid (bg_0), quiet and right-aligned — not on a
   band of their own with its own edge. */
QHeaderView:vertical {{
    background: {c["bg_0"]};
}}
/* Transparent: RowNumberHeader paints the row's own zebra colour first. */
QHeaderView::section:vertical {{
    background: transparent;
    color: {c["text_4"]};
    border: none;
    padding: 0 6px 0 8px;
    font-family: {MONO_CSS};
    font-size: {fs_small};
    font-weight: 400;
}}
QTableWidget[zebra="false"] QHeaderView::section:vertical {{
    border-bottom: 1px solid {c["line_soft"]};
}}
QTableView QTableCornerButton::section {{
    background: {c["bg_1"]};
    border: none;
    border-bottom: 1px solid {c["line"]};
}}
/* In-cell editor. MUST be opaque: the table keeps painting the old item text
   underneath while the editor is open, so a transparent editor draws the newly
   typed text on top of the old one (unreadable double-draw). */
QTableWidget QLineEdit {{
    background: {c["bg_2"]};
    border: 1px solid {focus_ring};
    padding: 0 5px;
    margin: 0;
    color: {c["text_1"]};
    selection-background-color: {c["accent_soft"]};
    selection-color: {c["text_1"]};
    font-family: {MONO_CSS};
    font-size: {fs};
}}

/* ─── RAW CONSOLE (command strip under the log) ─────────────────── */
QWidget#console {{
    background: {c["bg_1"]};
    border-top: 1px solid {c["line"]};
}}
QLabel#consoleLabel {{
    color: {c["text_4"]};
    font-size: {fs_small};
    text-transform: uppercase;
}}
QLabel#consoleCrc {{
    color: {c["text_4"]};
    font-family: {MONO_CSS};
    font-size: {fs};
    min-width: 90px;
}}
QLabel#consoleEdited {{
    color: {c["warn"]};
    font-size: {fs_small};
    min-width: 90px;
}}
QLineEdit#consoleInput {{
    background: {c["bg_0"]};
    color: {c["text_1"]};
    border: 1px solid {c["line"]};
    border-radius: 4px;
    padding: 2px 8px;
    font-family: {MONO_CSS};
    font-size: {fs};
    selection-background-color: {c["accent_soft"]};
}}
QLineEdit#consoleInput:focus {{
    border-color: {focus_ring};
}}
QLineEdit#consoleInput[invalid="true"] {{
    border-color: {c["error"]};
    color: {c["error"]};
}}
QPushButton#consoleSend {{
    background: {c["accent"]};
    color: {c["accent_fg"]};
    border: none;
    border-radius: 6px;
    padding: 0 18px;
    font-weight: 600;
    font-size: {fs};
    min-height: 30px;
    max-height: 30px;
}}
QPushButton#consoleSend:hover {{
    background: {accent_hover};
}}

/* ─── LOG PANEL ──────────────────────────────────────────────────── */
QWidget#logPanel {{
    background: {c["bg_0"]};
    border-top: 1px solid {c["line"]};
}}
/* The tabs are 34px tall inside a 36px bar, so a bottom border on the BAR
   was drawn in the same two pixels the active tab uses for its own accent
   underline — the tab visibly climbed onto a bright rule. The bar carries no
   rule now; the active tab's underline is the only mark at that edge, which
   is what a tab strip is supposed to look like. */
QWidget#logTabBar {{
    background: {c["bg_1"]};
    max-height: 36px;
    min-height: 36px;
}}
QLineEdit#logSearch {{
    background: {c["bg_0"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 2px 8px;
    font-size: {fs_small};
    min-height: 22px;
    max-height: 22px;
}}
QLineEdit#logSearch:focus {{
    border-color: {focus_ring};
}}
QTextEdit#txLog {{
    background: {c["bg_0"]};
    color: {c["text_2"]};
    border: none;
    font-family: {MONO_CSS};
    font-size: {fs};
    padding: 8px;
    selection-background-color: {c["bg_4"]};
}}
QPushButton#logTab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 6px 16px;
    color: {c["text_3"]};
    font-size: {fs};
    min-height: 34px;
}}
QPushButton#logTab[active="true"] {{
    color: {c["text_1"]};
    border-bottom: 2px solid {c["accent"]};
    font-weight: 600;
}}
QPushButton#logTab:hover {{
    color: {c["text_1"]};
}}

/* ─── TREND PANEL ────────────────────────────────────────────────── */
QWidget#trendsPanel {{
    background: {c["bg_1"]};
    border-left: 1px solid {c["line"]};
}}
QLabel#trendsZoneTitle {{
    color: {c["text_1"]};
    font-size: {fs_h2};
    font-weight: 600;
    padding: 12px 16px;
    border-bottom: 1px solid {c["line"]};
    background: {c["bg_1"]};
}}
QWidget#trendCard {{
    background: {c["bg_2"]};
    border: 1px solid {c["line_soft"]};
    border-radius: 10px;
}}
QWidget#trendCard:hover {{
    border: 1px solid {c["line"]};
}}
QWidget#trendCard[dragging="true"] {{
    border: 1px solid {c["accent"]};
    background: {c["bg_3"]};
}}
QLabel#gTitle {{
    color: {c["text_1"]};
    font-size: {fs};
    font-weight: 600;
}}
/* THE number of the card: large, monospace, the live reading. */
QLabel#gValue {{
    color: {c["text_1"]};
    font-family: {MONO_CSS};
    font-size: {font_size + 9}pt;
    font-weight: 600;
}}
QLabel#gValue[state="stale"] {{
    color: {c["text_4"]};
}}
QLabel#gValue[state="waiting"] {{
    color: {c["text_4"]};
}}
QLabel#gUnit {{
    color: {c["text_3"]};
    font-size: {fs_h2};
}}
QLabel#gDelta {{
    color: {c["text_3"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}
QLabel#gDelta[state="stale"] {{
    color: {c["warn"]};
    font-family: {font_family};
}}
QLabel#gDelta[state="paused"] {{
    color: {c["accent"]};
    font-family: {font_family};
    font-weight: 600;
}}
QLabel#gMeta {{
    color: {c["text_4"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}
QLabel#gStatLbl {{
    color: {c["text_4"]};
    font-size: {fs_small};
}}
QLabel#gStatVal {{
    color: {c["text_2"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}
QLabel#gWait {{
    color: {c["text_4"]};
    background: transparent;
    font-size: {fs};
}}
QLabel#gGrip {{
    background: transparent;
}}
QPushButton#gIconBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
}}
QPushButton#gIconBtn:hover {{
    background: {c["bg_3"]};
}}
QWidget#gFoot {{
    background: transparent;
}}
QWidget#twSeg {{
    background: {c["bg_1"]};
    border-radius: 5px;
}}
QPushButton#twBtn {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px 8px;
    color: {c["text_3"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
    min-width: 26px;
    max-height: 20px;
}}
QPushButton#twBtn:hover {{
    color: {c["text_1"]};
}}
QPushButton#twBtn[active="true"] {{
    background: {c["bg_3"]};
    color: {c["text_1"]};
}}

/* ─── CONTEXT MENUS ──────────────────────────────────────────────── */
QMenu {{
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    border-radius: 8px;
    padding: 6px 0;
    color: {c["text_1"]};
    font-size: {fs};
}}
QMenu::item {{
    padding: 6px 24px;
    margin: 0 6px;
    border-radius: 4px;
    font-size: {fs};
}}
QMenu::item:selected {{
    background: {c["accent"]};
    color: {c["accent_fg"]};
}}
/* Disabled items are used as SECTION CAPTIONS. Without this rule Qt paints
   them from the disabled palette, which on a tinted accent came out a salmon
   red — a heading that looked like an error message. */
QMenu::item:disabled {{
    color: {c["text_4"]};
    background: transparent;
    padding-top: 8px;
    padding-bottom: 2px;
    text-transform: uppercase;
}}
QMenu::icon {{
    padding-left: 12px;
}}
QMenu::separator {{
    height: 1px;
    background: {c["line_soft"]};
    margin: 4px 12px;
}}

/* ─── DIALOGS / INPUTS ───────────────────────────────────────────── */
QDialog {{
    background: {c["bg_1"]};
}}
QGroupBox {{
    border: 1px solid {c["line"]};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 12px;
    color: {c["text_3"]};
    font-size: {fs_small};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}}
QLineEdit,
QTextEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox {{
    background: {c["bg_0"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 6px 10px;
    color: {c["text_1"]};
    font-size: {fs};
    selection-background-color: {c["accent_soft"]};
}}
QLineEdit:focus,
QTextEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border: 1px solid {focus_ring};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 22px;
}}
/* Real chevron image. Qt QSS can't draw a CSS border-triangle (it renders a
   filled box — the "rectangle arrow" bug), so use a themed PNG from icons.py. */
QComboBox::down-arrow {{
    image: {icons.icon_url("chevron", c["text_3"], 11)};
    width: 11px;
    height: 11px;
    margin-right: 8px;
}}
QComboBox::down-arrow:on, QComboBox::down-arrow:hover {{
    image: {icons.icon_url("chevron", c["text_1"], 11)};
}}
QComboBox QAbstractItemView {{
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    selection-background-color: {c["bg_4"]};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 24px;
    padding: 2px 8px;
    border-radius: 4px;
}}
/* Spin box up/down as themed triangles (matches the combo chevron). */
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border: none; border-top-right-radius: 6px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border: none; border-bottom-right-radius: 6px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {c["bg_3"]};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: {icons.icon_url("chevron_up", c["text_3"], 9)};
    width: 9px; height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: {icons.icon_url("chevron", c["text_3"], 9)};
    width: 9px; height: 9px;
}}
QPushButton {{
    background: {c["bg_3"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 6px 16px;
    color: {c["text_1"]};
    font-size: {fs};
}}
QPushButton:hover {{
    background: {c["bg_4"]};
    border-color: {c["line_strong"]};
}}
QPushButton:pressed {{
    background: {c["line_strong"]};
}}
QPushButton#btnPrimary {{
    background: {c["accent"]};
    border: 1px solid {c["accent"]};
    color: {c["accent_fg"]};
    font-weight: 600;
}}
QPushButton#btnPrimary:hover {{
    background: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton#btnSecondary, QPushButton#btnOutline {{
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    color: {c["text_1"]};
    font-weight: 500;
}}
QPushButton#btnSecondary:hover, QPushButton#btnOutline:hover {{
    background: {c["bg_3"]};
    border-color: {c["line_strong"]};
}}
QPushButton:disabled {{
    color: {c["text_4"]};
    background: {c["bg_2"]};
    border-color: {c["line_soft"]};
}}
/* Message boxes: themed to match the app (no native white chrome). The custom
   icon is set in code (dialogs.themed_message); here we theme the surface and
   give the default/accept button the accent so it reads as primary. */
QMessageBox {{
    background: {c["bg_1"]};
}}
QMessageBox QLabel {{
    background: transparent;
    color: {c["text_1"]};
    font-size: {fs};
}}
QMessageBox QPushButton {{
    background: {c["bg_3"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 6px 18px;
    min-width: 78px;
    color: {c["text_1"]};
}}
QMessageBox QPushButton:hover {{
    background: {c["bg_4"]};
    border-color: {c["line_strong"]};
}}
QMessageBox QPushButton:default {{
    background: {c["accent"]};
    border: 1px solid {c["accent"]};
    color: {c["accent_fg"]};
    font-weight: 600;
}}
QMessageBox QPushButton:default:hover {{
    background: {accent_hover};
}}
QCheckBox {{
    color: {c["text_2"]};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {c["line_strong"]};
    border-radius: 4px;
    background: {c["bg_0"]};
}}
QCheckBox::indicator:checked {{
    background: {c["accent"]};
    border-color: {c["accent"]};
    image: {icons.icon_url("check", c["accent_fg"], 12)};
}}
QCheckBox::indicator:hover {{
    border-color: {c["accent"]};
}}
QCheckBox:disabled {{
    color: {c["text_4"]};
}}
QTabWidget::pane {{
    border: 1px solid {c["line"]};
    border-top: none;
    border-radius: 0 0 6px 6px;
}}
QTabBar::tab {{
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    border-bottom: none;
    padding: 6px 16px;
    color: {c["text_3"]};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {c["bg_1"]};
    color: {c["text_1"]};
}}
QTabBar::tab:hover {{
    color: {c["text_2"]};
}}

/* ─── SETTINGS DIALOG ────────────────────────────────────────────── */
QWidget#ovBar {{
    background: {c["bg_1"]};
    border-bottom: 1px solid {c["line"]};
}}
QLabel#ovTitle {{
    color: {c["text_1"]};
    font-size: {fs_h2};
    font-weight: 600;
}}
QPushButton#btnGhost {{
    background: transparent;
    border: none;
    color: {c["text_3"]};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: {fs_small};
}}
QPushButton#btnGhost:hover {{
    background: {c["bg_2"]};
    color: {c["text_1"]};
}}
QListWidget#stSide {{
    background: {c["bg_1"]};
    border: none;
    border-right: 1px solid {c["line_soft"]};
    padding: 12px 8px;
    outline: none;
}}
QListWidget#stSide::item {{
    color: {c["text_2"]};
    border-radius: 6px;
    padding: 0;
    margin-bottom: 1px;
}}
QListWidget#stSide::item:hover {{
    background: {c["bg_2"]};
    color: {c["text_1"]};
}}
QListWidget#stSide::item:selected {{
    background: {c["bg_3"]};
    color: {c["text_1"]};
}}
QWidget#stContent {{
    background: {c["bg_0"]};
}}
QScrollArea {{
    background: {c["bg_0"]};
    border: none;
}}
QWidget#stSection {{
    background: transparent;
}}
QLabel#stSectionTitle {{
    color: {c["text_1"]};
    font-size: {fs_h1};
    font-weight: 600;
    padding-bottom: 2px;
}}
QLabel#stSectionDesc {{
    color: {c["text_3"]};
    font-size: {fs_small};
    padding-bottom: 12px;
}}
QWidget#stColumn, QWidget#stFieldLabel {{
    background: transparent;
}}
QWidget#stField {{
    background: transparent;
    border-top: 1px solid {c["line_soft"]};
}}
QLabel#stFieldName {{
    color: {c["text_1"]};
    font-size: {fs};
    font-weight: 500;
}}
QLabel#stFieldHint {{
    color: {c["text_4"]};
    font-size: {fs_small};
}}
QWidget#stFooter {{
    background: {c["bg_1"]};
    border-top: 1px solid {c["line"]};
}}

/* Segmented control */
/* Segmented pill — same look as the toolbar RU/EN switch (one style for
   every value switch: theme, parity, stop bits, graph window, ...). */
QWidget#segmented {{
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    border-radius: 15px;
}}
QPushButton#segItem {{
    background: transparent;
    border: none;
    color: {c["text_3"]};
    padding: 0 14px;
    border-radius: 12px;
    font-size: {fs_small};
    font-weight: 500;
    min-height: 24px;
    max-height: 24px;
}}
QPushButton#segItem:hover {{
    color: {c["text_1"]};
}}
QPushButton#segItem[active="true"] {{
    background: {c["accent"]};
    color: {c["accent_fg"]};
    font-weight: 600;
}}

/* Slider */
QSlider {{
    background: transparent;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {c["line"]};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {c["accent"]};
    border-radius: 2px;
}}
QSlider::add-page:horizontal {{
    background: {c["line"]};
    border-radius: 2px;
}}
/* Light ring-handle: reads well on both the dark and the light palette. */
QSlider::handle:horizontal {{
    background: {c["bg_0"]};
    border: 2px solid {c["accent"]};
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {c["accent"]};
}}
QLabel#sliderVal {{
    color: {c["text_2"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}

/* st-input controls */
QLineEdit#stInput,
QComboBox#stInput,
QSpinBox#stInput {{
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 5px 10px;
    color: {c["text_1"]};
    font-size: {fs_small};
}}
QLineEdit#stInput:focus,
QComboBox#stInput:focus,
QSpinBox#stInput:focus {{
    border: 1px solid {focus_ring};
    background: {c["bg_0"]};
}}
/* Watch window */
/* Watch panel (frameless: its own chrome, card + shadow). */
QWidget#watchWin {{
    background: transparent;
}}
QFrame#watchCard {{
    background: {c["bg_1"]};
    border: 1px solid {c["line"]};
    border-radius: 12px;
}}
QWidget#watchBar {{
    background: transparent;
    border-bottom: 1px solid {c["line_soft"]};
}}
QLabel#wTitle {{
    color: {c["text_1"]};
    font-weight: 600;
}}
QLabel#wCount {{
    color: {c["text_4"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}
QScrollArea#watchScroll, QWidget#watchList {{
    background: transparent;
}}
QFrame#watchRow {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}}
QFrame#watchRow:hover {{
    background: {c["bg_2"]};
}}
QFrame#watchRow[selected="true"] {{
    background: {c["bg_2"]};
    border-color: {c["line"]};
}}
QLabel#wName {{
    color: {c["text_1"]};
}}
QLabel#wName[missing="true"] {{
    color: {c["text_4"]};
    font-style: italic;
}}
QLabel#wValue {{
    color: {c["text_1"]};
    font-family: {MONO_CSS};
    font-size: {font_size + 4}pt;
    font-weight: 600;
}}
QLabel#wValue[state="none"] {{
    color: {c["text_4"]};
}}
QLabel#wUnit {{
    color: {c["text_3"]};
}}
QLabel#wMeta {{
    color: {c["text_4"]};
    font-size: {fs_small};
}}
QLineEdit#wWrite {{
    background: {c["bg_0"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 2px 8px;
    color: {c["text_1"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}
QLineEdit#wWrite:focus {{
    border-color: {focus_ring};
}}
QSizeGrip#watchGrip {{
    background: transparent;
}}
QPushButton#iconBtn:checked {{
    background: {c["accent_tint"]};
}}
/* Empty states (gui.widgets.EmptyState): a tile, a title, a sentence, the
   first step. Transparent — it floats over the empty grid or canvas. */
QWidget#emptyPane {{
    background: transparent;
}}
QLabel#emptyTile {{
    background: {c["bg_2"]};
    border: 1px solid {c["line_soft"]};
    border-radius: 14px;
}}
QLabel#emptyTitle {{
    color: {c["text_1"]};
    font-size: {fs_h3};
    font-weight: 600;
}}
QLabel#emptyBody {{
    color: {c["text_3"]};
    font-size: {fs};
}}
/* "Nothing here yet" copy, shown in place of an empty grid. */
QLabel#emptyState {{
    color: {c["text_4"]};
    font-size: {fs};
    background: transparent;
    padding: 40px;
}}

/* Scanner progress + dashboard card close button */
QProgressBar#scanProgress {{
    background: {c["bg_2"]};
    border: none;
    border-radius: 2px;
}}
QProgressBar#scanProgress::chunk {{
    background: {c["accent"]};
    border-radius: 3px;
}}
/* Dashboard mode pill: running (green) / editing (amber). */
QLabel#modeBadge {{
    border-radius: 10px;
    padding: 2px 10px;
    font-size: {fs_small};
    font-weight: 600;
    color: {c["ok"]};
    background: {c["ok_tint"]};
}}
QLabel#modeBadge[state="edit"] {{
    color: {c["warn"]};
    background: {c["warn_tint"]};
}}
QWidget#dashCanvas {{
    background: {c["bg_0"]};
}}
QLineEdit#dashInput {{
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    border-radius: 6px;
    padding: 4px 8px;
    color: {c["text_1"]};
    font-family: {MONO_CSS};
}}
QLineEdit#dashInput:focus {{
    border: 1px solid {focus_ring};
    background: {c["bg_0"]};
}}
QPushButton#dashCardX {{
    background: transparent;
    border: none;
    border-radius: 11px;
    color: {c["text_4"]};
    font-size: {fs_small};
}}
QPushButton#dashCardX:hover {{
    background: {c["error_tint"]};
    color: {c["error"]};
}}
/* Live typography sample under the font picker */
QLabel#stFontPreview {{
    background: {c["bg_0"]};
    border: 1px dashed {c["line_strong"]};
    border-radius: 8px;
    padding: 10px 14px;
    color: {c["text_1"]};
}}

/* Shortcuts / About rows */
QWidget#stShortcutRow,
QWidget#stAboutRow {{
    background: transparent;
    border-bottom: 1px solid {c["line_soft"]};
}}
QLabel#stShortcutLbl {{
    color: {c["text_2"]};
    font-size: {fs_small};
}}
QLabel#stAboutKey {{
    color: {c["text_4"]};
    font-size: {fs_small};
}}
QLabel#stAboutVal {{
    color: {c["text_2"]};
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}
QLabel#kbdPill {{
    color: {c["text_2"]};
    background: {c["bg_2"]};
    border: 1px solid {c["line"]};
    border-radius: 4px;
    padding: 2px 7px;
    font-family: {MONO_CSS};
    font-size: {fs_small};
}}

/* ─── SCROLLBARS ─────────────────────────────────────────────────── */
/* The page areas (::add-page/::sub-page) and the corner MUST be styled too —
   otherwise Windows renders its native white, dotted track behind the handle. */
QScrollBar:vertical {{
    background: {c["bg_1"]};
    width: 12px;
    margin: 0;
    border: none;
}}
/* The handle rests on `line` and only brightens under the pointer. On
   line_strong it was a near-white bar parked across the bottom of every
   table — louder than the data it was scrolling. */
QScrollBar::handle:vertical {{
    background: {c["line"]};
    border-radius: 4px;
    min-height: 28px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c["line_strong"]};
}}
QScrollBar:horizontal {{
    background: {c["bg_1"]};
    height: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {c["line"]};
    border-radius: 4px;
    min-width: 28px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c["line_strong"]};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
    background: none;
    border: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
QAbstractScrollArea::corner {{
    background: {c["bg_1"]};
    border: none;
}}

/* ─── TOOLTIPS ───────────────────────────────────────────────────── */
QToolTip {{
    background: {c["bg_3"]};
    border: 1px solid {c["line"]};
    color: {c["text_2"]};
    padding: 6px 10px;
    border-radius: 6px;
    font-size: {fs_small};
}}

"""

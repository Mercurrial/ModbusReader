# gui/dialogs.py
"""Themed message dialogs in the onboarding-card style.

A QMessageBox — even with QSS — keeps the NATIVE window chrome (white title
bar, system icon), which visibly breaks the app's design. These dialogs are
frameless rounded cards exactly like the onboarding guide: dark card, themed
icon, accent primary button. Modal; draggable by the card; Esc = the reject
button, Enter = the default button.
"""

from PyQt6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QLineEdit,
)
from PyQt6.QtCore import Qt

from gui import icons
from gui.theme_manager import get_theme, _mix

# kind -> (icon name in icons.py, semantic colour token)
_KINDS = {
    "warning":  ("warning", "warn"),
    "error":    ("warning", "error"),
    "question": ("help",    "accent"),
    "info":     ("info",    "info"),
    "success":  ("check",   "ok"),
}

_ROLE_DESTRUCTIVE = QMessageBox.ButtonRole.DestructiveRole
_ROLE_REJECT = QMessageBox.ButtonRole.RejectRole


def button_qss(c: dict, kind: str) -> str:
    """Card-dialog button styles, shared with the other card dialogs
    (gui/update.py). kind: "primary" | "destructive" | "plain" | "ghost"."""
    if kind == "primary":
        return (f"QPushButton {{ color:{c['accent_fg']}; background:{c['accent']};"
                f" border:none; border-radius:7px; font-size:13px;"
                f" font-weight:600; padding:7px 20px; }}"
                f"QPushButton:hover {{ background:{_mix(c['accent'], c['text_1'], 0.16)}; }}"
                f"QPushButton:disabled {{ background:{c['bg_3']}; color:{c['text_4']}; }}")
    if kind == "destructive":
        # Bare error-red text on the card background was unreadable.
        # A tinted fill plus a solid border lifts it clear of bg_2
        # while still reading as "this one throws work away".
        return (f"QPushButton {{ color:{c['error']};"
                f" background:{c['error_tint']};"
                f" border:1px solid {c['error']}; border-radius:7px;"
                f" font-size:13px; font-weight:600; padding:7px 16px; }}"
                f"QPushButton:hover {{ background:{c['error']};"
                f" color:{c['bg_0']}; }}")
    if kind == "ghost":
        return (f"QPushButton {{ color:{c['text_3']}; background:transparent;"
                f" border:none; border-radius:7px; font-size:13px; padding:7px 10px; }}"
                f"QPushButton:hover {{ color:{c['text_1']}; background:{c['bg_3']}; }}")
    return (f"QPushButton {{ color:{c['text_1']}; background:{c['bg_3']};"
            f" border:1px solid {c['line']}; border-radius:7px;"
            f" font-size:13px; padding:7px 16px; }}"
            f"QPushButton:hover {{ background:{c['bg_4']}; }}")


class _CardDialog(QDialog):
    """Frameless rounded-card modal (matches OnboardingGuide's card)."""

    def __init__(self, parent, theme_name, kind, title, text, buttons,
                 field: str | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.choice = -1
        self._drag_at = None

        c = get_theme(theme_name)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setObjectName("dlgCard")
        card.setStyleSheet(f"""
            QFrame#dlgCard {{
                background: {c['bg_2']};
                border: 1px solid {c['line_strong']};
                border-radius: 12px;
            }}
        """)
        # Minimum, not fixed: three buttons did not fit 400 px and the middle
        # label came out clipped mid-word ("ыйти без сохранени").
        card.setMinimumWidth(400)
        card.setMaximumWidth(560)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 17)
        lay.setSpacing(10)

        icon_name, token = _KINDS.get(kind, ("info", "info"))
        head = QHBoxLayout()
        head.setSpacing(12)
        ico = QLabel()
        ico.setPixmap(icons.pixmap(icon_name, c.get(token, c["text_1"]), 26))
        ico.setStyleSheet("background: transparent;")
        ico.setFixedSize(28, 28)
        lbl_title = QLabel(title)
        lbl_title.setWordWrap(True)
        lbl_title.setStyleSheet(
            f"color:{c['text_1']}; background:transparent; "
            f"font-size:16px; font-weight:700;")
        head.addWidget(ico, alignment=Qt.AlignmentFlag.AlignTop)
        head.addWidget(lbl_title, 1)
        lay.addLayout(head)

        if text:
            lbl_body = QLabel(text)
            lbl_body.setWordWrap(True)
            lbl_body.setStyleSheet(
                f"color:{c['text_2']}; background:transparent; "
                f"font-size:13px; line-height:145%;")
            lay.addWidget(lbl_body)
        # Optional one-line input (themed_input): the native QInputDialog
        # came with a white Windows title bar in the middle of a dark app.
        self.edit = None
        if field is not None:
            self.edit = QLineEdit(field)
            self.edit.selectAll()
            self.edit.setStyleSheet(
                f"QLineEdit {{ background:{c['bg_0']}; color:{c['text_1']};"
                f" border:1px solid {c['line_strong']}; border-radius:7px;"
                f" padding:7px 10px; font-size:13px;"
                f" selection-background-color:{c['accent_soft']}; }}"
                f"QLineEdit:focus {{ border-color:{c['text_3']}; }}")
            self.edit.returnPressed.connect(self._accept_default)
            lay.addWidget(self.edit)
        lay.addSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        self._reject_idx = -1
        self._default_idx = -1
        for i, (label, role, is_default) in enumerate(buttons):
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            # Never let a label be cut: the button asks for the room it needs.
            b.setMinimumWidth(b.fontMetrics().horizontalAdvance(label) + 34)
            if is_default:
                style = button_qss(c, "primary")
                b.setDefault(True)
                self._default_idx = i
            elif role == _ROLE_DESTRUCTIVE:
                style = button_qss(c, "destructive")
            else:
                style = button_qss(c, "plain")
            b.setStyleSheet(style)
            b.clicked.connect(lambda _=False, idx=i: self._pick(idx))
            if role == _ROLE_REJECT and self._reject_idx < 0:
                self._reject_idx = i
            row.addWidget(b)
        lay.addLayout(row)

    def _pick(self, idx):
        self.choice = idx
        self.accept()

    def _accept_default(self):
        if self._default_idx >= 0:
            self._pick(self._default_idx)

    def showEvent(self, e):
        super().showEvent(e)
        if self.edit is not None:
            self.edit.setFocus()

    def reject(self):                       # Esc / programmatic close
        self.choice = self._reject_idx
        super().reject()

    # Frameless -> let the user drag the card around.
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_at = e.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_at is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_at)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_at = None
        super().mouseReleaseEvent(e)


def themed_message(parent, theme_name, kind, title, text, buttons):
    """Show a themed modal card dialog.

    buttons: list of (label, role, is_default) where role is a
             QMessageBox.ButtonRole (kept for call-site compatibility).
    Returns the index of the clicked button, or the reject button's index
    (-1 if none) when dismissed with Esc.
    """
    dlg = _CardDialog(parent, theme_name, kind, title, text, buttons)
    dlg.exec()
    return dlg.choice


def themed_input(parent, theme_name, title, label, text="", ok_label="OK",
                 cancel_label="Cancel") -> tuple:
    """One-line text input in the card style. Returns ``(text, accepted)``,
    the same shape as the Qt getText() it replaces."""
    dlg = _CardDialog(parent, theme_name, "question", title, label,
                      [(cancel_label, QMessageBox.ButtonRole.RejectRole, False),
                       (ok_label, QMessageBox.ButtonRole.AcceptRole, True)],
                      field=text)
    dlg.exec()
    ok = dlg.choice == 1
    return (dlg.edit.text() if ok else text), ok


def themed_info(parent, theme_name, kind, title, text, ok_label="OK"):
    """One-button notice (errors, info) in the same card style."""
    themed_message(parent, theme_name, kind, title, text,
                   [(ok_label, QMessageBox.ButtonRole.AcceptRole, True)])

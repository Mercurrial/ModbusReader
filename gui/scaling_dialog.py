# gui/scaling_dialog.py
"""Engineering-units editor for one register: scale/offset/unit + enum map.

Opened from the profile editor's row context menu. Returns result_cfg with the
keys to merge back into the register dict (or None if cancelled). Frameless
card, matching dialogs.py."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit,
)
from PyQt6.QtCore import Qt

from core import datatypes
from gui.theme_manager import get_theme, _mix


def _num(v, default):
    try:
        f = float(str(v).replace(",", "."))
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def parse_enum(text: str) -> dict:
    """Free-text enum editor → {int_key: label}. One 'key = label' per line;
    blank lines and unparsable keys are skipped."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        try:
            key = int(k, 0)
        except ValueError:
            # int("01", 0) is an error in Python (no leading zeros in base 0),
            # so "01 = Работа" — how status codes are often written — was
            # silently dropped. Fall back to plain decimal.
            try:
                key = int(k, 10)
            except ValueError:
                continue
        out[str(key)] = v.strip()
    return out


def enum_to_text(enum: dict) -> str:
    if not isinstance(enum, dict):
        return ""
    lines = []
    for k, v in enum.items():
        try:
            lines.append(f"{int(k)} = {v}")
        except (TypeError, ValueError):
            continue
    return "\n".join(lines)


class ScalingDialog(QDialog):
    def __init__(self, reg: dict, theme_name: str, t, parent=None):
        super().__init__(parent)
        self.result_cfg = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        c = get_theme(theme_name)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("dlgCard")
        card.setStyleSheet(
            f"QFrame#dlgCard {{ background: {c['bg_2']};"
            f" border: 1px solid {c['line_strong']}; border-radius: 12px; }}"
            f" QLineEdit, QPlainTextEdit {{ background:{c['bg_1']};"
            f" border:1px solid {c['line']}; border-radius:6px; padding:5px 8px;"
            f" color:{c['text_1']}; }}")
        card.setFixedWidth(400)
        outer.addWidget(card)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(22, 20, 22, 17)
        lo.setSpacing(9)

        title = QLabel(t("engUnitsTitle"))
        title.setStyleSheet(f"color:{c['text_1']}; background:transparent;"
                            f"font-size:16px; font-weight:700;")
        lo.addWidget(title)
        name = QLabel(f"{datatypes.key_label(datatypes.reg_key(reg))} · {reg.get('name', '')}")
        name.setStyleSheet(f"color:{c['text_3']}; background:transparent;"
                           f"font-size:12px;")
        lo.addWidget(name)

        def _lbl(txt):
            l = QLabel(txt)
            l.setStyleSheet(f"color:{c['text_3']}; background:transparent;"
                            f"font-size:12px;")
            return l

        # scale / offset / unit
        row = QHBoxLayout()
        row.setSpacing(8)
        self.ed_scale = QLineEdit(str(reg.get("scale", 1.0)))
        self.ed_offset = QLineEdit(str(reg.get("offset", 0.0)))
        self.ed_unit = QLineEdit(str(reg.get("unit", "")))
        for ed, lbl in ((self.ed_scale, t("engScale")),
                        (self.ed_offset, t("engOffset")),
                        (self.ed_unit, t("dashUnit"))):
            box = QVBoxLayout()
            box.setSpacing(3)
            box.addWidget(_lbl(lbl))
            box.addWidget(ed)
            row.addLayout(box)
        lo.addLayout(row)

        formula = QLabel(t("engFormula"))
        formula.setStyleSheet(f"color:{c['text_4']}; background:transparent;"
                              f"font-size:11px;")
        lo.addWidget(formula)

        lo.addWidget(_lbl(t("engEnum")))
        self.ed_enum = QPlainTextEdit(enum_to_text(reg.get("enum")))
        self.ed_enum.setPlaceholderText(t("enumPlaceholder"))
        self.ed_enum.setFixedHeight(84)
        lo.addWidget(self.ed_enum)

        btns = QHBoxLayout()
        btns.addStretch()
        b_cancel = QPushButton(t("cancel"))
        b_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        b_cancel.setStyleSheet(
            f"QPushButton {{ color:{c['text_1']}; background:{c['bg_3']};"
            f" border:1px solid {c['line']}; border-radius:7px;"
            f" font-size:13px; padding:7px 16px; }}"
            f"QPushButton:hover {{ background:{c['bg_4']}; }}")
        b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t("apply"))
        b_ok.setDefault(True)
        b_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        b_ok.setStyleSheet(
            f"QPushButton {{ color:{c['accent_fg']}; background:{c['accent']};"
            f" border:none; border-radius:7px; font-size:13px;"
            f" font-weight:600; padding:7px 20px; }}"
            f"QPushButton:hover {{ background:{_mix(c['accent'], c['text_1'], 0.16)}; }}")
        b_ok.clicked.connect(self._accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        lo.addLayout(btns)

    def _accept(self):
        scale = _num(self.ed_scale.text(), 1.0)
        if scale == 0:
            # ×0 turns every reading into the offset and cannot be inverted
            # for a write; treat it as "no scaling" rather than store it.
            scale = 1.0
        self.result_cfg = {
            "scale": scale,
            "offset": _num(self.ed_offset.text(), 0.0),
            "unit": self.ed_unit.text().strip(),
            "enum": parse_enum(self.ed_enum.toPlainText()),
        }
        self.accept()

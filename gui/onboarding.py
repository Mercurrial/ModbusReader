# gui/onboarding.py
"""First-run / Help coach-mark overlay.

A dim layer over the main window that spotlights one widget at a time and shows
a floating card describing it. Walk through the steps with Next / Back, leave
anytime with Skip (or Esc). Shown on launch and from the Help button.

The overlay is a child of the window's central widget, so its coordinates line
up with the widgets it highlights. It dims everything *around* the target by
painting four bands (rather than cutting a hole), which is robust for a child
widget that shares the parent's backing store.
"""

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
)
from PyQt6.QtCore import Qt, QRect, QPoint, QEvent, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen

from gui.theme_manager import get_theme, _mix


class OnboardingGuide(QWidget):
    """Step-through spotlight overlay. Build with a list of step dicts:

        {"target": QWidget | None, "title": str, "body": str}

    A step with target=None (or a hidden target) shows the card centered with no
    spotlight — handy for an intro/outro step. *target* may also be a list of
    widgets, in which case the spotlight covers their bounding box (e.g. to
    highlight two adjacent export buttons together)."""

    finished = pyqtSignal()

    def __init__(self, parent, steps, theme_name="Dark", accent=None, lang="ru"):
        super().__init__(parent)
        self._c = get_theme(theme_name, accent)
        self._lang = lang
        # Drop steps whose target was explicitly hidden (e.g. a toggled-off
        # panel). isHidden() — unlike isVisible() — ignores whether an ancestor
        # is shown yet, so steps survive even if the guide is built early.
        self._steps = [s for s in steps if self._step_has_target(s)]
        self._idx = 0

        self.setObjectName("onbOverlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_card()
        parent.installEventFilter(self)

    # ─────────────────────────────────────────── helpers
    @staticmethod
    def _step_has_target(step):
        """A step is kept if it has no target, or at least one visible target."""
        tgt = step.get("target")
        if tgt is None:
            return True
        targets = tgt if isinstance(tgt, (list, tuple)) else [tgt]
        return any(w is not None and not w.isHidden() for w in targets)

    def _L(self, ru, en):
        return ru if self._lang == "ru" else en

    def _build_card(self):
        c = self._c
        self.card = QFrame(self)
        self.card.setObjectName("onbCard")
        self.card.setStyleSheet(f"""
            QFrame#onbCard {{
                background: {c['bg_2']};
                border: 1px solid {c['line_strong']};
                border-radius: 12px;
            }}
        """)
        self.card.setFixedWidth(390)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(22, 19, 22, 17)
        lay.setSpacing(9)

        self.lbl_step = QLabel()
        self.lbl_step.setStyleSheet(
            f"color:{c['text_2']}; background:transparent; font-size:12px; "
            f"font-weight:700; letter-spacing:1.5px;")

        self.lbl_title = QLabel()
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet(
            f"color:{c['text_1']}; background:transparent; font-size:18px; font-weight:700;")

        self.lbl_body = QLabel()
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setStyleSheet(
            f"color:{c['text_1']}; background:transparent; font-size:14px; line-height:150%;")

        lay.addWidget(self.lbl_step)
        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_body)
        lay.addSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.btn_skip = QPushButton(self._L("Пропустить", "Skip"))
        self.btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_skip.setStyleSheet(f"""
            QPushButton {{ color:{c['text_2']}; background:transparent;
                           border:none; font-size:13px; padding:7px 6px; }}
            QPushButton:hover {{ color:{c['text_1']}; }}
        """)
        self.btn_skip.clicked.connect(self._finish)

        self.btn_back = QPushButton(self._L("Назад", "Back"))
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_back.setStyleSheet(f"""
            QPushButton {{ color:{c['text_1']}; background:{c['bg_3']};
                           border:1px solid {c['line']}; border-radius:7px;
                           font-size:13px; padding:7px 16px; }}
            QPushButton:hover {{ background:{c['bg_4']}; }}
        """)
        self.btn_back.clicked.connect(self._back)

        self.btn_next = QPushButton()
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_next.setStyleSheet(f"""
            QPushButton {{ color:{c['accent_fg']}; background:{c['accent']};
                           border:none; border-radius:7px; font-size:13px;
                           font-weight:600; padding:7px 20px; }}
            QPushButton:hover {{ background:{_mix(c['accent'], c['text_1'], 0.16)}; }}
        """)
        self.btn_next.clicked.connect(self._next)

        row.addWidget(self.btn_skip)
        row.addStretch()
        row.addWidget(self.btn_back)
        row.addWidget(self.btn_next)
        lay.addLayout(row)

    # ─────────────────────────────────────────── lifecycle
    def show_guide(self):
        """Show the overlay and jump to the first step. No-op if no steps."""
        if not self._steps:
            self.finished.emit()
            self.deleteLater()
            return
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._goto(0)

    def _goto(self, idx):
        self._idx = max(0, min(idx, len(self._steps) - 1))
        step = self._steps[self._idx]
        n = len(self._steps)
        self.lbl_step.setText(self._L("ШАГ", "STEP") + f"  {self._idx + 1} / {n}")
        self.lbl_title.setText(step.get("title", ""))
        self.lbl_body.setText(step.get("body", ""))
        self.btn_back.setVisible(self._idx > 0)
        last = self._idx == n - 1
        self.btn_next.setText(self._L("Готово", "Done") if last
                              else self._L("Далее", "Next"))
        self.card.adjustSize()
        self._reposition()
        self.update()

    def _next(self):
        if self._idx >= len(self._steps) - 1:
            self._finish()
        else:
            self._goto(self._idx + 1)

    def _back(self):
        self._goto(self._idx - 1)

    def _finish(self):
        p = self.parentWidget()
        if p is not None:
            p.removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.deleteLater()

    # ─────────────────────────────────────────── geometry
    def _target_rect(self):
        if not self._steps:
            return None
        tgt = self._steps[self._idx].get("target")
        if tgt is None:
            return None
        targets = tgt if isinstance(tgt, (list, tuple)) else [tgt]
        rect = None
        for w in targets:
            if w is None or w.isHidden():
                continue
            top_left = w.mapTo(self.parentWidget(), QPoint(0, 0))
            r = QRect(top_left, w.size())
            rect = r if rect is None else rect.united(r)
        return rect

    def _reposition(self):
        full = self.rect()
        cw, ch = self.card.width(), self.card.height()
        margin = 16
        tr = self._target_rect()
        if tr is None:
            x = (full.width() - cw) // 2
            y = (full.height() - ch) // 2
        else:
            if tr.bottom() + margin + ch <= full.height():
                y = tr.bottom() + margin
            elif tr.top() - margin - ch >= 0:
                y = tr.top() - margin - ch
            else:
                y = max(margin, min(full.height() - ch - margin, tr.bottom() + margin))
            x = tr.center().x() - cw // 2
            x = max(margin, min(x, full.width() - cw - margin))
        self.card.move(x, y)

    # ─────────────────────────────────────────── events
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = self.rect()
        dim = QColor(8, 10, 14, 190)
        tr = self._target_rect()
        if tr is None:
            p.fillRect(full, dim)
            return
        pad = 6
        r = tr.adjusted(-pad, -pad, pad, pad)
        rx, ry, rw, rh = r.x(), r.y(), r.width(), r.height()
        # Four dim bands around the spotlight (gap-free, no compositing tricks).
        p.fillRect(QRect(0, 0, full.width(), ry), dim)
        p.fillRect(QRect(0, ry + rh, full.width(), full.height() - (ry + rh)), dim)
        p.fillRect(QRect(0, ry, rx, rh), dim)
        p.fillRect(QRect(rx + rw, ry, full.width() - (rx + rw), rh), dim)
        # Accent ring around the highlighted widget.
        pen = QPen(QColor(self._c["accent"]))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 9, 9)

    def resizeEvent(self, e):
        self._reposition()
        super().resizeEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._finish()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Return,
                   Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._next()
        elif k == Qt.Key.Key_Left:
            self._back()
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, e):
        if obj is self.parentWidget() and e.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(obj, e)

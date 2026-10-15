# gui_snapshot.py
"""Snapshot / compare view — "what did that knob actually change?".

Take a snapshot of every current value, change something on the device, then
compare. The table shows one row per register with before / after / delta and
colours only what moved, so a hundred-row map still answers the question at a
glance.

The comparison itself is in snapshots.py (pure); this file is the view.
"""

import json
import os

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
)

import datatypes
import icons
from gui_widgets import EmptyState, Segmented
import snapshots as sn
from dialogs import themed_info

_FILTERS = ("all", sn.CHANGED, sn.ADDED, sn.REMOVED)


class SnapshotView(QWidget):
    """Register values frozen at a moment, and the diff against now."""

    def __init__(self, ctx, get_registers, get_values, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.get_registers = get_registers      # () -> profile rows
        self.get_values = get_values            # () -> {addr: displayed value}
        self.baseline: dict | None = None
        self._rows: list = []
        self._counts: dict = {}
        self.setObjectName("snapshotView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        t, c = self.ctx.t, self.ctx.theme_tokens()
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_take = QPushButton("  " + t("snapTake"))
        self.btn_take.setObjectName("btnPrimary")
        self.btn_take.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_take.setIcon(icons.icon("camera", c["accent_fg"], 14))
        self.btn_take.setIconSize(QSize(13, 13))
        self.btn_take.clicked.connect(self.take_snapshot)
        bar.addWidget(self.btn_take)

        self.btn_compare = QPushButton("  " + t("snapCompare"))
        self.btn_compare.setObjectName("tbBtn")
        self.btn_compare.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_compare.clicked.connect(self.compare_now)
        bar.addWidget(self.btn_compare)

        self.btn_save = QPushButton("  " + t("snapSave"))
        self.btn_save.setObjectName("tbBtn")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_snapshot)
        bar.addWidget(self.btn_save)

        self.btn_load = QPushButton("  " + t("snapLoad"))
        self.btn_load.setObjectName("tbBtn")
        self.btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load.clicked.connect(self.load_snapshot)
        bar.addWidget(self.btn_load)

        self._paint_icons()

        bar.addStretch()
        self.seg_filter = Segmented(
            [(k, t(f"snapFilter{k.capitalize()}")) for k in _FILTERS],
            "all")
        self.seg_filter.valueChanged.connect(lambda _v: self._render())
        bar.addWidget(self.seg_filter)
        lo.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setObjectName("scanTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        lo.addWidget(self.table, 1)

        # An empty grid — six headings over a black void — does not read as
        # "nothing yet", it reads as broken. When there are no rows, show the
        # next action instead of the skeleton of a table.
        self.lbl_empty = EmptyState("camera", t("snapEmptyTitle"), "")
        self.lbl_empty.apply_theme(self.ctx.theme_tokens())
        lo.addWidget(self.lbl_empty, 1)

        self.lbl_status = QLabel(t("snapIdle"))
        self.lbl_status.setObjectName("mhCrumb")
        lo.addWidget(self.lbl_status)
        self._set_headers()
        self._render()

    def _set_headers(self):
        t = self.ctx.t
        self.table.setHorizontalHeaderLabels(
            [t("address"), t("name"), t("snapBefore"), t("snapAfter"),
             t("snapDelta"), t("snapState")])

    # ── actions ───────────────────────────────────────────────────────
    def take_snapshot(self):
        regs = self.get_registers() or []
        if not regs:
            themed_info(self, self.ctx.theme, "info", self.ctx.t("snapTitle"),
                        self.ctx.t("snapNoProfile"))
            return
        self.baseline = sn.make(regs, self.get_values() or {})
        n = len(self.baseline["registers"])
        self._counts = {}
        self.lbl_status.setText(self.ctx.t("snapTaken").format(n=n))
        self._rows = []
        self._render()

    def compare_now(self):
        t = self.ctx.t
        if not self.baseline:
            themed_info(self, self.ctx.theme, "info", t("snapTitle"),
                        t("snapNoBaseline"))
            return
        current = sn.make(self.get_registers() or [], self.get_values() or {})
        self._rows = sn.compare(self.baseline, current)
        self._counts = sn.summarize(self._rows)
        self._show_summary()
        self._render()

    def _show_summary(self):
        """Render the counts. Kept separate so a language switch can redraw
        the line instead of leaving it in the previous language."""
        if not self._counts:
            return
        c = self._counts
        self.lbl_status.setText(self.ctx.t("snapSummary").format(
            changed=c[sn.CHANGED], added=c[sn.ADDED],
            removed=c[sn.REMOVED], same=c[sn.SAME]))

    def save_snapshot(self):
        t = self.ctx.t
        if not self.baseline:
            themed_info(self, self.ctx.theme, "info", t("snapTitle"),
                        t("snapNoBaseline"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("snapSave"), "snapshot.mbsnap",
            "Snapshot (*.mbsnap);;JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(sn.dumps(self.baseline))
        except OSError as e:
            themed_info(self, self.ctx.theme, "error", t("errTitle"), str(e))

    def load_snapshot(self):
        t = self.ctx.t
        path, _ = QFileDialog.getOpenFileName(
            self, t("snapLoad"), "", "Snapshot (*.mbsnap *.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.baseline = sn.load(json.load(f))
        except (OSError, ValueError, json.JSONDecodeError) as e:
            themed_info(self, self.ctx.theme, "error", t("errTitle"), str(e))
            return
        self.lbl_status.setText(t("snapLoaded").format(
            name=os.path.basename(path),
            n=len(self.baseline["registers"])))
        self._rows = []
        self._render()

    # ── rendering ─────────────────────────────────────────────────────
    def _empty_text(self, filtered: bool) -> str:
        """Which 'nothing here' this is — they need different next actions."""
        t = self.ctx.t
        if not self.baseline:
            return t("snapEmptyNoBase")
        if not self._rows:
            return t("snapEmptyTaken")
        return t("snapEmptyFilter") if filtered else t("snapEmptySame")

    def _render(self):
        c, t = self.ctx.theme_tokens(), self.ctx.t
        want = self.seg_filter.value()
        rows = [r for r in self._rows if want == "all" or r["state"] == want]
        empty = not rows
        self.lbl_empty.setText(self._empty_text(want != "all") if empty else "")
        self.lbl_empty.setVisible(empty)
        self.table.setVisible(not empty)
        self.table.setRowCount(len(rows))
        colour = {sn.CHANGED: c["warn"], sn.ADDED: c["ok"],
                  sn.REMOVED: c["error"], sn.SAME: c["text_3"]}
        from gui_table import mono_font
        mono = mono_font(int(self.ctx.settings.get("font_size", 9)))
        for i, r in enumerate(rows):
            d = sn.delta(r)
            unit = f" {r['unit']}" if r.get("unit") else ""
            cells = [
                datatypes.key_label(r.get("key", r["addr"])),
                r.get("name", ""),
                "—" if r["before"] is None else f"{r['before']}{unit}",
                "—" if r["after"] is None else f"{r['after']}{unit}",
                "" if (d is None or r["state"] == sn.SAME) else f"{d:+g}",
                t(f"snapState{r['state'].capitalize()}"),
            ]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if col >= 4 or r["state"] != sn.SAME:
                    it.setForeground(QColor(colour[r["state"]]))
                if col in (0, 2, 3, 4):          # address and numbers: monospace
                    it.setFont(mono)
                self.table.setItem(i, col, it)

    # ── app plumbing ──────────────────────────────────────────────────
    def _paint_icons(self):
        c = self.ctx.theme_tokens()
        self.btn_take.setIcon(icons.icon("camera", c["accent_fg"], 14))
        for btn, name in ((self.btn_compare, "compare"), (self.btn_save, "save"),
                          (self.btn_load, "folder")):
            btn.setIcon(icons.icon(name, c["text_2"], 14))

    def apply_settings(self):
        self.lbl_empty.apply_theme(self.ctx.theme_tokens())
        self._paint_icons()
        self._render()

    def retranslate(self, t):
        self.lbl_empty.set_content(title=t("snapEmptyTitle"))
        self.btn_take.setText("  " + t("snapTake"))
        self.btn_compare.setText("  " + t("snapCompare"))
        self.btn_save.setText("  " + t("snapSave"))
        self.btn_load.setText("  " + t("snapLoad"))
        for key in _FILTERS:
            self.seg_filter._buttons[key].setText(
                t(f"snapFilter{key.capitalize()}"))
        self._set_headers()
        if self._counts:
            self._show_summary()
        elif not self.baseline:
            self.lbl_status.setText(t("snapIdle"))
        self._render()

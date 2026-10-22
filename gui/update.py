# gui/update.py
"""Updates in the window: the quiet check, the one question, the progress.

UpdateController (one per main window)
    start()          after the window is up: drop old downloads, check right
                     away and then every few hours — frozen builds only (a
                     source checkout and the tests never go online).
    check(manual)    background check; a manual one always answers ("you are
                     up to date" / why it failed), an automatic one speaks
                     only when there is something to offer.
    status_text      one line for Settings → About.

UpdateDialog
    The single question: what is new, «Обновить» / «Позже» / «Пропустить эту
    версию». «Обновить» downloads (progress, cancel) and verifies. An
    installed copy (since 26.10.3: a folder per version, see core/updater)
    then installs the new version beside the running one — invisibly, the
    app keeps working — and the card turns into «Версия … готова ·
    Перезапустить»: the restart takes as long as a start. A portable copy
    (or one installed the old way) hands over to quit_for_update() as before.

Automatic updates of an installed copy work like Telegram's: the check finds
a version, it is downloaded and installed in the background (for all users
only after one question, since Windows will ask for permission), and the
rail shows «Обновить до …». Nothing changes until the restart — or the next
start, when the launcher picks the newest folder.
"""
import os
import sys
import threading
import time

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal, QObject
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QWidget,
)

from gui import icons
from core import updater
from gui.dialogs import themed_info, button_qss
from gui.qt_utils import later
from app.settings_manager import save_settings
from gui.theme_manager import get_theme
from app.version import APP_VERSION

CHECK_EVERY_MS = 6 * 3600 * 1000      # a window left open for days still hears
# Right after start-up: the installer people download is the same file for
# months, so the first thing a fresh install does is bring itself up to date.
# The short pause lets the window paint and the demo open first.
FIRST_CHECK_MS = 1500
OFFER_RETRY_MS = 2000                 # an automatic offer waits for a free moment


def error_text(t, err: updater.UpdateError) -> str:
    key = f"updErr_{err.code}"
    msg = t(key)
    if msg == key:
        msg = t("updErr_http")
    return f"{msg}\n{err.detail}" if err.detail else msg


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f}"


class _CheckResult(QObject):
    done = pyqtSignal(object, object)          # Release | None, UpdateError | None


def _check_worker(kind: str, exe_name: str, result: _CheckResult):
    """One check, in a DAEMON Python thread. It used to be a QThread owned by
    the controller: closing the window while the check still waited on the
    network (no internet, a firewall that drops packets — up to TIMEOUT per
    step) destroyed a running QThread, and Qt aborts the process for that
    (exit 0xC0000409). A daemon thread holds nothing up and is simply
    abandoned at exit; *result* is parentless, so it lives as long as this
    thread references it, and after shutdown() nothing listens to it."""
    try:
        rel, err = updater.fetch_latest(kind=kind, exe_name=exe_name), None
    except updater.UpdateError as e:
        rel, err = None, e
    except Exception as e:                     # never let a check kill the app
        rel, err = None, updater.UpdateError("http", repr(e))
    try:
        result.done.emit(rel, err)             # queued to the GUI thread
    except RuntimeError:
        pass                                   # the application is going away


class _BackgroundResult(QObject):
    done = pyqtSignal(object, str, object)     # Release, path | "", UpdateError | None


def _download_worker(rel, result: _BackgroundResult):
    try:
        path, err = updater.download(rel), None
    except updater.UpdateError as e:
        path, err = "", e
    except Exception as e:                     # never let it kill the app
        path, err = "", updater.UpdateError("disk", repr(e))
    try:
        result.done.emit(rel, path, err)
    except RuntimeError:
        pass


class _DownloadThread(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str, object)             # path | "", UpdateError | None

    def __init__(self, rel, parent=None):
        super().__init__(parent)
        self.rel = rel
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            path = updater.download(self.rel, progress=self.progress.emit,
                                    cancelled=self._cancel.is_set)
        except updater.UpdateError as e:
            self.done.emit("", e)
        except Exception as e:
            self.done.emit("", updater.UpdateError("disk", repr(e)))
        else:
            self.done.emit(path, None)


class _InstallRunner(QObject):
    """The new installer, run invisibly beside the working app; its progress
    comes through a file (installer/ModbusReader.iss writes it)."""

    progress = pyqtSignal(float)               # 0…1
    done = pyqtSignal(int)                     # the installer's exit code

    def __init__(self, setup: str, all_users: bool, parent=None):
        super().__init__(parent)
        work = updater.downloads_dir()
        self.progress_file = os.path.join(work, "install-progress.txt")
        self.log_file = os.path.join(work, "install.log")
        self.args = updater.background_install_args(
            setup, self.progress_file, self.log_file, all_users)
        self.proc = None
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> str:
        """'' when started, else why not."""
        try:
            os.makedirs(os.path.dirname(self.progress_file), exist_ok=True)
            if os.path.exists(self.progress_file):
                os.remove(self.progress_file)
            self.proc = updater.start_detached(self.args)
        except OSError as e:
            return str(e)
        self._timer.start()
        return ""

    def _poll(self):
        state, frac = updater.read_progress(self.progress_file)
        if state == "progress":
            self.progress.emit(frac)
        code = self.proc.poll() if self.proc is not None else 1
        if code is not None:
            self._timer.stop()
            self.done.emit(int(code))


class UpdateDialog(QDialog):
    """Frameless card (the app's dialog style) for one offered release.

    ``outcome`` after exec(): "later" | "skip" | "page" | "install" (then
    ``path`` is the verified download — a portable copy hands over) |
    "restart" (the new version is installed beside this one).
    ``installed`` is True once the new version is in place, whatever the
    outcome — «Позже» on the ready card keeps it for later.

    *mode*: "offer" (download → install → ready), "install" (already
    downloaded: an install for all users waits for its one question),
    "ready" (installed: only the restart is left). *side* is
    {"root", "all_users"} for a copy with version folders, else None."""

    def __init__(self, ctx, rel, kind: str, parent=None, mode: str = "offer",
                 side: dict | None = None, path: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.ctx, self.rel, self.kind = ctx, rel, kind
        self.t = ctx.t
        self.outcome = "later"
        self.path = path
        self.side = side
        self.mode = mode
        self.installed = mode == "ready"
        self._dl = None
        self._runner = None
        self._drag_at = None
        c = get_theme(ctx.theme)
        self.c = c

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("updCard")
        card.setStyleSheet(f"""
            QFrame#updCard {{ background: {c['bg_2']};
                border: 1px solid {c['line_strong']}; border-radius: 12px; }}
            QLabel {{ background: transparent; }}
            QLabel#updTitle {{ color: {c['text_1']}; font-size: 16px; font-weight: 700; }}
            QLabel#updSub {{ color: {c['text_3']}; font-size: 12px; }}
            QLabel#updHead {{ color: {c['text_3']}; font-size: 11px; font-weight: 600;
                letter-spacing: 0.5px; }}
            QLabel#updNotes {{ color: {c['text_2']}; font-size: 12px; }}
            QLabel#updNote {{ color: {c['text_3']}; font-size: 12px; }}
            QLabel#updStatus {{ color: {c['text_2']}; font-size: 12px; }}
            QLabel#updStatus[error="true"] {{ color: {c['error']}; }}
            QScrollArea#updScroll {{ background: {c['bg_1']}; border: 1px solid {c['line']};
                border-radius: 8px; }}
            QWidget#updNotesBox, QWidget#updNotesWrap {{ background: transparent; }}
            QProgressBar {{ background: {c['bg_0']}; border: none; border-radius: 3px;
                max-height: 6px; min-height: 6px; }}
            QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
        """)
        card.setFixedWidth(480)
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        ico = QLabel()
        ico.setPixmap(icons.pixmap("download", c["accent"], 24))
        ico.setFixedSize(28, 28)
        head.addWidget(ico, alignment=Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.lbl_title = QLabel(self.t("updDlgTitle").format(ver=rel.version))
        self.lbl_title.setObjectName("updTitle")
        sub = self.t("updDlgSub").format(cur=APP_VERSION)
        if rel.size:
            sub += "  ·  " + self.t("updDlgSize").format(size=_mb(rel.size))
        self.lbl_sub = QLabel(sub)
        self.lbl_sub.setObjectName("updSub")
        names.addWidget(self.lbl_title)
        names.addWidget(self.lbl_sub)
        head.addLayout(names, 1)
        lay.addLayout(head)

        self._notes_wrap = QWidget()
        self._notes_wrap.setObjectName("updNotesWrap")   # else the global bg_1 slab
        nl = QVBoxLayout(self._notes_wrap)
        nl.setContentsMargins(0, 4, 0, 0)
        nl.setSpacing(6)
        if rel.notes:
            h = QLabel(self.t("updWhatsNew").upper())
            h.setObjectName("updHead")
            nl.addWidget(h)
            box = QWidget()
            box.setObjectName("updNotesBox")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 10, 12, 10)
            notes = QLabel(rel.notes)
            notes.setObjectName("updNotes")
            notes.setWordWrap(True)
            notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bl.addWidget(notes)
            sc = QScrollArea()
            sc.setObjectName("updScroll")
            sc.setWidgetResizable(True)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sc.setWidget(box)
            # As tall as the text (up to 220 px, then it scrolls) — a fixed
            # box left three lines floating in the middle of empty space.
            text_w = 480 - 44 - 24 - 2
            sc.setFixedHeight(min(220, notes.heightForWidth(text_w) + 20 + 2))
            self._notes_sc, self._notes_lbl = sc, notes
            nl.addWidget(sc)
        lay.addWidget(self._notes_wrap)

        # Why this copy cannot update itself (then the main button opens the
        # release page instead) — or what pressing it will do.
        self._blocker = self._blocking_reason()
        note = self._blocker or self.t("updRestartNote")
        if self.side is not None:
            if self.side.get("all_users") and not self._blocker:
                note += " " + self.t("updAdminNote")
        elif (not self._blocker and self.kind == "installed"
                and not updater.can_replace(sys.executable)):
            # Installed for all users (Program Files): the installer elevates
            # itself, so Windows asks — say so before the UAC prompt does.
            note += " " + self.t("updAdminNote")
        self.lbl_note = QLabel(note)
        self.lbl_note.setObjectName("updNote")
        self.lbl_note.setWordWrap(True)
        lay.addWidget(self.lbl_note)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("updStatus")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.hide()
        lay.addWidget(self.lbl_status)

        lay.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_skip = self._button(self.t("updSkip"), "ghost", self._skip)
        self.btn_later = self._button(self.t("updLater"), "plain", self._later)
        go = self.t("updOpenPage") if self._blocker else self.t("updGo")
        self.btn_go = self._button(go, "primary", self._go)
        self.btn_go.setDefault(True)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_later)
        row.addWidget(self.btn_go)
        lay.addLayout(row)
        # Size the notes box BEFORE the first show, with the stylesheet's
        # font on the label: a top-level keeps the size it was shown with.
        self.ensurePolished()
        if mode == "ready":
            self._show_ready()
        elif mode == "install":
            self.btn_go.setText(self.t("updInstallGo"))
        self._fit_notes()
        self.resize(self.sizeHint())

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_notes()
        later(0, self, self._fit_notes)        # again once the layout settled

    def _fit_notes(self):
        """Measure with the label's REAL width and font. Measured while
        building (default font) or in showEvent (before the layout gave the
        label its width) the notes came out a line short — the last line
        sat on the box's bottom edge."""
        sc = getattr(self, "_notes_sc", None)
        if sc is None:
            return
        lbl = self._notes_lbl
        # Before the first layout the label has no real width yet; the card
        # is fixed at 480, so its text column is known.
        width = (lbl.width() if lbl.isVisible() and lbl.width() > 50
                 else 480 - 44 - 24 - 2)
        sc.setFixedHeight(min(220, lbl.heightForWidth(width) + 20 + 4))
        # The container must not be squeezed below the box: the dialog's
        # height-for-width pass gave it less, and the box's bottom was cut.
        self._notes_wrap.setMinimumHeight(self._notes_wrap.sizeHint().height())
        self.layout().activate()
        if self.isVisible() and self.height() < self.minimumSizeHint().height():
            self.adjustSize()

    # ── pieces ────────────────────────────────────────────────────
    def _button(self, text: str, kind: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumWidth(b.fontMetrics().horizontalAdvance(text) + 34)
        b.setStyleSheet(button_qss(self.c, kind))
        b.clicked.connect(slot)
        return b

    def _blocking_reason(self) -> str:
        if self.kind == "source":
            return self.t("updSourceHint")
        if self.kind == "page":
            return self.t("updPageHint")
        if not self.rel.asset_url or not self.rel.sha256:
            return self.t("updNoBuildHint")
        if self.kind == "portable" and not updater.can_replace(sys.executable):
            return self.t("updNoWriteHint").format(
                dir=os.path.dirname(sys.executable))
        return ""

    def _set_status(self, text: str, error: bool = False):
        self.lbl_status.setText(text)
        self.lbl_status.setProperty("error", "true" if error else "false")
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)
        self.lbl_status.show()

    # ── choices ───────────────────────────────────────────────────
    def _skip(self):
        self.outcome = "skip"
        self.accept()

    def _later(self):
        if self._dl is not None:               # «Отмена» while downloading
            self._dl.cancel()
            return
        self.outcome = "later"
        self.accept()

    def _go(self):
        if self._blocker or self.outcome == "page":
            self.outcome = "page"
            self.accept()
            return
        if self.mode == "ready":
            self.outcome = "restart"
            self.accept()
            return
        if self.mode == "install" and self.path:
            self._start_install(self.path)
            return
        self._start_download()

    # ── install beside the running copy ───────────────────────────
    def _start_install(self, path: str):
        self.path = path
        self.btn_skip.hide()
        self.btn_go.hide()
        self.btn_later.setEnabled(False)       # the installer cannot be stopped
        self.lbl_note.hide()
        self.bar.setValue(0)
        self.bar.show()
        self._set_status(self.t("updInstallingPct").format(pct=0))
        self._runner = _InstallRunner(path, bool(self.side and self.side.get("all_users")),
                                      self)
        self._runner.progress.connect(self._on_install_progress)
        self._runner.done.connect(self._on_installed)
        err = self._runner.start()
        if err:
            self._runner = None
            self._install_failed(err)

    def _on_install_progress(self, frac: float):
        self.bar.setValue(int(frac * 1000))
        self.lbl_status.setText(self.t("updInstallingPct").format(pct=int(frac * 100)))

    def _on_installed(self, code: int):
        self._runner = None
        self.btn_later.setEnabled(True)
        if code != 0:
            self._install_failed(self.t("updInstallFailed").format(code=code))
            return
        self.installed = True
        self._show_ready()

    def _install_failed(self, text: str):
        self.bar.hide()
        self.btn_later.setEnabled(True)
        self._set_status(text, error=True)
        self.btn_later.setText(self.t("updClose"))
        if self.rel.page_url:
            self.btn_go.setText(self.t("updOpenPage"))
            self.btn_go.show()
            self.outcome = "page"

    def _show_ready(self):
        """The new version is in its folder: one button left."""
        self.mode = "ready"
        self.lbl_title.setText(self.t("updReadyTitle").format(ver=self.rel.version))
        self.lbl_sub.setText(self.t("updDlgSub").format(cur=APP_VERSION))
        self.bar.hide()
        self.lbl_status.hide()
        self.lbl_note.setText(self.t("updReadyNote"))
        self.lbl_note.show()
        self.btn_skip.hide()
        self.btn_later.setText(self.t("updLater"))
        self.btn_later.show()
        self.btn_go.setText(self.t("updRestart"))
        self.btn_go.setMinimumWidth(self.btn_go.fontMetrics().horizontalAdvance(
            self.t("updRestart")) + 34)
        self.btn_go.show()
        self.outcome = "later"
        self.adjustSize()

    def _start_download(self):
        self.btn_skip.hide()
        self.btn_go.hide()
        self.btn_later.setText(self.t("updCancel"))
        self.lbl_note.hide()
        self.bar.setValue(0)
        self.bar.show()
        self._set_status(self.t("updDownloading").format(
            done="0.0", total=_mb(self.rel.size)))
        self._dl = _DownloadThread(self.rel, self)
        self._dl.progress.connect(self._on_progress)
        self._dl.done.connect(self._on_downloaded)
        self._dl.start()

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.bar.setValue(int(1000 * done / total))
        self.lbl_status.setText(self.t("updDownloading").format(
            done=_mb(done), total=_mb(total or self.rel.size)))

    def _on_downloaded(self, path: str, err):
        dl, self._dl = self._dl, None
        if dl is not None:
            dl.wait(2000)
        if err is None and self.side is not None:
            self.btn_later.setText(self.t("updLater"))
            self._start_install(path)
            return
        if err is None:
            self.bar.setValue(1000)
            self._set_status(self.t("updRestarting"))
            self.path = path
            self.outcome = "install"
            later(600, self, self.accept)
            return
        if err.code == "cancelled":
            self.outcome = "later"
            self.accept()
            return
        # Failed: say why, and offer the manual way.
        self.bar.hide()
        self._set_status(error_text(self.t, err), error=True)
        self.btn_later.setText(self.t("updClose"))
        if self.rel.page_url:
            self.btn_go.setText(self.t("updOpenPage"))
            self.btn_go.show()
            self.outcome = "page"

    def reject(self):                           # Esc
        if self._dl is not None:
            self._dl.cancel()
            return
        if self._runner is not None and self._runner.running:
            return                              # a few seconds: let it finish
        self.outcome = "later"
        super().reject()

    def done(self, r):
        if self._dl is not None:                # closing mid-download
            self._dl.cancel()
            self._dl.wait(3000)
            self._dl = None
        super().done(r)

    # Frameless → drag by the card.
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


class UpdateController(QObject):
    status_changed = pyqtSignal(str)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.kind = updater.install_kind()
        self._checker = None
        self._offering = False
        self._pending = None          # (rel, mode, path) waiting for a free moment
        self._status = ""
        # An installed copy with a folder per version (since 26.10.3):
        # updates go in beside it while it works.
        root = updater.install_root() if self.kind == "installed" else ""
        self.side = ({"root": root, "all_users": updater.installed_for_all_users(root)}
                     if root else None)
        self._bg = None               # the background download in flight
        self._runner = None           # the background installer in flight
        self._ready = None            # Release installed and waiting for a restart
        rail = getattr(win, "nav_rail", None)
        if rail is not None and hasattr(rail, "update_clicked"):
            rail.update_clicked.connect(self.show_ready)
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_EVERY_MS)
        self._timer.timeout.connect(lambda: self.check(manual=False))

    # ── helpers ───────────────────────────────────────────────────
    @property
    def settings(self) -> dict:
        return self.win.settings

    def t(self, key: str) -> str:
        return self.win.ctx.t(key)

    @property
    def status_text(self) -> str:
        if self._status:
            return self._status
        ts = int(self.settings.get("update_last_check") or 0)
        if ts <= 0:
            return self.t("updNever")
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))
        return self.t("updLastCheck").format(when=when)

    def _set_status(self, text: str):
        self._status = text
        self.status_changed.emit(text)

    @property
    def busy(self) -> bool:
        return (self._checker is not None or self._offering
                or self._pending is not None or self._bg is not None
                or (self._runner is not None and self._runner.running))

    def _user_occupied(self) -> bool:
        """The first-launch guide or another modal dialog is up: an automatic
        offer does not pile a second window on top — it waits."""
        return (getattr(self.win, "_guide", None) is not None
                or QApplication.activeModalWidget() is not None)

    # ── lifecycle ─────────────────────────────────────────────────
    def start(self):
        if self.kind == "source":
            return                  # a dev checkout / the tests never go online
        updater.cleanup_downloads()
        if self.side is not None:
            root = self.side["root"]
            here = os.path.dirname(os.path.abspath(sys.executable))
            # Older version folders: renamed, then deleted, off the GUI thread.
            threading.Thread(target=updater.cleanup_old_versions, args=(root, here),
                             name="old-versions", daemon=True).start()
            newest = updater.newest_installed(root)
            if newest and updater.is_newer(newest):
                # Installed earlier, not restarted yet (an older window).
                self._set_ready(updater.Release(newest, "", ""))
        self.apply_settings()
        if self.settings.get("update_auto", True):
            later(FIRST_CHECK_MS, self.win, lambda: self.check(manual=False))

    def apply_settings(self):
        if self.kind != "source" and self.settings.get("update_auto", True):
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def shutdown(self):
        self._timer.stop()
        self._pending = None
        bg, self._bg = self._bg, None
        if bg is not None:
            try:
                bg.done.disconnect()
            except TypeError:
                pass
        result, self._checker = self._checker, None
        if result is not None:                 # a check still in flight: let it go
            try:
                result.done.disconnect()
            except TypeError:
                pass

    # ── check ─────────────────────────────────────────────────────
    def check(self, manual: bool = False):
        if self.busy:
            return
        if not manual and not self.settings.get("update_auto", True):
            return
        self._set_status(self.t("updChecking"))
        result = _CheckResult()                # no parent: see _check_worker
        result.done.connect(lambda rel, err: self._on_checked(rel, err, manual))
        self._checker = result
        threading.Thread(target=_check_worker, name="update-check", daemon=True,
                         args=(self.kind, os.path.basename(sys.executable), result)
                         ).start()

    def _on_checked(self, rel, err, manual: bool):
        self._checker = None
        self.settings["update_last_check"] = int(time.time())
        theme = self.win.ctx.theme
        if err is not None:
            self._set_status(self.t("updStatusError"))
            if manual:
                themed_info(self.win, theme, "warning", self.t("updCheckFailed"),
                            error_text(self.t, err), ok_label=self.t("updClose"))
            return
        if rel is None:
            self._set_status(self.t("updLatest").format(ver=APP_VERSION))
            if manual:
                themed_info(self.win, theme, "success", self.t("updLatestTitle"),
                            self.t("updLatest").format(ver=APP_VERSION),
                            ok_label=self.t("updClose"))
            return
        self._set_status(self.t("updAvailable").format(ver=rel.version))
        if self._ready is not None and not updater.is_newer(rel.version, self._ready.version):
            if manual:
                self.offer(self._ready, mode="ready")
            return                   # already installed, waiting for the restart
        if not manual and self.settings.get("update_skip") == rel.version:
            return                   # «Пропустить эту версию» — until the next one
        if not manual and self.side is not None:
            self._background(rel)
            return
        self._offer_when_free(rel, "offer", "", manual)

    def _offer_when_free(self, rel, mode: str, path: str, now: bool = False):
        if not now and self._user_occupied():
            self._pending = (rel, mode, path)
            later(OFFER_RETRY_MS, self.win, self._offer_pending)
            return
        self.offer(rel, mode=mode, path=path)

    def _offer_pending(self):
        pending = self._pending
        if pending is None:
            return
        if self._user_occupied():
            later(OFFER_RETRY_MS, self.win, self._offer_pending)
            return
        self._pending = None
        rel, mode, path = pending
        self.offer(rel, mode=mode, path=path)

    # ── background: download → install beside → «restart» ────────
    def _background(self, rel):
        newest = updater.newest_installed(self.side["root"])
        if newest and not updater.is_newer(rel.version, newest):
            self._set_ready(rel)             # it is in place already
            return
        result = _BackgroundResult()          # parentless: see _download_worker
        result.done.connect(self._background_downloaded)
        self._bg = result
        threading.Thread(target=_download_worker, args=(rel, result),
                         name="update-download", daemon=True).start()

    def _background_downloaded(self, rel, path: str, err):
        self._bg = None
        if err is not None:
            self._set_status(self.t("updStatusError"))
            return
        if self.side["all_users"]:
            # Windows will ask for permission: one question first, not a
            # prompt out of nowhere in the middle of work.
            self._offer_when_free(rel, "install", path)
            return
        runner = _InstallRunner(path, False, self)
        runner.done.connect(lambda code, r=rel: self._background_installed(r, code))
        self._runner = runner
        err_text = runner.start()
        if err_text:
            self._runner = None
            self._set_status(self.t("updStatusError"))

    def _background_installed(self, rel, code: int):
        self._runner = None
        if code != 0:
            self._set_status(self.t("updInstallFailed").format(code=code))
            return
        self._set_ready(rel)
        self._offer_when_free(rel, "ready", "")

    def _set_ready(self, rel):
        self._ready = rel
        self._set_status(self.t("updReadyTitle").format(ver=rel.version))
        rail = getattr(self.win, "nav_rail", None)
        if rail is not None and hasattr(rail, "set_update"):
            rail.set_update(self.t("updRailReady").format(ver=rel.version),
                            self.t("updRailTip"))

    def show_ready(self):
        """The rail's «Обновить до …»."""
        if self._ready is not None and not self._offering:
            self.offer(self._ready, mode="ready")

    def restart(self) -> bool:
        """Quit and start the launcher — it opens the newest version."""
        if self.side is None:
            return False
        return self.win.quit_for_update([updater.launcher_path(self.side["root"])])

    # ── offer → install ──────────────────────────────────────────
    def offer(self, rel, mode: str = "offer", path: str = ""):
        self._offering = True
        try:
            dlg = UpdateDialog(self.win.ctx, rel, self.kind, self.win, mode=mode,
                               side=self.side, path=path)
            dlg.exec()
        finally:
            self._offering = False
        if dlg.installed:
            self._set_ready(rel)
        if dlg.outcome == "restart":
            self.restart()
        elif dlg.outcome == "skip":
            self.settings["update_skip"] = rel.version
            save_settings(self.settings)
        elif dlg.outcome == "page" and rel.page_url:
            QDesktopServices.openUrl(QUrl(rel.page_url))
        elif dlg.outcome == "install" and dlg.path:
            args = updater.handover_args(self.kind, dlg.path, sys.executable,
                                         updater.app_pids())
            self.win.quit_for_update(args)

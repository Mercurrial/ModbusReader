# gui/qt_utils.py
"""Small Qt helpers — currently the safe deferred-call primitive.

Why this exists: a `QTimer.singleShot(ms, callback)` whose callback touches a
widget can fire AFTER that widget was destroyed. Touching a dead C++ object
from Python is not a catchable error — PyQt aborts the process with an access
violation. This has bitten the project five times (settings dialog, deferred
settings apply, font-role chunks, dashboard pulse, profile-editor row slide),
so the guarded call lives here once instead of being re-invented per site.
"""

from PyQt6.QtCore import QTimer
from PyQt6 import sip


def alive(obj) -> bool:
    """True when the wrapped C++ object still exists."""
    try:
        return obj is not None and not sip.isdeleted(obj)
    except (TypeError, RuntimeError):
        return obj is not None


def later(ms: int, owner, callback, *args):
    """Run *callback* after *ms*, but only if *owner* is still alive.

    ``owner`` is the widget the callback touches (usually the one that owns
    the callback). Any RuntimeError from a race between the check and the call
    is swallowed — by then the widget is gone and the work is moot.

    Note this does NOT coalesce: N calls schedule N runs. For "do this once,
    after the user stops fiddling" use :func:`debounce`."""
    def _fire():
        if not alive(owner):
            return
        try:
            callback(*args)
        except RuntimeError:
            pass          # widget died between the check and the call
    QTimer.singleShot(ms, _fire)


def debounce(ms: int, owner, key: str, callback, *args):
    """Like :func:`later`, but a second call with the same *key* replaces the
    pending one instead of queueing beside it.

    This exists because a live preview that repolishes the whole widget tree
    costs hundreds of milliseconds. With plain ``later`` a user clicking
    through four colour schemes queued four full restyles that then ran
    back-to-back — the interface froze for seconds AFTER the clicking stopped,
    which is exactly what "changing the theme takes 3-5 seconds" felt like.
    Only the last request is worth honouring: the intermediate appearances are
    ones nobody asked to keep.

    The timer is parented to *owner*, so it dies with the widget instead of
    firing into a deleted object.
    """
    timers = getattr(owner, "_debounce_timers", None)
    if timers is None:
        timers = {}
        owner._debounce_timers = timers
    timer = timers.get(key)
    if timer is None or not alive(timer):
        timer = QTimer(owner)
        timer.setSingleShot(True)
        timers[key] = timer
    else:
        timer.stop()
        try:
            timer.timeout.disconnect()
        except TypeError:
            pass          # nothing was connected yet

    def _fire():
        if not alive(owner):
            return
        try:
            callback(*args)
        except RuntimeError:
            pass
    timer.timeout.connect(_fire)
    timer.start(ms)


def set_state(widget, state: str = "") -> None:
    """Set the ``state`` dynamic property ("", "error", "ok"…) and re-polish,
    so QSS rules like ``QLabel#mhCrumb[state="error"]`` apply.

    Status lines used to mark an error by prefixing "⛔" to the text — and
    then had to test the TEXT to know whether they were showing an error."""
    if widget.property("state") == state:
        return
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def fit_on_screens(x, y, w: int, h: int, areas: list) -> tuple:
    """A saved window rect made safe to restore: ``(x, y, w, h)``.

    ``areas`` are the screens' available rectangles, primary first. A rect
    saved on a monitor that is no longer there (laptop undocked, projector
    unplugged) would open the window where nobody can see it — only its
    taskbar button. Keep the position while a grabbable strip of the title
    bar is on some screen; otherwise centre the window on the primary one.
    The size never exceeds the screen it lands on. ``x``/``y`` may be None
    (nothing saved yet): the result is then centred as well."""
    if not areas:
        return x, y, w, h
    if x is not None and y is not None:
        for a in areas:
            # The top 32 px of the window, minus the system buttons' corner.
            vis_w = min(x + w, a.x() + a.width()) - max(x, a.x())
            vis_h = min(y + 32, a.y() + a.height()) - max(y, a.y())
            if vis_w >= 120 and vis_h >= 16:
                return x, y, min(w, a.width()), min(h, a.height())
    a = areas[0]
    w, h = min(w, a.width()), min(h, a.height())
    return (a.x() + (a.width() - w) // 2, a.y() + (a.height() - h) // 2, w, h)


def style_title_bar(widget, tokens: dict) -> bool:
    """The window's title bar in the app's colours (Windows only).

    The title bar is drawn by Windows, not Qt, so it stayed white over a
    dark app. Dark mode for it is a DWM attribute (Windows 10 20H1+); on
    Windows 11 the caption and its text can take the theme's own colours
    too. Returns True when Windows took the dark/light setting."""
    import sys
    if sys.platform != "win32" or widget is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        from PyQt6.QtGui import QColor
        hwnd = wintypes.HWND(int(widget.winId()))
        dwm = ctypes.windll.dwmapi

        def attr(key, value) -> bool:
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, key, ctypes.byref(v),
                                             ctypes.sizeof(v)) == 0

        bg = QColor(tokens.get("bg_1", "#ffffff"))
        dark = bg.lightness() < 128
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE; 19 on Windows 10 before 20H1.
        ok = attr(20, int(dark)) or attr(19, int(dark))

        def colorref(hex_color):
            c = QColor(hex_color)
            return c.red() | (c.green() << 8) | (c.blue() << 16)

        attr(35, colorref(tokens.get("bg_1", "#ffffff")))     # DWMWA_CAPTION_COLOR (Win 11)
        attr(36, colorref(tokens.get("text_1", "#000000")))   # DWMWA_TEXT_COLOR (Win 11)
        # Repaint the frame now, not at the next resize.
        SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020    # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP)
        return ok
    except Exception:
        return False


def _framed_window(w) -> bool:
    from PyQt6.QtCore import Qt
    return (w.isWindow()
            and not (w.windowFlags() & Qt.WindowType.FramelessWindowHint))


class TitleBarStyler:
    """Every window with a Windows frame — the main window, the map editor,
    a popped-out chart — gets its title bar in the theme's colours when it
    becomes the active window, and again on a theme change
    (``restyle_all``). (An app-wide event filter caught each Show too, but
    ran Python for every event — ~40 000 calls a restyle.)"""

    def __init__(self, app, tokens_fn):
        self.tokens_fn = tokens_fn
        app.focusWindowChanged.connect(self._on_focus_window)

    def _on_focus_window(self, window):
        from PyQt6.QtWidgets import QApplication
        if window is None:
            return
        for w in QApplication.topLevelWidgets():
            if w.windowHandle() is window and _framed_window(w):
                style_title_bar(w, self.tokens_fn())

    def restyle_all(self, tokens: dict | None = None):
        from PyQt6.QtWidgets import QApplication
        tokens = tokens or self.tokens_fn()
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and _framed_window(w):
                style_title_bar(w, tokens)

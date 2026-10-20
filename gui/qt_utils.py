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

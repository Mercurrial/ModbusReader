# main.py

import os
import sys
import time
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QTimer

from app import settings_manager
from app.settings_manager import load_settings
from gui.styles import get_stylesheet
from gui.theme_manager import set_active
from app.version import APP_VERSION

ERROR_LOG_NAME = "modbusreader_errors.log"
FINISH_DELAY_MS = 120                # the window paints, then the splash goes (as gui.splash)


def error_log_path() -> str:
    """Next to app_settings.json — the one folder the app can always write."""
    return os.path.join(os.path.dirname(settings_manager.SETTINGS_FILE),
                        ERROR_LOG_NAME)


def _write_error_log(text: str) -> None:
    try:
        path = error_log_path()
        # Keep the file bounded: a fault in a paint handler can repeat many
        # times a second.
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"ModbusReader v{APP_VERSION} ===\n{text}")
    except OSError:
        pass


def my_excepthook(exc_type, value, tback):
    """Global hook for exceptions nothing else caught.

    Overriding sys.excepthook also stops PyQt from aborting the process on an
    exception in a slot. The traceback goes to stderr AND to a log file:
    the packaged build has no console, so a print alone was lost — and with it
    any chance of finding out what went wrong on the operator's machine."""
    text = "".join(traceback.format_exception(exc_type, value, tback))
    print("CRITICAL ERROR:\n" + text, file=sys.stderr)
    _write_error_log(text)


# Переопределяем стандартный обработчик
sys.excepthook = my_excepthook


def _close_splash():
    """Close the PyInstaller start-up splash (one-file builds only; the
    module does not exist when running from source)."""
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass


def _bundle_splash_alive() -> bool:
    """True in the one-file exe: its PyInstaller splash (the same card, as a
    picture) has been up since the double-click and stays until the window
    is — a second, live card on top of it would only flicker."""
    try:
        import pyi_splash  # type: ignore
        return bool(pyi_splash.is_alive())
    except Exception:
        return False


def _file_argument(argv: list) -> str:
    """A project / map handed over on the command line — what Explorer
    passes when a .mbproj is double-clicked (the installer registers it)."""
    for a in argv[1:]:
        if (not a.startswith("-") and a.lower().endswith((".mbproj", ".json"))
                and os.path.isfile(a)):
            return os.path.abspath(a)
    return ""


def startup_document(argv: list, first_run: bool) -> tuple:
    """What to open once the window is up: ("project", path) for a file
    handed over by Explorer, ("demo", "") on the very first launch — a new
    user lands in a working example, not in an empty grid — else (None, "")."""
    path = _file_argument(argv)
    if path:
        return "project", path
    if first_run:
        return "demo", ""
    return None, ""


def main():
    # Second half of a portable self-update: THIS exe is the new version,
    # started by the old one just before it quit (updater.finish_update —
    # waits for it, takes its place, starts it). No window, no Qt.
    from core import updater
    if updater.FINISH_FLAG in sys.argv:
        code = updater.finish_update(sys.argv)
        _close_splash()
        sys.exit(code)

    # Настройка HighDPI (PassThrough) для четкого промышленного интерфейса на любых мониторах
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # First launch = no settings file yet (an update keeps it, so people who
    # already use the app never get the demo pushed at them).
    first_run = not os.path.exists(settings_manager.SETTINGS_FILE)
    app = QApplication(sys.argv)
    app.setApplicationName("ModbusReader")
    app.setApplicationVersion(APP_VERSION)
    from gui import icons
    app.setWindowIcon(icons.app_icon())    # every window, taskbar included

    # Безопасное чтение настроек. load_settings() is CWD-independent (absolute
    # path) and self-healing (falls back to the .bak on a corrupt file), so the
    # startup stylesheet always reflects the user's real, saved preferences.
    theme_to_use = "Dark"
    font_family  = "Inter, Segoe UI, system-ui, sans-serif"
    font_size    = 9
    accent       = "neutral"
    lang         = "ru"
    try:
        settings = load_settings()
        lang         = str(settings.get("lang", lang))
        raw = settings.get("theme", "Dark")
        # Normalise to title-case "Dark" / "Light"
        theme_to_use = "Light" if str(raw).lower() == "light" else "Dark"
        font_family  = settings.get("font_family", font_family)
        font_size    = int(settings.get("font_size", font_size))
        accent       = settings.get("accent", accent)
        # PUBLISH the saved appearance before building the stylesheet.
        # get_stylesheet() reads the scheme/contrast from theme_manager's active
        # state; without this the startup QSS was generated from the DEFAULT
        # scheme while widgets built later (dialogs, popups) used the saved one
        # — so a chosen scheme appeared to change almost nothing on screen.
        set_active(settings.get("scheme"), settings.get("contrast"), accent)
    except (ValueError, TypeError):
        # Malformed values (e.g. "font_size": "big") must never prevent startup.
        print("Settings unreadable. Falling back to default 'Dark' theme.")

    # The start-up card (gui/splash.py): up before the heavy imports, so the
    # double-click answers at once — unless the one-file exe's own picture of
    # it already is.
    splash = None
    if not _bundle_splash_alive():
        try:
            from gui.splash import StartupSplash
            splash = StartupSplash(lang, f"v{APP_VERSION}")
            splash.show_now()
        except Exception:
            splash = None                # a card is never worth not starting

    def stage(key: str, progress: float):
        nonlocal splash
        if splash is not None:
            try:
                splash.step(key, progress)
            except Exception:            # never let the card stop the start
                splash = None

    app.setStyleSheet(get_stylesheet(theme_to_use, font_family, font_size, accent))

    # Инициализация и запуск графического интерфейса
    try:
        stage("splashModules", 0.12)
        from gui.main_window import ModernScadaApp
        stage("splashWindow", 0.62)
        window = ModernScadaApp()
        window.show()
        # In front of whatever was active when the user double-clicked (Windows
        # still flashes the taskbar button instead if they have since started
        # working in another program — their focus wins).
        window.raise_()
        window.activateWindow()
    except Exception as e:
        _close_splash()
        if splash is not None:
            splash.close()
        text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        print("FATAL ERROR during GUI initialization:\n" + text, file=sys.stderr)
        _write_error_log(text)
        # A plain native box on purpose: the app's own themed dialogs may be
        # exactly what failed to build.
        QMessageBox.critical(
            None, "ModbusReader",
            f"Не удалось запустить ModbusReader / ModbusReader failed to start:\n\n"
            f"{type(e).__name__}: {e}\n\n{error_log_path()}")
        sys.exit(1)
    # The window is up: the card leaves once the window has painted (closing
    # it at once left a beat of bare desktop between the two).
    if splash is not None:
        try:
            splash.finish()
        except Exception:
            splash.hide()
    QTimer.singleShot(FINISH_DELAY_MS, _close_splash)   # the one-file exe's picture
    kind, path = startup_document(sys.argv, first_run)
    if kind:
        QTimer.singleShot(0, (lambda: window._open_project(path)) if kind == "project"
                          else window._open_demo)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

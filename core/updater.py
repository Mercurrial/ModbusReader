# core/updater.py
"""Self-update: find a newer release, download it, hand over to it.

Logic only — urllib and subprocess, no widgets (the dialog and the
check-on-start live in gui/update.py).

Where updates come from: the LATEST (not draft, not pre-release) GitHub
release of ``version.UPDATE_REPO``, read anonymously through the REST API —
so that repository must be public. There is ONE release — each version
gets its own tag vYY.MM.N and moves the release to it — titled
"ModbusReader YY.MM.N"; it carries the builds as assets:

    ModbusReader.exe              the one-file portable build
    ModbusReader_debug.exe        the same with a console (portable)
    ModbusReader-Setup.exe        the installer (any name starting so is
                                  accepted)

A copy updates the way it was installed: a portable exe is replaced in
place, an installed copy runs the new installer silently. Every download is
checked against the SHA-256 GitHub computed for the asset when it was
uploaded (the ``digest`` field) — no checksum, no install.

Handing over: a running exe cannot overwrite itself.
  portable   the DOWNLOADED exe is started as ``--finish-update``: it waits
             for this copy's processes to exit, copies itself over the old
             exe and starts it (finish_update below — runs before any Qt).
  installed  (since 26.10.3) every version has its own folder beside a
             launcher (installer/ModbusReader.iss). The new installer runs
             invisibly WHILE THIS COPY KEEPS WORKING — nothing it writes is
             in use — and puts the next version beside this one; "restart"
             then only starts the launcher, which picks the newest folder.
             The next start removes the folders of older versions.
             (A copy installed the old way — ≤ 26.10.2, the program in the
             installation folder itself — hands over as before: the
             installer with /WAITPID=<pid> waits for the app to exit,
             installs and starts it again.)
No script interpreter on the way: a hidden PowerShell / cmd that sleeps,
deletes and relaunches is exactly what antivirus heuristics block (it was
refused intermittently on the development machine), and a .cmd file is read
in the OEM code page — a Cyrillic user name in the path would break it.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.version import APP_VERSION, UPDATE_REPO
# Shared with the installer window, which must not pull the network in:
from core.procs import (parse_version, posix_alive as _posix_alive,  # noqa: F401
                        wait_for_exit as _wait_for_exit)

API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
PORTABLE_ASSET = "ModbusReader.exe"
INSTALLER_PREFIX = "ModbusReader-Setup"
TIMEOUT = 15                         # seconds per network operation
_CHUNK = 64 * 1024
_NOTES_MAX = 1500


class UpdateError(Exception):
    """A check or download that failed for a reason worth telling the user.

    ``code`` picks the message (i18n ``updErr_<code>``); ``detail`` is the
    technical remainder (HTTP status, OS error)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class Release:
    version: str          # "2.4.0"
    notes: str            # release text, markdown stripped
    page_url: str         # the release page (fallback: download by hand)
    asset_name: str = ""  # "" — newer, but no build for this kind of copy
    asset_url: str = ""
    size: int = 0
    sha256: str = ""      # lower-case hex


# ── versions ───────────────────────────────────────────────────────
def is_newer(remote, local=APP_VERSION) -> bool:
    r, cur = parse_version(remote), parse_version(local)
    return r is not None and cur is not None and r > cur


# ── what kind of copy is running ───────────────────────────────────
def install_kind() -> str:
    """"source" (python main.py), "installed" (put there by the installer),
    "portable" (an exe someone copied somewhere) or "page" (a Linux / macOS
    build: the update is offered, its release page opened)."""
    if not getattr(sys, "frozen", False):
        return "source"
    if sys.platform != "win32":
        # Linux / macOS builds: no self-replacing yet — the update is offered
        # and its release page opened (a portable copy would otherwise pick
        # ModbusReader.exe, the Windows build).
        return "page"
    from app.settings_manager import is_installed_dir
    return ("installed" if is_installed_dir(os.path.dirname(sys.executable))
            else "portable")


# ── side-by-side versions (installed copies since 26.10.3) ─────────
VERSION_PREFIX = "app-"
MARKER = ".installed"                  # written into a version folder last
LAUNCHER = "ModbusReader.exe"


def install_root() -> str:
    """The installation folder of this copy if it runs from a version folder
    (…/ModbusReader/app-26.10.3/), else ""."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return ""
    here = os.path.dirname(os.path.abspath(sys.executable))
    if not os.path.basename(here).lower().startswith(VERSION_PREFIX):
        return ""
    from app.settings_manager import install_root as _root
    return _root(here)


def version_dirs(root: str) -> list:
    """[(version tuple, folder)] of the versions in *root* whose
    installation finished, oldest first."""
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for name in names:
        if not name.lower().startswith(VERSION_PREFIX):
            continue
        folder = os.path.join(root, name)
        ver = parse_version(name[len(VERSION_PREFIX):])
        if (ver is None or not os.path.isfile(os.path.join(folder, MARKER))
                or not os.path.isfile(os.path.join(folder, LAUNCHER))):
            continue
        out.append((ver, folder))
    return sorted(out)


def newest_installed(root: str) -> str:
    """The highest finished version in *root* as text ("" if none)."""
    dirs = version_dirs(root)
    return os.path.basename(dirs[-1][1])[len(VERSION_PREFIX):] if dirs else ""


def cleanup_old_versions(root: str, current_dir: str) -> list:
    """Remove the version folders older than the running one. A folder is
    renamed first: Windows refuses that while a program inside it still
    runs (another window of an older version), and such a folder is left
    for the next start instead of being half-deleted under it."""
    removed = []
    try:
        cur = parse_version(os.path.basename(current_dir)[len(VERSION_PREFIX):])
        names = os.listdir(root)
    except (OSError, TypeError):
        return removed
    if cur is None:
        return removed
    current = os.path.normcase(os.path.abspath(current_dir))
    for name in names:
        folder = os.path.join(root, name)
        if not name.lower().startswith(VERSION_PREFIX) or not os.path.isdir(folder):
            continue
        if os.path.normcase(os.path.abspath(folder)) == current:
            continue
        if ".removing-" in name:                   # left over by an earlier attempt
            shutil.rmtree(folder, ignore_errors=True)
            continue
        ver = parse_version(name[len(VERSION_PREFIX):])
        if ver is None or ver >= cur:
            continue                               # never a newer one
        doomed = f"{folder}.removing-{os.getpid()}"
        try:
            os.rename(folder, doomed)
        except OSError:
            continue                               # in use — next time
        shutil.rmtree(doomed, ignore_errors=True)
        removed.append(name)
    return removed


def launcher_path(root: str) -> str:
    return os.path.join(root, LAUNCHER)


UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 r"\{A571CF74-F203-4766-AF18-6780232E6CC4}_is1")


def _per_user_location() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            loc, _ = winreg.QueryValueEx(k, "InstallLocation")
        return str(loc)
    except (OSError, ImportError):
        return ""


def installed_for_all_users(root: str, per_user_location=_per_user_location) -> bool:
    """An install for everyone (the installer needs Windows' permission)
    or just for this user (the background update asks nothing)."""
    loc = per_user_location()
    if not loc:
        return True
    norm = lambda p: os.path.normcase(os.path.abspath(p.rstrip("\\/")))
    return norm(loc) != norm(root)


def background_install_args(setup: str, progress: str, log: str,
                            all_users: bool) -> list:
    """The new installer, invisibly, beside the running copy: no window, no
    closing of running programs (nothing in use is touched), no start."""
    return [setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
            "/NOCANCEL", "/NOLAUNCH", "/NOCLOSEAPPLICATIONS",
            "/ALLUSERS" if all_users else "/CURRENTUSER",
            f"/PROGRESS={progress}", f"/LOG={log}"]


def read_progress(path: str) -> tuple:
    """The installer's progress file: ("progress", 0…1) while copying,
    ("done", 1.0) at the end, ("", 0.0) before anything was written (or
    while the file is being rewritten)."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read().strip()
    except OSError:
        return "", 0.0
    if text.startswith("done"):
        return "done", 1.0
    parts = text.split()
    if len(parts) == 3 and parts[0] == "progress":
        try:
            done, total = int(parts[1]), int(parts[2])
        except ValueError:
            return "", 0.0
        return "progress", (min(1.0, done / total) if total > 0 else 0.0)
    return "", 0.0


def _is_onefile() -> bool:
    # One-file builds unpack into %TEMP%\_MEIxxxx; the exe the user started
    # is a separate bootloader process that holds the file until we exit.
    return os.path.basename(getattr(sys, "_MEIPASS", "") or "").startswith("_MEI")


def app_pids() -> list[int]:
    pids = [os.getpid()]
    if _is_onefile():
        pids.append(os.getppid())
    return pids


def can_replace(path: str) -> bool:
    """Can a new file be put next to *path* (portable copy in a writable
    folder, not Program Files)?"""
    probe = os.path.join(os.path.dirname(os.path.abspath(path)), ".update_probe")
    try:
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


# ── the release feed ───────────────────────────────────────────────
def _clean_notes(body: str) -> str:
    """Markdown → readable plain text for a small dialog."""
    lines = []
    for line in str(body or "").replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^\s*#+\s*", "", line)                 # headings
        line = re.sub(r"^\s*[-*]\s+", "• ", line)              # bullets
        line = re.sub(r"(\*\*|__|`)", "", line)                # emphasis, code
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)   # links → text
        lines.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text) > _NOTES_MAX:
        text = text[:_NOTES_MAX].rsplit(" ", 1)[0] + " …"
    return text


def _pick_asset(assets: list, kind: str, exe_name: str) -> dict | None:
    by_name = {a.get("name", ""): a for a in assets if isinstance(a, dict)}
    if kind == "page":
        return None                        # nothing to download and run here
    if kind == "installed":
        for name, a in by_name.items():
            if name.startswith(INSTALLER_PREFIX) and name.lower().endswith(".exe"):
                return a
        return None
    # Portable: the same flavour that is running (the console build updates
    # to the console build), else the plain one.
    return by_name.get(exe_name) or by_name.get(PORTABLE_ASSET)


def parse_release(data: dict, kind: str, exe_name: str = PORTABLE_ASSET) -> Release | None:
    """The GitHub "latest release" JSON → Release, or None if it is not a
    usable release at all (draft, pre-release, no version anywhere).

    The version is read from the release TITLE ("ModbusReader 26.10.1"),
    the tag (v26.10.1) being the fallback: the repository keeps ONE release,
    which each version moves to its own tag, and the title is what a person
    checks on the page."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    ver = parse_version(data.get("name")) or parse_version(data.get("tag_name"))
    if ver is None:
        return None
    rel = Release(version=".".join(map(str, ver)),
                  notes=_clean_notes(data.get("body", "")),
                  page_url=str(data.get("html_url") or ""))
    a = _pick_asset(data.get("assets") or [], kind, exe_name)
    if a is not None:
        digest = str(a.get("digest") or "")
        rel.asset_name = str(a.get("name", ""))
        rel.asset_url = str(a.get("browser_download_url") or "")
        rel.size = int(a.get("size") or 0)
        rel.sha256 = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""
    return rel


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": f"ModbusReader/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    })


def fetch_latest(repo: str = UPDATE_REPO, kind: str | None = None,
                 exe_name: str | None = None) -> Release | None:
    """The newest release IF it is newer than this copy, else None.
    Raises UpdateError when the question could not be answered."""
    kind = kind or install_kind()
    exe_name = exe_name or os.path.basename(sys.executable)
    try:
        with urllib.request.urlopen(
                _request(API_LATEST.format(repo=repo), "application/vnd.github+json"),
                timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 404: no published release yet — or the repository is private
        # (anonymous reads of a private repo look exactly like "not found").
        if e.code == 404:
            raise UpdateError("not_found", f"HTTP 404 · {repo}")
        if e.code in (403, 429):
            raise UpdateError("rate_limit", f"HTTP {e.code}")
        raise UpdateError("http", f"HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("offline", str(getattr(e, "reason", e)))
    except ValueError as e:
        raise UpdateError("bad_reply", str(e))
    rel = parse_release(data, kind, exe_name)
    return rel if rel is not None and is_newer(rel.version) else None


# ── download ───────────────────────────────────────────────────────
def downloads_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ModbusReader", "updates")


def _download_name(rel: Release) -> str:
    stem, ext = os.path.splitext(rel.asset_name or PORTABLE_ASSET)
    if rel.version not in stem:
        stem = f"{stem}-{rel.version}"
    return stem + (ext or ".exe")


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(rel: Release, dest_dir: str | None = None, progress=None,
             cancelled=None) -> str:
    """Fetch the release's build into *dest_dir*, verified; returns the path.

    *progress(done, total)* is called per chunk; *cancelled()* returning True
    stops the download. A finished, verified file from an earlier attempt is
    reused ("Later" yesterday, "Update" today costs nothing)."""
    if not rel.asset_url.startswith("https://github.com/"):
        raise UpdateError("no_build")
    if not re.fullmatch(r"[0-9a-f]{64}", rel.sha256 or ""):
        raise UpdateError("checksum", "no SHA-256 for the asset")
    dest_dir = dest_dir or downloads_dir()
    final = os.path.join(dest_dir, _download_name(rel))
    part = final + ".part"
    try:
        os.makedirs(dest_dir, exist_ok=True)
        if os.path.exists(final) and _sha256_of(final) == rel.sha256:
            if progress:
                progress(rel.size, rel.size)
            return final
    except OSError as e:
        raise UpdateError("disk", str(e))

    h = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(_request(rel.asset_url, "application/octet-stream"),
                                    timeout=TIMEOUT) as r, open(part, "wb") as f:
            if not r.geturl().startswith("https://"):
                raise UpdateError("bad_reply", "redirected off HTTPS")
            total = rel.size or int(r.headers.get("Content-Length") or 0)
            head = b""
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError("cancelled")
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                if len(head) < 2:
                    head += chunk[:2]
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        if rel.size and got != rel.size:
            raise UpdateError("size", f"{got} / {rel.size}")
        if h.hexdigest() != rel.sha256:
            raise UpdateError("checksum", "SHA-256 mismatch")
        if not head.startswith(b"MZ"):
            raise UpdateError("bad_reply", "not a Windows program")
        os.replace(part, final)
    except UpdateError:
        _remove(part)
        raise
    except urllib.error.HTTPError as e:
        _remove(part)
        raise UpdateError("http", f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError) as e:
        _remove(part)
        raise UpdateError("offline", str(getattr(e, "reason", e)))
    except OSError as e:
        _remove(part)
        raise UpdateError("disk", str(e))
    return final


def _remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def cleanup_downloads(dest_dir: str | None = None, current: str = APP_VERSION):
    """Delete downloaded builds this copy has already moved past (run at
    start-up: the update that was just installed is no longer needed)."""
    dest_dir = dest_dir or downloads_dir()
    try:
        names = os.listdir(dest_dir)
    except OSError:
        return
    cur = parse_version(current)
    for name in names:
        ver = parse_version(name)
        if name.endswith(".part") or (ver is not None and cur is not None and ver <= cur):
            _remove(os.path.join(dest_dir, name))


# ── hand-over ──────────────────────────────────────────────────────
FINISH_FLAG = "--finish-update"


def child_env() -> dict:
    """Environment for a program we start: no traces of this one-file
    bundle. An inherited _MEI path (Qt plugins, the bootloader's state) would
    send the child into the temp folder we are about to delete;
    PYINSTALLER_RESET_ENVIRONMENT makes a frozen child start from scratch."""
    mei = getattr(sys, "_MEIPASS", "") or ""
    env = {k: v for k, v in os.environ.items() if not (mei and mei in v)}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def start_detached(args: list[str]) -> subprocess.Popen:
    """Start *args* so that it outlives this process."""
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True, env=child_env())
    try:
        return subprocess.Popen(args, creationflags=flags | 0x01000000, **kw)
    except OSError:
        # 0x01000000 = CREATE_BREAKAWAY_FROM_JOB; refused when the job we run
        # in does not allow it — then a plain detached start.
        return subprocess.Popen(args, creationflags=flags, **kw)


def handover_args(kind: str, downloaded: str, target: str,
                  pids: list[int]) -> list[str]:
    """What to start right before this copy quits."""
    if kind == "installed":
        return [downloaded, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                "/SP-", f"/WAITPID={pids[0]}"]
    return [downloaded, FINISH_FLAG,
            "--wait", ",".join(str(int(p)) for p in pids),
            "--target", target]


def _parse_finish_args(argv: list[str]) -> tuple[list[int], str]:
    pids, target = [], ""
    for i, a in enumerate(argv):
        if a == "--wait" and i + 1 < len(argv):
            pids = [int(x) for x in argv[i + 1].split(",") if x.strip().isdigit()]
        elif a == "--target" and i + 1 < len(argv):
            target = argv[i + 1]
    return pids, target


def finish_update(argv: list[str], source: str | None = None,
                  relaunch: bool = True, retries: int = 60) -> int:
    """Second half of a portable update, run BY THE NEW EXE.

    Waits for the old copy to exit, puts *source* (this exe) beside the old
    one, renames it over the old one — retried while the old bootloader still
    holds the file — and starts the result. If the swap never succeeds the
    old exe is started anyway: a failed update never leaves the user without
    a working program. Returns the process exit code."""
    import shutil
    pids, target = _parse_finish_args(argv)
    source = source or sys.executable
    if not target or os.path.abspath(target) == os.path.abspath(source):
        return 2
    if not _wait_for_exit(pids, 120):
        return 3                           # old copy hung: touch nothing
    tmp = target + ".new"
    swapped = False
    try:
        shutil.copy2(source, tmp)
        for _ in range(retries):
            try:
                os.replace(tmp, target)
                swapped = True
                break
            except OSError:
                time.sleep(0.5)
    except OSError:
        pass
    if not swapped:
        _remove(tmp)
    if relaunch and os.path.exists(target):
        start_detached([target])
    return 0 if swapped else 1

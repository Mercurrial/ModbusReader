# updater.py
"""Self-update: find a newer release, download it, hand over to it.

Logic only — urllib and subprocess, no widgets (the dialog and the
check-on-start live in gui_update.py).

Where updates come from: the LATEST (not draft, not pre-release) GitHub
release of ``version.UPDATE_REPO``, read anonymously through the REST API —
so that repository must be public. A release carries the builds as assets:

    ModbusReader.exe              the one-file portable build
    ModbusReader_debug.exe        the same with a console (portable)
    ModbusReader-Setup-X.Y.Z.exe  the installer (per user, no admin rights)

A copy updates the way it was installed: a portable exe is replaced in
place, an installed copy runs the new installer silently. Every download is
checked against the SHA-256 GitHub computed for the asset when it was
uploaded (the ``digest`` field) — no checksum, no install.

Handing over: a running exe cannot overwrite itself.
  portable   the DOWNLOADED exe is started as ``--finish-update``: it waits
             for this copy's processes to exit, copies itself over the old
             exe and starts it (finish_update below — runs before any Qt).
  installed  the downloaded installer is started with /WAITPID=<pid>: its
             own [Code] waits for the app to exit, installs silently and its
             [Run] entry starts the app again.
No script interpreter on the way: a hidden PowerShell / cmd that sleeps,
deletes and relaunches is exactly what antivirus heuristics block (it was
refused intermittently on the development machine), and a .cmd file is read
in the OEM code page — a Cyrillic user name in the path would break it.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.version import APP_VERSION, UPDATE_REPO

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
def parse_version(text) -> tuple | None:
    """'v2.3.0' / '2.3' / 'ModbusReader 2.3.1' → (2, 3, 0) …; None if no number."""
    m = re.search(r"(\d+)(?:[._](\d+))?(?:[._](\d+))?", str(text or ""))
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def is_newer(remote, local=APP_VERSION) -> bool:
    r, cur = parse_version(remote), parse_version(local)
    return r is not None and cur is not None and r > cur


# ── what kind of copy is running ───────────────────────────────────
def install_kind() -> str:
    """"source" (python main.py), "installed" (put there by the installer)
    or "portable" (an exe someone copied somewhere)."""
    if not getattr(sys, "frozen", False):
        return "source"
    from app.settings_manager import is_installed_dir
    return ("installed" if is_installed_dir(os.path.dirname(sys.executable))
            else "portable")


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
    usable release at all (draft, pre-release, no version in the tag)."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    ver = parse_version(data.get("tag_name") or data.get("name"))
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


def _wait_for_exit(pids: list[int], timeout_s: float) -> bool:
    """True once every pid has exited (or never existed)."""
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    k32.WaitForSingleObject.restype = ctypes.c_uint32
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    ok = True
    for pid in pids:
        h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            continue                       # already gone
        try:
            if k32.WaitForSingleObject(h, int(timeout_s * 1000)) != 0:
                ok = False                 # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(h)
    return ok


def finish_update(argv: list[str], source: str | None = None,
                  relaunch: bool = True, retries: int = 60) -> int:
    """Second half of a portable update, run BY THE NEW EXE.

    Waits for the old copy to exit, puts *source* (this exe) beside the old
    one, renames it over the old one — retried while the old bootloader still
    holds the file — and starts the result. If the swap never succeeds the
    old exe is started anyway: a failed update never leaves the user without
    a working program. Returns the process exit code."""
    import shutil
    import time
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

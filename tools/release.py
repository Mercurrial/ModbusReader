# tools/release.py
"""Prepare a release: pick the version, write it everywhere it appears.

    python tools/release.py            # the next calendar version for today
    python tools/release.py 26.11.0    # an explicit one
    python tools/release.py --show     # current and next, change nothing

Versions are CALENDAR versions, YY.MM.N: 26.10.0 is the first release of
October 2026, 26.10.1 the next one that month, 26.11.0 the first in November.
The number says how fresh a copy is; it only ever grows (26.x > the 2.x of
the semantic-version era), which is all the updater compares.

Writes app/version.py (APP_VERSION, RELEASE_DATE) and the CHANGELOG: the
upcoming section "## [Не выпущено]" becomes "## [26.10.0] — 2026-10-16"
(re-running for the same version refreshes the date) and a link reference
"[26.10.0]: …/releases/tag/v26.10.0" is added at the bottom. A README
«Версия **X**» line, if present, is kept in step (the README normally shows a
release badge).
It does not commit, tag or publish — it prints those steps.
"""
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REPO_URL = "https://github.com/Mercurrial/ModbusReader"
UNRELEASED = "Не выпущено"
_VERSION_RE = re.compile(r"^\d{2}\.(?:[1-9]|1[0-2])\.\d+$")


def parse(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def next_version(current: str, today: datetime.date) -> str:
    """The first release of a month is YY.MM.0; each further one in the same
    month adds one to the last number."""
    yy, mm = today.year % 100, today.month
    cur = parse(current) if re.fullmatch(r"\d+\.\d+\.\d+", current) else (0, 0, 0)
    if cur[:2] == (yy, mm):
        return f"{yy}.{mm}.{cur[2] + 1}"
    return f"{yy}.{mm}.0"


def _sub_once(pattern: str, repl: str, text: str, what: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"release: could not find {what}")
    return new


def _write(path: str, text: str):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def apply(version: str, date: str, root: str = ROOT):
    p = os.path.join(root, "app", "version.py")
    s = open(p, encoding="utf-8").read()
    s = _sub_once(r'^APP_VERSION = ".*"$', f'APP_VERSION = "{version}"', s, "APP_VERSION")
    s = _sub_once(r'^RELEASE_DATE = ".*"$', f'RELEASE_DATE = "{date}"', s, "RELEASE_DATE")
    _write(p, s)

    p = os.path.join(root, "CHANGELOG.md")
    s = open(p, encoding="utf-8").read()
    head = re.compile(r"^## \[(?:" + re.escape(UNRELEASED) + "|" + re.escape(version)
                      + r")\](?: — \d{4}-\d{2}-\d{2})?[ \t]*$", re.M)
    if not head.search(s):
        sys.exit(f"release: CHANGELOG has no «## [{UNRELEASED}]» section to release")
    s = head.sub(f"## [{version}] — {date}", s, count=1)
    link = f"[{version}]: {REPO_URL}/releases/tag/v{version}"
    if link not in s:
        # Newest link first, right above the existing references.
        refs = re.search(r"^\[[^\]]+\]: ", s, re.M)
        if refs:
            s = s[:refs.start()] + link + "\n" + s[refs.start():]
        else:
            s = s.rstrip("\n") + "\n\n" + link + "\n"
    # "[Не выпущено]" compares against the newest release from now on.
    s = re.sub(r"^\[" + re.escape(UNRELEASED) + r"\]: .*$",
               f"[{UNRELEASED}]: {REPO_URL}/compare/v{version}...HEAD", s, flags=re.M)
    _write(p, s)

    # The README shows the version through a release badge; an explicit
    # «Версия **X**» line, if one is ever added back, is kept in step.
    p = os.path.join(root, "README.md")
    s = open(p, encoding="utf-8").read()
    new = re.sub(r"Версия \*\*[^*]+\*\*", f"Версия **{version}**", s, count=1)
    if new != s:
        _write(p, new)


def main():
    from app.version import APP_VERSION
    today = datetime.date.today()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    version = args[0] if args else next_version(APP_VERSION, today)
    if "--show" in sys.argv:
        print(f"current {APP_VERSION}, next {next_version(APP_VERSION, today)}")
        return
    if not _VERSION_RE.match(version):
        sys.exit(f"release: {version!r} is not YY.MM.N")
    if _VERSION_RE.match(APP_VERSION) and parse(version) < parse(APP_VERSION):
        sys.exit(f"release: {version} is older than {APP_VERSION}")
    apply(version, today.isoformat())
    print(f"ModbusReader {version} ({today.isoformat()}) written to app/version.py "
          "and CHANGELOG.md. Next:")
    print("  python -m pytest")
    print(f'  git commit -am "release: {version}"')
    print(f'  git tag -a v{version} -m "ModbusReader {version}"')
    print("  python tools/build_installer.py --portable")
    print(f"  gh release create v{version} dist/ModbusReader-Setup-{version}.exe "
          "dist/ModbusReader.exe dist/ModbusReader_debug.exe")


if __name__ == "__main__":
    main()

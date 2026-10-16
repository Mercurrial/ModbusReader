# version.py
"""Single source of the app version (shown in the rail brand + About)."""

APP_VERSION = "2.2.0"
RELEASE_DATE = "2026-10-15"

# Where updates come from: the GitHub repository whose LATEST release carries
# the builds (see updater.py). Read anonymously — it must be public.
UPDATE_REPO = "Mercurrial/ModbusReader"
SOURCE_URL = f"https://github.com/{UPDATE_REPO}"

# GNU GPL v3 or later (LICENSE). Not a free choice: PyQt6 is GPL-3.0-only and
# ships inside every build. THIRD_PARTY_LICENSES.md lists the rest.
LICENSE_ID = "GPL-3.0-or-later"

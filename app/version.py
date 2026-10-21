# app/version.py
"""Single source of the app version (shown in the rail brand + About).

Calendar versions, YY.MM.N — set by tools/release.py, not by hand."""

APP_VERSION = "26.10.2"
RELEASE_DATE = "2026-10-21"

# Where updates come from: the GitHub repository whose LATEST release carries
# the builds (see updater.py). Read anonymously — it must be public.
UPDATE_REPO = "Mercurrial/ModbusReader"
SOURCE_URL = f"https://github.com/{UPDATE_REPO}"

# GNU GPL v3 or later (LICENSE). Not a free choice: PyQt6 is GPL-3.0-only and
# ships inside every build. THIRD_PARTY_LICENSES.md lists the rest.
LICENSE_ID = "GPL-3.0-or-later"

# Voluntary support (DonationAlerts). Shown in README, the GitHub «Sponsor»
# button (.github/FUNDING.yml) and one row in About — nowhere else.
DONATE_URL = "https://dalink.to/mercurrial"

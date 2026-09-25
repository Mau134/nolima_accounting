"""Application-wide configuration: branding, paths and constants."""
import os
import sys
from pathlib import Path

from . import __version__

APP_NAME = "Nolima Accounting"
VERSION = __version__
VENDOR = "Nolima Tech Consultants"
VENDOR_PHONE = "099 025 2341"
VENDOR_EMAIL = "info@nolima.mw"

# GitHub repository checked for updates (owner/repo). Releases tagged vX.Y.Z.
UPDATE_REPO = "Mau134/nolima-accounting"
# Optional: full URL of update.json on your own website (its signature must be at the same URL + ".sig").
# Leave as None to use the latest GitHub release of UPDATE_REPO.
UPDATE_FEED_URL = None
UPDATE_CHECK_HOURS = 6

# Brand colours (shared with Nolima Store)
NAVY = "#0F2A47"
NAVY_2 = "#16365A"
NAVY_3 = "#1E4470"
EMERALD = "#1B7F5C"
EMERALD_2 = "#22986E"
BG = "#F2F6F9"
CARD = "#FFFFFF"
LINE = "#D8E0E8"
TEXT = "#0F2A47"
MUTED = "#5B6B7C"
DANGER = "#B42318"
WARNING = "#B54708"


def resource_path(*parts) -> Path:
    """Locate bundled resources both in source and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def data_dir() -> Path:
    override = os.environ.get("NOLIMA_ACC_DATA")
    if override:
        d = Path(override)
    elif os.name == "nt":
        root = Path(os.environ.get("PROGRAMDATA") or os.environ.get("APPDATA") or Path.home())
        d = root / "NolimaAccounting"
    else:
        d = Path.home() / ".nolima_accounting"
    try:
        for sub in ("companies", "backups", "exports"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        # e.g. ProgramData not writable when the app was copied without the installer
        d = Path(os.environ.get("APPDATA") or Path.home()) / "NolimaAccounting"
        for sub in ("companies", "backups", "exports"):
            (d / sub).mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_COMPANY_FILE = "company.nacc"

# Pre-filled in the company set-up screen; the app asks for a new password on first sign-in.
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

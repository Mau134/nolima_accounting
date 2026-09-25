"""Remote updates.

Nolima publishes three files on a GitHub release (or any web server):

    NolimaAccounting-Setup-x.y.z.exe   the installer
    update.json                        what the new version is, where the installer is, its SHA-256
    update.json.sig                    Ed25519 signature of update.json (made with the licence signing key)

The program checks the feed, verifies the signature with the public key it already carries for
licences, downloads the installer, checks its SHA-256 and runs it silently. A tampered manifest or
installer is refused, so only updates you signed can ever be installed on a customer's computer.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import config as C

MANIFEST = "update.json"
SIGNATURE = "update.json.sig"
APP_ID = "NolimaAccounting"


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    size: int
    notes: str
    mandatory: bool
    published: str


def vtuple(v: str):
    parts = []
    for p in str(v).lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def _get(url, timeout=15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"NolimaAccounting/{C.VERSION}",
                                               "Accept": "application/octet-stream, application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as exc:
        raise UpdateError(f"Could not reach the update server ({exc}).") from exc


def _feed():
    """Return the (manifest_url, signature_url) pair."""
    if C.UPDATE_FEED_URL:
        return C.UPDATE_FEED_URL, C.UPDATE_FEED_URL + ".sig"
    data = json.loads(_get(f"https://api.github.com/repos/{C.UPDATE_REPO}/releases/latest").decode())
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    if MANIFEST not in assets or SIGNATURE not in assets:
        raise UpdateError("The latest release has no signed update manifest.")
    return assets[MANIFEST], assets[SIGNATURE]


def verify_manifest(manifest: bytes, signature: bytes) -> dict:
    from .licensing import _public_key
    pub = _public_key()
    if pub is None:
        raise UpdateError("This copy has no verification key, so updates cannot be checked.")
    try:
        pub.verify(bytes.fromhex(signature.decode().strip()), manifest)
    except Exception:
        raise UpdateError("The update is not signed by Nolima Tech Consultants and was refused.")
    data = json.loads(manifest.decode())
    if data.get("app") != APP_ID:
        raise UpdateError("The update manifest is for a different program.")
    return data


def check() -> UpdateInfo | None:
    """Newer signed version available -> UpdateInfo, up to date -> None. Raises UpdateError."""
    m_url, s_url = _feed()
    data = verify_manifest(_get(m_url), _get(s_url))
    if vtuple(data["version"]) <= vtuple(C.VERSION):
        return None
    return UpdateInfo(data["version"], data["url"], data["sha256"].lower(), int(data.get("size", 0)),
                      data.get("notes", ""), bool(data.get("mandatory", False)), data.get("published", ""))


def download(info: UpdateInfo, progress=None, cancelled=lambda: False) -> Path:
    """Download the installer to a temp folder and verify its SHA-256. progress(done, total)."""
    target = Path(tempfile.gettempdir()) / f"NolimaAccounting-Setup-{info.version}.exe"
    req = urllib.request.Request(info.url, headers={"User-Agent": f"NolimaAccounting/{C.VERSION}"})
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(target, "wb") as out:
            total = int(r.headers.get("Content-Length") or info.size or 0)
            done = 0
            while True:
                if cancelled():
                    raise UpdateError("Download cancelled.")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Download failed ({exc}).") from exc
    if h.hexdigest() != info.sha256:
        target.unlink(missing_ok=True)
        raise UpdateError("The downloaded installer failed its security check and was deleted.")
    return target


def can_self_install() -> bool:
    return os.name == "nt" and getattr(sys, "frozen", False)


def install(installer: Path):
    """Start the silent installer; the caller must then close the program."""
    if not can_self_install():
        raise UpdateError("Automatic installation only works in the installed Windows program.\n"
                          f"The installer was saved to:\n{installer}")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)

"""Licence keys for Nolima Accounting.

Key layout (before signing), 20 bytes, big-endian:
    version  u8   (1)
    plan     u8   (plan code from plans.PLANS)
    users    u16  (0 = unlimited)
    issued   u16  (days since 2020-01-01)
    expires  u16  (days since 2020-01-01; licence valid through this day)
    serial   u32  (licence number issued by the generator)
    machine  8 bytes (machine fingerprint)
followed by a 64-byte Ed25519 signature. The 84 bytes are base32 encoded and
grouped as NOLIMA-XXXXX-XXXXX-...

Only Nolima holds the private key (in the licence generator), so keys cannot
be forged or edited; the public key in license_pubkey.py verifies them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import platform
import struct
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import plans

EPOCH = date(2020, 1, 1)
PAYLOAD_FMT = ">BBHHHI8s"
PAYLOAD_LEN = struct.calcsize(PAYLOAD_FMT)  # 20
SIG_LEN = 64
PREFIX = "NOLIMA"


class LicenseError(Exception):
    pass


def _dev_override(name: str):
    """Test/demo overrides are honoured only when running from source, never in the installed program."""
    if getattr(sys, "frozen", False):
        return None
    return os.environ.get(name) or None


# ---------------------------------------------------------------- machine id
def _windows_machine_guid() -> str | None:
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                             0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(val)
    except Exception:
        return None


def _linux_machine_id() -> str | None:
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            v = Path(p).read_text().strip()
            if v:
                return v
        except Exception:
            pass
    return None


def _mac_serial() -> str | None:
    try:
        out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                             capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except Exception:
        pass
    return None


def machine_fingerprint() -> bytes:
    """8 stable bytes identifying this computer."""
    override = _dev_override("NOLIMA_MACHINE_ID")
    if override:
        raw = override
    else:
        system = platform.system()
        raw = None
        if system == "Windows":
            raw = _windows_machine_guid()
        elif system == "Linux":
            raw = _linux_machine_id()
        elif system == "Darwin":
            raw = _mac_serial()
        if not raw:
            raw = f"mac:{uuid.getnode():012x}"
    return hashlib.sha256(("nolima-acc|" + raw).encode()).digest()[:8]


def format_machine_id(fp: bytes) -> str:
    h = fp.hex().upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def parse_machine_id(text: str) -> bytes:
    h = text.replace("-", "").replace(" ", "").strip()
    if len(h) != 16:
        raise LicenseError("Machine ID must be 16 hexadecimal characters (XXXX-XXXX-XXXX-XXXX).")
    try:
        return bytes.fromhex(h)
    except ValueError as exc:
        raise LicenseError("Machine ID contains invalid characters.") from exc


def this_machine_id() -> str:
    return format_machine_id(machine_fingerprint())


# ---------------------------------------------------------------- key codec
def _d2n(d: date) -> int:
    return (d - EPOCH).days


def _n2d(n: int) -> date:
    return EPOCH + timedelta(days=n)


@dataclass
class LicenseInfo:
    plan_key: str
    plan_name: str
    users: int
    issued: date
    expires: date
    serial: int
    machine: bytes
    modules: list = field(default_factory=list)

    @property
    def users_label(self) -> str:
        return "Unlimited" if self.users == 0 else str(self.users)

    def to_dict(self):
        return {"plan": self.plan_key, "users": self.users, "issued": self.issued.isoformat(),
                "expires": self.expires.isoformat(), "serial": self.serial,
                "machine": format_machine_id(self.machine)}


def build_payload(plan_code: int, users: int, issued: date, expires: date,
                  serial: int, machine: bytes) -> bytes:
    return struct.pack(PAYLOAD_FMT, 1, plan_code, users, _d2n(issued), _d2n(expires), serial, machine)


def encode_key(payload: bytes, signature: bytes) -> str:
    b32 = base64.b32encode(payload + signature).decode().rstrip("=")
    groups = [b32[i:i + 5] for i in range(0, len(b32), 5)]
    return PREFIX + "-" + "-".join(groups)


def decode_key(key: str) -> tuple[bytes, bytes]:
    text = "".join(key.split()).upper()
    if text.startswith(PREFIX):
        text = text[len(PREFIX):]
    text = text.replace("-", "")
    text += "=" * (-len(text) % 8)
    try:
        raw = base64.b32decode(text)
    except Exception as exc:
        raise LicenseError("This is not a valid Nolima licence key.") from exc
    if len(raw) != PAYLOAD_LEN + SIG_LEN:
        raise LicenseError("Licence key is incomplete. Copy the whole key including all groups.")
    return raw[:PAYLOAD_LEN], raw[PAYLOAD_LEN:]


def parse_payload(payload: bytes) -> LicenseInfo:
    ver, plan_code, users, iss, exp, serial, machine = struct.unpack(PAYLOAD_FMT, payload)
    if ver != 1:
        raise LicenseError("Unsupported licence version. Please update Nolima Accounting.")
    key, plan = plans.plan_by_code(plan_code)
    if not plan:
        raise LicenseError("Licence refers to an unknown package.")
    return LicenseInfo(key, plan["name"], users, _n2d(iss), _n2d(exp), serial, machine,
                       list(plan["modules"]))


def _public_key():
    from . import license_pubkey
    hexkey = _dev_override("NOLIMA_PUBKEY_HEX") or license_pubkey.PUBLIC_KEY_HEX
    if not hexkey:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hexkey))


def verify_key(key: str, machine: bytes | None = None) -> LicenseInfo:
    payload, sig = decode_key(key)
    pub = _public_key()
    if pub is None:
        raise LicenseError("This copy of Nolima Accounting has no verification key. "
                           "Contact Nolima Tech Consultants.")
    try:
        pub.verify(sig, payload)
    except Exception as exc:
        raise LicenseError("Licence key signature is invalid. Check for typing mistakes.") from exc
    info = parse_payload(payload)
    machine = machine if machine is not None else machine_fingerprint()
    if info.machine != machine:
        raise LicenseError(
            f"This licence belongs to another computer (Machine ID {format_machine_id(info.machine)}). "
            f"This computer's Machine ID is {format_machine_id(machine)}.")
    return info


# ---------------------------------------------------------------- status
ACTIVE, REMINDER, GRACE, READONLY, TRIAL, NONE = "active", "reminder", "grace", "readonly", "trial", "none"


@dataclass
class LicenseStatus:
    state: str
    info: LicenseInfo | None
    days_left: int
    message: str
    modules: list
    max_users: int

    @property
    def writable(self) -> bool:
        return self.state in (ACTIVE, REMINDER, GRACE, TRIAL)

    def has(self, module: str) -> bool:
        return module in self.modules


class LicenseManager:
    """Stores the active key and trial start, and computes licence status."""

    def __init__(self, store_dir: Path):
        self.path = Path(store_dir) / "licence.json"
        self._data = self._load()

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    # clock-tamper protection: remember the latest date ever seen
    def _today(self, today: date | None) -> tuple[date, bool]:
        today = today or date.today()
        seen = self._data.get("last_seen")
        tampered = False
        if seen:
            seen_d = date.fromisoformat(seen)
            if today < seen_d - timedelta(days=2):
                tampered = True
            if today > seen_d:
                self._data["last_seen"] = today.isoformat()
                self._save()
        else:
            self._data["last_seen"] = today.isoformat()
            self._save()
        return today, tampered

    def install(self, key: str, today: date | None = None) -> LicenseInfo:
        info = verify_key(key)
        today = today or date.today()
        if info.expires < today - timedelta(days=plans.GRACE_DAYS):
            raise LicenseError(f"This key expired on {info.expires:%d %b %Y}. Ask Nolima for a renewal key.")
        current = self.current_info()
        if current and info.expires < current.expires:
            raise LicenseError(f"The installed licence already runs to {current.expires:%d %b %Y}, "
                               "later than this key.")
        self._data["key"] = "".join(key.split())
        history = self._data.setdefault("history", [])
        history.append({"serial": info.serial, "expires": info.expires.isoformat(),
                        "installed": today.isoformat()})
        self._save()
        return info

    def current_key(self) -> str | None:
        return self._data.get("key")

    def current_info(self) -> LicenseInfo | None:
        key = self._data.get("key")
        if not key:
            return None
        try:
            return verify_key(key)
        except LicenseError:
            return None

    def start_trial(self, today: date | None = None):
        if "trial_start" not in self._data:
            self._data["trial_start"] = (today or date.today()).isoformat()
            self._save()

    def status(self, today: date | None = None) -> LicenseStatus:
        today, tampered = self._today(today)
        if tampered:
            return LicenseStatus(READONLY, self.current_info(), 0,
                                 "The computer date appears to have been set back. Correct the date and time "
                                 "to continue working.", ["core"], 1)
        key = self._data.get("key")
        if key:
            try:
                info = verify_key(key)
            except LicenseError as exc:
                return LicenseStatus(READONLY, None, 0, str(exc), ["core"], 1)
            days = (info.expires - today).days
            mods, users = info.modules, info.users
            if days < -plans.GRACE_DAYS:
                return LicenseStatus(READONLY, info, days,
                                     f"Your licence expired on {info.expires:%d %b %Y}. Nolima Accounting is in "
                                     "read-only mode: you can view and print, but not post. Enter a renewal key "
                                     "to continue.", mods, users)
            if days < 0:
                left = plans.GRACE_DAYS + days
                return LicenseStatus(GRACE, info, days,
                                     f"Your licence expired on {info.expires:%d %b %Y}. {left} grace day(s) left "
                                     "before read-only mode.", mods, users)
            if days <= plans.REMINDER_DAYS:
                return LicenseStatus(REMINDER, info, days,
                                     f"Your {info.plan_name} licence expires in {days} day(s), on "
                                     f"{info.expires:%d %b %Y}. Renew to avoid interruption.", mods, users)
            return LicenseStatus(ACTIVE, info, days,
                                 f"{info.plan_name} licence active until {info.expires:%d %b %Y}.", mods, users)
        # trial
        start = self._data.get("trial_start")
        if start:
            left = plans.TRIAL_DAYS - (today - date.fromisoformat(start)).days
            biz = plans.PLANS["business"]
            if left >= 0:
                return LicenseStatus(TRIAL, None, left,
                                     f"Trial version: {left} day(s) left. Contact Nolima to buy a licence.",
                                     list(biz["modules"]), biz["users"])
            return LicenseStatus(READONLY, None, left,
                                 "The trial period has ended. Enter a licence key to continue posting.",
                                 list(biz["modules"]), 1)
        return LicenseStatus(NONE, None, 0, "No licence installed.", ["core"], 1)

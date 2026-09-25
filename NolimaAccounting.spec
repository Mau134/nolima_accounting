# PyInstaller build specification for Nolima Accounting.
# Build:  python -m PyInstaller --noconfirm --clean NolimaAccounting.spec
# Output: dist/NolimaAccounting/NolimaAccounting.exe (folder build: starts fast, easy to update)
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "nolima_acc" / "__init__.py").read_text()).group(1)

version_file = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple(int(x) for x in (VERSION.split(".") + ["0"] * 4)[:4])
    version_file = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Nolima Tech Consultants"),
            StringStruct("FileDescription", "Nolima Accounting"),
            StringStruct("FileVersion", VERSION),
            StringStruct("ProductName", "Nolima Accounting"),
            StringStruct("ProductVersion", VERSION),
            StringStruct("LegalCopyright", "(c) Nolima Tech Consultants"),
            StringStruct("OriginalFilename", "NolimaAccounting.exe")])]),
              VarFileInfo([VarStruct("Translation", [1033, 1200])])])

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=["cryptography.hazmat.primitives.asymmetric.ed25519", "PIL._tkinter_finder"]
    + (["winreg"] if sys.platform == "win32" else []),
    # the licence generator and its private key must never be packaged
    excludes=["license_generator", "nolima_license_generator", "pytest", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="NolimaAccounting",
    icon=str(ROOT / "assets" / "nolima.ico"),
    version=version_file,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="NolimaAccounting", upx=False)

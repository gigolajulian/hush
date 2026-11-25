"""Builds dist\\Hush.exe (Windows, one file, no console). Run with the venv Python after: pip install pyinstaller
install.ps1 runs this for you."""
import re
from pathlib import Path

import PyInstaller.__main__
from PIL import Image

root = Path(__file__).resolve().parent.parent
build = root / "build"
build.mkdir(exist_ok=True)
version = re.search(r'^VERSION = "([^"]+)"', (root / "hush.py").read_text(encoding="utf-8"), re.M)[1]
nums = ", ".join((version.split(".") + ["0"] * 4)[:4])

Image.open(root / "assets" / "icon.png").save(build / "hush.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
# FileDescription is the name Task Manager and the tray settings show
(build / "version.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums})),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Julian Gigola'),
    StringStruct('FileDescription', 'Hush'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('InternalName', 'Hush'),
    StringStruct('OriginalFilename', 'Hush.exe'),
    StringStruct('ProductName', 'Hush'),
    StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")

PyInstaller.__main__.run([
    str(root / "hush.py"), "--name", "Hush", "--onefile", "--windowed", "--noconfirm", "--clean",
    "--icon", str(build / "hush.ico"), "--version-file", str(build / "version.txt"),
    "--hidden-import", "pystray._win32",  # pystray picks its backend at runtime
    "--distpath", str(root / "dist"), "--workpath", str(build), "--specpath", str(build),
])

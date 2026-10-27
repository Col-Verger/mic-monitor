# -*- coding: utf-8 -*-
"""Генерирует файл версии для PyInstaller из строки версии.

    python tools/make_version_info.py 1.2.0 build/version_info.txt
"""

import sys
from pathlib import Path

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tuple4},
    prodvers={tuple4},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'mic-monitor contributors'),
            StringStruct('FileDescription', 'mic-monitor — оверлей громкости микрофона'),
            StringStruct('FileVersion', '{version}.0'),
            StringStruct('InternalName', 'MicMonitor'),
            StringStruct('LegalCopyright', 'MIT License'),
            StringStruct('OriginalFilename', 'MicMonitor.exe'),
            StringStruct('ProductName', 'MicMonitor'),
            StringStruct('ProductVersion', '{version}.0')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv: list[str]) -> int:
    version = (argv[1] if len(argv) > 1 else "1.0.0").lstrip("v")
    out = Path(argv[2] if len(argv) > 2 else "build/version_info.txt")

    parts = [int(p) for p in version.split(".")][:4]
    while len(parts) < 4:
        parts.append(0)
    tuple4 = "(" + ", ".join(str(p) for p in parts) + ")"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.format(tuple4=tuple4, version=version), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

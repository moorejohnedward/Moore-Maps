"""Writes version_info.txt (the version shown in the .exe's Properties > Details) from mooremaps/__init__.py."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
src = open(os.path.join(ROOT, "mooremaps", "__init__.py"), encoding="utf-8").read()
ver = re.search(r'__version__\s*=\s*"([^"]+)"', src).group(1)
parts = [int(x) for x in ver.split(".")] + [0] * 4
a, b, c, d = parts[:4]
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, {d}), prodvers=({a}, {b}, {c}, {d}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'John Moore'),
      StringStruct('FileDescription', 'Moore Maps - picture to topographic training map'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'MooreMaps'),
      StringStruct('OriginalFilename', 'MooreMaps.exe'),
      StringStruct('ProductName', 'Moore Maps'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
open(os.path.join(ROOT, "version_info.txt"), "w", encoding="utf-8").write(text)
print("version_info.txt ->", ver)

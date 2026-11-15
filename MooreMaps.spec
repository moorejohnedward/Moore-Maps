# PyInstaller recipe for one self-contained MooreMaps.exe
# Build:  pyinstaller --noconfirm MooreMaps.spec   (or just run Build-Exe.bat)
from PyInstaller.utils.hooks import collect_data_files

datas = [("assets/app.ico", "assets"), ("assets/logo.png", "assets")]
datas += collect_data_files("sv_ttk")

a = Analysis(
    ["MooreMaps.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=[],
    excludes=["scipy", "pandas", "IPython", "PyQt5", "PyQt6", "PySide2", "PySide6",
              "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_qt5agg",
              "matplotlib.backends.backend_wx", "matplotlib.backends.backend_gtk3agg",
              "pytest", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MooreMaps",
    icon="assets/app.ico",
    console=False,          # a normal window app, no black console box
    upx=False,
    version="version_info.txt",
)

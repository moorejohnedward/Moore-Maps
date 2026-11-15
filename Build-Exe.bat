@echo off
title Building Moore Maps
cd /d "%~dp0"
echo Building Moore Maps (single .exe)...
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python isn't installed. Get Python 3.12 from python.org ^(tick "Add python.exe to PATH"^),
  echo or skip building: download MooreMaps.exe from the project's GitHub Releases page.
  pause
  exit /b 1
)
python -m pip install --upgrade -r requirements.txt pyinstaller
python tools\write_version_info.py
python -m PyInstaller --noconfirm --distpath "Release (app to run and share)" MooreMaps.spec
if errorlevel 1 (
  echo.
  echo Build failed. Scroll up to see the error.
  pause
  exit /b 1
)
echo.
echo Done! Your app is in "Release (app to run and share)\MooreMaps.exe"
start "" "Release (app to run and share)"
pause

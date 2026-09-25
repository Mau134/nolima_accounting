@echo off
REM Opens the Nolima Licence Generator (run build\build_windows.bat once first).
cd /d "%~dp0"
if not exist .buildenv\Scripts\pythonw.exe (
  echo Run build\build_windows.bat once first - it installs what the generator needs.
  pause
  exit /b 1
)
start "" .buildenv\Scripts\pythonw.exe license_generator\nolima_license_generator.py

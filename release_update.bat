@echo off
setlocal
REM ==========================================================================
REM  Publish a remote update to every Nolima Accounting customer.
REM  1. Raise __version__ in nolima_acc\__init__.py (e.g. 1.0.1) and write
REM     what changed in release_notes.txt
REM  2. Double-click this file.
REM  Needs: GitHub CLI (https://cli.github.com) signed in with  gh auth login
REM ==========================================================================
cd /d "%~dp0"
call build\build_windows.bat nopause || (echo Build failed. & pause & exit /b 1)
set BPY=.buildenv\Scripts\python.exe
for /f "delims=" %%v in ('%BPY% -c "import nolima_acc; print(nolima_acc.__version__)"') do set APPVER=%%v
set SETUP=Output\NolimaAccounting-Setup-%APPVER%.exe
if not exist "%SETUP%" (echo %SETUP% not found - is Inno Setup installed? & pause & exit /b 1)
if not exist release_notes.txt echo Improvements and fixes.> release_notes.txt

set MAND=
choice /c YN /n /m "Make this update REQUIRED (customers cannot postpone it)? [Y/N] "
if errorlevel 2 (set MAND=) else (set MAND=--mandatory)

echo Signing update %APPVER%...
%BPY% license_generator\nolima_license_generator.py sign-update "%SETUP%" --version %APPVER% --notes-file release_notes.txt %MAND% || (pause & exit /b 1)

where gh >nul 2>nul
if errorlevel 1 (
  echo.
  echo  GitHub CLI not found. Publish manually: on github.com open your repository, Releases,
  echo  "Draft a new release", tag v%APPVER%, and attach these three files from the Output folder:
  echo     NolimaAccounting-Setup-%APPVER%.exe   update.json   update.json.sig
  explorer Output
  pause & exit /b 0
)
gh release create v%APPVER% "%SETUP%" Output\update.json Output\update.json.sig --title "Nolima Accounting %APPVER%" --notes-file release_notes.txt || (pause & exit /b 1)
echo.
echo  PUBLISHED. Customers' copies will offer version %APPVER% within 6 hours, or at next start.
pause

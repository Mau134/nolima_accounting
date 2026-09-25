@echo off
setlocal
REM ==========================================================================
REM  Nolima Accounting - Windows build. Double-click this file.
REM  Result: Output\NolimaAccounting-Setup-<version>.exe  - copy it to any PC.
REM ==========================================================================
cd /d "%~dp0.."
echo.
echo  NOLIMA ACCOUNTING - BUILD
echo  Project folder: %CD%
echo.

REM ---- 1. Python ------------------------------------------------------------
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" (
  echo  Python is not installed. Install Python 3.12 from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" on the first screen of the installer.
  goto :fail
)

REM ---- 2. Build environment with all packages ------------------------------
if not exist .buildenv\Scripts\python.exe (
  echo [1/5] Creating build environment...
  %PY% -m venv .buildenv || goto :fail
)
set BPY=.buildenv\Scripts\python.exe
echo [2/5] Installing packages (first time takes a few minutes)...
%BPY% -m pip install --upgrade pip --quiet
%BPY% -m pip install -r requirements.txt --quiet || (echo  Package install failed - check the internet connection. & goto :fail)

REM ---- 3. Licence signing key ----------------------------------------------
%BPY% -c "from nolima_acc import license_pubkey as k; import sys; sys.exit(0 if k.PUBLIC_KEY_HEX else 1)"
if errorlevel 1 (
  echo [3/5] Creating your licence signing key...
  %BPY% license_generator\nolima_license_generator.py init || goto :fail
  echo.
  echo  IMPORTANT: back up the folder %USERPROFILE%\NolimaLicenseVault
  echo  to a flash disk and the cloud. Without it you cannot renew customers.
  echo.
) else (
  echo [3/5] Licence key found.
)

for /f "delims=" %%v in ('%BPY% -c "import nolima_acc; print(nolima_acc.__version__)"') do set APPVER=%%v
echo       Version %APPVER%

REM ---- 4. Tests and packaging ----------------------------------------------
echo [4/5] Testing and packaging...
%BPY% tests\test_core.py || (echo  Tests failed - build stopped. & goto :fail)
%BPY% -m PyInstaller --noconfirm --clean --log-level WARN --workpath .pyibuild NolimaAccounting.spec || goto :fail

REM ---- 5. Installer ---------------------------------------------------------
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo.
  echo  The program is built in dist\NolimaAccounting\ but Inno Setup 6 is not installed,
  echo  so there is no Setup.exe yet. Install it from https://jrsoftware.org/isdl.php
  echo  and run this file again.
  set BUILD_FAILED=1
  goto :end
)
echo [5/5] Building installer...
"%ISCC%" /Q /DAppVersion=%APPVER% build\installer.iss || goto :fail
echo.
echo  SUCCESS:  %CD%\Output\NolimaAccounting-Setup-%APPVER%.exe
if /i not "%~1"=="nopause" explorer Output
goto :end

:fail
set BUILD_FAILED=1
echo.
echo  BUILD FAILED. Take a screenshot of this window and send it to Claude.
:end
echo.
if /i not "%~1"=="nopause" pause
if defined BUILD_FAILED exit /b 1
exit /b 0

@echo off
rem CodeLock launcher.
rem Usage:
rem   run_codelock.bat                 normal mode
rem   run_codelock.bat --dry-run       safe demo; nothing is blocked
rem   run_codelock.bat --self-test     offline checks
rem   run_codelock.bat --self-test-ui  GUI smoke test
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_CMD="
if exist ".venv\Scripts\python.exe" set "PYTHON_CMD="%CD%\.venv\Scripts\python.exe""
if not defined PYTHON_CMD if exist ".venv\bin\python.exe" set "PYTHON_CMD="%CD%\.venv\bin\python.exe""
if not defined PYTHON_CMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo.
    echo ERROR: Python 3 was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
    echo Select "Add python.exe to PATH" during installation, then run:
    echo     py -3 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

%PYTHON_CMD% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Tkinter could not be loaded with this Python installation.
    echo Use the standard python.org Windows build, which includes Tkinter.
    echo Current Python: %PYTHON_CMD%
    echo.
    pause
    exit /b 1
)

%PYTHON_CMD% -c "import pypdf" >nul 2>nul
if errorlevel 1 (
    echo NOTE: pypdf is not installed. TXT and DOCX syllabus uploads still work;
    echo       PDF uploads will show a clear missing-dependency message.
    echo       Install it with: %PYTHON_CMD% -m pip install pypdf
    echo.
)

echo Starting CodeLock from %CD%
echo Python: %PYTHON_CMD%
echo.
%PYTHON_CMD% main.py %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo CodeLock exited with code %EXITCODE%.
    echo If the window did not open, run: %PYTHON_CMD% main.py --self-test
    echo.
    pause
)
exit /b %EXITCODE%

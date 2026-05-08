@echo off
REM Launcher for Windows.
REM Double-click to launch the SUPS transcription app.
REM On first launch it creates a virtualenv and installs requirements.

setlocal
cd /d "%~dp0"

set "PYTHON=python"
set "VENV_DIR=.venv"

where %PYTHON% >nul 2>&1
if errorlevel 1 (
    echo Loi: khong tim thay Python. Hay cai Python 3.9+ tu https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "%VENV_DIR%" (
    echo [setup] Tao virtualenv tai %VENV_DIR% ...
    %PYTHON% -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"

if not exist "%VENV_DIR%\.deps_installed" (
    echo [setup] Cai dat thu vien (chi chay lan dau)...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Loi khi cai dat thu vien.
        pause
        exit /b 1
    )
    type nul > "%VENV_DIR%\.deps_installed"
)

echo [run] Khoi dong ung dung...
python app.py %*
endlocal

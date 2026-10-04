@echo off
REM Server launcher dev launcher. Creates .venv_launcher on first run and
REM installs this project into it in editable mode.
REM
REM Tkinter GUI, not a server - deliberately has no LABEL/DESCRIPTION so it
REM never lists itself (discovery also skips its own folder).
cd /d "%~dp0"

if not exist ".venv_launcher\Scripts\python.exe" (
    echo Creating virtual environment .venv_launcher ...
    py -m venv .venv_launcher
    call .venv_launcher\Scripts\activate
    echo Installing server_launcher in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_launcher\Scripts\activate
)

py -m src.run

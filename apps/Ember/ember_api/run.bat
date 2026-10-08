@echo off
REM ember_api dev launcher. Creates .venv_ember_api on first run and installs
REM this project into it in editable mode.
REM
REM LABEL: Ember API
REM DESCRIPTION: FastAPI backend for ember_web: accounts, login sessions and roles/permissions.
cd /d "%~dp0"

if not defined EMBER_API_PORT set EMBER_API_PORT=8030

if not exist ".venv_ember_api\Scripts\python.exe" (
    echo Creating virtual environment .venv_ember_api ...
    py -m venv .venv_ember_api
    call .venv_ember_api\Scripts\activate
    echo Installing ember_api in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_ember_api\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  ember_api stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

@echo off
REM mini_games dev launcher - serves the game backend (Emberlings) over HTTP on the
REM port in configs\config_app.json (8060 by default).
REM LABEL: Mini Games
REM DESCRIPTION: Game backend for Ember (Emberlings: collect and battle Ascended). Battle engine, Laya-assisted AI and saved progress. No LLM, no billing.

cd /d "%~dp0"

if not exist ".venv_mini_games\Scripts\python.exe" (
    echo Creating virtual environment .venv_mini_games ...
    py -m venv .venv_mini_games
    call .venv_mini_games\Scripts\activate
    echo Installing mini_games in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_mini_games\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  mini_games stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

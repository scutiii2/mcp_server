@echo off
REM chat_cli launcher. Creates .venv_chat_cli on first run and installs this
REM project into it in editable mode. Arguments are passed on:
REM   run.bat --user ada --agent claude-agent
REM An interactive terminal chat, not a server, so it is not in server_launcher.
cd /d "%~dp0"

if not exist ".venv_chat_cli\Scripts\python.exe" (
    echo Creating virtual environment .venv_chat_cli ...
    py -m venv .venv_chat_cli
    call .venv_chat_cli\Scripts\activate
    echo Installing chat_cli in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_chat_cli\Scripts\activate
)

py -m src.main %*

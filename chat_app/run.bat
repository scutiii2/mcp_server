@echo off
REM chat_app dev launcher. Creates .venv_chat on first run and installs
REM this project into it in editable mode.
REM
REM Extra args (e.g. --mcp-url http://127.0.0.1:8010/mcp) pass straight
REM through to src.run - see its --help.
REM
REM LABEL: Chat App
REM DESCRIPTION: Flask chat UI with MCP tool-calling, network-level security, and an LLM chat interface backed by ai_agent instances.
cd /d "%~dp0"

if not exist ".venv_chat\Scripts\python.exe" (
    echo Creating virtual environment .venv_chat ...
    py -m venv .venv_chat
    call .venv_chat\Scripts\activate
    echo Installing chat_app in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_chat\Scripts\activate
)

:run
py -m src.run %*

echo.
echo ----------------------------------------
echo  chat_app stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

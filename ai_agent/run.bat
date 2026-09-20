@echo off
REM ai_agent dev launcher - default instance (anthropic, port 9100).
REM Replaces the old run_ai_agent_anthropic.bat/run_ai_agent_openai.bat
REM pair: to run a second instance on a different provider/port at the
REM same time, override the env vars before calling this, e.g.:
REM   set AI_AGENT_PROVIDER=openai
REM   set AI_AGENT_PORT=9101
REM   run.bat
REM (server_launcher's per-instance flag editor does exactly this.)
REM
REM Extra args (e.g. --gateway openrouter) pass straight through to
REM src.server - see its --help.
REM
REM LABEL: AI Agent
REM DESCRIPTION: Standalone MCP agent, one pinned LLM provider+model - talks to mcp_server as an MCP client while exposing itself as an MCP server to chat_app.
if not defined AI_AGENT_PROVIDER set AI_AGENT_PROVIDER=anthropic
if not defined AI_AGENT_PORT set AI_AGENT_PORT=9100

cd /d "%~dp0"

if not exist ".venv_ai_agent\Scripts\python.exe" (
    echo Creating virtual environment .venv_ai_agent ...
    py -m venv .venv_ai_agent
    call .venv_ai_agent\Scripts\activate
    echo Installing ai_agent in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_ai_agent\Scripts\activate
)

:run
py -m src.server %*

echo.
echo ----------------------------------------
echo  ai_agent (%AI_AGENT_PROVIDER%) stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

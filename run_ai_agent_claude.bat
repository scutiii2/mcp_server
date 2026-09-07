@echo off
REM Explicit Claude-backed ai_agent instance - for running side by side
REM with run_ai_agent_openai.bat. Same codebase/venv as run_ai_agent.bat
REM (which just uses whatever secret_llm.env already says); this one
REM pins the provider/port explicitly so it can't drift out of sync
REM with the OpenAI instance's port.
REM
REM Reads ANTHROPIC_API_KEY from the same ai_agent/secrets/secret_llm.env
REM as run_ai_agent.bat/run_ai_agent_openai.bat - fill in that file's
REM ANTHROPIC_API_KEY line too. Having both ANTHROPIC_API_KEY and
REM OPENAI_API_KEY set there at once is fine: each provider module only
REM ever checks its own key.
set AI_AGENT_PROVIDER=claude
set AI_AGENT_PORT=9100

REM Activate the virtual environment
call .\venv_ai_agent\Scripts\activate

REM Change directory to ai_agent
cd /d "%~dp0ai_agent"

:run
REM Run ai_agent
py -m src.server

echo.
echo ----------------------------------------
echo  ai_agent (claude) stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

@echo off
REM Second ai_agent instance, backed by OpenAI instead of Claude - for
REM running two agents side by side (e.g. testing both from chat_app's
REM dropdown at once). Same codebase/venv as run_ai_agent.bat, just a
REM different provider + port.
REM
REM Reads OPENAI_API_KEY from the same ai_agent/secrets/secret_llm.env
REM as run_ai_agent.bat - fill in that file's OPENAI_API_KEY line too.
REM Having both ANTHROPIC_API_KEY and OPENAI_API_KEY set there at once
REM is fine: each provider module only ever checks its own key.
set AI_AGENT_PROVIDER=openai
set AI_AGENT_PORT=9101

REM Activate the virtual environment
call .\venv_ai_agent\Scripts\activate

REM Change directory to ai_agent
cd /d "%~dp0ai_agent"

:run
REM Run ai_agent
py -m src.server

echo.
echo ----------------------------------------
echo  ai_agent (openai) stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

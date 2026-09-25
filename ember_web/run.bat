@echo off
REM ember_web dev launcher. Installs node_modules on first run, then starts
REM the Vite dev server.
REM
REM Extra args pass straight through to vite (e.g. --open).
REM
REM LABEL: Ember Web
REM DESCRIPTION: Vue 3 + TypeScript chat frontend talking to ai_agent and mcp_server directly over MCP.
cd /d "%~dp0"

if not defined EMBER_WEB_PORT set EMBER_WEB_PORT=5173

if not exist "node_modules" (
    echo Installing ember_web dependencies ...
    call npm install
)

:run
call npm run dev -- %*

echo.
echo ----------------------------------------
echo  ember_web stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

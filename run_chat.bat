@echo off
REM Open the chat page in default browser (once, not on every restart)
REM start http://127.0.0.1:5000

REM Activate the virtual environment
call .\venv_chat\Scripts\activate

REM Change directory to mcp_server
cd /d "%~dp0chat_app"

:run
REM Run the MCP server
py -m src.run

echo.
echo ----------------------------------------
echo  Server Stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
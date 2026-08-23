@echo off
REM Change directory to mcp_server
cd /d "%~dp0chat_app"

REM Open the chat page in default browser (once, not on every restart)
REM start http://127.0.0.1:5000

:run
REM Run the Server Stopped
.\.venv\Scripts\python.exe -m run

echo.
echo ----------------------------------------
echo  Server Stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
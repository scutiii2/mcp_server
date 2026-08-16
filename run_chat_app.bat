@echo off
REM Change directory to chat_app
cd /d "%~dp0chat_app"

REM Activate the virtual environment
call .\venv_chat\Scripts\activate

REM Open the chat page in default browser (once, not on every restart)
start http://127.0.0.1:5009/chat

:run
REM Run the chat app
py -m chat_app.run

echo.
echo ----------------------------------------
echo  Chat app stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

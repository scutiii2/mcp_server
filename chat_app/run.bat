@echo off
REM Activate the virtual environment
call .\.venv\Scripts\activate

REM Open the chat page in default browser (once, not on every restart)
REM start http://127.0.0.1:5000

:run
REM Run the Server Stopped
py -m run

echo.
echo ----------------------------------------
echo  Server Stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
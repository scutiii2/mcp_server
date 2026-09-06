@echo off
REM Activate the virtual environment
call .\venv_ai_agent\Scripts\activate

REM Change directory to ai_agent
cd /d "%~dp0ai_agent"

:run
REM Run ai_agent
py -m src.server

echo.
echo ----------------------------------------
echo  ai_agent stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

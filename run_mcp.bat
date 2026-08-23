@echo off
REM Activate the virtual environment
call .\venv_mcp\Scripts\activate

REM Change directory to mcp_server
cd /d "%~dp0mcp_server"

:run
REM Run the MCP server
py -m src.run

echo.
echo ----------------------------------------
echo  MCP server stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

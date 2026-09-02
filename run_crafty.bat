@echo off
REM Activate crafty_mcp_server's own virtual environment - see
REM crafty_mcp_server/README.md for how to create it (python -m venv .venv
REM inside crafty_mcp_server/, then pip install -e ".[dev]").
call .\crafty_mcp_server\.venv\Scripts\activate

REM Change directory to crafty_mcp_server
cd /d "%~dp0crafty_mcp_server"

:run
REM Run the Crafty MCP server
py -m src.server

echo.
echo ----------------------------------------
echo  Crafty MCP server stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

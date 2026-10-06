@echo off
REM MCP server dev launcher. Creates .venv_mcp on first run and installs
REM this project into it in editable mode - the "pip install -e .[dev]"
REM setup step the README used to ask you to run by hand.
REM
REM LABEL: MCP Server
REM DESCRIPTION: MCP tool server - capabilities (server manager) and an extension proxy, over streamable HTTP.
cd /d "%~dp0"

if not exist ".venv_mcp\Scripts\python.exe" (
    echo Creating virtual environment .venv_mcp ...
    py -m venv .venv_mcp
    call .venv_mcp\Scripts\activate
    echo Installing mcp_server in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_mcp\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  MCP server stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

@echo off
REM Change directory to mcp_server
cd /d "%~dp0mcp_server"

REM Activate the virtual environment
call .\venv_mcp\Scripts\activate

REM Run the MCP server
py -m mcp_server.run

REM Keep the window open after execution
pause

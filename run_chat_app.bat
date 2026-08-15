@echo off
REM Change directory to mcp_server
cd /d "%~dp0chat_app"

REM Activate the virtual environment
call .\venv_chat\Scripts\activate

REM Open the chat page in default browser
start http://127.0.0.1:5009/chat

REM Run the MCP server
py -m chat_app.run

REM Keep the window open after execution
pause

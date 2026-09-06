@echo off
REM Launches mcp_server and chat_app together, each in its own window with
REM its own virtual environment (venv_mcp / venv_chat) - no mixing of the
REM two, since each window activates its venv independently.
REM
REM The restart-on-stop prompt lives in run_mcp_server.bat / run_chat_app.bat
REM themselves, so it works the same whether you run them individually or
REM launch both from here - if a server is closed (Ctrl+C, crash, or the
REM window's X), that window offers to restart just that one server without
REM touching the other.

start "MCP Server" cmd /k call "%~dp0run_mcp.bat"

REM Brief head start so chat_app's first extension/provider fetch doesn't
REM race mcp_server's own startup - not required (chat_app degrades
REM gracefully if mcp_server isn't up yet), just a smoother first load.
timeout /t 2 /nobreak >nul

start "Chat App" cmd /k call "%~dp0run_chat.bat"

start "AI Agent" cmd /k call "%~dp0run_ai_agent.bat"

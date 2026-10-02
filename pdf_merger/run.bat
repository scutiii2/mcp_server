@echo off
REM pdf_merger dev launcher. Creates .venv_pdf_merger on first run and installs
REM this project into it in editable mode.
REM
REM LABEL: PDF Merger
REM DESCRIPTION: Merges PDFs and images into one PDF. REST API for pdf_merger_web, MCP endpoint for mcp_server.
cd /d "%~dp0"

if not defined PDF_MERGER_PORT set PDF_MERGER_PORT=8040

if not exist ".venv_pdf_merger\Scripts\python.exe" (
    echo Creating virtual environment .venv_pdf_merger ...
    py -m venv .venv_pdf_merger
    call .venv_pdf_merger\Scripts\activate
    echo Installing pdf_merger in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_pdf_merger\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  pdf_merger stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

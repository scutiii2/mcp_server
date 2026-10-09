@echo off
REM video_downloader dev launcher. Creates .venv_video_downloader on first run and
REM installs this project into it in editable mode.
REM
REM LABEL: Video Downloader
REM DESCRIPTION: Downloads videos and audio with yt-dlp. REST API for video_downloader_web, MCP endpoint for mcp_server.
cd /d "%~dp0"

if not exist ".venv_video_downloader\Scripts\python.exe" (
    echo Creating virtual environment .venv_video_downloader ...
    py -m venv .venv_video_downloader
    call .venv_video_downloader\Scripts\activate
    echo Installing video_downloader in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_video_downloader\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  video_downloader stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

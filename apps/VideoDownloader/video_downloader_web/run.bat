@echo off
REM video_downloader_web dev launcher. Installs node_modules on first run, then starts
REM the Vite dev server. Extra args pass straight through to vite (e.g. --open).
REM
REM LABEL: Video Downloader Web
REM DESCRIPTION: Vue 3 + TypeScript web app for video_downloader: paste a link, pick a quality, download.
cd /d "%~dp0"

if not exist "node_modules" (
    echo Installing video_downloader_web dependencies ...
    call npm install
)

:run
call npm run dev -- %*

echo.
echo ----------------------------------------
echo  video_downloader_web stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

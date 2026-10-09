@echo off
REM pdf_merger_web dev launcher. Installs node_modules on first run, then starts
REM the Vite dev server. Extra args pass straight through to vite (e.g. --open).
REM
REM LABEL: PDF Merger Web
REM DESCRIPTION: Vue 3 + TypeScript web app for pdf_merger: upload, reorder pages and merge.
cd /d "%~dp0"

if not exist "node_modules" (
    echo Installing pdf_merger_web dependencies ...
    call npm install
)

:run
call npm run dev -- %*

echo.
echo ----------------------------------------
echo  pdf_merger_web stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

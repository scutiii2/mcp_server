@echo off
REM ember_admin dev launcher. Installs node_modules on first run, then starts
REM the Vite dev server.
REM
REM Extra args pass straight through to vite (e.g. --open).
REM
REM LABEL: Ember Admin
REM DESCRIPTION: Vue 3 + TypeScript admin app for ember: accounts, analytics, capabilities and extensions, through ember_api.
cd /d "%~dp0"

if not defined EMBER_ADMIN_PORT set EMBER_ADMIN_PORT=5175

if not exist "node_modules" (
    echo Installing ember_admin dependencies ...
    call npm install
)

:run
call npm run dev -- %*

echo.
echo ----------------------------------------
echo  ember_admin stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end

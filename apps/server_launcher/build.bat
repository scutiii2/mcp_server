@echo off
REM Builds the standalone exe: dist\scuti_server_launcher.exe
REM Double-click it. Needs Python 3.11+ on this machine to BUILD; the exe it
REM makes carries its own Python and runs on a machine without one.
REM Creates .venv_launcher on first run, like run.bat.
cd /d "%~dp0"

if not exist ".venv_launcher\Scripts\python.exe" (
    echo Creating virtual environment .venv_launcher ...
    py -m venv .venv_launcher
    if errorlevel 1 goto :failed
)
call .venv_launcher\Scripts\activate

echo Installing build tools ...
python -m pip install -e ".[build]"
if errorlevel 1 goto :failed

echo Building scuti_server_launcher.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name scuti_server_launcher ^
    --add-data "%~dp0src\assets;src\assets" ^
    --distpath dist --workpath build\pyinstaller --specpath build ^
    launcher.py
if errorlevel 1 goto :failed

echo Cleaning temporary build files ...
powershell -NoProfile -Command ^
    "$ErrorActionPreference = 'Stop'; $root = (Get-Location).Path;" ^
    "$work = Join-Path $root 'build\pyinstaller';" ^
    "if (Test-Path -LiteralPath $work) { $resolved = (Resolve-Path -LiteralPath $work).Path; if (-not $resolved.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Build path is outside the launcher folder' }; Remove-Item -LiteralPath $resolved -Recurse -Force };" ^
    "$spec = Join-Path $root 'build\scuti_server_launcher.spec'; if (Test-Path -LiteralPath $spec) { Remove-Item -LiteralPath $spec -Force };" ^
    "$build = Join-Path $root 'build'; if ((Test-Path -LiteralPath $build) -and @(Get-ChildItem -LiteralPath $build -Force).Count -eq 0) { Remove-Item -LiteralPath $build -Force }"
if errorlevel 1 echo Warning: the executable was built, but some temporary build files could not be removed.

echo.
echo Done: %~dp0dist\scuti_server_launcher.exe
pause
exit /b 0

:failed
echo.
echo Build failed - see the messages above.
pause
exit /b 1

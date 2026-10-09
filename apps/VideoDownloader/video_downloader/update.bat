@echo off
REM Upgrade yt-dlp inside the project venv (sites change often, old versions break).
cd /d "%~dp0"
if not exist ".venv_video_downloader\Scripts\python.exe" (
    echo Run run.bat once first to create the virtual environment.
    exit /b 1
)
call .venv_video_downloader\Scripts\activate
pip install -U "yt-dlp[default,curl-cffi]"
pip show yt-dlp | findstr /B "Version"

REM The curl_cffi address guard patches yt-dlp internals; check it still holds after the upgrade.
echo Checking the curl_cffi address guard against the new versions ...
python -m pytest tests/test_curl_guard.py -q
if errorlevel 1 (
    echo.
    echo ************************************************************************
    echo  WARNING: the curl_cffi guard tests FAILED with this yt-dlp/curl_cffi.
    echo  Impersonated requests may be unguarded or impersonation may be off.
    echo  Do not run the service until this is fixed, or roll yt-dlp back:
    echo    pip install "yt-dlp[default,curl-cffi]==<previous version>"
    echo ************************************************************************
    exit /b 1
)
echo Update the pin in pyproject.toml if you want this version to stick.

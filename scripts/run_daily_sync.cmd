@echo off
setlocal
rem Daily unattended sync. Set VAULT_PYTHON to pick the interpreter, else use the py launcher.
cd /d "%~dp0.."
if errorlevel 1 exit /b 1

set "LOG_DIR=%LOCALAPPDATA%\certifications-vault"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG=%LOG_DIR%\sync.log"

echo ===== %DATE% %TIME% start >> "%LOG%"
if defined VAULT_PYTHON (
    "%VAULT_PYTHON%" scripts\sync_local.py --yes >> "%LOG%" 2>&1
) else (
    py -3 scripts\sync_local.py --yes >> "%LOG%" 2>&1
)
set "RC=%ERRORLEVEL%"
echo ===== %DATE% %TIME% end exit=%RC% >> "%LOG%"
exit /b %RC%

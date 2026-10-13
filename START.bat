@powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" %* & if errorlevel 1 (exit /b 1) else exit /b 0

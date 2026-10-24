@echo off
rem Instability Control - beta installer. Double-click this file.
rem It runs install.ps1 (next to this file) with PowerShell; nothing is installed for other users and no admin is needed.
title Instability Control - installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo The installer stopped with code %RC%. Read the message above (the log file is named install_log.txt).
pause
exit /b %RC%

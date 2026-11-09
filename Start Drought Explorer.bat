@echo off
title Drought Intelligence Explorer
echo.
echo   Starting Drought Intelligence Explorer...
echo   Your browser will open in a moment.
echo.
echo   KEEP THIS WINDOW OPEN while using the app.
echo   Closing this window stops the app.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1"
if errorlevel 1 (
  echo.
  echo   Something went wrong starting the local server.
  echo   Take a screenshot of this window if you ask for help.
  pause
)

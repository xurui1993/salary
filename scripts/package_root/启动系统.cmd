@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0app\start.ps1" (
  echo 未找到 app\start.ps1，请完整解压源码包后再启动。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\start.ps1"
set "START_EXIT=%ERRORLEVEL%"
if not "%START_EXIT%"=="0" pause
exit /b %START_EXIT%

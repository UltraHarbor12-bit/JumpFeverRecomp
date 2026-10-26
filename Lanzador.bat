@echo off
rem Jump Fever Recomp - abre el launcher (GUI). Argumentos extra se pasan al launcher.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 tools\launcher\sjf_launcher.py %*
) else (
  python tools\launcher\sjf_launcher.py %*
)
if errorlevel 1 pause

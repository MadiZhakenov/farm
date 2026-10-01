@echo off
rem Auto-generation without GUI: topics from topics.txt (1 carousel per line).
rem Extra args pass through:  run_auto.bat "my topic" -n 5    or    run_auto.bat --loop 60
rem Log: out\auto_last.log
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run setup_windows.bat first & pause & exit /b 1)
".venv\Scripts\python.exe" auto_generate.py %*
pause

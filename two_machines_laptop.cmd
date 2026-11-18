@echo off
rem Ноутбук помогает главному ПК: та же партия, запуск прямо из общей папки (материалы не копируются).
rem Пример (на ноутбуке, в любой папке):
rem   \\192.168.11.39\farm\two_machines_laptop.cmd build_inspoy_moveon_v2.py --run 2m --yt 40 --jobs 6
rem На главном ПК — та же команда без этого файла:  python build_inspoy_moveon_v2.py --run 2m --yt 40 --jobs 6
rem Временные файлы — %LOCALAPPDATA%\farm_work, лог — ещё и в общей папке output\_work\_node_logs.
setlocal
set "FARM=%~dp0"
set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\farm_pycache"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
set "SCRIPT=%~1"
shift
set "ARGS="
:collect
if "%~1"=="" goto run
set "ARGS=%ARGS% %1"
shift
goto collect
:run
set "PY=%USERPROFILE%\GitHub\farm\.venv\Scripts\python.exe"
if exist "%PY%" goto go
where py >nul 2>nul && (set "PY=py -3.11" & goto go)
set "PY=python"
:go
echo [farm] %COMPUTERNAME%: %PY% "%FARM%%SCRIPT%"%ARGS%
%PY% "%FARM%%SCRIPT%"%ARGS%
endlocal

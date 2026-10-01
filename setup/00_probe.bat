@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set LOG=setup\probe.log
echo ==== probe %date% %time% ==== > %LOG%
echo --- py launcher --- >> %LOG%
py -0p >> %LOG% 2>&1
echo --- python --- >> %LOG%
where python >> %LOG% 2>&1
python --version >> %LOG% 2>&1
echo --- git --- >> %LOG%
git --version >> %LOG% 2>&1
echo --- nvidia --- >> %LOG%
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv >> %LOG% 2>&1
echo --- ollama --- >> %LOG%
where ollama >> %LOG% 2>&1
ollama list >> %LOG% 2>&1
echo --- chrome --- >> %LOG%
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" echo chrome ok >> %LOG%
echo --- disk --- >> %LOG%
wmic logicaldisk where "DeviceID='C:'" get FreeSpace >> %LOG% 2>&1
echo DONE >> %LOG%

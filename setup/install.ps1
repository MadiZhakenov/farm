# Farm — установка на Windows. Запуск: двойной клик по setup_windows.bat
# Лог: setup\install.log
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Log = Join-Path $PSScriptRoot "install.log"
"" | Out-File $Log -Encoding utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

function Say([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $Log -Value $line -Encoding UTF8
}
function Run([string]$exe, [string[]]$a) {
    Add-Content -Path $Log -Value ("> " + $exe + " " + ($a -join " ")) -Encoding UTF8
    & $exe @a 2>&1 | ForEach-Object {
        $s = "$_"
        Write-Host $s
        Add-Content -Path $Log -Value $s -Encoding UTF8
    }
    $code = $LASTEXITCODE
    Add-Content -Path $Log -Value ("exit=" + $code) -Encoding UTF8
    return $code
}
function Probe([string]$exe, [string[]]$a) {
    try { $o = & $exe @a 2>$null; if ($LASTEXITCODE -eq 0) { return ($o | Out-String).Trim() } } catch {}
    return $null
}

$Steps = [ordered]@{}
function Mark([string]$k, [string]$v) { $Steps[$k] = $v; Say ("{0}: {1}" -f $k, $v) }

Say "=== Farm install: $Root ==="

# ---------- 1. Python 3.11/3.12 с tkinter ----------
$Py = $null
foreach ($ver in @("3.11", "3.12")) {
    $p = Probe "py" @("-$ver", "-c", "import sys,tkinter;print(sys.executable)")
    if ($p) { $Py = $p; break }
}
if (-not $Py) {
    foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "C:\Program Files\Python311\python.exe",
                     "C:\Program Files\Python312\python.exe")) {
        if (Test-Path $c) {
            $p = Probe $c @("-c", "import sys,tkinter;print(sys.executable)")
            if ($p) { $Py = $p; break }
        }
    }
}
if (-not $Py) {
    Say "Python 3.11 не найден — ставлю через winget (только для текущего пользователя)…"
    Run "winget" @("install", "-e", "--id", "Python.Python.3.11", "--scope", "user", "--silent",
                   "--accept-package-agreements", "--accept-source-agreements") | Out-Null
    $c = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    if (Test-Path $c) { $Py = Probe $c @("-c", "import sys,tkinter;print(sys.executable)") }
}
if (-not $Py) {
    Mark "python" "FAIL — поставь Python 3.11 с python.org (галочка tcl/tk) и запусти снова"
    Read-Host "Enter — закрыть"; exit 1
}
Mark "python" $Py

# ---------- 2. venv ----------
$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Say "Создаю .venv…"
    Run $Py @("-m", "venv", ".venv") | Out-Null
}
if (-not (Test-Path $VPy)) { Mark "venv" "FAIL"; Read-Host "Enter — закрыть"; exit 1 }
Run $VPy @("-m", "pip", "install", "--upgrade", "pip", "wheel") | Out-Null
Mark "venv" ".venv ok"

# ---------- 3. torch (CUDA если есть NVIDIA) ----------
$Index = "https://download.pytorch.org/whl/cpu"
$Gpu = Probe "nvidia-smi" @("--query-gpu=name,driver_version", "--format=csv,noheader")
if ($Gpu) {
    $drv = [double](($Gpu -split ",")[-1].Trim() -replace "^(\d+\.\d+).*", '$1')
    if ($drv -ge 560) { $Index = "https://download.pytorch.org/whl/cu126" }
    elseif ($drv -ge 520) { $Index = "https://download.pytorch.org/whl/cu118" }
    Say "GPU: $Gpu -> $Index"
} else { Say "NVIDIA GPU не найдена -> torch CPU" }
$have = Probe $VPy @("-c", "import torch;print(torch.__version__, torch.cuda.is_available())")
$wantCuda = $Index -notlike "*cpu"
if (-not $have -or ($wantCuda -and $have -notlike "*True")) {
    Run $VPy @("-m", "pip", "install", "--upgrade", "torch", "torchvision", "--index-url", $Index) | Out-Null
}
$have = Probe $VPy @("-c", "import torch;print(torch.__version__, 'cuda' if torch.cuda.is_available() else 'cpu')")
if ($wantCuda -and $have -notlike "*cuda") {
    Say "CUDA-сборка не завелась — ставлю CPU torch"
    Run $VPy @("-m", "pip", "install", "--force-reinstall", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu") | Out-Null
    $have = Probe $VPy @("-c", "import torch;print(torch.__version__, 'cuda' if torch.cuda.is_available() else 'cpu')")
}
Mark "torch" ($(if ($have) { $have } else { "FAIL" }))

# ---------- 4. зависимости ----------
$rc = Run $VPy @("-m", "pip", "install", "-r", "requirements.txt", "pytest")
Mark "requirements" ($(if ($rc -eq 0) { "ok" } else { "FAIL (см. лог)" }))

# ---------- 5. .env ----------
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Say ".env создан из .env.example" }
$envTxt = Get-Content ".env" -Raw
if ($envTxt -match "GEMINI_API_KEY\s*=\s*(your_key_here)?\s*(\r?\n|$)") {
    Mark "gemini_key" "НЕ ЗАДАН — открой .env и впиши GEMINI_API_KEY"
} else { Mark "gemini_key" "задан" }

# ---------- 6. Ollama (moondream для спорных фото) ----------
$Ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $Ollama -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $Ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if ($Ollama) {
    if (-not (Probe $Ollama @("list"))) {
        Say "Запускаю ollama serve…"
        Start-Process -FilePath $Ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
    }
    $rc = Run $Ollama @("pull", "moondream")
    Mark "ollama" ($(if ($rc -eq 0) { "moondream ok" } else { "pull FAIL (не критично)" }))
} else { Mark "ollama" "не установлен (не критично: спорные фото без vision-проверки)" }

# ---------- 7. SigLIP (скачать веса заранее) ----------
$rc = Run $VPy @("-c", "import sys;sys.path.insert(0,'.');from core.taste_embedder import get_embedder;print('SigLIP:', get_embedder().ensure())")
Mark "siglip" ($(if ($rc -eq 0) { "ok" } else { "FAIL (см. лог)" }))

# ---------- 8. extension-lab (если есть Node) ----------
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location "extension-lab"; $rc = Run "npm.cmd" @("ci", "--no-audit", "--no-fund"); Pop-Location
    Mark "extension-lab" ($(if ($rc -eq 0) { "npm ok" } else { "npm FAIL (не критично)" }))
} else { Mark "extension-lab" "Node не найден (нужен только для extension-lab)" }

# ---------- 9. проверки ----------
$rc = Run $VPy @("-c", "import sys;sys.path.insert(0,'.');import core, tkinter, carousel_factory_app, review_panel, auto_generate;print('imports ok')")
Mark "imports" ($(if ($rc -eq 0) { "ok" } else { "FAIL" }))
$rc = Run $VPy @("-m", "pytest", "tests", "-q", "-rs")
Mark "tests" ($(if ($rc -eq 0) { "ok" } else { "FAIL (см. лог)" }))
$rc = Run $VPy @("setup\check_pinterest.py")
Mark "pinterest" ($(if ($rc -eq 0) { "ok" } else { "FAIL (см. лог)" }))

Say "=== ИТОГ ==="
$Steps.GetEnumerator() | ForEach-Object { Say ("  {0,-14} {1}" -f $_.Key, $_.Value) }
Say "Готово. Дальше: впиши ключ в .env -> run_factory.bat (GUI) или run_auto.bat (автогенерация)."
Read-Host "Enter — закрыть"

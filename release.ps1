# release.ps1 - Voice Commander: release local em um comando
# Uso:
#   powershell -File release.ps1            # gate + build + stop app + install silencioso
#   powershell -File release.ps1 -NoInstall  # gate + build, sem parar/instalar (dev/CI)

param(
    [switch]$NoInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

# --- 1. Gate de verificacao ---------------------------------------------
Write-Output "[...] Gate: py_compile"
$pyFiles = (Get-ChildItem voice\*.py, voice\webui\*.py).FullName
python -m py_compile $pyFiles
if ($LASTEXITCODE -ne 0) { Write-Output "[ERRO] py_compile falhou"; exit 1 }
Write-Output "[OK]   py_compile limpo"

Write-Output "[...] Gate: ruff check"
python -m ruff check .
if ($LASTEXITCODE -ne 0) { Write-Output "[ERRO] ruff encontrou problemas"; exit 1 }
Write-Output "[OK]   ruff limpo"

Write-Output "[...] Gate: pytest"
python -m pytest tests/ -q
if ($LASTEXITCODE -ne 0) { Write-Output "[ERRO] pytest falhou"; exit 1 }
Write-Output "[OK]   pytest passou"

# --- 2. Versao: injetar __version__ em installer.iss ---------------------
$initContent = Get-Content voice\__init__.py -Raw
if ($initContent -notmatch '__version__\s*=\s*"([^"]+)"') {
    Write-Output "[ERRO] Nao encontrei __version__ em voice\__init__.py"
    exit 1
}
$version = $Matches[1]

$issPath = "build\installer.iss"
$issContent = Get-Content $issPath -Raw
if ($issContent -notmatch 'AppVersion=[^\r\n]+') {
    Write-Output "[ERRO] Nao encontrei linha AppVersion= em $issPath"
    exit 1
}
$issContent = $issContent -replace 'AppVersion=[^\r\n]+', "AppVersion=$version"
Set-Content -Path $issPath -Value $issContent -NoNewline
Write-Output "[OK]   AppVersion injetado: $version"

# --- 3. Build (reusa build.bat) ------------------------------------------
# Limpeza previa: o cleanup interno do build.bat usa paths relativos ao cwd build/
# e nunca alcanca dist\ na raiz; PyInstaller COLLECT aborta se o dir nao estiver vazio.
if (Test-Path dist\VoiceCommander) {
    Remove-Item -Recurse -Force dist\VoiceCommander
    Write-Output "[OK]   dist\VoiceCommander anterior removido"
}
Write-Output "[...] Build: PyInstaller + Inno Setup (build.bat)"
Push-Location build
# stdin nul: o pause no final do build.bat nao bloqueia o fluxo de um comando so
cmd /c ".\build.bat < nul"
$buildExit = $LASTEXITCODE
Pop-Location
if ($buildExit -ne 0) { Write-Output "[ERRO] build.bat falhou (exit $buildExit)"; exit 1 }

$exePath = "dist\VoiceCommander\VoiceCommander.exe"
$setupPath = "dist\VoiceCommanderSetup.exe"
if (-not (Test-Path $exePath)) { Write-Output "[ERRO] Artefato ausente: $exePath"; exit 1 }
if (-not (Test-Path $setupPath)) { Write-Output "[ERRO] Artefato ausente: $setupPath"; exit 1 }
Write-Output "[OK]   Artefatos gerados: $exePath, $setupPath"

# --- 4. Warn condicional: watchdog de dev ---------------------------------
try {
    $task = Get-ScheduledTask -TaskName "VoiceTranscription" -ErrorAction Stop
    if ($task.State -ne "Disabled") {
        Write-Output "[WARN] Scheduled task 'VoiceTranscription' (watchdog de dev) esta ativa. Ela mata VoiceCommander.exe e pode conflitar com a instancia instalada."
    }
} catch {
    # task nao existe, nada a fazer
}

if ($NoInstall) {
    Write-Output "[SKIP] -NoInstall: pulando stop do app e instalacao silenciosa"
    Write-Output ""
    Write-Output "[OK]   Resumo: versao=$version | exe=$exePath | setup=$setupPath | instalado=nao (-NoInstall)"
    exit 0
}

# --- 5. Stop app -----------------------------------------------------------
$proc = Get-Process -Name VoiceCommander -ErrorAction SilentlyContinue
if ($proc) {
    Write-Output "[...] Encerrando VoiceCommander.exe em execucao"
    Stop-Process -Name VoiceCommander -Force -ErrorAction SilentlyContinue
    $waited = 0
    while ((Get-Process -Name VoiceCommander -ErrorAction SilentlyContinue) -and ($waited -lt 10)) {
        Start-Sleep -Milliseconds 500
        $waited++
    }
    Write-Output "[OK]   VoiceCommander.exe encerrado"
} else {
    Write-Output "[OK]   VoiceCommander.exe nao estava em execucao"
}

# --- 6. Install silencioso --------------------------------------------------
Write-Output "[...] Instalando (silencioso, admin via UAC se necessario)"
Start-Process -FilePath $setupPath -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
Write-Output "[OK]   Instalacao concluida"

# --- 7. Resumo final -------------------------------------------------------
Write-Output ""
Write-Output "[OK]   Resumo: versao=$version | exe=$exePath | setup=$setupPath | instalado=sim"

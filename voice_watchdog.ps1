# voice_watchdog.ps1 - JP Labs
# Mantem voice.py vivo enquanto o computador esta ligado.
# Verifica a cada 30s se o processo esta rodando.
# Se nao estiver, inicia via pythonw.exe (sem janela).
# Executado pelo Task Scheduler no logon do usuario.

$Script  = Join-Path $PSScriptRoot "voice.py"
$WorkDir = $PSScriptRoot
$LogFile = Join-Path $PSScriptRoot "watchdog.log"

# Detecta o pythonw correto: tenta path classico, Windows Store e PATH
function Find-PythonW {
    $candidates = @(
        "C:\Users\joaop\AppData\Local\Programs\Python\Python313\pythonw.exe",
        "C:\Users\joaop\AppData\Local\Microsoft\WindowsApps\pythonw.exe",
        "C:\Users\joaop\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\pythonw.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    # Fallback: busca no PATH
    $found = Get-Command "pythonw.exe" -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    # Ultimo recurso: usa python.exe
    $foundPy = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($foundPy) { return $foundPy.Source }
    return $null
}

$PythonW = Find-PythonW

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-VoiceProcess {
    # Busca qualquer processo python/pythonw (incluindo pythonw3.13, pythonw3.12, etc.)
    # que tenha voice.py na command line via WMI
    try {
        $wmiProcs = Get-CimInstance -ClassName Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*voice.py*" }
        if ($wmiProcs) {
            return $wmiProcs | Select-Object -First 1
        }
    } catch {
        # Fallback: Get-Process com wildcard
        $procs = Get-Process -Name "python*" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            try {
                $wmi = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $($p.Id)" -ErrorAction SilentlyContinue
                if ($wmi -and $wmi.CommandLine -like "*voice.py*") {
                    return $p
                }
            } catch {}
        }
    }
    return $null
}

function Start-VoiceScript {
    if (-not $PythonW) {
        Write-Log "ERRO: pythonw.exe nao encontrado em nenhum caminho conhecido."
        return
    }
    Write-Log "Iniciando voice.py via $PythonW ..."
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $PythonW
        $psi.Arguments = "`"$Script`""
        $psi.WorkingDirectory = $WorkDir
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $psi.UseShellExecute = $false
        $proc = [System.Diagnostics.Process]::Start($psi)
        Write-Log "voice.py iniciado (PID $($proc.Id))"
    } catch {
        Write-Log "ERRO ao iniciar voice.py: $_"
    }
}

# Aguarda 10s no boot antes de verificar pela primeira vez
# (da tempo ao sistema inicializar o audio e o teclado)
Write-Log "=== Watchdog iniciado === pythonw: $PythonW"

# Fix race condition: elimina qualquer processo VoiceCommander.exe remanescente
# de sessao anterior (EXE via Startup Folder ja foi removido, mas pode haver
# processos orphaos prendendo o mutex Global\VoiceJPLabs_SingleInstance).
$exeProc = Get-Process -Name "VoiceCommander" -ErrorAction SilentlyContinue
if ($exeProc) {
    Write-Log "VoiceCommander.exe encontrado (PID $($exeProc.Id)) — encerrando para liberar mutex..."
    Stop-Process -Id $exeProc.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Log "VoiceCommander.exe encerrado."
}

Start-Sleep -Seconds 10

while ($true) {
    $voiceProc = Get-VoiceProcess

    if ($null -eq $voiceProc) {
        Write-Log "voice.py NAO encontrado - iniciando..."
        Start-VoiceScript
        # Aguarda 8s apos iniciar antes de checar novamente
        Start-Sleep -Seconds 8
    }
    # Processo encontrado - silencioso (nao loga para nao encher o arquivo)

    Start-Sleep -Seconds 30
}

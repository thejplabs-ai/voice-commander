# Setup Voice Transcription Task Scheduler - JP Labs
# Registra o watchdog no Task Scheduler para rodar no logon.
# O watchdog mantem o voice.py vivo continuamente.
#
# Como executar (1x, como Administrador):
#   powershell -ExecutionPolicy Bypass -File "C:\Users\joaop\voice-commander\setup_voice_task.ps1"

$TaskName    = "VoiceTranscription"
$PowerShellW = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
$Watchdog    = Join-Path $PSScriptRoot "voice_watchdog.ps1"
$WorkDir     = $PSScriptRoot

# Valida que os arquivos existem antes de registrar
if (-not (Test-Path $Watchdog)) {
    Write-Host "ERRO: Watchdog nao encontrado em $Watchdog" -ForegroundColor Red
    exit 1
}

# Remove task existente se houver
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Task anterior removida (se existia)." -ForegroundColor Yellow

# Define a acao: powershell.exe rodando o watchdog (sem janela, ExecutionPolicy Bypass)
$Action = New-ScheduledTaskAction `
    -Execute $PowerShellW `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Watchdog`"" `
    -WorkingDirectory $WorkDir

# Trigger: ao fazer logon do usuario atual
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings:
# - ExecutionTimeLimit 0 = sem limite de tempo (roda indefinidamente)
# - RestartCount 5 e RestartInterval 2min = se o watchdog morrer, Task Scheduler reinicia
# - StartWhenAvailable = inicia mesmo se o trigger foi perdido
# - MultipleInstances IgnoreNew = nunca roda duas copias
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -MultipleInstances IgnoreNew

# Principal: rodar como usuario atual, sessao interativa (necessario para hotkeys e audio)
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Registrar a task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Voice-to-text JP Labs - watchdog que mantem voice.py vivo. Auto-inicia no logon." `
    -Force

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host ""
    Write-Host "Task '$TaskName' criada com sucesso!" -ForegroundColor Green
    Write-Host "Estado : $($task.State)"
    Write-Host "Trigger: AtLogOn ($($env:USERNAME))"
    Write-Host "Executa: powershell voice_watchdog.ps1 (mantem voice.py vivo)"
    Write-Host ""
    Write-Host "Para iniciar agora sem reiniciar:" -ForegroundColor Cyan
    Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Cyan
} else {
    Write-Host "ERRO: Task nao foi criada. Verifique permissoes." -ForegroundColor Red
    exit 1
}

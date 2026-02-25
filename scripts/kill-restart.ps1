# Mata o python3.13.exe rodando voice.py + bash zombies das tentativas anteriores
$voiceProcs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -like 'python*' -and $_.CommandLine -like '*voice.py*') -or
    ($_.Name -eq 'bash.exe' -and $_.CommandLine -like '*voice.py*')
}
foreach ($p in $voiceProcs) {
    Write-Output "Killing PID=$($p.ProcessId) $($p.Name)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Write-Output "Iniciando voice.py..."
Set-Location "C:\Users\joaop\voice-commander"
Start-Process -FilePath "python" -ArgumentList "voice.py" -NoNewWindow -Wait

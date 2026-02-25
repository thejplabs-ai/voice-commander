# Mata watchdog (pythonw) + VoiceCommander
Get-Process -Name pythonw,python,VoiceCommander -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output "Killing: $($_.Id) $($_.Name)"
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 2
Write-Output "Todos os processos mortos."

Get-Process -Name python,pythonw,VoiceCommander -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output "Killing: $($_.Id) $($_.Name)"
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 1
Write-Output "Done killing. Starting voice.py..."
Set-Location "C:\Users\joaop\voice-commander"
& python voice.py

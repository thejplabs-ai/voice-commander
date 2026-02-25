Stop-Process -Name VoiceCommander -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800

$dir = [Environment]::GetFolderPath('LocalApplicationData') + '\Microsoft\Windows\Explorer'
$files = Get-ChildItem $dir -Filter 'iconcache_*' -ErrorAction SilentlyContinue
Write-Host "Found $($files.Count) iconcache files in $dir"
$files | Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host 'Icon cache cleared'

Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Process explorer
Write-Host 'Explorer restarted'

Start-Sleep -Seconds 1
Start-Process 'C:\Users\joaop\voice-commander\dist\VoiceCommander\VoiceCommander.exe'
Write-Host 'VoiceCommander started'

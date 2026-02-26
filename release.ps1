Set-Location "C:\Users\joaop\voice-commander"
$version = "v1.0.14"
$zipName = "VoiceCommander-$version.zip"

Write-Output "Zippando dist\VoiceCommander..."
if (Test-Path $zipName) { Remove-Item $zipName }
Compress-Archive -Path "dist\VoiceCommander" -DestinationPath $zipName -CompressionLevel Optimal
$sizeMB = [math]::Round((Get-Item $zipName).Length / 1MB, 1)
Write-Output "Zip criado: $zipName ($sizeMB MB)"

$notes = @"
Fix: clipboard 64-bit OverflowError + Gemini 2.5 Flash

SetClipboardData falhava com OverflowError quando endereco de memoria passava de 2GB no Windows 64-bit. Fix: declarar argtypes para todas funcoes win32 do clipboard. Retry no OpenClipboard (10x, 50ms). Upgrade gemini-2.0-flash para gemini-2.5-flash.
"@

$notesFile = "release-notes.tmp.txt"
$notes | Out-File -FilePath $notesFile -Encoding utf8

Write-Output "Criando release $version no GitHub..."
gh release create $version $zipName --title "Voice Commander $version - fix clipboard 64-bit + Gemini 2.5" --notes-file $notesFile

Remove-Item $notesFile -ErrorAction SilentlyContinue
Write-Output "Release criado!"

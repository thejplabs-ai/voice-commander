# Setup Voice Commander — Startup VBS + Start Menu Shortcut
# Configura o VoiceCommander.exe para iniciar automaticamente no Windows
# e cria atalho no Start Menu para aparecer na pesquisa do Windows.
#
# Como executar (1x, nao precisa de administrador):
#   powershell -ExecutionPolicy Bypass -File "C:\Users\joaop\voice-commander\setup_startup.ps1"

$ExePath     = Join-Path $PSScriptRoot "dist\VoiceCommander\VoiceCommander.exe"
$ExeDir      = Join-Path $PSScriptRoot "dist\VoiceCommander"
$AppData     = [System.Environment]::GetFolderPath('ApplicationData')
$StartupDir  = Join-Path $AppData "Microsoft\Windows\Start Menu\Programs\Startup"
$StartMenuDir = Join-Path $AppData "Microsoft\Windows\Start Menu\Programs"
$VbsPath     = Join-Path $StartupDir "voice-to-text.vbs"
$LnkPath     = Join-Path $StartMenuDir "Voice Commander.lnk"

# Validar que o .exe existe
if (-not (Test-Path $ExePath)) {
    Write-Host "ERRO: VoiceCommander.exe nao encontrado em $ExePath" -ForegroundColor Red
    Write-Host "Execute o build primeiro: python -m PyInstaller build/VoiceCommander.spec --distpath dist --workpath build/pyinstaller-work --noconfirm" -ForegroundColor Yellow
    exit 1
}

# --- 1. Criar/atualizar startup VBS ---
$vbsContent = @"
Set WShell = CreateObject("WScript.Shell")
WShell.Run "powershell -Command ""Stop-Process -Name pythonw3.13 -Force -ErrorAction SilentlyContinue; Stop-Process -Name VoiceCommander -Force -ErrorAction SilentlyContinue""", 0, True
WShell.Run """$ExePath""", 0, False
"@

Set-Content -Path $VbsPath -Value $vbsContent -Encoding UTF8
Write-Host "Startup VBS criado: $VbsPath" -ForegroundColor Green

# --- 2. Criar atalho no Start Menu ---
$WShell = New-Object -ComObject WScript.Shell
$lnk = $WShell.CreateShortcut($LnkPath)
$lnk.TargetPath      = $ExePath
$lnk.WorkingDirectory = $ExeDir
$lnk.IconLocation    = "$ExePath,0"
$lnk.Description     = "Voice Commander - Transcricao por voz com Whisper"
$lnk.Save()
Write-Host "Atalho Start Menu criado: $LnkPath" -ForegroundColor Green

Write-Host ""
Write-Host "Setup completo!" -ForegroundColor Cyan
Write-Host "  - Startup : $VbsPath"
Write-Host "  - Atalho  : $LnkPath"
Write-Host ""
Write-Host "Para iniciar agora:" -ForegroundColor Cyan
Write-Host "  Start-Process '$ExePath'" -ForegroundColor Cyan

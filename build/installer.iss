; Voice Commander — Inno Setup Script
; Gera VoiceCommanderSetup.exe (~35MB)

[Setup]
AppName=Voice Commander
AppVersion=1.0.11
; TODO: sync version — manter em sincronia com __version__ em voice.py
AppCopyright=Copyright (C) 2026 JP Labs
AppPublisher=JP Labs
AppPublisherURL=https://voice.jplabs.ai
AppSupportURL=https://voice.jplabs.ai
DefaultDirName={autopf}\VoiceCommander
DefaultGroupName=Voice Commander
OutputBaseFilename=VoiceCommanderSetup
OutputDir=..\dist
Compression=lzma2/ultra64
SolidCompression=yes
; Não requer admin — instala em Program Files mas funciona sem UAC se necessário
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "..\dist\VoiceCommander\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
; Atalho na área de trabalho
Name: "{autodesktop}\Voice Commander"; Filename: "{app}\VoiceCommander.exe"; \
    Comment: "Voice Commander — JP Labs"
; Iniciar com o Windows (startup)
Name: "{autostartup}\Voice Commander"; Filename: "{app}\VoiceCommander.exe"; \
    Comment: "Voice Commander — JP Labs"
; Menu Iniciar
Name: "{group}\Voice Commander"; Filename: "{app}\VoiceCommander.exe"
Name: "{group}\Desinstalar Voice Commander"; Filename: "{uninstallexe}"

[Run]
; Oferecer abrir o app após instalação
Filename: "{app}\VoiceCommander.exe"; Description: "Abrir Voice Commander"; \
    Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Remover dados do usuário ao desinstalar (opcional — comentar para preservar)
; Type: filesandordirs; Name: "{userappdata}\VoiceCommander"

[Messages]
; Mensagem customizada na tela de boas-vindas
WelcomeLabel2=Este instalador vai configurar o Voice Commander no seu computador.%n%nVocê precisará de uma chave de licença (obtida em voice.jplabs.ai) e uma chave Google Gemini (gratuita em aistudio.google.com/apikey) para ativar o app.%n%nSe o Windows Defender exibir aviso de segurança, clique em "Mais informações" → "Executar assim mesmo".

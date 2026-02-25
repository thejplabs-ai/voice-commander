@echo off
REM Voice Commander — PyInstaller Build Script
REM Uso: build\build.bat
REM Output: dist\VoiceCommander\ + dist\VoiceCommanderSetup.exe (via Inno Setup)

echo === Voice Commander Build ===
echo.

REM Verificar Python
python --version || (echo ERRO: Python nao encontrado & exit /b 1)

REM Verificar PyInstaller
python -m pyinstaller --version || (
    echo Instalando PyInstaller...
    pip install pyinstaller
)

REM Limpar build anterior
if exist dist\VoiceCommander rmdir /s /q dist\VoiceCommander
if exist build\VoiceCommander rmdir /s /q build\VoiceCommander

echo.
echo [1/3] Compilando com PyInstaller...

REM Descobrir caminho do silero_vad_v6.onnx dinamicamente
for /f "delims=" %%i in ('python -c "import faster_whisper, os; print(os.path.join(os.path.dirname(faster_whisper.__file__), 'assets', 'silero_vad_v6.onnx'))"') do set SILERO_ONNX=%%i

echo     silero_vad_v6.onnx: %SILERO_ONNX%

python -m pyinstaller voice.py ^
    --name VoiceCommander ^
    --windowed ^
    --onedir ^
    --hidden-import sounddevice ^
    --hidden-import faster_whisper ^
    --hidden-import keyboard ^
    --hidden-import customtkinter ^
    --hidden-import pystray ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageDraw ^
    --hidden-import google.genai ^
    --hidden-import numpy ^
    --collect-all customtkinter ^
    --collect-all faster_whisper ^
    --add-data "%SILERO_ONNX%;faster_whisper/assets" ^
    --distpath dist ^
    --workpath build\pyinstaller-work ^
    --specpath build

if errorlevel 1 (
    echo ERRO: PyInstaller falhou
    exit /b 1
)

echo.
echo [2/3] Build concluido em dist\VoiceCommander\

REM Verificar se Inno Setup esta instalado
where iscc >nul 2>&1
if errorlevel 1 (
    echo.
    echo [3/3] Inno Setup nao encontrado — pulando gerador de instalador.
    echo       Instale Inno Setup em: https://jrsoftware.org/isdl.php
    echo       Depois rode: iscc build\installer.iss
    goto :done
)

echo.
echo [3/3] Gerando instalador com Inno Setup...
iscc build\installer.iss

if errorlevel 1 (
    echo ERRO: Inno Setup falhou
    exit /b 1
)

echo.
echo === Build completo! ===
echo Instalador: dist\VoiceCommanderSetup.exe

:done
echo.
pause

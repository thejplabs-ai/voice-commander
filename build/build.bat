@echo off
REM Voice Commander — PyInstaller Build Script
REM Uso: cd build && build.bat
REM Output: dist\VoiceCommander\ + dist\VoiceCommanderSetup.exe (via Inno Setup)

echo === Voice Commander Build ===
echo.

REM Verificar Python
python --version || (echo ERRO: Python nao encontrado & exit /b 1)

REM Verificar PyInstaller
python -m PyInstaller --version || (
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

REM Descobrir caminho das DLLs CUDA (nvidia-cublas-cu12, nvidia-cudnn-cu12)
for /f "delims=" %%i in ('python -c "import nvidia.cublas, os; print(os.path.join(os.path.dirname(nvidia.cublas.__path__[0]), 'cublas', 'bin'))"') do set CUBLAS_BIN=%%i
for /f "delims=" %%i in ('python -c "import nvidia.cudnn, os; print(os.path.join(os.path.dirname(nvidia.cudnn.__path__[0]), 'cudnn', 'bin'))"') do set CUDNN_BIN=%%i

echo     cublas DLLs: %CUBLAS_BIN%
echo     cudnn DLLs : %CUDNN_BIN%

REM Resolver path absoluto do projeto (parent de build/) e do build dir
for %%A in ("%~dp0..") do set PROJECT_ROOT=%%~fA
for %%A in ("%~dp0.") do set BUILD_DIR=%%~fA
echo     projeto    : %PROJECT_ROOT%

python -m PyInstaller "%PROJECT_ROOT%\voice\__main__.py" ^
    --name VoiceCommander ^
    --icon "%BUILD_DIR%\icon.ico" ^
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
    --hidden-import openai ^
    --hidden-import webview ^
    --hidden-import nvidia.cublas ^
    --hidden-import nvidia.cudnn ^
    --collect-all customtkinter ^
    --collect-all faster_whisper ^
    --collect-all openai ^
    --collect-all webview ^
    --add-data "%SILERO_ONNX%;faster_whisper/assets" ^
    --add-data "%PROJECT_ROOT%\voice\webui\onboarding.html;voice\webui" ^
    --add-data "%PROJECT_ROOT%\voice\webui\settings.html;voice\webui" ^
    --add-binary "%CUBLAS_BIN%\cublas64_12.dll;." ^
    --add-binary "%CUBLAS_BIN%\cublasLt64_12.dll;." ^
    --add-binary "%CUDNN_BIN%\cudnn64_9.dll;." ^
    --add-binary "%CUDNN_BIN%\cudnn_ops64_9.dll;." ^
    --add-binary "%CUDNN_BIN%\cudnn_cnn64_9.dll;." ^
    --add-binary "%CUDNN_BIN%\cudnn_graph64_9.dll;." ^
    --distpath "%PROJECT_ROOT%\dist" ^
    --workpath "%BUILD_DIR%\pyinstaller-work" ^
    --specpath "%BUILD_DIR%"

if errorlevel 1 (
    echo ERRO: PyInstaller falhou
    exit /b 1
)

echo.
echo [2/3] Build concluido em dist\VoiceCommander\

REM Verificar se Inno Setup esta instalado (PATH ou locais comuns)
set ISCC=
where iscc >nul 2>&1 && set ISCC=iscc
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files\Inno Setup 6\ISCC.exe

if not defined ISCC (
    echo.
    echo [3/3] Inno Setup nao encontrado — pulando gerador de instalador.
    echo       Instale Inno Setup em: https://jrsoftware.org/isdl.php
    goto :done
)

echo.
echo [3/3] Gerando instalador com Inno Setup...
"%ISCC%" installer.iss

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

@echo off
echo Instalando dependencias do voice-to-text...
echo.
pip install -r "%~dp0requirements.txt"
echo.
echo Instalacao concluida!
echo Execute voice-run.bat para iniciar.
pause

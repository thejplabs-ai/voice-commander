# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:\\Users\\joaop\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python313\\site-packages\\faster_whisper\\assets\\silero_vad_v6.onnx', 'faster_whisper/assets'), ('C:\\Users\\joaop\\voice-commander\\voice\\webui\\onboarding.html', 'voice\\webui'), ('C:\\Users\\joaop\\voice-commander\\voice\\webui\\settings.html', 'voice\\webui')]
binaries = [('C:\\Users\\joaop\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python313\\site-packages\\nvidia\\cublas\\bin\\cublas64_12.dll', '.'), ('C:\\Users\\joaop\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python313\\site-packages\\nvidia\\cublas\\bin\\cublasLt64_12.dll', '.'), ('C:\\Users\\joaop\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python313\\site-packages\\nvidia\\cudnn\\bin\\cudnn64_9.dll', '.'), ('C:\\Users\\joaop\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python313\\site-packages\\nvidia\\cudnn\\bin\\cudnn_ops64_9.dll', '.'), ('C:\\Users\\joaop\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python313\\site-packages\\nvidia\\cudnn\\bin\\cudnn_cnn64_9.dll', '.'), ('C:\\Users\\joaop\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python313\\site-packages\\nvidia\\cudnn\\bin\\cudnn_graph64_9.dll', '.')]
hiddenimports = ['sounddevice', 'faster_whisper', 'keyboard', 'customtkinter', 'pystray', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'google.genai', 'numpy', 'openai', 'webview', 'nvidia.cublas', 'nvidia.cudnn']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openai')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\joaop\\voice-commander\\voice\\__main__.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VoiceCommander',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\joaop\\voice-commander\\build\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoiceCommander',
)

# voice/mutex.py — named mutex for single-instance enforcement

import ctypes
import os
import sys

from voice import state

_MUTEX_NAME = "Global\\VoiceJPLabs_SingleInstance"


def _acquire_named_mutex() -> None:
    state._mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        print("[ERRO] Outra instância do voice.py já está rodando.")
        sys.exit(1)
    print(f"[OK]   Mutex adquirido (PID {os.getpid()})")


def _release_named_mutex() -> None:
    if state._mutex_handle:
        ctypes.windll.kernel32.ReleaseMutex(state._mutex_handle)
        ctypes.windll.kernel32.CloseHandle(state._mutex_handle)
        state._mutex_handle = None

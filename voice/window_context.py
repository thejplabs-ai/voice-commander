# voice/window_context.py — Captura título e processo da janela ativa (Feature 2)
# Usa apenas DLLs padrão Win10/11 — sem nova dependência Python.

import ctypes
import ctypes.wintypes
import os


def get_foreground_window_info() -> str:
    """Retorna string descritiva da janela ativa ou '' se falhar.

    Formato: 'Processo: Code.exe\\nTítulo: gemini.py — voice-commander'
    Usa GetForegroundWindow + GetWindowTextW + QueryFullProcessImageNameW.
    """
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Handle da janela ativa
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""

        # Título da janela
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()

        # PID da janela
        pid = ctypes.wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return f"Título: {title}" if title else ""

        # Nome do processo via QueryFullProcessImageNameW (disponível Win Vista+)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        process_name = ""
        if h_proc:
            try:
                proc_buf = ctypes.create_unicode_buffer(1024)
                buf_size = ctypes.wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h_proc, 0, proc_buf, ctypes.byref(buf_size)):
                    process_name = os.path.basename(proc_buf.value)
            finally:
                kernel32.CloseHandle(h_proc)

        parts = []
        if process_name:
            parts.append(f"Processo: {process_name}")
        if title:
            parts.append(f"Título: {title}")
        return "\n".join(parts)

    except Exception as e:
        print(f"[WARN] window_context: {e}")
        return ""

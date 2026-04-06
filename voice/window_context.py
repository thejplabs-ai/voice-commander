# voice/window_context.py — Captura contexto da janela ativa (processo + categoria)
# Epic 5.5: enriquece prompts de AI com contexto do app em uso.

import ctypes
import ctypes.wintypes
import os

# ── Mapeamento processo → categoria ──────────────────────────────────────────

_PROCESS_CATEGORIES: dict[str, str] = {
    # Editores de código
    "code.exe": "code_editor",
    "cursor.exe": "code_editor",
    "windsurf.exe": "code_editor",
    "pycharm64.exe": "code_editor",
    "idea64.exe": "code_editor",
    "devenv.exe": "code_editor",
    "notepad++.exe": "code_editor",
    "sublime_text.exe": "code_editor",
    # Email
    "outlook.exe": "email",
    "thunderbird.exe": "email",
    # Browser
    "chrome.exe": "browser",
    "msedge.exe": "browser",
    "firefox.exe": "browser",
    "brave.exe": "browser",
    "opera.exe": "browser",
    # Chat/messaging
    "slack.exe": "chat",
    "discord.exe": "chat",
    "teams.exe": "chat",
    "telegram.exe": "chat",
    "whatsapp.exe": "chat",
    # Documentos
    "winword.exe": "document",
    "excel.exe": "spreadsheet",
    "powerpnt.exe": "presentation",
    "notepad.exe": "text_editor",
    # Terminal
    "windowsterminal.exe": "terminal",
    "cmd.exe": "terminal",
    "powershell.exe": "terminal",
    "pwsh.exe": "terminal",
}

# PROCESS_QUERY_LIMITED_INFORMATION — menor privilégio necessário (sem PROCESS_ALL_ACCESS)
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_app_category(process_name: str) -> str:
    """Retorna a categoria do processo. Case-insensitive. Default: "other"."""
    return _PROCESS_CATEGORIES.get(process_name.lower(), "other")


def get_process_name() -> str:
    """
    Retorna o nome do executável da janela ativa (ex: "code.exe").
    Usa PROCESS_QUERY_LIMITED_INFORMATION — privilégio mínimo.
    Retorna "" em caso de falha.
    """
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""

        pid = ctypes.wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""

        hprocess = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hprocess:
            return ""

        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.wintypes.DWORD(1024)

            # QueryFullProcessImageNameW disponível a partir do Vista
            success = kernel32.QueryFullProcessImageNameW(hprocess, 0, buf, ctypes.byref(size))
            if success and buf.value:
                return os.path.basename(buf.value)

            # Fallback: GetModuleFileNameExW (requer psapi)
            buf2 = ctypes.create_unicode_buffer(1024)
            if psapi.GetModuleFileNameExW(hprocess, None, buf2, 1024):
                return os.path.basename(buf2.value)

        finally:
            kernel32.CloseHandle(hprocess)

    except Exception:
        pass

    return ""


def get_foreground_window_info() -> dict:
    """
    Retorna dict com título, processo e categoria da janela ativa.

    Retorno:
        {
            "title": str,       # título da janela
            "process": str,     # nome do executável (ex: "code.exe")
            "category": str     # categoria mapeada (ex: "code_editor") ou "other"
        }

    Nunca levanta exceção — retorna dict vazio em caso de falha.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()

        # Título da janela
        title = ""
        if hwnd:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()

        # Nome do processo
        process = get_process_name()
        category = get_app_category(process) if process else "other"

        return {
            "title": title,
            "process": process,
            "category": category,
        }
    except Exception:
        return {"title": "", "process": "", "category": "other"}

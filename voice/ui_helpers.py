# voice/ui_helpers.py — shared UI utilities (no CTk dependency)
# Imported by ui.py, ui_onboarding.py, and ui_settings.py.

import ctypes
import pathlib


def _apply_taskbar_icon(root, ico_path: pathlib.Path) -> None:
    """Força o ícone correto no taskbar do Windows via Win32 API.

    GetParent(winfo_id()) retorna 0 para janelas top-level no Tk/CTk — por isso
    usamos FindWindowW pelo título da janela, que devolve o HWND real que o
    Windows usa para o botão na taskbar.
    """
    if not ico_path.exists():
        return
    try:
        root.update_idletasks()
        title = root.title()
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if not hwnd:
            hwnd = root.winfo_id()
        if not hwnd:
            return
        LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x0080
        for size, kind in ((32, 1), (16, 0)):
            hicon = ctypes.windll.user32.LoadImageW(
                None, str(ico_path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, kind, hicon)
    except Exception as e:
        print(f"[WARN] Falha ao aplicar ícone no taskbar: {e}")

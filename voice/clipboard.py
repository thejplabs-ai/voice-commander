# voice/clipboard.py — copy to clipboard, paste via SendInput, read clipboard

import ctypes
import ctypes.wintypes
import time


def copy_to_clipboard(text: str) -> None:
    """Copia texto para o clipboard via win32 API (sem subprocess)."""
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # Declarar restype explicitamente — sem isso ctypes trunca handles 64-bit para 32-bit
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.c_void_p]

    encoded = (text + '\0').encode('utf-16-le')
    size = len(encoded)

    # OpenClipboard pode falhar se outra app estiver usando — retry até 10x
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Não foi possível abrir o clipboard")

    try:
        user32.EmptyClipboard()
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h_mem:
            raise RuntimeError("GlobalAlloc falhou")
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            raise RuntimeError("GlobalLock falhou")
        ctypes.memmove(p_mem, encoded, size)
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
    finally:
        user32.CloseClipboard()


def read_clipboard(max_chars: int = 0) -> str:
    """Lê o texto atual do clipboard via win32 API. Retorna string vazia se falhar.

    Args:
        max_chars: Se > 0, trunca o texto retornado para este limite (Story 4.5.4).
    """
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return ""

    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return ""
        # Validar tamanho do buffer ANTES de wstring_at para evitar
        # access violation (SEH exception nativa que except Exception nao captura)
        kernel32.GlobalSize.restype = ctypes.c_size_t
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        buf_size = kernel32.GlobalSize(h_data)
        if buf_size < 2:  # mínimo 2 bytes para 1 wchar null-terminator
            return ""
        p_data = kernel32.GlobalLock(h_data)
        if not p_data:
            return ""
        try:
            # Limitar leitura ao tamanho real do buffer (em wchars, excluindo null)
            max_wchars = buf_size // 2
            text = ctypes.wstring_at(p_data, max_wchars)
            # Remover null terminators internos
            null_pos = text.find('\0')
            if null_pos >= 0:
                text = text[:null_pos]
            if not text:
                return ""
            if max_chars > 0 and len(text) > max_chars:
                return text[:max_chars]
            return text
        finally:
            kernel32.GlobalUnlock(h_data)
    except Exception:
        return ""
    finally:
        user32.CloseClipboard()


def simulate_copy() -> None:
    """Simula Ctrl+C via SendInput para capturar texto selecionado.

    Mesmo padrão de paste_via_sendinput() mas com VK_C (0x43) ao invés de VK_V.
    Aguarda 50ms após SendInput para o clipboard ser populado antes de leitura.
    """
    INPUT_KEYBOARD  = 1
    KEYEVENTF_KEYUP = 0x0002

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.wintypes.WORD),
            ("wScan",       ctypes.wintypes.WORD),
            ("dwFlags",     ctypes.wintypes.DWORD),
            ("time",        ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_ulong),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.wintypes.DWORD), ("union", INPUT_UNION)]

    VK_CONTROL = 0x11
    VK_C       = 0x43

    inputs = (INPUT * 4)(
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, dwFlags=0))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_C,       dwFlags=0))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_C,       dwFlags=KEYEVENTF_KEYUP))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, dwFlags=KEYEVENTF_KEYUP))),
    )
    ctypes.windll.user32.SendInput(4, inputs, ctypes.sizeof(INPUT))
    time.sleep(0.05)  # aguarda clipboard ser populado pelo OS


def paste_via_sendinput() -> None:
    INPUT_KEYBOARD  = 1
    KEYEVENTF_KEYUP = 0x0002

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.wintypes.WORD),
            ("wScan",       ctypes.wintypes.WORD),
            ("dwFlags",     ctypes.wintypes.DWORD),
            ("time",        ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_ulong),  # ULONG_PTR — escalar, não ponteiro (fix OverflowError no PyInstaller)
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.wintypes.DWORD), ("union", INPUT_UNION)]

    VK_CONTROL = 0x11
    VK_V       = 0x56

    inputs = (INPUT * 4)(
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, dwFlags=0))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_V,       dwFlags=0))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_V,       dwFlags=KEYEVENTF_KEYUP))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, dwFlags=KEYEVENTF_KEYUP))),
    )
    ctypes.windll.user32.SendInput(4, inputs, ctypes.sizeof(INPUT))

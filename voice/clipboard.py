# voice/clipboard.py — copy to clipboard, paste via SendInput, read clipboard

import ctypes
import ctypes.wintypes
import time

# --- Structs do SendInput (definidas UMA vez, corretas para x64 e x86) ---
#
# O Windows valida cbSize == sizeof(INPUT) real do OS (40 bytes em x64, 28 em
# x86). Isso exige a union completa (MOUSEINPUT é o maior membro e dita o
# tamanho) e dwExtraInfo como ULONG_PTR (8 bytes em x64). A definição antiga
# (union só com KEYBDINPUT + dwExtraInfo c_ulong de 4 bytes) dava sizeof=20 e
# TODO SendInput falhava com ERROR_INVALID_PARAMETER (87) sem injetar nada.
# c_size_t é escalar do tamanho do ponteiro — cobre ULONG_PTR sem o
# OverflowError do PyInstaller que motivou o c_ulong.
_ULONG_PTR = ctypes.c_size_t

_INPUT_KEYBOARD  = 1
_KEYEVENTF_KEYUP = 0x0002


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.wintypes.LONG),
        ("dy",          ctypes.wintypes.LONG),
        ("mouseData",   ctypes.wintypes.DWORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.wintypes.WORD),
        ("wScan",       ctypes.wintypes.WORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg",    ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("union", _INPUT_UNION)]


def _key_chord_inputs(vk_modifier: int, vk_key: int):
    """Array INPUT[4]: modifier down, key down, key up, modifier up."""
    def _ki(vk, flags):
        return _INPUT(type=_INPUT_KEYBOARD,
                      union=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, dwFlags=flags)))
    return (_INPUT * 4)(
        _ki(vk_modifier, 0),
        _ki(vk_key, 0),
        _ki(vk_key, _KEYEVENTF_KEYUP),
        _ki(vk_modifier, _KEYEVENTF_KEYUP),
    )


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

    # Sem restype explícito o ctypes trunca o HANDLE 64-bit para 32 — o handle
    # truncado faz GlobalSize retornar 0 e a leitura devolver "" em silêncio
    # (dependia do endereço da alocação: flaky por boot/processo).
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
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


def _wait_modifiers_released(timeout_s: float = 1.5) -> None:
    """Aguarda o usuário soltar Shift/Ctrl/Alt físicos antes de injetar input.

    WM_HOTKEY dispara com os modificadores do combo ainda pressionados; se o
    Ctrl+C sintético for injetado nesse estado, o app em foco recebe
    Ctrl+Alt+C (Alt físico ainda down) e a cópia nunca acontece.
    """
    # ponytail: polling 10ms com timeout 1.5s; no timeout injeta mesmo assim
    # (pior caso = comportamento antigo). Se precisar de mais robustez, injetar
    # KEYUP dos modificadores antes do Ctrl+C.
    deadline = time.time() + timeout_s
    vks = (0x10, 0x11, 0x12)  # VK_SHIFT, VK_CONTROL, VK_MENU (Alt)
    while time.time() < deadline:
        if not any(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks):
            return
        time.sleep(0.01)


def simulate_copy() -> None:
    """Simula Ctrl+C via SendInput para capturar texto selecionado.

    Mesmo padrão de paste_via_sendinput() mas com VK_C (0x43) ao invés de VK_V.
    Espera os modificadores físicos do hotkey soltarem antes de injetar (senão
    o app em foco recebe Ctrl+Alt+C) e aguarda 50ms após SendInput para o
    clipboard ser populado antes de leitura.
    """
    _wait_modifiers_released()

    try:
        from voice.window_context import get_foreground_window_info
        _fg = get_foreground_window_info().get("process", "?")
        print(f"[INFO] simulate_copy: enviando Ctrl+C para {_fg}\n")
    except Exception:
        pass

    VK_CONTROL = 0x11
    VK_C       = 0x43
    inputs = _key_chord_inputs(VK_CONTROL, VK_C)

    user32 = ctypes.windll.user32
    seq_before = user32.GetClipboardSequenceNumber()

    sent = user32.SendInput(4, inputs, ctypes.sizeof(_INPUT))
    if sent != 4:
        err = ctypes.windll.kernel32.GetLastError()
        print(f"[WARN] simulate_copy: SendInput injetou {sent}/4 eventos (win err {err}) — janela elevada (admin)?\n")
        return

    # Aguarda o app em foco publicar o clipboard: o sequence number do
    # clipboard muda a cada SetClipboardData. Poll até 500ms; sleep fixo de
    # 50ms era pouco para browsers/apps lentos.
    deadline = time.time() + 0.5
    while time.time() < deadline:
        if user32.GetClipboardSequenceNumber() != seq_before:
            time.sleep(0.02)  # margem para o app terminar de escrever os formatos
            return
        time.sleep(0.01)
    print("[WARN] simulate_copy: clipboard nao mudou apos Ctrl+C — nada selecionado ou janela nao responde a Ctrl+C\n")


def paste_via_sendinput() -> None:
    VK_CONTROL = 0x11
    VK_V       = 0x56
    inputs = _key_chord_inputs(VK_CONTROL, VK_V)
    sent = ctypes.windll.user32.SendInput(4, inputs, ctypes.sizeof(_INPUT))
    if sent != 4:
        err = ctypes.windll.kernel32.GetLastError()
        print(f"[WARN] paste: SendInput injetou {sent}/4 eventos (win err {err}) — "
              "paste bloqueado (janela admin ou shell sandboxado); texto ficou no clipboard, use Ctrl+V\n")

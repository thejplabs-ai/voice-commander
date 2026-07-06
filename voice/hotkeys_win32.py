# voice/hotkeys_win32.py — Global hotkeys via Win32 RegisterHotKey (ctypes puro).
#
# Substitui a lib `keyboard` (arquivada upstream, thread de processamento morre
# silenciosamente em qualquer exceção de callback — causa raiz do "hotkey
# morre" em produção).
#
# Gotcha central: RegisterHotKey(None, id, mods, vk) vincula o hotkey à THREAD
# chamadora — o WM_HOTKEY chega na message queue dessa thread. Por isso
# registro E pump (GetMessageW) rodam na MESMA thread daemon, que este módulo
# possui e gerencia (_pump). Callbacks NUNCA rodam na thread do pump — sempre
# despachados para uma worker thread daemon nova (_dispatch_hotkey), para que
# uma exceção no callback do usuário jamais derrube o loop de mensagens.
#
# Rebind em runtime: request_rebind() posta WM_APP_REBIND na thread do pump
# via PostThreadMessageW — thread-safe, sem lock (Win32 enfileira a mensagem).

import ctypes
import ctypes.wintypes
import threading
from typing import Callable

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("message", ctypes.wintypes.UINT),
        ("wParam", ctypes.wintypes.WPARAM),
        ("lParam", ctypes.wintypes.LPARAM),
        ("time", ctypes.wintypes.DWORD),
        ("pt", ctypes.wintypes.POINT),
    ]


# Declarar restype/argtypes explicitamente — sem isso ctypes trunca handles
# 64-bit e não valida os tipos de retorno (mesmo motivo do voice/clipboard.py).
user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.wintypes.UINT, ctypes.wintypes.UINT]

user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]

user32.GetMessageW.restype = ctypes.c_int  # -1/0/nonzero — não é BOOL puro
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.UINT]

user32.PeekMessageW.restype = ctypes.wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(MSG), ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.UINT, ctypes.wintypes.UINT
]

user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL
user32.PostThreadMessageW.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
]

kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD
kernel32.GetLastError.restype = ctypes.wintypes.DWORD


# ── Constantes Win32 ──────────────────────────────────────────────────────────

MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_WIN = 0x8
MOD_NOREPEAT = 0x4000  # suprime auto-repeat do WM_HOTKEY com tecla segurada

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_REBIND = 0x8001  # WM_APP (0x8000) + 1

ERROR_HOTKEY_ALREADY_REGISTERED = 1409


# ── Parser ────────────────────────────────────────────────────────────────────

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}

_KEYS: dict[str, int] = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
for _d in "0123456789":
    _KEYS[_d] = ord(_d)
for _c in "abcdefghijklmnopqrstuvwxyz":
    _KEYS[_c] = ord(_c.upper())
for _n in range(1, 25):
    _KEYS[f"f{_n}"] = 0x70 + (_n - 1)


def parse_hotkey(combo: str) -> tuple[int, int]:
    """'ctrl+shift+space' -> (modifiers, vk). Raises ValueError com mensagem clara em combo inválido.

    Case-insensitive, tolera espaços. Exige >=1 modificador (hotkey global sem
    modificador sequestraria tecla pura do sistema) e exatamente uma tecla
    final não-modificadora. MOD_NOREPEAT é sempre OR-ado no resultado.
    """
    if not combo or not combo.strip():
        raise ValueError(f"combo de hotkey vazio: {combo!r}")

    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"combo de hotkey vazio: {combo!r}")

    mods = 0
    key_parts = []
    for part in parts:
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        else:
            key_parts.append(part)

    if mods == 0:
        raise ValueError(f"combo precisa de pelo menos um modificador: {combo!r}")
    if not key_parts:
        raise ValueError(f"combo precisa de uma tecla além dos modificadores: {combo!r}")
    if len(key_parts) > 1:
        raise ValueError(f"combo precisa de exatamente uma tecla não-modificadora: {combo!r}")

    key = key_parts[0]
    if key not in _KEYS:
        raise ValueError(f"tecla desconhecida no combo: {key!r}")

    return mods | MOD_NOREPEAT, _KEYS[key]


# ── Estado do módulo (singleton — thread do pump é única por processo) ───────

_registered: dict[int, Callable] = {}
_bindings_provider: Callable[[], list[tuple[str, str, Callable]]] | None = None
_failure_reporter: Callable[[list[tuple[str, str, int]]], None] | None = None
_thread: threading.Thread | None = None
_thread_id: int = 0
_ready_event = threading.Event()


# ── Registro / desregistro (funções testáveis sem pump real) ────────────────

def _register_bindings(bindings: list[tuple[str, str, Callable]]) -> list[tuple[str, str, int]]:
    """Registra cada binding via RegisterHotKey. Retorna failures (config_key, combo, win_error_code).

    ValueError do parser vira failure com code 0. Um binding falhar não impede
    o registro dos demais do ciclo. Ids sequenciais por chamada (1..N).
    """
    failures: list[tuple[str, str, int]] = []
    for hotkey_id, (config_key, combo, callback) in enumerate(bindings, start=1):
        try:
            mods, vk = parse_hotkey(combo)
        except ValueError:
            failures.append((config_key, combo, 0))
            continue

        if not user32.RegisterHotKey(None, hotkey_id, mods, vk):
            failures.append((config_key, combo, kernel32.GetLastError()))
            continue

        _registered[hotkey_id] = callback
        print(f"[OK]   Hotkey registrado: {config_key} = {combo}")

    return failures


def _unregister_all() -> None:
    """UnregisterHotKey para cada id atualmente registrado (só os que registraram)."""
    for hotkey_id in list(_registered.keys()):
        user32.UnregisterHotKey(None, hotkey_id)
    _registered.clear()


def _register_all() -> None:
    """(Re)lê bindings_provider(), registra tudo e reporta failures (se houver) uma vez."""
    failures = _register_bindings(_bindings_provider())
    if failures:
        _failure_reporter(failures)


def _dispatch_hotkey(hotkey_id: int) -> None:
    """WM_HOTKEY recebido -> spawna o callback numa worker thread daemon nova.

    NUNCA executa o callback inline (thread do pump não pode travar). Id
    desconhecido é ignorado silenciosamente.
    """
    callback = _registered.get(hotkey_id)
    if callback is not None:
        threading.Thread(target=callback, daemon=True).start()


# ── Thread do pump ────────────────────────────────────────────────────────────

def _pump() -> None:
    global _thread_id

    msg = MSG()
    # PeekMessageW (PM_NOREMOVE=0) cria a message queue desta thread — precisa
    # rodar antes de qualquer RegisterHotKey/GetMessageW na mesma thread.
    user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
    _thread_id = kernel32.GetCurrentThreadId()

    # Guard total: exceção de provider/reporter no registro inicial não pode
    # impedir o _ready_event (start() ficaria bloqueado 5s) nem matar o pump.
    try:
        _register_all()
    except Exception as e:
        print(f"[ERRO] Falha no registro inicial de hotkeys: {e}")
    finally:
        _ready_event.set()

    try:
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:  # WM_QUIT
                break
            if ret == -1:
                print("[ERRO] GetMessageW falhou no pump de hotkeys")
                break

            # Guard do corpo do loop: exceção de handler (dispatch, provider ou
            # reporter no rebind) loga e continua — o pump NUNCA morre por
            # exceção (a classe de falha que este módulo existe pra eliminar).
            try:
                if msg.message == WM_HOTKEY:
                    _dispatch_hotkey(msg.wParam)
                elif msg.message == WM_APP_REBIND:
                    _unregister_all()
                    _register_all()
            except Exception as e:
                print(f"[ERRO] Exceção no pump de hotkeys (msg {msg.message:#06x}): {e}")
    finally:
        # Sempre desregistrar na saída — hotkeys globais órfãos persistem no
        # SO até o fim do processo e bloqueiam re-registro.
        _unregister_all()


# ── API pública ────────────────────────────────────────────────────────────────

def start(
    bindings_provider: Callable[[], list[tuple[str, str, Callable]]],
    failure_reporter: Callable[[list[tuple[str, str, int]]], None],
) -> None:
    """Inicia a thread daemon do message loop e registra os hotkeys.

    bindings_provider: sem args -> list[(config_key, combo, callback)], re-lido
    a cada (re)registro. failure_reporter: chamado (da thread do pump) só se
    houve falhas num ciclo. Aguarda a thread sinalizar prontidão (timeout 5s).
    """
    global _bindings_provider, _failure_reporter, _thread

    if _thread is not None and _thread.is_alive():
        return  # pump já rodando — usar request_rebind() para trocar bindings

    _bindings_provider = bindings_provider
    _failure_reporter = failure_reporter
    _ready_event.clear()
    _thread = threading.Thread(target=_pump, daemon=True, name="HotkeyPump")
    _thread.start()
    if not _ready_event.wait(timeout=5):
        print("[WARN] Hotkey pump não sinalizou prontidão em 5s")


def request_rebind() -> None:
    """Re-registra tudo imediatamente (unregister all -> bindings_provider() -> register).

    Thread-safe via PostThreadMessageW. No-op se não iniciado.
    """
    if _thread is None or not _thread.is_alive():
        return
    if not user32.PostThreadMessageW(_thread_id, WM_APP_REBIND, 0, 0):
        print(f"[WARN] PostThreadMessageW falhou no rebind de hotkeys: erro {kernel32.GetLastError()}")


def stop() -> None:
    """Posta WM_QUIT; pump desregistra tudo e sai. Idempotente."""
    global _thread

    if _thread is None or not _thread.is_alive():
        return
    if not user32.PostThreadMessageW(_thread_id, WM_QUIT, 0, 0):
        print(f"[WARN] PostThreadMessageW falhou no stop de hotkeys: erro {kernel32.GetLastError()}")
    _thread.join(timeout=5)
    _thread = None

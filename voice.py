#!/usr/bin/env python3
"""
Voice-to-text v2  |  JP Labs
Ctrl+Shift+Space        = gravar / parar  →  transcrição pura (PT+EN bilíngue)
Ctrl+Alt+Space          = gravar / parar  →  prompt simples (bullet points)
Ctrl+CapsLock+Space     = gravar / parar  →  prompt estruturado COSTAR via Gemini
Ctrl+Shift+Alt+Space    = gravar / parar  →  query direta Gemini (resposta imediata)

Proteções contra garbling:
- Named mutex (Windows): mata instância anterior automaticamente
- Paste via ctypes.SendInput: bypass total da lib keyboard (zero re-entrada)
- suppress=False nos hotkeys: evita latência em Ctrl/Shift/Alt globais
  (suppress=True causava delay perceptível em Ctrl+C, Ctrl+V, Shift+seta, etc.)
- _toggle_lock: evita dois ciclos paralelos dentro da mesma instância
- current_mode salvo ao INICIAR gravação (não ao parar)
"""

import os
import sys
import builtins
import datetime
import threading
import time
import tempfile
import wave
import ctypes
import ctypes.wintypes

# ---------------------------------------------------------------------------
# Log em arquivo — essencial quando rodando via pythonw (sem console)
# ---------------------------------------------------------------------------
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice.log")

# Reconfigurar stdout/stderr para UTF-8 (evita UnicodeEncodeError com ═, etc.)
# Quando rodando via pythonw.exe, stdout/stderr são None — tratar gracefully
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is not None:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_orig_print = builtins.print

def _log_print(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    # Só chama _orig_print se stdout existir (pythonw não tem console)
    if sys.stdout is not None:
        try:
            _orig_print(*args, **kwargs)
        except Exception:
            pass
    try:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

builtins.print = _log_print

# ---------------------------------------------------------------------------
# Imports que podem falhar (logamos o erro)
# ---------------------------------------------------------------------------
try:
    import sounddevice as sd
    import numpy as np
    import winsound
    import keyboard
except Exception as _e:
    print(f"[ERRO IMPORT] {_e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Named mutex — instância única garantida pelo SO
# ---------------------------------------------------------------------------
_MUTEX_NAME = "Global\\VoiceJPLabs_SingleInstance"
_mutex_handle = None


def _acquire_named_mutex():
    global _mutex_handle
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        print("[ERRO] Outra instância do voice.py já está rodando.")
        sys.exit(1)
    print(f"[OK]   Mutex adquirido (PID {os.getpid()})")


def _release_named_mutex():
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


# ---------------------------------------------------------------------------
# Configuração — carregada uma vez no startup
# ---------------------------------------------------------------------------
_CONFIG: dict = {}
_GEMINI_API_KEY: str | None = None

_DEFAULT_QUERY_SYSTEM_PROMPT = (
    "Você é um assistente direto e preciso. "
    "Responda à pergunta do usuário de forma clara, concisa e útil. "
    "Vá direto ao ponto sem rodeios desnecessários. "
    "O texto pode misturar português e inglês — responda no mesmo idioma da pergunta."
)


def load_config() -> dict:
    """Carrega todas as configurações do .env uma vez no startup."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    config: dict = {
        "GEMINI_API_KEY": None,
        "WHISPER_MODEL": "small",
        "MAX_RECORD_SECONDS": 120,
        "AUDIO_DEVICE_INDEX": None,
        "QUERY_HOTKEY": "ctrl+shift+alt+space",
        "QUERY_SYSTEM_PROMPT": "",
    }
    if not os.path.exists(env_path):
        return config
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in config and val:
                if key == "MAX_RECORD_SECONDS":
                    try:
                        config[key] = int(val)
                    except ValueError:
                        pass
                elif key == "AUDIO_DEVICE_INDEX":
                    try:
                        config[key] = int(val)
                    except ValueError:
                        pass
                else:
                    config[key] = val
    # Filtrar placeholder
    if config["GEMINI_API_KEY"] == "your_gemini_api_key_here":
        config["GEMINI_API_KEY"] = None
    return config


# ---------------------------------------------------------------------------
# Configuração de áudio
# ---------------------------------------------------------------------------
SAMPLE_RATE     = 16000
CHANNELS        = 1
stop_event      = threading.Event()
is_recording    = False
is_transcribing = False
frames_buf      = []
record_thread   = None
_toggle_lock    = threading.Lock()
current_mode    = "transcribe"  # "transcribe" | "simple" | "prompt" | "query"

# ---------------------------------------------------------------------------
# Story 2.1 — System Tray (pystray + Pillow)
# ---------------------------------------------------------------------------
_tray_icon = None
_tray_available = False
_tray_state = "idle"        # "idle" | "recording" | "processing"
_tray_last_mode = "—"

# Tentar importar pystray e Pillow — fallback silencioso se não disponíveis
try:
    import pystray
    from PIL import Image, ImageDraw
    _tray_available = True
except ImportError:
    print("[WARN] pystray/Pillow não instalados — system tray desativado. "
          "Instale com: pip install pystray Pillow")


def _make_tray_icon(state: str = "idle") -> "Image.Image":
    """
    Gera ícone 64x64 RGBA com círculo colorido indicando o estado:
    - idle:       cinza  (#808080)
    - recording:  vermelho (#FF3333)
    - processing: amarelo  (#FFD700)
    """
    color_map = {
        "idle":       "#808080",
        "recording":  "#FF3333",
        "processing": "#FFD700",
    }
    color = color_map.get(state, "#808080")
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Círculo preenchido com margem de 4px
    draw.ellipse([4, 4, 60, 60], fill=color)
    return img


def _tray_tooltip() -> str:
    state_labels = {
        "idle":       "Idle",
        "recording":  "Gravando",
        "processing": "Processando",
    }
    label = state_labels.get(_tray_state, _tray_state)
    return f"Voice Commander | {label} | Último: {_tray_last_mode}"


def _update_tray_state(state: str, mode: str | None = None) -> None:
    """Atualiza ícone e tooltip da system tray."""
    global _tray_state, _tray_last_mode
    _tray_state = state
    if mode is not None:
        _tray_last_mode = mode
    if _tray_icon is not None and _tray_available:
        try:
            _tray_icon.icon = _make_tray_icon(state)
            _tray_icon.title = _tray_tooltip()
        except Exception as e:
            print(f"[WARN] Falha ao atualizar ícone da tray: {e}")


def _tray_show_status(icon, item) -> None:  # type: ignore[type-arg]
    """Menu item 'Status' — exibe MessageBox com info atual."""
    state_labels = {
        "idle":       "Idle (aguardando hotkey)",
        "recording":  "Gravando...",
        "processing": "Processando transcrição...",
    }
    mode_labels = {
        "transcribe": "Transcrição pura",
        "simple":     "Prompt simples",
        "prompt":     "Prompt COSTAR",
        "query":      "Query Gemini",
        "—":          "—",
    }
    gemini_status = "Ativo" if _GEMINI_API_KEY else "Desativado"
    state_label = state_labels.get(_tray_state, _tray_state)
    mode_label  = mode_labels.get(_tray_last_mode, _tray_last_mode)
    msg = (
        f"Voice Commander — JP Labs\n\n"
        f"Estado:      {state_label}\n"
        f"Último modo: {mode_label}\n"
        f"Gemini:      {gemini_status}\n"
        f"Whisper:     {_CONFIG.get('WHISPER_MODEL', 'small')}\n"
        f"Log:         {_log_path}"
    )
    ctypes.windll.user32.MessageBoxW(0, msg, "Voice Commander — Status", 0x40)


def _tray_on_quit(icon, item) -> None:  # type: ignore[type-arg]
    """Menu item 'Encerrar' — shutdown gracioso."""
    print("[INFO] Encerramento solicitado via system tray.")
    stop_event.set()
    try:
        icon.stop()
    except Exception:
        pass
    _release_named_mutex()
    os._exit(0)


def _start_tray() -> None:
    """Inicia system tray em thread daemon. Fallback silencioso se pystray indisponível."""
    global _tray_icon

    if not _tray_available:
        return

    try:
        menu = pystray.Menu(
            pystray.MenuItem("Status", _tray_show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Encerrar", _tray_on_quit),
        )
        _tray_icon = pystray.Icon(
            name="VoiceCommander",
            icon=_make_tray_icon("idle"),
            title=_tray_tooltip(),
            menu=menu,
        )

        def _run_tray():
            try:
                _tray_icon.run()
            except Exception as e:
                print(f"[WARN] System tray encerrada inesperadamente: {e}")

        t = threading.Thread(target=_run_tray, daemon=True)
        t.start()
        print("[OK]   System tray iniciada")
    except Exception as e:
        print(f"[WARN] Falha ao iniciar system tray: {e}")


def _stop_tray() -> None:
    """Remove ícone da tray corretamente (sem fantasma)."""
    global _tray_icon
    if _tray_icon is not None and _tray_available:
        try:
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon = None


# ---------------------------------------------------------------------------
# Whisper — lazy load
# ---------------------------------------------------------------------------
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        model_name = _CONFIG.get("WHISPER_MODEL", "small")
        print(f"[...] Carregando Whisper {model_name} (primeira vez — pode demorar ~30s)...")
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print("[OK]  Whisper pronto (PT+EN bilíngue)")
    return _whisper_model


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------
def load_gemini_key() -> str | None:
    """Mantido para compatibilidade. No startup, use _GEMINI_API_KEY global."""
    return _CONFIG.get("GEMINI_API_KEY")


def correct_with_gemini(text: str) -> str:
    if not _GEMINI_API_KEY:
        return text
    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)
        prompt = (
            "Você é um corretor de transcrição de voz para texto em português brasileiro e inglês.\n"
            "O texto abaixo foi gerado por speech-to-text e pode conter erros de transcrição, "
            "palavras erradas, falta de pontuação, ou frases cortadas.\n"
            "O texto pode misturar português e inglês (code-switching) — preserve ambos os idiomas.\n"
            "Corrija esses erros mantendo o sentido e o estilo original.\n"
            "Retorne APENAS o texto corrigido, sem explicações, sem aspas, sem prefixos.\n\n"
            f"Texto: {text}"
        )
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        corrected = response.text.strip()
        if corrected:
            print(f"[OK]   Original : {text}")
            print(f"[OK]   Corrigido: {corrected}")
            return corrected
    except Exception as e:
        print(f"[WARN] Gemini indisponível ({e}), usando texto original")
    return text


def simplify_as_prompt(text: str) -> str:
    """
    Organiza a transcrição em prompt limpo com bullet points — sem XML, sem COSTAR.
    Fidelidade total ao input: nenhum detalhe omitido, output proporcional à riqueza do input.
    """
    if not _GEMINI_API_KEY:
        return text

    word_count = len(text.split())
    print(f"[...]  Input: {word_count} palavras → modo prompt simples (fidelidade total)")

    meta_prompt = f"""Você é especialista em prompt engineering.
O texto abaixo é transcrição de voz informal (pode misturar PT e EN).
Transforme-o em um prompt limpo e direto para usar em qualquer LLM.

PRIORIDADE ABSOLUTA: Preservar CADA detalhe, contexto e nuance que o usuário mencionou.
Não comprima, não resuma, não omita nenhuma informação do input.
Se o input for longo e detalhado, o output também deve ser longo e detalhado.

ESTRUTURA:
1. Um ou mais parágrafos explicando o contexto e o que se quer — sem label, só texto corrido
2. Requisitos, detalhes específicos ou etapas listados como bullet points logo abaixo

REGRAS:
- Sem XML, sem seções SYSTEM/USER, sem headers, sem labels como "Contexto:" ou "Objetivo:"
- Os bullet points devem ser frases completas, não palavras soltas
- Preserve a intenção original completamente — não invente nem omita nada do input
- A quantidade de linhas e bullets deve ser proporcional à riqueza do input
- Retorne APENAS o prompt, sem explicações adicionais

Transcrição: {text}"""

    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=meta_prompt,
            config=genai.types.GenerateContentConfig(temperature=0.1),
        )
        simplified = response.text.strip()
        if simplified:
            print(f"[OK]   Prompt simplificado ({len(simplified)} chars)")
            return simplified
    except Exception as e:
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


def structure_as_prompt(text: str) -> str:
    if not _GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando texto original")
        return text

    meta_prompt = f"""Você é especialista em prompt engineering para LLMs (Claude, GPT-4, Gemini).
O texto abaixo é transcrição de voz informal (pode misturar PT e EN).
Transforme-o em prompt estruturado profissional usando o framework COSTAR com XML tags.

Siga EXATAMENTE este formato (substitua os colchetes pelo conteúdo):

═══════════════════════════════════════
SYSTEM PROMPT
═══════════════════════════════════════
<role>
[Papel e persona ideal para executar esta tarefa]
</role>

<behavior>
[2-4 diretrizes comportamentais específicas e relevantes]
</behavior>

<output_format>
[Formato exato do output: markdown, JSON, lista, prosa, etc.]
</output_format>

═══════════════════════════════════════
USER PROMPT
═══════════════════════════════════════
<context>
[Background, situação atual, dados relevantes]
</context>

<objective>
[Tarefa específica e clara — o que exatamente deve ser feito]
</objective>

<style_and_tone>
[Estilo de escrita, tom (formal/direto/técnico) e audiência-alvo]
</style_and_tone>

<response>
[Formato e constraints da resposta: tamanho, idioma, estrutura]
</response>

REGRAS:
- Infira o papel ideal com base na natureza da tarefa
- Seja específico em todas as seções (nunca deixe vago)
- Preserve a intenção original do usuário
- Retorne APENAS o prompt estruturado, sem explicações adicionais

Transcrição: {text}"""

    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=meta_prompt)
        structured = response.text.strip()
        if structured:
            print(f"[OK]   Prompt estruturado ({len(structured)} chars)")
            return structured
    except Exception as e:
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


# ---------------------------------------------------------------------------
# Story 2.2 — Modo 4: Query Direta Gemini
# ---------------------------------------------------------------------------
def query_with_gemini(text: str) -> str:
    """
    Envia a transcrição diretamente ao Gemini como pergunta/query e retorna a resposta.
    Fallback sem Gemini: retorna texto original com prefixo informativo.
    """
    if not _GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando transcrição com prefixo")
        return f"[SEM RESPOSTA GEMINI] {text}"

    system_prompt = _CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
    if not system_prompt:
        system_prompt = _DEFAULT_QUERY_SYSTEM_PROMPT

    print(f"[...]  Query Gemini ({len(text)} chars)...")

    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)

        # Combina system prompt + query do usuário em um único contents
        full_prompt = f"{system_prompt}\n\n{text}"

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=full_prompt,
            config=genai.types.GenerateContentConfig(temperature=0.3),
        )
        answer = response.text.strip()
        if answer:
            print(f"[OK]   Resposta Gemini ({len(answer)} chars)")
            return answer
    except Exception as e:
        print(f"[WARN] Gemini indisponível ({e}), retornando transcrição com prefixo")

    return f"[SEM RESPOSTA GEMINI] {text}"


# ---------------------------------------------------------------------------
# Clipboard + Paste
# ---------------------------------------------------------------------------
def copy_to_clipboard(text: str) -> None:
    import subprocess
    proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
    proc.communicate(input=text.encode('utf-16le'))
    proc.wait()


def paste_via_sendinput() -> None:
    INPUT_KEYBOARD  = 1
    KEYEVENTF_KEYUP = 0x0002

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.wintypes.WORD),
            ("wScan",       ctypes.wintypes.WORD),
            ("dwFlags",     ctypes.wintypes.DWORD),
            ("time",        ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
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


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------
def record() -> list:
    frames = []
    stop_event.clear()
    max_seconds = _CONFIG.get("MAX_RECORD_SECONDS", 120)
    max_frames = int(max_seconds * SAMPLE_RATE / 1024)
    warn_frames = int((max_seconds - 5) * SAMPLE_RATE / 1024)  # aviso 5s antes
    frame_count = 0

    device_index = _CONFIG.get("AUDIO_DEVICE_INDEX")

    try:
        stream_kwargs: dict = {
            "samplerate": SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": "float32",
        }
        if device_index is not None:
            stream_kwargs["device"] = device_index

        with sd.InputStream(**stream_kwargs) as stream:
            while not stop_event.is_set():
                data, _ = stream.read(1024)
                frames.append(data.copy())
                frame_count += 1

                if frame_count == warn_frames:
                    winsound.Beep(600, 200)  # bip de aviso 5s antes (frequência distinta)
                    print(f"[WARN] Gravação encerra em 5s (limite: {max_seconds}s)")

                if frame_count >= max_frames:
                    print(f"[WARN] Timeout de gravação atingido ({max_seconds}s)")
                    stop_event.set()
                    break

    except Exception as e:
        print(f"[ERRO gravação] {e}")
    return frames


# ---------------------------------------------------------------------------
# Transcrição + pós-processamento
# ---------------------------------------------------------------------------
def transcribe(frames: list, mode: str = "transcribe") -> None:
    global is_transcribing
    if not frames:
        print("[ERRO]  Sem áudio\n")
        winsound.Beep(200, 300)
        is_transcribing = False
        _update_tray_state("idle")
        return

    # Atualizar tray para "processando"
    _update_tray_state("processing", mode)

    print("[...]  Transcrevendo (Whisper)...")
    audio_data = np.concatenate(frames, axis=0)
    temp_path = None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name

    try:
        with wave.open(temp_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())

        model = get_whisper_model()
        segments, _ = model.transcribe(temp_path, language=None)
        raw_text = " ".join(s.text for s in segments).strip()

        if not raw_text:
            print("[ERRO]  Não entendi. Tente novamente.\n")
            winsound.Beep(200, 300)
            return

        print(f"[OK]   Whisper: {raw_text}")

        if mode == "prompt":
            print("[...]  Estruturando prompt (COSTAR)...")
            text = structure_as_prompt(raw_text)
        elif mode == "simple":
            print("[...]  Simplificando prompt...")
            text = simplify_as_prompt(raw_text)
        elif mode == "query":
            print("[...]  Consultando Gemini (query direta)...")
            text = query_with_gemini(raw_text)
        else:
            print("[...]  Corrigindo...")
            text = correct_with_gemini(raw_text)

        copy_to_clipboard(text)
        print(f"[OK]   Texto no clipboard ({len(text)} chars)")

        winsound.Beep(440, 100)
        winsound.Beep(440, 100)

        time.sleep(0.5)
        paste_via_sendinput()

        print("[OK]   Colado!\n")

    except Exception as e:
        print(f"[ERRO]  {e}\n")
        winsound.Beep(200, 300)
    finally:
        is_transcribing = False
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        # Voltar tray para idle após finalizar
        _update_tray_state("idle")


# ---------------------------------------------------------------------------
# Toggle recording
# ---------------------------------------------------------------------------
def toggle_recording(mode: str = "transcribe") -> None:
    global is_recording, is_transcribing, frames_buf, record_thread, current_mode

    with _toggle_lock:
        if is_transcribing:
            print("[SKIP] Aguardando transcrição anterior terminar...\n")
            winsound.Beep(300, 150)
            return

        if not is_recording:
            current_mode = mode
            is_recording = True
            frames_buf = []
            stop_event.clear()

            # Atualizar tray para "gravando"
            _update_tray_state("recording", mode)

            if mode == "transcribe":
                winsound.Beep(880, 200)
                print("[REC]  Gravando... (Ctrl+Shift+Space para parar)\n")
            elif mode == "simple":
                winsound.Beep(880, 150)
                time.sleep(0.05)
                winsound.Beep(880, 150)
                time.sleep(0.05)
                winsound.Beep(880, 150)
                print("[REC]  Gravando para PROMPT SIMPLES... (Ctrl+Alt+Space para parar)\n")
            elif mode == "query":
                # Bip distinto: 1 longo (880Hz 400ms) + 1 curto (1100Hz 150ms)
                winsound.Beep(880, 400)
                time.sleep(0.05)
                winsound.Beep(1100, 150)
                print("[REC]  Gravando para QUERY GEMINI... (mesmo hotkey para parar)\n")
            else:
                winsound.Beep(880, 150)
                time.sleep(0.05)
                winsound.Beep(880, 150)
                print("[REC]  Gravando para PROMPT COSTAR... (Ctrl+CapsLock+Space para parar)\n")

            def do_record():
                global frames_buf
                frames_buf = record()

            record_thread = threading.Thread(target=do_record, daemon=True)
            record_thread.start()
        else:
            is_recording = False
            is_transcribing = True
            stop_event.set()
            print("[STOP] Parando gravação...\n")
            if record_thread:
                record_thread.join(timeout=3)
            threading.Thread(
                target=transcribe,
                args=(list(frames_buf), current_mode),
                daemon=True,
            ).start()


# ---------------------------------------------------------------------------
# Hotkeys
# ---------------------------------------------------------------------------
def on_hotkey(mode: str = "transcribe") -> None:
    threading.Thread(target=toggle_recording, args=(mode,), daemon=True).start()


# ---------------------------------------------------------------------------
# Story 2.3 — Validação de microfone no startup
# ---------------------------------------------------------------------------
def validate_microphone() -> None:
    """
    Testa o sd.InputStream com o dispositivo configurado.
    Timeout: 3 segundos via thread com join(timeout=3).
    App continua mesmo se a validação falhar.
    """
    device_index = _CONFIG.get("AUDIO_DEVICE_INDEX")
    device_display = str(device_index) if device_index is not None else "padrão"

    mic_ok_flag = [False]
    mic_error: list = []

    def _test_mic():
        try:
            stream_kwargs: dict = {
                "samplerate": SAMPLE_RATE,
                "channels": CHANNELS,
                "dtype": "float32",
            }
            if device_index is not None:
                stream_kwargs["device"] = device_index

            with sd.InputStream(**stream_kwargs) as stream:
                stream.read(64)  # Leitura mínima para confirmar abertura
            mic_ok_flag[0] = True
        except Exception as e:
            mic_error.append(str(e))

    t = threading.Thread(target=_test_mic, daemon=True)
    t.start()
    t.join(timeout=3)

    if mic_ok_flag[0]:
        print(f"[OK]   Microfone validado (dispositivo: {device_display})")
    else:
        error_detail = mic_error[0] if mic_error else "timeout"
        print(
            f"[WARN] Microfone não acessível (dispositivo: {device_display}) "
            f"— verifique permissões de áudio ({error_detail})"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    global _CONFIG, _GEMINI_API_KEY

    # Limpa log anterior
    try:
        with open(_log_path, "w", encoding="utf-8") as f:
            f.write(f"=== voice.py iniciado {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception:
        pass

    # Carrega configurações uma vez
    _CONFIG = load_config()
    _GEMINI_API_KEY = _CONFIG.get("GEMINI_API_KEY")

    # Log de startup
    gemini_ok = _GEMINI_API_KEY is not None
    key_display = f"***{_GEMINI_API_KEY[-4:]}" if gemini_ok else "não configurada"
    device_display = str(_CONFIG["AUDIO_DEVICE_INDEX"]) if _CONFIG["AUDIO_DEVICE_INDEX"] is not None else "padrão do sistema"
    query_hotkey = _CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space")

    print("═" * 54)
    print("  Voice-to-text v2  |  JP Labs")
    print("═" * 54)
    print("  [Ctrl+Shift+Space]          Transcrição pura")
    print("  [Ctrl+Alt+Space]            Prompt simples (bullet points)")
    print("  [Ctrl+CapsLock+Space]       Prompt estruturado (COSTAR)")
    print(f"  [{query_hotkey.title()}]  Query direta Gemini")
    print("  Idiomas : PT-BR + EN (automático)")
    print(f"  Gemini  : {'ativo (' + key_display + ')' if gemini_ok else 'desativado (sem .env)'}")
    print(f"  Whisper : {_CONFIG['WHISPER_MODEL']}")
    print(f"  Timeout : {_CONFIG['MAX_RECORD_SECONDS']}s")
    print(f"  Mic     : {device_display}")
    print("  Sair    : Ctrl+C (ou menu System Tray > Encerrar)")
    print("═" * 54 + "\n")

    _acquire_named_mutex()

    # Story 2.3 — Validar microfone após adquirir mutex
    validate_microphone()

    # Story 2.1 — Iniciar system tray (thread daemon, fallback silencioso)
    _start_tray()

    # Loop de resiliência: se keyboard.wait() retornar inesperadamente
    # (exception não capturada, sinal externo, etc.), os hotkeys são
    # re-registrados e o loop recomeça. Ctrl+C encerra limpo.
    _restart_count = 0
    while True:
        # Limpa hotkeys anteriores antes de re-registrar (evita duplicatas no restart)
        try:
            keyboard.unhook_all()
        except Exception:
            pass

        try:
            # suppress=False: sem latência em Ctrl/Shift/Alt globais.
            # O Space que "vaza" para a aplicação ativa é inofensivo na prática.
            keyboard.add_hotkey("ctrl+shift+space",     lambda: on_hotkey("transcribe"), suppress=False)
            keyboard.add_hotkey("ctrl+alt+space",       lambda: on_hotkey("simple"),     suppress=False)
            keyboard.add_hotkey("ctrl+caps lock+space", lambda: on_hotkey("prompt"),     suppress=False)
            keyboard.add_hotkey(
                _CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space"),
                lambda: on_hotkey("query"),
                suppress=False,
            )

            if _restart_count == 0:
                print("[OK]   Hotkeys registrados. Aguardando...\n")
            else:
                print(f"[OK]   Hotkeys re-registrados (restart #{_restart_count}). Aguardando...\n")

            keyboard.wait()

            # keyboard.wait() retornou sem exceção — significa saída limpa (ex: Ctrl+C capturado
            # internamente pela lib). Encerrar.
            break

        except KeyboardInterrupt:
            # Ctrl+C explícito — saída intencional
            break

        except Exception as e:
            _restart_count += 1
            print(f"[ERRO] Loop de hotkeys crashou: {e}")
            print(f"[INFO] Reiniciando hotkeys em 3s (tentativa #{_restart_count})...\n")
            time.sleep(3)
            continue  # Reinicia o while

    stop_event.set()
    _stop_tray()
    _release_named_mutex()
    print("\nSaindo...")


if __name__ == "__main__":
    main()

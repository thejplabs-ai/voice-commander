#!/usr/bin/env python3
"""
Voice-to-text v2  |  JP Labs
Ctrl+Shift+Space    = gravar / parar  →  transcrição pura (PT+EN bilíngue)
Ctrl+Alt+Space      = gravar / parar  →  prompt simples (bullet points)
Ctrl+CapsLock+Space = gravar / parar  →  prompt estruturado COSTAR via Gemini

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
current_mode    = "transcribe"  # "transcribe" ou "prompt"

# ---------------------------------------------------------------------------
# Whisper — lazy load
# ---------------------------------------------------------------------------
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        print("[...] Carregando Whisper base (primeira vez — pode demorar ~30s)...")
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        print("[OK]  Whisper pronto (PT+EN bilíngue)")
    return _whisper_model


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------
def load_gemini_key():
    # .env na raiz do próprio repositório (mesma pasta que voice.py)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return None
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key and key != "your_api_key_here":
                    return key
    return None


def correct_with_gemini(text):
    api_key = load_gemini_key()
    if not api_key:
        return text
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
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


def simplify_as_prompt(text):
    """
    Organiza a transcrição em prompt limpo com bullet points — sem XML, sem COSTAR.
    Fidelidade total ao input: nenhum detalhe omitido, output proporcional à riqueza do input.
    """
    api_key = load_gemini_key()
    if not api_key:
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
        client = genai.Client(api_key=api_key)
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


def structure_as_prompt(text):
    api_key = load_gemini_key()
    if not api_key:
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
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=meta_prompt)
        structured = response.text.strip()
        if structured:
            print(f"[OK]   Prompt estruturado ({len(structured)} chars)")
            return structured
    except Exception as e:
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


# ---------------------------------------------------------------------------
# Clipboard + Paste
# ---------------------------------------------------------------------------
def copy_to_clipboard(text):
    import subprocess
    proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
    proc.communicate(input=text.encode('utf-16le'))
    proc.wait()


def paste_via_sendinput():
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
def record():
    frames = []
    stop_event.clear()
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
            while not stop_event.is_set():
                data, _ = stream.read(1024)
                frames.append(data.copy())
    except Exception as e:
        print(f"[ERRO gravação] {e}")
    return frames


# ---------------------------------------------------------------------------
# Transcrição + pós-processamento
# ---------------------------------------------------------------------------
def transcribe(frames, mode="transcribe"):
    global is_transcribing
    if not frames:
        print("[ERRO]  Sem áudio\n")
        winsound.Beep(200, 300)
        is_transcribing = False
        return

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


# ---------------------------------------------------------------------------
# Toggle recording
# ---------------------------------------------------------------------------
def toggle_recording(mode="transcribe"):
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
def on_hotkey(mode="transcribe"):
    threading.Thread(target=toggle_recording, args=(mode,), daemon=True).start()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Limpa log anterior
    try:
        with open(_log_path, "w", encoding="utf-8") as f:
            f.write(f"=== voice.py iniciado {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception:
        pass

    gemini_ok = load_gemini_key() is not None

    print("═" * 48)
    print("  Voice-to-text v2  |  JP Labs")
    print("═" * 48)
    print("  [Ctrl+Shift+Space]     Transcrição pura")
    print("  [Ctrl+Alt+Space]       Prompt simples (bullet points)")
    print("  [Ctrl+CapsLock+Space]  Prompt estruturado (COSTAR)")
    print("  Idiomas : PT-BR + EN (automático)")
    print(f"  Gemini  : {'ativo' if gemini_ok else 'desativado (sem .env)'}")
    print("  Sair    : Ctrl+C")
    print("═" * 48 + "\n")

    _acquire_named_mutex()

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
    _release_named_mutex()
    print("\nSaindo...")


if __name__ == "__main__":
    main()

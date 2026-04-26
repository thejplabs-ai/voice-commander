# voice/whisper.py — Whisper model loading, CUDA DLL discovery, transcription logic

import os
import sys

from voice import state

# ── CUDA DLL discovery ───────────────────────────────────────────────────────
# ctranslate2 requer cublas64_12.dll e cudnn64_9.dll no DLL search path.
# Quando instalados via pip (nvidia-cublas-cu12, nvidia-cudnn-cu12), ficam
# em site-packages/nvidia/*/bin/ — fora do PATH do sistema.
# Registrar ANTES de qualquer import do faster_whisper/ctranslate2.
def _register_cuda_dlls() -> None:
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return
    # PyInstaller: DLLs ficam no _MEIPASS (mesma pasta do exe)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass and os.path.isdir(meipass):
            os.add_dll_directory(meipass)
        return
    # Dev: DLLs nos pacotes nvidia pip (site-packages/nvidia/*/bin/)
    try:
        import nvidia.cublas
        import nvidia.cudnn
        for pkg in (nvidia.cublas, nvidia.cudnn):
            bin_dir = os.path.join(os.path.dirname(pkg.__path__[0]), pkg.__name__.split(".")[-1], "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
    except ImportError:
        pass  # nvidia.cublas/cudnn não instalados — CUDA via toolkit ou indisponível
    except (AttributeError, OSError) as e:
        print(f"[WARN] CUDA DLL discovery falhou ({type(e).__name__}: {e}) — continuando sem add_dll_directory")

_register_cuda_dlls()

# ── Constants ─────────────────────────────────────────────────────────────────

SAMPLE_RATE = 16000

_FAST_MODES    = {"transcribe", "bullet", "email", "translate"}
_QUALITY_MODES = {"simple", "prompt", "query"}

_HOTWORDS = (
    "deploy, build, pipeline, debounce, commit, branch, merge, "
    "webhook, script, frontend, backend, API, token, workflow, "
    "debug, SOP, prompt, buffer, cache, endpoint, payload, query"
)

_DEFAULT_INITIAL_PROMPT = (
    "Falo português brasileiro com termos técnicos em inglês. "
    "Exemplos: 'o build falhou', 'faz o deploy', 'testa o pipeline', "
    "'o debounce não funciona', 'criar um SOP', 'estruturar o prompt', "
    "'o webhook está caindo', 'revisar o script', 'o frontend quebrou', "
    "'configurar a API', 'commitar as mudanças', 'fazer o merge', "
    "'o token expirou', 'rodar o workflow', 'debug do backend'."
)


# ── Symlink resolution ────────────────────────────────────────────────────────

def _resolve_hf_model_path(model_name: str) -> str | None:
    """Resolve o path real de um modelo HuggingFace, resolvendo symlinks.

    ctranslate2 (C++) não segue symlinks do HuggingFace no Windows em certos
    contextos (pós-install do Inno Setup, UAC elevation). Esta função encontra
    o snapshot directory e resolve model.bin para o blob real.
    Retorna o path do diretório com arquivos reais, ou None se não encontrar.
    """
    hf_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    model_dir = os.path.join(hf_cache, f"models--Systran--faster-whisper-{model_name}", "snapshots")
    if not os.path.isdir(model_dir):
        return None
    # Pegar o snapshot mais recente
    try:
        snapshots = [d for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d))]
    except OSError:
        return None
    if not snapshots:
        return None
    snapshot = os.path.join(model_dir, snapshots[-1])
    model_bin = os.path.join(snapshot, "model.bin")
    # Se model.bin é symlink, resolver para o path real
    if os.path.islink(model_bin):
        real_path = os.path.realpath(model_bin)
        if os.path.exists(real_path):
            # Retornar o diretório do snapshot — ctranslate2 espera um diretório
            # com model.bin, config.json, etc. Precisamos criar um temp dir com
            # os arquivos resolvidos? Não — mais simples: substituir symlinks por hardlinks.
            _resolve_symlinks_in_dir(snapshot)
            return snapshot
    elif os.path.exists(model_bin):
        return snapshot  # Arquivo real, sem symlink
    return None


def _resolve_symlinks_in_dir(directory: str) -> None:
    """Substitui symlinks por hardlinks no diretório (Windows-safe).

    Hardlinks funcionam sem privilégios especiais no mesmo filesystem.
    Se hardlink falhar (cross-device), faz copy.
    """
    import shutil
    for entry in os.listdir(directory):
        full_path = os.path.join(directory, entry)
        if os.path.islink(full_path):
            real_target = os.path.realpath(full_path)
            if os.path.exists(real_target):
                try:
                    os.remove(full_path)
                    os.link(real_target, full_path)
                except OSError:
                    # Cross-device ou sem permissão para hardlink — copiar
                    try:
                        os.remove(full_path) if os.path.exists(full_path) else None
                        shutil.copy2(real_target, full_path)
                    except Exception as e:
                        print(f"[WARN] Falha ao resolver symlink {entry}: {e}")


# ── Whisper model loader ───────────────────────────────────────────────────────

def _is_oom_error(err_msg: str) -> bool:
    """Detecta erros de OOM no texto de uma exception (string já em lowercase)."""
    return (
        "out of memory" in err_msg
        or "oom" in err_msg
        or "cuda failed" in err_msg
    )


def get_whisper_model(mode: str = "transcribe"):
    """Lazy-load Whisper. Seleciona modelo e device com base no modo.

    Thread-safe: protegido por state._whisper_model_lock (double-check pattern)
    para evitar race entre _preload_whisper() e primeira transcrição — sem o
    lock, ambos podem disparar WhisperModel(...) em paralelo, duplicando VRAM
    (OOM com large-v3).

    Fallback chain: configured model/cuda → configured model/cpu → tiny/cpu.
    Se ctranslate2 falhar com 'Unable to open file' (symlinks do HuggingFace no
    Windows), resolve symlinks para hardlinks e tenta novamente.
    """
    device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    if mode in _FAST_MODES:
        model_name = state._CONFIG.get("WHISPER_MODEL_FAST") or state._CONFIG.get("WHISPER_MODEL", "tiny")
    elif mode in _QUALITY_MODES:
        model_name = state._CONFIG.get("WHISPER_MODEL_QUALITY") or state._CONFIG.get("WHISPER_MODEL", "tiny")
    else:
        model_name = state._CONFIG.get("WHISPER_MODEL", "tiny")

    cache_key = (model_name, device)
    # Fast path sem lock — cache hit comum, evita contenção
    if state._whisper_model is not None and state._whisper_cache_key == cache_key:
        return state._whisper_model

    with state._whisper_model_lock:
        # Double-check dentro do lock — outra thread pode ter carregado enquanto
        # esperávamos o lock.
        if state._whisper_model is not None and state._whisper_cache_key == cache_key:
            return state._whisper_model

        if state._whisper_model is not None:
            print(f"[INFO] Whisper reconfigurando: {state._whisper_cache_key} → {cache_key}")
        else:
            print(f"[...] Carregando Whisper {model_name} em {device} (modo: {mode})...")

        # int8_float16 em CUDA: menor pegada de VRAM + menos fragmentação que int8 puro.
        # int8 em CPU: mantém o comportamento original.
        compute = "int8_float16" if device == "cuda" else "int8"

        from faster_whisper import WhisperModel
        try:
            state._whisper_model = WhisperModel(model_name, device=device, compute_type=compute)
            state._whisper_cache_key = cache_key
            print(f"[OK]  Whisper {model_name}/{device} pronto (PT-BR âncora + termos EN via hotwords)")
        except Exception as _err:
            err_msg = str(_err).lower()
            # Symlink issue: ctranslate2 não segue symlinks do HuggingFace no Windows
            if "unable to open" in err_msg and "model.bin" in err_msg:
                resolved = _resolve_hf_model_path(model_name)
                if resolved:
                    print("[INFO] Symlinks HuggingFace resolvidos — tentando novamente...")
                    try:
                        state._whisper_model = WhisperModel(resolved, device=device, compute_type=compute)
                        state._whisper_cache_key = cache_key
                        print(f"[OK]  Whisper {model_name}/{device} pronto (symlinks resolvidos)")
                        return state._whisper_model
                    except Exception as _resolved_err:
                        print(f"[WARN] Ainda falhou após resolver symlinks: {_resolved_err}")
                        _err = _resolved_err
                        err_msg = str(_resolved_err).lower()

            # OOM explícito — log claro ANTES do fallback (observabilidade Bug #2)
            if _is_oom_error(err_msg):
                print(f"[ERRO] VRAM insuficiente carregando {model_name} em {device}. Fallback acionado.")

            # Fallback 1: CUDA → CPU com mesmo modelo
            if device == "cuda":
                print(f"[WARN] CUDA indisponível ({type(_err).__name__}: {_err}) — fallback para CPU")
                device = "cpu"
                try:
                    state._whisper_model = WhisperModel(model_name, device=device, compute_type="int8")
                    state._whisper_cache_key = (model_name, device)
                    print(f"[OK]  Whisper {model_name}/cpu pronto (fallback CPU)")
                    return state._whisper_model
                except Exception as _cpu_err:
                    print(f"[WARN] Modelo {model_name}/cpu também falhou ({_cpu_err})")
                    # Continua para fallback 2

            # Fallback 2: modelo de emergência tiny/cpu (sempre disponível, ~75MB)
            if model_name != "tiny":
                print("[WARN] Fallback emergencial: tiny/cpu")
                try:
                    state._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
                    state._whisper_cache_key = ("tiny", "cpu")
                    print("[OK]  Whisper tiny/cpu pronto (fallback emergencial)")
                    return state._whisper_model
                except Exception as _tiny_err:
                    print(f"[ERRO] Fallback tiny/cpu falhou: {_tiny_err}")
                    raise
            raise
        return state._whisper_model



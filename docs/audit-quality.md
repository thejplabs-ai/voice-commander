# Code Quality & Performance Audit -- Voice Commander

**Data:** 2026-04-03
**Agente:** QUINN (QA Specialist)
**Resultado:** BLOQUEADO -- 2 CRITICAL, 6 HIGH

---

## 1. Startup Performance (Diagnostico app.py)

### Mapa de inicializacao de `main()`:

```
1. SetCurrentProcessExplicitAppUserModelID     ~0ms
2. load_config()                                ~5ms (I/O .env)
3. load_profile()                               ~5ms (I/O user-profile.json)
4. _needs_onboarding() check                    ~0ms
5. _rotate_log()                                ~10ms (glob + rename)
6. _cleanup_temp_wavs()                         ~5ms (glob + stat)
7. _log_startup_info()                          ~0ms
8. threading briefing check                     ~0ms (async)
9. _acquire_named_mutex()                       ~0ms
10. threading _preload_whisper                   ~2-8s (GARGALO #1)
11. validate_microphone()                        ~3s timeout (GARGALO #2)
12. _start_tray()                               ~100ms (PIL icon gen)
13. threading license_check_loop                 ~0ms
14. _hotkey_loop()                               bloqueante
```

Gargalos identificados:
- **validate_microphone()** e sincrono. Bloqueia startup por ate 3s. **[HIGH]** Deveria ser async ou ter timeout menor.
- **_preload_whisper** roda em thread (bom), mas `validate_microphone` o bloqueia antes.

---

## 2. UI / Settings Lentidao (voice/ui.py)

| Finding | Sev | Descricao |
|---------|-----|-----------|
| **F-UI-01** | **CRITICAL** | `theme._font()` cria e destroi um `tk.Tk()` root A CADA CHAMADA. Cada label/botao no SettingsWindow chama uma FONT_* que cria+destroi tk.Tk(). Com ~100 widgets no SettingsWindow, sao ~100 instancias de Tk criadas e destruidas. Isso e a causa primaria da lentidao. |
| **F-UI-02** | **HIGH** | `_build()` do SettingsWindow constroi TODAS as 6 secoes (status, modes, general, advanced, profile, about) de uma vez. Cada secao instancia dezenas de widgets CTk. Deveria ser lazy: construir cada secao apenas quando o usuario navega ate ela. |
| **F-UI-03** | **MEDIUM** | OnboardingWindow constroi todos os 5 steps de uma vez (`_build_step_1..5`), cada um com multiplos cards e labels. Mesma causa de lentidao que o SettingsWindow. |
| **F-UI-04** | **MEDIUM** | `_build_section_general` chama `_build_ai_provider_section` e `_build_license_section`, ambos com muitos widgets. Toda a arvore de widgets e renderizada antes de ser visivel. |

### Root cause do F-UI-01

Arquivo: `voice/theme.py:49-58`

```python
def _font(family: str, size: int, bold: bool = False) -> tuple:
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        r = tk.Tk()          # <-- CRIA JANELA TK A CADA CHAMADA
        r.withdraw()
        families = tkfont.families(r)
        r.destroy()           # <-- DESTROI
        fam = family if family in families else _FALLBACK.get(family, "Segoe UI")
    except Exception:
        fam = _FALLBACK.get(family, "Segoe UI")
    return (fam, size, weight)
```

Cada chamada a `FONT_HEADING()`, `FONT_BODY()`, etc. instancia e destroi um tk.Tk(). Com ~100+ widgets no SettingsWindow, sao centenas de ciclos de inicializacao do Tk.

**Fix recomendado:** Cache o resultado de `tkfont.families()` numa variavel de modulo na primeira chamada.

---

## 3. Bugs e Race Conditions

| ID | Sev | Modulo | Descricao |
|----|-----|--------|-----------|
| **B-01** | **CRITICAL** | `state.py` | `_state_lock` declarado mas quase nao utilizado. O comentario na linha 77-78 diz que protege `_ai_last_call_time, _query_cooldown_until, _tray_state, _clipboard_context, _screenshot_bytes, _window_context`, mas: `_query_cooldown_until` e lido SEM lock em `toggle_recording()` (audio.py:477). `_clipboard_context` e atribuido SEM lock em `toggle_recording()` (audio.py:491-510). `_screenshot_bytes` e atribuido SEM lock (audio.py:524-535). `_window_context` e atribuido SEM lock (audio.py:514-521). O `_state_lock` so e usado em `ai_provider.py:20` e `tray.py:89`. |
| **B-02** | **HIGH** | `audio.py` | `_last_hotkey_time` e uma global mutavel. Embora protegida por `_hotkey_debounce_lock`, o pattern `non-blocking tryacquire` descarta silenciosamente hotkeys legitimos se o lock estiver ocupado por mais de 0ms. Pode causar hot-key perdido raro. |
| **B-03** | **HIGH** | `gemini.py:20` | Double-checked locking no `_get_gemini_client()` tem data race. A leitura `if state._gemini_client is None` (linha 20) nao esta dentro do lock. Em CPython com GIL isso funciona na pratica, mas e um pattern fragil. Se `genai.Client()` for lento, duas threads podem entrar no check simultaneamente. |
| **B-04** | **HIGH** | `audio.py:598` | `list(state.frames_buf)` e copiado FORA do lock na linha 598. O comentario diz "nao ha risco de frames_buf ser zerado durante o join" porque o debounce garante >=1000ms. Mas se o debounce falhar ou o sistema estiver sob carga, outra thread poderia zerar `frames_buf` antes da copia. |
| **B-05** | **MEDIUM** | `tray.py:100` | `_update_tray_state` acessa `state._tray_icon` fora do `_state_lock`. A atribuicao a `state._tray_icon` em `_start_tray()` e `_stop_tray()` nao e protegida por lock, criando possivel race condition. |
| **B-06** | **MEDIUM** | `overlay.py:99` | `SetProcessDpiAwareness(2)` e chamado DENTRO de `_OverlayThread._build()`, ou seja, apos o DPI awareness ja ter sido definido pelo processo principal. A API do Windows ignora chamadas subsequentes, mas se o overlay thread rodar ANTES do main thread setar DPI, pode ter efeito colateral. |
| **B-07** | **LOW** | `briefing.py:113-120` | `_show_briefing_window` cria um novo `ctk.CTk()` em thread daemon. Cada `CTk()` chama `ctk.set_appearance_mode("dark")` e `ctk.set_default_color_theme("dark-blue")` que sao globals do customtkinter. Se o SettingsWindow estiver aberto ao mesmo tempo, ha race condition nos globals do CTk. |
| **B-08** | **LOW** | `config.py:122` | Variaveis novas adicionadas ao `.env` pelo usuario que NAO estao no dict de defaults sao silenciosamente ignoradas por `if key in config`. Nao e um bug direto, mas pode confundir usuarios que adicionam configs custom. |

---

## 4. Codigo Morto e Imports Nao Utilizados

| ID | Sev | Modulo | Descricao |
|----|-----|--------|-----------|
| **D-01** | **LOW** | `ui.py:554` | `MODES` na classe `SettingsWindow` e identico ao `MODES` de `OnboardingWindow`. Duplicacao desnecessaria. Comentario diz "mantida para compatibilidade" mas nao e referenciada em nenhum outro lugar do SettingsWindow. |
| **D-02** | **LOW** | `ui.py:975` | `_on_mode_hover` e apenas um alias para `_on_mode_card_hover`. Comentario diz "Alias mantido para compatibilidade interna" mas nao ha callers. |
| **D-03** | **LOW** | `audio.py:449-459` | `_MODE_LOG_LABELS` no audio.py duplica parcialmente `MODE_LABELS` de modes.py. Poderia usar `modes.py` diretamente. |
| **D-04** | **LOW** | `animate.py` | Modulo inteiro nao e importado por nenhum outro modulo no projeto. `overlay.py` reimplementa animacoes inline em vez de usar `animate.py`. |
| **D-05** | **LOW** | `__init__.py:28` | `from voice.gemini import _get_gemini_client` no __init__.py forca import do modulo gemini no startup, que importa `from google import genai` (via conftest mock em testes, mas em producao faz import real do google-genai). |

---

## 5. Compatibilidade pythonw.exe (sys.stdout = None)

| ID | Sev | Modulo | Descricao |
|----|-----|--------|-----------|
| **P-01** | **HIGH** | `app.py:24` | `print(f"[ERRO IMPORT] {_e}")` no try/except do import keyboard (linha 24) usa print ANTES do patch de `_log_print` ser aplicado. Se `logging_.py` nao foi importado ainda e `pythonw.exe` esta ativo, `sys.stdout` e None e o `builtins.print` original crasharia. Porem, o `__init__.py` importa `logging_` antes de `app.py`, entao o patch ja esta ativo. SAFE, mas fragil. |
| **P-02** | **HIGH** | `audio.py:43` | `print(f"[ERRO IMPORT] {_e}")` seguido de `sys.exit(1)` no import de sounddevice/numpy/winsound. Mesmo cenario que P-01, mais critico porque chama `sys.exit(1)` sem feedback ao usuario em pythonw.exe. O usuario veria o processo encerrar sem nenhuma mensagem. |
| **P-03** | **MEDIUM** | `logging_.py:20-24` | O patch `_log_print` verifica `sys.stdout is not None` antes de chamar `_orig_print`, o que e correto. Porem, se `_log_print` for chamado antes de `state._log_path` estar populado (antes de paths.py ser importado), o `open(state._log_path, "a")` abriria um arquivo com path vazio `""`, causando `FileNotFoundError`. Na pratica, `__init__.py` importa `paths` antes de `logging_`, entao e safe. Mas e fragil. |

---

## 6. Audio (voice/audio.py) -- Threading e Buffer

| ID | Sev | Descricao |
|----|-----|-----------|
| **A-01** | **MEDIUM** | `record()` appenda frames dentro de `state._toggle_lock` (linha 149). Isso significa que a thread de gravacao adquire o RLock a cada 64ms (1024 frames / 16000 Hz). Se outra thread tentar adquirir `_toggle_lock` (ex: `toggle_recording` no path STOP), pode ter contencao. Na pratica, como `stream.read(1024)` e bloqueante e o lock e rapido, o impacto e minimo. |
| **A-02** | **MEDIUM** | `np.concatenate(frames, axis=0)` na linha 354 cria uma copia inteira do audio em memoria. Para gravacoes longas (120s a 16kHz = ~3.8MB float32), isso dobra o uso de RAM momentaneamente. Nao e critico, mas vale notar. |
| **A-03** | **LOW** | `_do_transcription` faz `import inspect` a cada chamada (linha 201) para checar se faster-whisper suporta `hotwords`. Deveria cachear o resultado. |

---

## 7. Gemini (voice/gemini.py) -- Error Handling e Timeout

| ID | Sev | Descricao |
|----|-----|-----------|
| **G-01** | **HIGH** | Nenhuma funcao Gemini define timeout. `client.models.generate_content()` pode bloquear indefinidamente se o servidor Gemini estiver lento. O `retry_api_call` retenta em erros transientes, mas se a chamada nao retornar, a thread fica travada para sempre. |
| **G-02** | **MEDIUM** | Cada funcao (correct, simplify, structure, query, bullet, email, translate, visual_query, pipeline, briefing) repete o mesmo pattern de try/except/rate_limit/fallback. Muito boilerplate. `ai_utils.call_with_fallback()` existe mas so e usado por `openai_.py`, nao por `gemini.py`. |
| **G-03** | **LOW** | `transcribe_audio_with_gemini` le o arquivo WAV inteiro em memoria (`audio_bytes = f.read()`) sem limite de tamanho. Para gravacoes longas, isso pode ser MBs. |

---

## 8. State (voice/state.py) -- Thread Safety

| ID | Sev | Descricao |
|----|-----|-----------|
| **S-01** | **CRITICAL** | Conforme detalhado em B-01, o `_state_lock` existe mas nao e consistentemente usado. Variaveis mutaveis sao acessadas sem lock por multiplas threads. Na pratica, o GIL do CPython evita corrupcao de memoria, mas o comportamento nao e garantido e torna o codigo fragil para futuras otimizacoes. |
| **S-02** | **MEDIUM** | `is_recording` e `is_transcribing` sao booleans acessados por multiplas threads sem lock (exceto dentro de `_toggle_lock` no toggle_recording). O `is_transcribing` e setado para `False` no `finally` de `transcribe()` (audio.py:427) e checado no inicio de `toggle_recording()` (audio.py:469), ambos protegidos por `_toggle_lock`. OK para o pattern atual, mas adicoes futuras podem quebrar. |
| **S-03** | **LOW** | `_gemini_client`, `_openai_client`, `_groq_client` sao singletons lazy, cada um com seu proprio lock. Consistente. |

---

## 9. Testes (tests/) -- Cobertura e Fragilidades

| ID | Sev | Descricao |
|----|-----|-----------|
| **T-01** | **MEDIUM** | Zero testes para `openrouter.py` (novo provider prioritario). O modulo tem 338 linhas e 13 funcoes. Cobertura: 0%. |
| **T-02** | **MEDIUM** | Zero testes para `groq_.py`. Apenas a classe stub existe. |
| **T-03** | **MEDIUM** | Zero testes para `animate.py`, `screenshot.py`, `window_context.py`, `wakeword.py`, `briefing.py`, `user_profile.py`, `history_search.py`, `modes.py`, `paths.py`, `mutex.py`. |
| **T-04** | **MEDIUM** | `test_ui.py` testa apenas `_finish()` e `_save()` bypasando o CTk inteiro. A lentidao da UI (F-UI-01) nunca seria detectada por testes. |
| **T-05** | **LOW** | `conftest.py` instala stubs para `google.genai` como MagicMock global, o que pode mascarar erros reais de import chain. |
| **T-06** | **LOW** | Testes levam 103s para 251 tests. Lento para unit tests. Provavelmente por imports pesados (faster_whisper mock, etc). |
| **T-07** | **LOW** | Sem teste de integracao real (pipeline completo mic -> whisper -> gemini -> paste). Compreensivel dado que requer hardware/APIs, mas vale documentar como gap. |

### Cobertura estimada por modulo:

| Modulo | Testes | Estimativa |
|--------|--------|------------|
| audio.py | test_audio.py + test_audio_recording.py + test_vad_fix.py | ~65% |
| gemini.py | test_gemini.py | ~70% |
| config.py | test_config.py | ~75% |
| ai_provider.py | test_ai_provider.py | ~80% |
| openai_.py | test_openai.py | ~60% |
| clipboard.py | test_clipboard.py | ~85% |
| overlay.py | test_overlay.py | ~40% (API publica, nao renderizacao) |
| tray.py | test_tray.py | ~50% |
| ui.py | test_ui.py | ~15% (so disk writes) |
| license.py | test_license.py | ~80% |
| logging_.py | test_log_rotation.py + test_history.py | ~60% |
| shutdown.py | test_shutdown.py | ~70% |
| openrouter.py | -- | **0%** |
| groq_.py | -- | **0%** |
| briefing.py | -- | **0%** |
| user_profile.py | -- | **0%** |
| screenshot.py | -- | **0%** |
| window_context.py | -- | **0%** |
| history_search.py | -- | **0%** |
| wakeword.py | -- | **0%** |
| animate.py | -- | **0%** |
| modes.py | -- | **0%** |
| paths.py | -- | **0%** |
| mutex.py | -- | **0%** |

**Estimativa geral: ~35-40% de cobertura real.** Longe dos 80% target.

---

## 10. Memory Leaks Potenciais

| ID | Sev | Descricao |
|----|-----|-----------|
| **M-01** | **MEDIUM** | `_start_recording_tooltip_thread()` (tray.py:71-84) cria uma nova thread a CADA inicio de gravacao. Cada thread roda `while state._tray_state == "recording"` e termina quando o estado muda. Se o usuario gravar 100 vezes, 100 threads sao criadas (daemon=True, entao terminam, mas ha overhead de criacao). |
| **M-02** | **MEDIUM** | `_license_check_loop()` (app.py:69-82) e uma thread infinita com `while True: time.sleep(60)`. Nunca termina exceto com `os._exit()`. Na pratica daemon=True resolve, mas `graceful_shutdown()` nao a sinaliza. |
| **M-03** | **LOW** | `frames_buf` em state.py e uma lista que cresce durante gravacao. O `finally` em `transcribe()` (audio.py:427-444) limpa `_screenshot_bytes`, `_clipboard_context`, e `_window_context`, mas NAO limpa `frames_buf`. Ele e limpo no proximo START (audio.py:485: `state.frames_buf = []`). Entre o fim da transcricao e o proximo START, os frames ficam em memoria. |
| **M-04** | **LOW** | `state._whisper_model` nunca e liberado uma vez carregado. Como e um singleton, isso e intencional. Mas para modelos grandes (large-v2, large-v3), pode ocupar >1GB de RAM. |

---

## 11. Security Scan

| ID | Sev | Descricao |
|----|-----|-----------|
| **SEC-01** | **LOW** | `license.py:12`: `_K = [ord(c) ^ 0x42 for c in "jp-labs-vc-secret-2026"]` e XOR trivial. A string secret pode ser recuperada com um one-liner. Documentado como design decision (Epic 5 implementaria server-side). |
| **SEC-02** | **LOW** | `ui.py:1291-1314`: `_on_wakeword_toggle` executa `subprocess.check_call([sys.executable, "-m", "pip", "install", ...])` sem validacao de input. Os nomes dos pacotes sao hardcoded, entao nao ha injection risk real, mas o pattern de `pip install` silencioso e questionavel. |
| **SEC-03** | **INFO** | `clipboard.py` le/escreve clipboard sem nenhuma sanitizacao. Intencional para uma ferramenta voice-to-text, mas vale notar que conteudo malicioso no clipboard e colado diretamente. |

---

## 12. Achados Adicionais

| ID | Sev | Descricao |
|----|-----|-----------|
| **X-01** | **LOW** | `__init__.py` faz side-effect imports que populam state e patcham builtins.print. Isso e necessario para o funcionamento, mas torna o import de `voice` nao-inocuo. Os testes mitigam isso com `conftest.py`. |
| **X-02** | **LOW** | `app.py:331`: `if state._CONFIG.get("WAKE_WORD_ENABLED", False) is True` usa `is True` que e correto apos a conversao bool em load_config, mas seria mais pythonic usar simplesmente `if state._CONFIG.get(...)`. Consistente no projeto inteiro, entao e style choice. |
| **X-03** | **INFO** | `openrouter.py` duplica `_build_context_prefix()` de `gemini.py`. Mesma logica, mas implementada separadamente. Poderia ser centralizada em `ai_utils.py`. |

---

## Veredito Final

### BLOCK (deploy bloqueado ate resolver):

- [ ] **F-UI-01**: `theme._font()` cria/destroi tk.Tk() a cada chamada. ~100+ instancias durante abertura do SettingsWindow. Causa direta da lentidao reportada. Cachear `tkfont.families()` em variavel de modulo. @ `voice/theme.py:49-58`
- [ ] **B-01 / S-01**: `_state_lock` declarado mas inconsistentemente usado. Variaveis compartilhadas entre threads acessadas sem protecao. @ `voice/state.py:77-79`, `voice/audio.py:477,491,514,524`

### WARN (corrigir na proxima iteracao):

- [ ] **G-01**: Chamadas Gemini sem timeout. Thread pode bloquear indefinidamente. Adicionar `timeout=30` ao `generate_content()`. @ `voice/gemini.py` (todas as funcoes)
- [ ] **F-UI-02**: SettingsWindow constroi todas as secoes de uma vez. Implementar lazy loading por secao. @ `voice/ui.py:686-691`
- [ ] **B-03**: Double-checked locking no _get_gemini_client() sem lock na primeira leitura. @ `voice/gemini.py:20-26`
- [ ] **P-02**: `sys.exit(1)` silencioso em pythonw.exe se import de sounddevice falhar. Adicionar fallback com MessageBox. @ `voice/audio.py:37-44`
- [ ] **T-01**: openrouter.py sem cobertura de testes (0%). Provider prioritario. @ `voice/openrouter.py`
- [ ] **T-03**: 12 modulos com 0% de cobertura. Total estimado: ~35-40%. Target: 80%. @ `tests/`
- [ ] **D-04**: `animate.py` nao e importado por nenhum modulo. Codigo morto ou incompleto. @ `voice/animate.py`
- [ ] **M-01**: Nova thread criada a cada gravacao para tooltip do tray. @ `voice/tray.py:71-84`

### PASS:

- 251 testes passando (test suite green)
- py_compile: todos os modulos sem erros de sintaxe
- Padrao de logging consistente ([OK], [...], [WARN], [ERRO], etc.)
- Debounce de hotkey bem implementado com lock atomico
- Graceful shutdown robusto com timeout e fallback
- Singleton pattern consistente para clientes AI (Gemini, OpenAI, Groq, OpenRouter)
- Clipboard win32 API com retry e proper cleanup
- Config load com defaults explicitos e validacao de tipos
- Overlay thread-safe via queue.Queue
- Audio recording com proper cleanup no finally
- License validation local sem network call (design intencional)

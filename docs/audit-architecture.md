# Architecture Review -- Voice Commander v1.0.15

**Data:** 2026-04-03
**Agente:** ARIA (VP Architecture)

---

## 1. Mapa de Dependencias entre Modulos

```
                    state.py (0 deps, leaf)
                    modes.py (0 deps, leaf)
                   theme.py (0 deps, leaf)
                 animate.py (0 deps, leaf, DEAD CODE)
                ai_utils.py (0 deps, leaf)
               clipboard.py (0 deps, leaf)
          window_context.py (0 deps, leaf)
              screenshot.py (0 deps, leaf)
                       |
                    paths.py -- state
                   mutex.py -- state
                 logging_.py -- state
                 license.py -- state
            user_profile.py -- state
                wakeword.py -- state
                       |
                 config.py -- state, openrouter (lazy)
                       |
              gemini.py -- state, ai_utils, user_profile (lazy)
             openai_.py -- state, ai_utils
          openrouter.py -- state, ai_utils, user_profile (lazy)
              groq_.py -- state, ai_utils (DEAD CODE)
                       |
         ai_provider.py -- state, openrouter, gemini, openai_ (lazy)
                       |
              overlay.py -- state, modes
                 tray.py -- state, theme, modes, paths, ui, config (lazy)
                       |
               audio.py -- state, ai_provider, tray, logging_, clipboard, modes,
                          overlay (lazy), window_context (lazy), screenshot (lazy)
                       |
            shutdown.py -- state, mutex, audio (lazy)
     history_search.py -- state, paths, clipboard, theme (lazy)
           briefing.py -- state, gemini (lazy), user_profile (lazy)
                       |
                 ui.py -- state, theme, paths, license, config, user_profile (lazy)
                       |
                app.py -- state, config, license, logging_, mutex, tray, audio,
                         shutdown, ui, user_profile, briefing, wakeword, 
                         history_search, overlay
                       |
           __init__.py -- state, paths, logging_, config, license, gemini
            __main__.py -- app
```

---

## 2. Classificacao dos 30 Modulos

### Essenciais (14 modulos) -- o core do app

| Modulo | LOC | Justificativa |
|--------|-----|---------------|
| `state.py` | 79 | Estado global. Raiz do DAG. |
| `paths.py` | 29 | Resolucao dev vs .exe. |
| `config.py` | 234 | Carga/save do .env. |
| `logging_.py` | 112 | Patch de print + history append. |
| `audio.py` | 671 | Gravacao, transcricao, toggle, hotkey. O coracao do app. |
| `gemini.py` | 653 | Provider primario. Todas as funcoes de modo + STT + visual + pipeline. |
| `ai_provider.py` | 152 | Facade de routing. |
| `clipboard.py` | 125 | Copy/read/paste via ctypes. Sem dep. |
| `overlay.py` | 430 | Toast de feedback visual. UX core. |
| `tray.py` | 321 | System tray. Unica interface persistente visivel. |
| `app.py` | 347 | Entry point + hotkey loop. |
| `shutdown.py` | 78 | Graceful shutdown. |
| `mutex.py` | 26 | Instancia unica. |
| `__init__.py` / `__main__.py` | 33 | Bootstrap. |

### Pode fundir (9 modulos)

| Modulo | LOC | Proposta |
|--------|-----|----------|
| `modes.py` | 63 | Fundir em `state.py`. Sao 3 dicts e 3 one-liners. |
| `ai_utils.py` | 80 | Fundir em `ai_provider.py`. Usado apenas por providers. |
| `license.py` | 68 | Fundir em `config.py`. Sao 3 funcoes (~60 LOC). |
| `screenshot.py` | 51 | Fundir em `audio.py` (chamado apenas de la). 1 funcao. |
| `window_context.py` | 57 | Fundir em `audio.py` (chamado apenas de la). 1 funcao. |
| `user_profile.py` | 139 | Manter separado mas e candidato. Acoplado a briefing e gemini. |
| `theme.py` | 101 | Manter se UI permanecer. Leaf node. |
| `briefing.py` | 199 | Fundir em `gemini.py` (toda logica Gemini). UI ficaria em `ui.py`. |
| `history_search.py` | 282 | Manter separado (janela CTk propria). |

### Pode eliminar (3 modulos)

| Modulo | LOC | Justificativa |
|--------|-----|---------------|
| `groq_.py` | 162 | **DEAD CODE.** Nenhum import em nenhum lugar. Nao referenciado em `ai_provider.py`. State tem `_groq_client` mas ninguem seta via dispatch. |
| `animate.py` | 190 | **DEAD CODE.** Nenhum import em todo o codebase. 0 usos. |
| `openai_.py` | 243 | **Quase morto.** So ativado se `AI_PROVIDER=openai` E sem `OPENROUTER_API_KEY`. Com OpenRouter como prioridade 1, OpenAI direto e redundante (OpenRouter proxy ja faz a mesma coisa). |

### Critico: `ui.py` = 1.734 LOC (24.6% do codebase)

`ui.py` sozinho e quase 1/4 de todo o codigo Python. Contem:
- `OnboardingWindow` (~5 steps wizard)
- `SettingsWindow` (sidebar com ~10 tabs)
- `_apply_taskbar_icon`

E o modulo mais complexo do projeto e o que mais dificulta manutencao. Se for simplificar algo, comece aqui.

---

## 3. Analise do Padrao AI Provider

```
ai_provider.py (facade)
  |-- openrouter.py (337 LOC) -- prioridade 1
  |-- gemini.py     (653 LOC) -- prioridade 2
  |-- openai_.py    (243 LOC) -- prioridade 3
  +-- groq_.py      (162 LOC) -- DEAD CODE
```

### Diagnostico: over-abstracted.

Problemas concretos:

1. **Duplicacao massiva de prompts.** Cada provider reimplementa os mesmos 8-9 modos (correct, simplify, structure, query, bullet, email, translate, pipeline) com prompts quase identicos. Sao ~30 funcoes que fazem a mesma coisa com SDKs diferentes.

2. **OpenRouter e OpenAI usam a mesma SDK** (openai). `openrouter.py` e literalmente `openai_.py` com `base_url` diferente. Poderiam ser o mesmo cliente com URL configuravel.

3. **groq_.py e 100% dead code.** Removivel hoje.

4. **openai_.py e semi-morto.** A chain de prioridade e: OpenRouter > Gemini > OpenAI. Se OpenRouter esta configurado (e o recomendado), OpenAI direto nunca roda. E OpenRouter ja pode usar modelos OpenAI.

5. **_build_context_prefix() duplicada** em `gemini.py` e `openrouter.py`. Mesma funcao, copiada.

### Proposta de simplificacao:

```
ai_provider.py (facade + prompts centralizados)
  |-- prompts.py     (NEW: todos os system prompts por modo, 1 lugar)
  |-- gemini.py      (cliente Gemini, transcricao, visual query)
  +-- openai_compat.py (1 cliente para OpenRouter/OpenAI/Groq via base_url)
```

Economia estimada: ~500 LOC eliminados (groq_ + openai_ + duplicacao de prompts).

---

## 4. Analise de state.py

`state.py` como namespace global de estado mutavel e um padrao pragmatico para app single-process desktop. Nao e anti-pattern neste contexto.

**Pontos positivos:**
- 0 imports de `voice.*` (raiz do DAG, sem ciclo)
- Locks bem definidos (`_toggle_lock`, `_state_lock`, `_settings_window_lock`)
- Nomenclatura consistente (`_` prefix para internos)

**Pontos negativos:**
- 79 linhas com ~40 variaveis globais. Funciona hoje mas escala mal.
- Mistura de concerns: estado de gravacao, singletons de AI, estado de UI, configs.

**Veredicto:** Manter como esta. Para um app desktop pessoal, o pattern e adequado. Refatorar para classes/dataclass so vale a pena se o app crescer significativamente (Epic 5+ com multi-user ou plugin system).

---

## 5. Analise de modes.py

63 LOC, 3 dicts e 3 funcoes wrapper que apenas chamam `.get()`.

**Veredicto:** Modulo pequeno demais para existir separado. Fundir em `state.py` (zero deps, e onde `selected_mode` ja vive) ou em `audio.py` (e quem mais consome).

---

## 6. Analise de ai_utils.py

80 LOC, 2 funcoes (`retry_api_call`, `call_with_fallback`). Usado por gemini.py, openai_.py, openrouter.py, groq_.py.

**Veredicto:** Pode fundir em `ai_provider.py` se os providers forem consolidados. Se mantiver providers separados, justifica existir como shared utility.

---

## 7. Dependencias -- requirements.txt

| Pacote | Necessario? | Veredicto |
|--------|------------|-----------|
| `sounddevice` | Sim | Core: captura de audio |
| `numpy` | Sim | Core: processamento de frames |
| `faster-whisper` | Sim | Core: transcricao local |
| `keyboard` | Sim | Core: hotkeys globais |
| `google-genai` | Sim | Core: Gemini (provider primario) |
| `pystray` | Sim | Core: system tray |
| `Pillow` | Sim | Core: icone da tray + screenshot |
| `customtkinter` | **Questionavel** | Usado para onboarding, settings, briefing, history search. E 89KB de dep para UIs que poderiam ser tkinter puro (como o overlay ja e). |
| `openai` | **Questionavel** | Necessario se OpenRouter ativo. Se Gemini for o unico provider (cenario comum), e dep morta em runtime. Mas o build requer. |
| `pytest` | Dev only | OK |
| `ruff` | Dev only | OK |

**Proposta:**
- `openai` poderia ser opcional (import lazy com fallback). Hoje ja faz import lazy, mas o pin em requirements.txt forca instalacao.
- `customtkinter` poderia ser substituido por tkinter puro (como overlay.py prova que funciona). Economia: 1 dep + simplificacao de ui.py.
- Nenhuma dependencia pode ser removida sem perda de funcionalidade existente. A questao e se a funcionalidade justifica.

---

## 8. Fluxo Completo: Hotkey -> Audio -> Whisper -> Gemini -> Paste

```
1. Hotkey press (keyboard lib)
   +-- on_hotkey()                           [audio.py:608]
       |-- Debounce atomico (1000ms, Lock)
       +-- Thread(toggle_recording)

2. toggle_recording(mode) START path          [audio.py:462]
   |-- Lock _toggle_lock
   |-- state.current_mode = mode
   |-- state.frames_buf = []
   |-- Captura clipboard context              [clipboard.py:54]
   |-- Captura window context (se enabled)    [window_context.py:9]
   |-- Captura screenshot (se modo visual)    [screenshot.py:8]
   |-- _update_tray_state("recording")        [tray.py:87]
   |-- play_sound("start")                    [audio.py:66]
   |-- overlay.show_recording()               [overlay.py:378]
   +-- Thread(record).start()

3. record()                                   [audio.py:127]
   +-- sd.InputStream loop -> state.frames_buf.append()

4. Hotkey press novamente
   +-- toggle_recording() STOP path           [audio.py:565]
       |-- state.is_recording = False
       |-- state.stop_event.set()
       |-- thread.join(5s) fora do lock
       +-- Thread(transcribe, frames, mode)

5. transcribe(frames, mode)                   [audio.py:325]
   |-- _update_tray_state("processing")
   |-- overlay.show_processing(mode)
   |-- np.concatenate(frames)
   |-- Escrever WAV temporario
   |-- _do_transcription(wav, mode)           [audio.py:169]
   |   |-- Se STT_PROVIDER=gemini: gemini.transcribe_audio_with_gemini()
   |   +-- Se whisper: get_whisper_model(mode) -> model.transcribe()
   |       |-- Tenta com VAD
   |       |-- Fallback sem VAD se falhar
   |       +-- Fallback CUDA->CPU se necessario
   |-- _post_process_and_paste(raw_text, mode) [audio.py:297]
   |   |-- ai_provider.process(mode, text)     [ai_provider.py:14]
   |   |   |-- Cooldown check (2s)
   |   |   |-- Profile trigger check (transcribe only)
   |   |   +-- Dispatch: OpenRouter > Gemini > OpenAI
   |   |       +-- Funcao do modo (correct/simplify/structure/query/...)
   |   |-- copy_to_clipboard(result)           [clipboard.py:8]
   |   |-- play_sound("success")
   |   |-- sleep(paste_delay)
   |   +-- paste_via_sendinput()               [clipboard.py:97]
   |-- overlay.show_done(text)
   |-- _append_history(...)                    [logging_.py:66]
   +-- finally: cleanup (state reset, temp file, tray idle)
```

### Onde ha complexidade desnecessaria:

1. **_do_transcription e um labirinto.** 130 LOC com 3 niveis de try/except aninhados, fallback VAD, fallback CUDA->CPU, fallback para no-VAD se resultado vazio. Funciona, mas e a funcao mais fragil do codebase.

2. **audio.py acumula responsabilidades demais.** Gravacao, transcricao, processamento, paste, beeps, modelo Whisper, hotkey, debounce, microfone validation. Sao 671 LOC com 6 concerns diferentes.

3. **O fluxo passa por 7-8 modulos** para uma operacao conceptualmente simples (gravar -> transcrever -> processar -> colar). Cada modulo adiciona uma camada de indirection.

4. **overlay e importado lazy dentro de funcoes** em audio.py (3x) e app.py (1x). Isso e porque overlay importa state/modes mas audio.py tambem depende de overlay. O design de imports esta correto mas a quantidade de imports lazy indica acoplamento.

---

## 9. Proposta de Arquitetura v2 Simplificada

### Antes (30 arquivos, 7.059 LOC)

```
voice/
|-- __init__.py          28
|-- __main__.py           5
|-- ai_provider.py      152
|-- ai_utils.py          80
|-- animate.py          190   <- DEAD CODE
|-- app.py              347
|-- audio.py            671
|-- briefing.py         199
|-- clipboard.py        125
|-- config.py           234
|-- gemini.py           653
|-- groq_.py            162   <- DEAD CODE
|-- history_search.py   282
|-- license.py           68
|-- logging_.py         112
|-- modes.py             63
|-- mutex.py             26
|-- openai_.py          243   <- SEMI-MORTO
|-- openrouter.py       337
|-- overlay.py          430
|-- paths.py             29
|-- screenshot.py        51
|-- shutdown.py          78
|-- state.py             79
|-- theme.py            101
|-- tray.py             321
|-- ui.py              1734
|-- user_profile.py     139
|-- wakeword.py          63
+-- window_context.py    57
                       -----
                       7059 LOC
```

### Depois (proposta: 18 arquivos, ~5.200 LOC estimado)

```
voice/
|-- __init__.py          30   (manter)
|-- __main__.py           5   (manter)
|-- state.py            130   (+ modes.py absorvido)
|-- config.py           280   (+ license.py absorvido)
|-- paths.py             29   (manter)
|-- logging_.py         112   (manter)
|-- mutex.py             26   (manter)
|-- shutdown.py          78   (manter)
|-- clipboard.py        125   (manter)
|-- ai_provider.py      200   (+ ai_utils.py absorvido + prompts centralizados)
|-- gemini.py           500   (- prompts duplicados, + briefing logic)
|-- openai_compat.py    200   (openrouter + openai + groq via base_url config)
|-- audio.py            580   (+ screenshot + window_context absorvidos,
|                               - _do_transcription extraido)
|-- overlay.py          430   (manter, ja e tkinter puro)
|-- tray.py             321   (manter)
|-- theme.py            101   (manter)
|-- ui.py              1500   (- ~200 LOC de dead code e duplicacao)
|-- user_profile.py     139   (manter)
+-- features/
    |-- history_search.py   282   (manter)
    |-- briefing.py          80   (so UI, logica gemini em gemini.py)
    +-- wakeword.py          63   (manter)
                           -----
                           ~5200 LOC (estimativa)
```

### Diagrama da arquitetura v2:

```
                    +-------------------------------------+
                    |            USER INPUT                |
                    |  (keyboard hotkey / wake word / tray)|
                    +----------------+--------------------+
                                     |
                    +----------------v--------------------+
                    |           app.py                     |
                    |   main(), hotkey_loop, startup       |
                    +--+------+------+-------+------------+
                       |      |      |       |
            +----------v+  +--v--+ +-v--+  +-v----------+
            | audio.py  |  |tray |  | ui |  |  features/ |
            | record    |  |.py  |  |.py |  | wakeword   |
            | transcribe|  |     |  |    |  | briefing   |
            | toggle    |  +-----+  +----+  | history    |
            +------+----+                   +------------+
                   |
        +----------v-------------+
        |    ai_provider.py      |
        |  (prompts + routing)   |
        +--+-------------+------+
           |             |
    +------v--+   +------v--------+
    |gemini.py|   |openai_compat  |
    |(native) |   |.py            |
    |STT+LLM  |   |(OpenRouter    |
    |+visual  |   | /OpenAI/Groq) |
    +---------+   +---------------+
           |             |
    +------v-------------v-------+
    |          state.py          |
    |   (global state + modes)   |
    +------+---------------------+
           |
    +------v-----------------+
    | config.py              |
    | (+ license)            |
    | paths.py               |
    | logging_.py            |
    | mutex.py               |
    | clipboard.py           |
    | shutdown.py            |
    +------------------------+
```

---

## 10. Estimativa de Complexidade Antes/Depois

| Metrica | Antes (v1) | Depois (v2) | Delta |
|---------|-----------|-------------|-------|
| Arquivos .py | 30 | 21 | -30% |
| LOC total | 7.059 | ~5.200 | -26% |
| Dead code (LOC) | 352 (animate + groq_) | 0 | -100% |
| Providers AI | 4 (gemini, openai_, openrouter, groq_) | 2 (gemini, openai_compat) | -50% |
| Funcoes de modo duplicadas | ~32 (8 modos x 4 providers) | ~16 (8 modos x 2) | -50% |
| Prompts duplicados | 4 copias (1 por provider) | 1 (centralizado) | -75% |
| Imports circulares/lazy | ~15 | ~8 | -47% |
| Modulos com <70 LOC | 7 | 2 | -71% |
| ui.py como % do total | 24.6% | ~29% | +4% (precisa de atencao futura) |

---

## 11. Acoes Recomendadas (Priorizadas)

### P0 -- Imediato (0 risco, 0 regressao)

1. Deletar `voice/groq_.py` (dead code, 0 imports)
2. Deletar `voice/animate.py` (dead code, 0 imports)
3. Remover `_groq_client`, `_GROQ_API_KEY` de `state.py`
4. Remover bloco de Groq reset de `config.py:_reload_config()`

### P1 -- Curto prazo (baixo risco)

5. Fundir `modes.py` em `state.py` (mover 3 dicts + 3 funcoes)
6. Fundir `license.py` em `config.py` (3 funcoes, ~60 LOC)
7. Fundir `ai_utils.py` em `ai_provider.py`
8. Fundir `screenshot.py` + `window_context.py` em `audio.py` (cada um e 1 funcao usada 1 vez)

### P2 -- Medio prazo (requer testes)

9. Consolidar `openrouter.py` + `openai_.py` em `openai_compat.py` (mesma SDK, base_url diferente)
10. Centralizar prompts em `ai_provider.py` (eliminar duplicacao entre providers)
11. Extrair `_do_transcription` de `audio.py` para funcao mais limpa com menos niveis de try/except

### P3 -- Longo prazo (avaliacao de custo/beneficio)

12. Avaliar se `customtkinter` justifica existir como dep (overlay ja funciona com tkinter puro)
13. Dividir `ui.py` (1734 LOC) em `ui_onboarding.py` + `ui_settings.py`

# Feature Discovery & Waste Audit -- Voice Commander

**Data:** 2026-04-03
**Agente:** ATLAS (Research & Strategy Analyst)
**Metodologia:** Leitura completa de todos os 23 modulos em `voice/`, analise de `config.py` (variaveis), `.env.example` (documentacao), e cruzamento das configuracoes com o codigo ativo.

---

## 1. Mapa Completo de Features

### 1.1 Core Pipeline (caminho principal de uso)

| Feature | Modulo(s) | Status | Observacao |
|---------|-----------|--------|------------|
| Gravacao de audio via hotkey | `audio.py`, `app.py` | Funciona bem | Debounce atomico, lock correto, timeout com aviso sonoro |
| Transcricao Whisper local | `audio.py` | Funciona bem | VAD com fallback, hotwords, beam_size configuravel |
| Transcricao via Gemini STT | `audio.py`, `gemini.py` | Funciona | Rota alternativa -- `STT_PROVIDER=gemini`. Usada raramente por custo |
| Correcao ortografica Gemini | `gemini.py` | Funciona bem | Minimalista, bypass configuravel (`GEMINI_CORRECT=false`) |
| Paste via SendInput | `clipboard.py` | Funciona bem | ctypes puro, sem dependencia de keyboard |
| Registro de hotkeys resiliente | `app.py` | Funciona bem | Re-registra automaticamente se `keyboard.wait()` crashar |
| System tray (3 estados visuais) | `tray.py` | Funciona bem | Idle/recording/processing com icone colorido |
| Overlay de feedback visual | `overlay.py` | Funciona bem | tkinter puro, sem roubar foco, animacao slide+fade |
| Historico de transcricoes | `logging_.py` | Funciona bem | `history.jsonl`, rotacao de log, max entries configuravel |

### 1.2 Modos de Processamento

| Modo (id) | Funcao AI | Status | Avaliacao |
|-----------|-----------|--------|-----------|
| `transcribe` | `correct_with_gemini` / `correct` (OR) | Funciona bem | Modo principal, usado com maior frequencia |
| `email` | `draft_email_with_gemini` / `draft_email` (OR) | Funciona | Completo e testado |
| `simple` | `simplify_as_prompt` / `simplify` (OR) | Funciona | Util para prompt engineering |
| `prompt` | `structure_as_prompt` / `structure` (OR) | Funciona | COSTAR com XML -- nicho |
| `query` | `query_with_gemini` / `query` (OR) | Funciona bem | Com clipboard context automatico |
| `bullet` | `bullet_dump_with_gemini` / `bullet_dump` (OR) | Funciona | Fora do ciclo padrao por default |
| `translate` | `translate_with_gemini` / `translate` (OR) | Funciona | Fora do ciclo padrao por default |
| `visual` | `visual_query_with_gemini` | Funciona | Desativado por padrao (VISUAL_HOTKEY vazio) |
| `pipeline` | `execute_pipeline` | Funciona | Desativado por padrao (PIPELINE_HOTKEY vazio) |
| `clipboard_context` | (legacy) | Obsoleto | ID existe em `modes.py` mas nao ha hotkey, nao aparece no ciclo. Funcionalidade absorvida pelo modo `query` com `CLIPBOARD_CONTEXT_ENABLED=true` |

### 1.3 Features Opcionais (Epic 4.6)

| Feature | Config | Modulo | Status | Avaliacao real |
|---------|--------|--------|--------|----------------|
| User Profile | `USER_PROFILE_ENABLED=false` | `user_profile.py` | Funciona | OFF por default. Util, mas ninguem habilita -- overhead em todo prompt |
| Window Context | `WINDOW_CONTEXT_ENABLED=false` | `window_context.py` | Funciona | OFF por default. Questionavel -- titulo da janela raramente util |
| Visual Query | `VISUAL_HOTKEY=` (vazio) | `screenshot.py`, `gemini.py` | Funciona | Desativado por default. Funcional mas hotkey extra complexifica setup |
| Briefing Matinal | `BRIEFING_ENABLED=false` | `briefing.py` | Funciona com limitacoes | OFF por default. Depende de historico com 3+ entradas nas ultimas 24h. Custo de chamada Gemini no startup |
| Pipeline Composto | `PIPELINE_HOTKEY=` (vazio) | `audio.py`, `gemini.py`, `openrouter.py` | Funciona | Desativado por default. Sobreposicao com modo `query` + clipboard context |

### 1.4 Providers de AI

| Provider | Modulo | Ativo por padrao | Status | Observacao |
|----------|--------|-----------------|--------|------------|
| Gemini (direto) | `gemini.py` | Sim (fallback) | Funciona bem | Provider historico, ainda o principal |
| OpenRouter | `openrouter.py` | Sim (prioridade 1 se key configurada) | Funciona | Smart routing: Llama 4 Scout (modos rapidos) + Gemini (complexos) |
| OpenAI (direto) | `openai_.py` | Nao (prioridade 3) | Funciona | Legacy. Sem diferencial real vs OpenRouter |
| Groq | `groq_.py` | Nao | Codigo morto | **Nunca chamado** -- `ai_provider.py` nao roteia para Groq em nenhum caminho |

### 1.5 Infrastructure/Support

| Feature | Modulo | Status | Observacao |
|---------|--------|--------|------------|
| Named Mutex (instancia unica) | `mutex.py` | Funciona bem | Win32 nativo |
| Graceful shutdown | `shutdown.py` | Funciona bem | Libera mutex, espera transcricao pendente |
| Rotacao de log | `logging_.py` | Funciona bem | Mantem N sessoes configuravel |
| Onboarding wizard (5 steps) | `ui.py` | Funciona | CTk -- chamado apenas na primeira execucao |
| Settings dialog | `ui.py` | Funciona | CTk com sidebar -- inclui abas para Whisper, Gemini, hotkeys, perfil |
| History search | `history_search.py` | Funciona | CTk, busca em tempo real, clique para colar |
| Limpeza de WAVs temporarios | `app.py` | Funciona | Deleta `tmp*.wav` com mtime > 1h no startup |
| Wake word detection | `wakeword.py` | Parcialmente implementado | Codigo OK, deps ausentes do requirements.txt |
| Animate engine | `animate.py` | Codigo morto | Classe `Animator` + easing functions. Importado por nenhum modulo atual |
| Theme system | `theme.py` | Funciona bem | Design tokens JP Labs, usado em CTk e overlay |
| Modes centralization | `modes.py` | Funciona bem | Eliminou duplicacao entre modulos |
| Profile trigger por voz | `ai_provider.py` | Funciona | "adiciona ao meu perfil: ..." no modo `transcribe` |
| Cleanup de clipboard/screenshot apos transcricao | `audio.py` | Funciona bem | Evita memory leak no `finally` |
| Cooldown anti-bounce query | `state.py`, `audio.py` | Funciona | 2s cooldown apos modo query |
| Debug de performance | `config.py`, `audio.py` | Funciona | `DEBUG_PERF=true` imprime breakdown [PERF] |

---

## 2. Classificacao por Status

### Funciona bem (nucleo saudavel)

- Gravacao + transcricao + paste (pipeline principal)
- Modos `transcribe`, `query`, `email` (mais usados)
- Overlay de feedback visual
- System tray com 3 estados
- History search
- Cleanup e shutdown gracioso
- Retry com backoff exponencial (`ai_utils.py`)
- OpenRouter como gateway principal

### Funciona mas com uso questionavel

- `bullet` e `translate` -- modos validos, mas fora do ciclo padrao por default. Se nao estao no ciclo, como o usuario os acessa? So via tray menu ou editando `CYCLE_MODES`. Baixa discoverability.
- Briefing Matinal -- funciona, mas e OFF por default, depende de historico suficiente, e faz uma chamada Gemini no startup as 8h. Custo alto, beneficio baixo para uso solo.
- User Profile -- overhead constante em todos os prompts para todos os modos, mesmo quando o contexto nao e relevante. OFF por default por uma razao.
- Window Context -- baixo ROI. Raramente o titulo da janela muda o output da AI de forma significativa para os casos de uso reais (transcrever, email, query generica).

### Funciona mas nunca e usado (desativado por default sem caminho claro de ativacao)

- Visual Query (`VISUAL_HOTKEY` vazio) -- requer o usuario editar `.env` manualmente. Nao aparece no onboarding.
- Pipeline (`PIPELINE_HOTKEY` vazio) -- mesma situacao.
- `clipboard_context` como modo (ID existe em `modes.py`) -- nunca e ativavel como modo ciclo. Funcionalidade existe via `query` + clipboard automatico.

### Codigo morto ou parcialmente implementado

| Item | Localizacao | Situacao |
|------|-------------|----------|
| `groq_.py` -- modulo inteiro | `voice/groq_.py` | **Nunca chamado.** `ai_provider.py` nao tem nenhum branch para Groq. As funcoes `correct_with_groq`, `bullet_dump_with_groq`, `draft_email_with_groq`, `translate_with_groq` existem mas nao sao referenciadas em nenhum caminho de execucao. |
| `animate.py` -- `Animator` e helpers | `voice/animate.py` | Modulo completo sem nenhum importador atual. `overlay.py` implementou as proprias animacoes inline (slide/fade com `after()`). O modulo foi criado para uso futuro em CTk mas nenhuma janela o usa. |
| `clipboard_context` mode ID | `voice/modes.py` linha 17 | Modo declarado como `"clipboard_context": "Contexto do Clipboard"` -- nunca e selecionado, sem hotkey, sem rota em `ai_provider.py`. |
| Wake word -- dependencia ausente | `voice/wakeword.py` | Codigo correto, mas `openwakeword` + `onnxruntime` **nao estao em `requirements.txt`**. Se `WAKE_WORD_ENABLED=true`, a thread sobe e cai imediatamente com `[WARN] Wake word desativado -- dependencia ausente`. |
| `QUERY_HOTKEY` (legacy) | `config.py` linha 19 | Variavel carregada no config com default `ctrl+shift+alt+space`, mas nunca registrada como hotkey em `app.py`. O loop `_hotkey_loop()` nao usa `QUERY_HOTKEY`. Sobrou de versao anterior. |
| `AI_PROVIDER` config flag | `config.py`, `app.py` | Variavel existe (`gemini` | `openai`), mas `ai_provider.py` ignora ela -- a prioridade real e `OPENROUTER_API_KEY > GEMINI_API_KEY > OPENAI_API_KEY`. `AI_PROVIDER` nunca e lida em `ai_provider.py`. |

---

## 3. Analise Detalhada dos Casos Criticos

### `groq_.py` -- Dead code confirmado

`ai_provider.py` tem tres branches: `_dispatch_openrouter`, `_dispatch_gemini`, `_dispatch_openai`. Groq nao existe como branch. `groq_.py` tem 4 funcoes implementadas, nenhuma importada. O ficheiro ocupa ~163 linhas sem contribuir para execucao.

Causa provavel: Groq foi planejado como alternativa fast para os modos `transcribe/email/bullet/translate`, mas foi substituido por OpenRouter (que ja usa Llama 4 Scout nos fast modes). O arquivo foi esquecido.

### `animate.py` -- Dead code confirmado

Grep de todos os modulos: nenhum `from voice.animate import` ou `from voice import animate` em producao. O modulo foi construido como abstracao para animacoes CTk, mas `overlay.py` (tkinter puro) nao usa CTk e implementou suas animacoes diretamente. `ui.py` e `briefing.py` nao usam `Animator`.

### `wakeword.py` -- Parcialmente implementado

O codigo esta correto mas as dependencias (`openwakeword`, `onnxruntime`) nao estao pinadas em `requirements.txt`. Qualquer usuario que definir `WAKE_WORD_ENABLED=true` tera a feature silenciosamente desativada com `[WARN]`. Nao e bug de codigo -- e bug de setup.

### `QUERY_HOTKEY` -- Variavel obsoleta

`config.py` carrega `QUERY_HOTKEY=ctrl+shift+alt+space` como default. `.env.example` documenta ela. `app.py/_hotkey_loop()` nao registra esta hotkey. O modo query e acessado via `CYCLE_HOTKEY` + ciclo de modos, nao via hotkey dedicada. A variavel sobreviveu de quando `query` tinha hotkey propria (Epic anterior).

### `AI_PROVIDER` -- Variavel documentada mas ignorada em runtime

`.env.example` documenta `AI_PROVIDER=gemini | openai`. `config.py` carrega o valor. Mas `ai_provider.py` usa prioridade explicita por presenca de API key -- nunca le `AI_PROVIDER`. Isso significa que se o usuario tem `AI_PROVIDER=openai` mas tambem tem `OPENROUTER_API_KEY` configurada, o comportamento sera OpenRouter, contrariando a intencao declarada.

---

## 4. Auditoria do `.env.example` vs Codigo

| Variavel | Documentada | Usada no codigo | Status |
|----------|-------------|-----------------|--------|
| `LICENSE_KEY` | Sim | Sim | OK |
| `OPENROUTER_API_KEY` | Sim | Sim (prioridade 1) | OK |
| `GEMINI_API_KEY` | Sim | Sim (prioridade 2) | OK |
| `GEMINI_MODEL` | Sim | Sim | OK |
| `WHISPER_MODEL` | Sim | Sim (fallback global) | OK |
| `WHISPER_MODEL_FAST` | Sim | Sim | OK |
| `WHISPER_MODEL_QUALITY` | Sim | Sim | OK |
| `MAX_RECORD_SECONDS` | Sim | Sim | OK |
| `AUDIO_DEVICE_INDEX` | Sim | Sim | OK |
| `QUERY_HOTKEY` | Sim | **Nao** -- lida no config mas nunca registrada | RUIDO |
| `QUERY_SYSTEM_PROMPT` | Sim | Sim (modo query e visual) | OK |
| `WHISPER_LANGUAGE` | Sim | Sim | OK |
| `HISTORY_MAX_ENTRIES` | Sim | Sim | OK |
| `LOG_KEEP_SESSIONS` | Sim | Sim | OK |
| `VAD_THRESHOLD` | Sim | Sim | OK |
| `WHISPER_INITIAL_PROMPT` | Sim | Sim | OK |
| `AI_PROVIDER` | Sim | **Ignorada em runtime** -- `ai_provider.py` usa key presence | ENGANOSA |
| `OPENAI_API_KEY` | Sim | Sim (prioridade 3) | OK |
| `GROQ_API_KEY` | Sim | **Nunca roteada** -- `groq_.py` nunca chamado | RUIDO |
| `STT_PROVIDER` | Sim | Sim | OK |
| `GEMINI_CORRECT` | Sim | Sim | OK |
| `CYCLE_HOTKEY` | Sim | Sim | OK |
| `CYCLE_MODES` | Sim | Sim | OK |
| `OVERLAY_ENABLED` | Sim | Sim | OK |
| `HISTORY_HOTKEY` | Sim | Sim | OK |
| `CLIPBOARD_CONTEXT_ENABLED` | Sim | Sim | OK |
| `CLIPBOARD_CONTEXT_MAX_CHARS` | Sim | Sim | OK |
| `WHISPER_BEAM_SIZE` | Sim | Sim | OK |
| `PASTE_DELAY_MS` | Sim | Sim | OK |
| `USER_PROFILE_ENABLED` | Sim | Sim | OK |
| `WINDOW_CONTEXT_ENABLED` | Sim | Sim | OK |
| `VISUAL_HOTKEY` | Sim | Sim | OK |
| `SCREENSHOT_MAX_WIDTH` | Sim | Sim | OK |
| `BRIEFING_ENABLED` | Sim | Sim | OK |
| `BRIEFING_MIN_ENTRIES` | Sim | Sim | OK |
| `PIPELINE_HOTKEY` | Sim | Sim | OK |
| `PIPELINE_CLIPBOARD_MAX_CHARS` | Sim | Sim | OK |
| `DEBUG_PERF` | Sim | Sim | OK |
| `WAKE_WORD_ENABLED` | Nao (ausente no .env.example) | Sim (lida no config) | INCONSISTENTE |
| `WAKE_WORD_KEYWORD` | Nao (ausente no .env.example) | Sim | INCONSISTENTE |
| `OPENROUTER_MODEL_FAST` | Nao (ausente no .env.example) | Sim | INCONSISTENTE |
| `OPENROUTER_MODEL_QUALITY` | Nao (ausente no .env.example) | Sim | INCONSISTENTE |
| `GROQ_MODEL` | Nao (ausente no .env.example) | Sim (mas em modulo dead) | IRRELEVANTE |
| `SOUND_START/SUCCESS/ERROR/WARNING/SKIP` | Nao (ausentes no .env.example) | Sim | INCONSISTENTE |

---

## 5. Sumario Executivo

### Remover (codigo morto com custo de manutencao)

| Item | Motivo |
|------|--------|
| `voice/groq_.py` (inteiro) | Nunca chamado. OpenRouter ja cobre o papel com Llama 4 Scout |
| `voice/animate.py` (inteiro) | Nunca importado. Overlay usa animacoes inline; nenhuma janela CTk usa `Animator` |
| `"clipboard_context"` de `modes.py` | ID de modo fantasma. Nao existe hotkey, rota, ou ponto de acesso |
| `QUERY_HOTKEY` de `config.py` e `.env.example` | Variavel obsoleta. Hotkey foi removida de `app.py` em algum Epic, mas config e docs sobreviveram |
| `GROQ_API_KEY` e `GROQ_MODEL` de `config.py` | Sem modulo ativo que use. Remove junto com `groq_.py` |

### Corrigir (documentacao vs comportamento)

| Item | Correcao |
|------|---------|
| `AI_PROVIDER` -- documentada mas ignorada | Ou (a) remover a variavel e atualizar docs para explicar a prioridade real por key, ou (b) implementar o roteamento por `AI_PROVIDER` em `ai_provider.py` |
| `WAKE_WORD_ENABLED/KEYWORD` -- sem documentacao | Adicionar ao `.env.example` com aviso de dependencia (`openwakeword`, `onnxruntime`) |
| `OPENROUTER_MODEL_FAST/QUALITY` -- sem documentacao | Adicionar ao `.env.example` |
| `SOUND_*` vars -- sem documentacao | Adicionar ao `.env.example` |
| Wake word -- dependencias ausentes | Adicionar `openwakeword` e `onnxruntime` ao `requirements.txt` OU documentar que sao opcionais e como instalar |

### Simplificar (features que complicam sem valor proporcional)

| Feature | Recomendacao |
|---------|-------------|
| Briefing Matinal | Feature valida conceitualmente, mas overhead de chamada Gemini no startup para gerar 3 bullets. Considerar tornar trigger manual (hotkey ou menu tray) em vez de automatico no startup |
| User Profile | OK como esta (OFF por default). O risco e encorajar ativacao sem perceber que injeta contexto em absolutamente todos os prompts, incluindo `transcribe` (onde e irrelevante) |
| Window Context | Baixo ROI. Raramente o titulo da janela muda o output da AI de forma significativa. Candidato a remocao na proxima revisao |
| Visual Query e Pipeline (desativados por default) | O setup requer editar `.env` manualmente. Se sao features validas, deveriam aparecer no Settings dialog com toggle, nao depender de edicao manual |

### Manter sem mudanca

- Todo o core pipeline (gravacao, transcricao, paste)
- Todos os 5 modos do ciclo padrao
- Overlay, system tray, history search
- OpenRouter como provider principal
- `ai_utils.py`, `modes.py`, `theme.py`, `clipboard.py`, `state.py`
- `wakeword.py` (manter o codigo, so corrigir docs e requirements)

# PRD — Voice Commander

**Versao do Produto:** 1.0.14
**Tipo:** Ferramenta pessoal (uso interno JP Labs)
**Owner:** JP
**PRD criado em:** 2026-02-24
**PRD atualizado em:** 2026-03-02
**Repositorio:** `thejplabs/voice-commander`

---

## Nota sobre Nomenclatura

> Os documentos anteriores (commits, DEX MEMORY, changelogs) usam o termo "Sprint N" para se referir aos ciclos de entrega iniciais. A partir deste PRD, a nomenclatura canonica passa a ser **Epic N**. O mapeamento retroativo e:
>
> - Sprint 1 = Epic 1
> - Sprint 2 = Epic 2
> - Sprint 3 = Epic 3
>
> Epic 4 em diante segue a nomenclatura nova. Ao referenciar trabalho passado, ambos os termos sao validos.

---

## 1. Overview

**Voice Commander** e uma ferramenta voice-to-text para Windows que captura audio via hotkey global, transcreve localmente com Whisper, processa com Gemini e cola o resultado diretamente onde o cursor estiver — sem janela visivel, sem distracao.

O produto resolve um fluxo real de trabalho do JP: ditar comandos, prompts e texto corrido em qualquer aplicativo do Windows com latencia minima e sem depender de servicos cloud para a transcricao.

### Modos de Operacao (atual — 7 modos)

| Hotkey | Modo | Comportamento |
|--------|------|---------------|
| `Ctrl+Shift+Space` | Transcricao pura | Transcreve e corrige erros de pronuncia via Gemini |
| `Ctrl+Alt+Space` | Prompt simples | Transcreve e organiza em bullet points |
| `Ctrl+CapsLock+Space` | Prompt estruturado | Formata em SYSTEM + USER com XML tags (framework COSTAR) |
| `Ctrl+Shift+Alt+Space` | Query direta Gemini | Transcreve e envia ao Gemini — cola a resposta direto |
| *(via CYCLE_HOTKEY)* | Clipboard Context | Captura clipboard atual como contexto para instrucao de voz |
| `VISUAL_HOTKEY` | Screenshot + Voice | Captura screenshot + voz — Gemini processa imagem e instrucao |
| `PIPELINE_HOTKEY` | Pipeline Composto | Clipboard como fonte + voz como instrucao — Gemini executa transformacao |

Hotkeys de modo 4, visual e pipeline sao configuráveis via `.env` (`QUERY_HOTKEY`, `VISUAL_HOTKEY`, `PIPELINE_HOTKEY`).

---

## 2. Constraints Tecnicas (BLOQUEANTES)

> Estas constraints sao inegociaveis para Epic 1-4. Revisao apenas a partir de Epic 5+.

### Windows-Only por Design

| Constraint | Detalhe |
|------------|---------|
| **Sistema Operacional** | Windows 10 / 11 exclusivo |
| **ctypes.windll** | Usado para `SendInput` (paste), `winsound` (beeps de feedback), `Named Mutex Win32` (singleton) |
| **SendInput** | Cola texto via simulacao de teclado — sem equivalente cross-platform simples |
| **winsound** | Beeps de feedback auditivo — API exclusiva do Windows |
| **Named Mutex Win32** | Garante instancia unica — usa `CreateMutexW` da win32 API |

**Suporte macOS/Linux: fora do escopo ate Epic 5+.** Qualquer story que proponha abstrair ctypes.windll deve ser movida para o backlog com justificativa de negocio clara.

### Runtime e Dependencias

| Constraint | Valor |
|------------|-------|
| **Python** | 3.13 exclusivo — dependencias testadas nesta versao |
| **Versoes pinadas** | `requirements.txt` com versoes fixas — nao atualizar sem ciclo de teste |
| **Dependencias principais** | faster-whisper 1.2.1, google-genai 1.63.0, keyboard 0.13.5, sounddevice 0.5.5, numpy 2.4.2, pystray 0.19.5, Pillow 11.1.0, customtkinter 5.2.2 |
| **Modelo Whisper** | `small` por default (~244 MB, baixado na 1a execucao) |
| **Execucao sem console** | `pythonw.exe` — stdout/stderr sao None, verificar antes de escrever |

---

## 3. Estado Atual — Epics 1-4 Entregues

### Epic 1 (Sprint 1) — Fundacao [DONE]

Estabeleceu o nucleo funcional do produto.

**Entregas:**
- Gravacao de audio via `sounddevice` com toggle por hotkey
- Transcricao local com `faster-whisper` (modelo `small`)
- 3 modos de output: transcricao pura, prompt simples, prompt estruturado
- Paste via `ctypes.SendInput` — zero dependencia de clipboard
- Singleton via Named Mutex Win32 (instancia unica garantida)
- Log em arquivo (`voice.log`)
- Cache de API key + configuracao centralizada via `.env`
- Timeout de gravacao `MAX_RECORD_SECONDS` com bip de aviso 5s antes
- Consolidacao dos launchers VBS (`launch_voice.vbs` com path absoluto + fallback)
- Dependencias pinadas em `requirements.txt`

---

### Epic 2 (Sprint 2) — UX e Modos [DONE]

Adicionou visibilidade de estado e expandiu os modos de operacao.

**Entregas:**
- System tray com 3 estados visuais via `pystray`:
  - Cinza = aguardando
  - Vermelho = gravando
  - Amarelo = processando
- Menu tray: Status (modo + configuracoes ativas), Encerrar
- Modo 4: Query Direta Gemini (`Ctrl+Shift+Alt+Space`, configuravel via `QUERY_HOTKEY`)
- Validacao de microfone no startup (falha com log `[ERRO]` se dispositivo indisponivel)
- Loop de resiliencia de hotkeys (re-registro automatico em caso de falha)

---

### Epic 3 (Sprint 3) — Observabilidade [DONE]

Adicionou rastreabilidade completa de transcricoes e logs robustos.

**Entregas:**

**Story 3.1 — Historico de transcricoes (`history.jsonl`)**
- Arquivo append-only com todas as transcricoes
- Campos: `timestamp`, `mode`, `raw_text`, `processed_text`, `duration_seconds`, `chars`
- Erros registrados com `"error": true` e `"processed_text": null`
- Trim automatico ao atingir `HISTORY_MAX_ENTRIES` (default: 500)
- Ignorado pelo git (dado pessoal)

**Story 3.2 — Rotacao de log por sessao**
- Log anterior renomeado para `voice.YYYY-MM-DD_HH-MM-SS.log` a cada startup
- `LOG_KEEP_SESSIONS` controla quantas sessoes manter (default: 5)
- Sessoes mais antigas deletadas automaticamente

**Story 3.3 — Graceful shutdown**
- Aguarda transcricao finalizar se gravacao ativa no momento do shutdown
- Thread-safe: usa `_toggle_lock` para ler estado de gravacao
- Timeout de 10s para transcricao de shutdown — apos isso, aborta com `[WARN]`
- `try/finally` garante `_release_named_mutex()` em qualquer cenario
- Reutilizado no Ctrl+C e no menu tray (Encerrar)

---

### Quick Wins 2026-02-24 [DONE]

| Item | Detalhe |
|------|---------|
| `.gitignore` | `history.jsonl` + `logs/` adicionados — dados pessoais nao versionados |
| Singleton Gemini | `_get_gemini_client()` — instancia unica em memoria, inicializada sob demanda |
| `__version__` em `voice.py` | Source unica de verdade para a versao — sem duplicacao |
| Clipboard via ctypes | `_paste_via_sendinput()` — refatoracao que consolida o metodo de paste |

---

### Epic 4 — Qualidade e Distribuicao [DONE — superado]

**Objetivo original:** Tornar o codebase testavel, modular e com CI automatizado.

**Status:** Concluido e superado. O codebase evoluiu alem do planejado original.

**Evidencias:**

| Story | Entrega | Status |
|-------|---------|--------|
| 4.1 — Pytest | `tests/` com 19 arquivos, 243 testes passando | DONE |
| 4.2 — Modularizacao | Pacote `voice/` com ~26 modulos | DONE |
| 4.3 — CI GitHub Actions | `.github/workflows/ci.yml` operacional | DONE |
| 4.4 — Gemini model abstraction (SM-3) | `GEMINI_MODEL` configuravel via `.env` | DONE |

**Features extras entregues no Epic 4 (alem do escopo original):**

| Feature | Detalhe |
|---------|---------|
| OpenAI como AI provider alternativo | `voice/ai_provider.py` — switch Gemini/OpenAI via `AI_PROVIDER` |
| Wake word | `voice/wakeword.py` |
| GPU/CUDA fallback automatico | Detectado e usado se disponivel |
| 7 modos de operacao | Expandido de 4 para 7 modos |
| Single hotkey ciclo de modos | `CYCLE_HOTKEY` implementado |

**Quick Wins QW-1 a QW-8 (housekeeping pre-Epic 4.5) [DONE]**

| QW | Descricao | Status |
|----|-----------|--------|
| QW-1 | Fix cooldown 2s apos modo query | DONE |
| QW-2 | Pin de versao do openai em requirements.txt | DONE |
| QW-3 | Wake word — dependencia ausente em requirements.txt | DONE |
| QW-4 | `beam_size` e `PASTE_DELAY_MS` configuravel | DONE |
| QW-5 | OpenAI startup check com fallback | DONE |
| QW-6 | Tray: duracao de gravacao no tooltip | DONE |
| QW-7 | Housekeeping: temp file cleanup no startup | DONE |
| QW-8 | ui.py — winfo_exists() check antes de interagir com Settings Window | DONE |

Commit de referencia: `eee3857 feat(ux): Quick Wins QW-1 a QW-8 + Epic 4.5 UX features`

---

## 4. Epic 4.5 — UX & Qualidade [6/7 DONE]

**Objetivo:** Fechar gaps de UX criticos e elevar cobertura de testes antes de distribuir comercialmente.
**Premissa:** Sem feedback visual claro, Epic 5 distribui um produto que o usuario percebe como "lento e opaco". UX primeiro.
**Branch:** `feature/SM-3-gemini-model`

| Story | Descricao | Status | Evidencia |
|-------|-----------|--------|-----------|
| 4.5.1 | Overlay/toast de feedback pos-hotkey | DONE | `voice/overlay.py` |
| 4.5.2 | Testes: audio, gemini, ai_provider | DONE | 243 testes (19 arquivos em `tests/`) |
| 4.5.3 | Hotkey de ciclo de modo | DONE | `CYCLE_HOTKEY` em `voice/config.py` |
| 4.5.4 | Modo "Clipboard Context" | DONE | `CLIPBOARD_CONTEXT_ENABLED` em config |
| 4.5.5 | Busca no historico (overlay CTk) | DONE | `voice/history_search.py`, `HISTORY_HOTKEY` |
| 4.5.6 | GEMINI_MODEL_QUALITY separado | NAO IMPLEMENTADO | Backlog P3 |
| 4.5.7 | Modo Screenshot + Voice | DONE | `voice/screenshot.py`, `VISUAL_HOTKEY` |

### Story 4.5.1 — Overlay/toast de feedback pos-hotkey [DONE]

**Modulo:** `voice/overlay.py`
**AC entregues:**
- Toast nao-bloqueante aparece ao pressionar hotkey de inicio
- Estado "Gravando": indicador vermelho + texto
- Estado "Processando": spinner + texto
- Estado "Pronto": preview do output (2s auto-dismiss)
- Overlay nao rouba foco da janela ativa
- `OVERLAY_ENABLED=true` no `.env.example`
- `OVERLAY_POSITION=bottom-right` configuravel

---

### Story 4.5.2 — Testes: audio, gemini, ai_provider [DONE]

**Evidencia:** 243 testes passando em 19 arquivos (`tests/`), cobertura expandida de 136 para 243 testes (+107)
**Commit:** `8967884 test: cobertura de 136 para 243 testes (+107) — Epic 4.5 e QWs`

---

### Story 4.5.3 — Hotkey de ciclo de modo [DONE]

**Config:** `CYCLE_HOTKEY` (default: `ctrl+shift+tab`)
**Funcionalidade:** Cicla entre os modos disponiveis em ordem circular; tray tooltip atualiza imediatamente

---

### Story 4.5.4 — Modo Clipboard Context [DONE]

**Config:** `CLIPBOARD_CONTEXT_ENABLED`
**Funcionalidade:** Captura clipboard no inicio da gravacao; injeta como contexto no prompt Gemini. Fallback para modo query se clipboard vazio.

---

### Story 4.5.5 — Busca no historico [DONE]

**Modulo:** `voice/history_search.py`
**Config:** `HISTORY_HOTKEY` (default: `ctrl+shift+h`)
**Funcionalidade:** Overlay customtkinter com campo de busca + lista de resultados; selecionar cola via `_paste_via_sendinput()`

---

### Story 4.5.6 — GEMINI_MODEL_QUALITY separado [NAO IMPLEMENTADO]

**Prioridade:** P3 — backlog
**Estimativa:** 0.5 dia
**Agente:** @dev
**Dependencias:** SM-3 concluida (GEMINI_MODEL ja configuravel)

**AC pendente:**
- `GEMINI_MODEL_QUALITY` no `.env.example` — permite modelo diferente para tarefas leves
- Se ausente: usa `GEMINI_MODEL` para tudo (comportamento atual preservado)
- Startup log: `[INFO] Gemini: {model} (quality: {quality_model})`

---

### Story 4.5.7 — Modo Screenshot + Voice [DONE]

**Modulo:** `voice/screenshot.py`
**Config:** `VISUAL_HOTKEY` (default: `ctrl+alt+shift+v`), `SCREENSHOT_MAX_WIDTH`
**Funcionalidade:** Captura screenshot + transcricao; envia para Gemini multimodal via `Part.from_bytes()`

---

## 5. Features Bonus (alem do roadmap original)

Quatro features implementadas no branch `feature/SM-3-gemini-model` alem do escopo planejado. Todas funcionais, testes escritos, config documentada. Status: aguardando merge em `master`.

### Feature 1 — User Profile

**Modulo:** `voice/user_profile.py`
**Config:** `USER_PROFILE_ENABLED`
**Storage:** `user-profile.json` em `_BASE_DIR`
**Estado:** `state._user_profile`
**Funcionalidade:** Fatos pessoais do usuario (nome, preferencias, contexto) injetados como prefixo em todos os prompts Gemini via `_build_context_prefix()` em `voice/gemini.py`.
**Voice trigger:** "adiciona ao meu perfil: [fato]"
**UI:** Settings > Perfil

---

### Feature 2 — Window Context

**Modulo:** `voice/window_context.py`
**Config:** `WINDOW_CONTEXT_ENABLED=false` (OFF por padrao)
**Estado:** `state._window_context`
**Funcionalidade:** Captura titulo e processo da janela ativa no inicio de `toggle_recording()` via ctypes. Injetado no contexto Gemini junto com User Profile.

---

### Feature 3 — Briefing Matinal

**Modulo:** `voice/briefing.py`
**Config:** `BRIEFING_ENABLED=true`, `BRIEFING_MIN_ENTRIES=3`
**Funcionalidade:** Thread daemon lancada 3s apos startup. Time gate: 8h (dispara apenas no periodo da manha). Gera resumo diario das transcricoes via `generate_daily_briefing(entries)`. UI: `BriefingWindow` customtkinter.

---

### Feature 4 — Pipeline Composto

**Hotkey:** `PIPELINE_HOTKEY` (default: `ctrl+alt+shift+p`)
**Config:** `PIPELINE_CLIPBOARD_MAX_CHARS=8000`
**Modo:** `"pipeline"`
**Funcionalidade:** Captura clipboard como fonte de dados + instrucao de voz → Gemini executa a transformacao via `execute_pipeline(instruction, source_text)`. Clipboard capturado sempre (ignora `CLIPBOARD_CONTEXT_ENABLED`).

---

## 6. Arquitetura Atual (2026-03-02)

| Atributo | Valor |
|----------|-------|
| **Versao** | 1.0.14 |
| **Branch ativo** | `feature/SM-3-gemini-model` |
| **Pacote principal** | `voice/` (~26 modulos) |
| **Testes** | 243 testes em `tests/` (19 arquivos) |
| **CI** | `.github/workflows/ci.yml` (GitHub Actions) |
| **Modos de operacao** | 7 (transcription, prompt, costar, query, clipboard_context, visual, pipeline) |
| **AI Providers** | Gemini (primario) + OpenAI (alternativo) via `voice/ai_provider.py` |

### Modulos principais (`voice/`)

| Modulo | Responsabilidade |
|--------|-----------------|
| `app.py` | Entry point e orquestracao principal |
| `config.py` | `load_config()`, `_BASE_DIR`, `.env` loading |
| `state.py` | Estado global (recording, mode, buffers, profiles) |
| `audio.py` | Gravacao sounddevice, timeout, bips |
| `gemini.py` | Cliente Gemini, `_build_context_prefix()`, 7 modos |
| `ai_provider.py` | Abstraction layer Gemini/OpenAI |
| `overlay.py` | Toast/feedback visual |
| `tray.py` | System tray, 3 estados visuais, menu |
| `ui.py` | Settings dialog (customtkinter) |
| `history_search.py` | Busca em history.jsonl (overlay) |
| `screenshot.py` | Captura de tela (PIL.ImageGrab) |
| `user_profile.py` | Perfil do usuario (load, add, remove facts) |
| `window_context.py` | Contexto da janela ativa (ctypes) |
| `briefing.py` | Briefing matinal (thread daemon, BriefingWindow) |
| `clipboard.py` | Leitura de clipboard |
| `license.py` | Validacao HMAC local |
| `transcribe.py` | faster-whisper, append history |
| `shutdown.py` | graceful_shutdown, release mutex |
| `wakeword.py` | Wake word detection |
| `theme.py` | Temas visuais |

### Hotkeys (lista completa)

| Config | Default | Feature |
|--------|---------|---------|
| `RECORD_HOTKEY` | `ctrl+shift+space` | Gravacao principal |
| `CYCLE_HOTKEY` | `ctrl+shift+tab` | Ciclar entre modos |
| `HISTORY_HOTKEY` | `ctrl+shift+h` | Buscar no historico |
| `VISUAL_HOTKEY` | `ctrl+alt+shift+v` | Screenshot + Voz |
| `PIPELINE_HOTKEY` | `ctrl+alt+shift+p` | Pipeline Composto |

---

## 7. Definition of Done

Criterios aplicaveis a todas as stories do Epic 4.5 em diante:

- [ ] Codigo commitado no branch `feature/{story-id}` e mergeado em `master`
- [ ] `python -m py_compile voice/*.py` sem erros
- [ ] 7 modos existentes sem regressao (testado manualmente)
- [ ] Testado com `pythonw.exe` (sem console — stdout/stderr sao None)
- [ ] `.env.example` atualizado se nova variavel de configuracao adicionada
- [ ] `README.md` atualizado se a feature e visivel ao usuario
- [ ] `python -m pytest tests/ -v` passa com zero falhas
- [ ] CI verde no PR antes do merge
- [ ] Prefixos de log respeitados: `[OK]`, `[...]`, `[WARN]`, `[ERRO]`, `[REC]`, `[STOP]`, `[SKIP]`, `[INFO]`

---

## 8. Epic 5 — Comercializacao [BLOQUEADO — nao iniciado]

**Status:** Planejado — nao iniciar antes do merge de `feature/SM-3-gemini-model` em `master`.

**Prerequisito inegociavel:**
1. Branch `feature/SM-3-gemini-model` mergeado em `master` (PR pendente)
2. Epic 4.5 majoritariamente concluido (6/7 stories DONE — Story 4.5.6 em backlog, nao bloqueante)
3. CI verde em `master`

**Objetivo:** Transformar a ferramenta pessoal em produto vendavel com licenciamento server-side e distribuicao via instalador.
**Estimativa total:** 12-16 dias
**Agentes:** @dev (DEX), @architect (design de API), @devops (GAGE para infra)

---

### Story 5.1 — Server-side license validation (LT-1)

**Prioridade:** P1 — bloqueante para comercializacao
**Estimativa:** 5-8 dias
**Agentes:** @dev + @architect
**Dependencias:** endpoint `voice.jplabs.ai` operacional (infra GAGE)

**Contexto:** O sistema HMAC local atual (`vc-{expiry_b64}-{sig}`) valida apenas a assinatura — nao verifica revogacao, nao rastrea uso, nao permite renovacao sem novo binario. A validacao server-side resolve isso.

**Nota critica de sequencia:** @architect deve definir o schema do endpoint antes do DEX implementar o cliente. Nao iniciar implementacao sem design de API aprovado.

**AC:**
- Endpoint `POST /validate` em `voice.jplabs.ai` — recebe chave, retorna `{valid, expires_at, plan}`
- HMAC local vira fallback offline (timeout 72h — atual)
- Diagrama de estados documentado: online-valid / online-invalid / offline-grace / offline-expired
- Chave como identificador de sessao (zero dados pessoais no payload)
- Retry com backoff exponencial (3 tentativas, timeout 5s por tentativa)
- Log: `[OK] Licenca validada (server) | expira em X dias`

---

### Story 5.2 — Auto-update simplificado (version.txt)

**Prioridade:** P1 — necessario para distribuicao sustentavel
**Estimativa:** 1-2 dias
**Agente:** @dev
**Dependencias:** Story 5.1 concluida (reusa endpoint `voice.jplabs.ai`)

**AC:**
- `GET https://voice.jplabs.ai/version.txt` no startup — retorna ultima versao disponivel
- Comparacao com `__version__` local
- Se nova versao: notificacao nao-intrusiva via tray balloon ou menu item "Atualizacao disponivel (vX.Y.Z)"
- Timeout da verificacao: 3s — nao bloqueia startup
- `AUTO_UPDATE_CHECK=true` no `.env.example` (pode desativar)
- Sem auto-instalacao — usuario clica e e redirecionado para pagina de download

---

### Story 5.3 — Instalador Inno Setup atualizado

**Prioridade:** P1 — prerequisito para distribuicao
**Estimativa:** 1 dia
**Agentes:** @dev + @devops
**Dependencias:** todas as features de Epic 4.5 mergeadas em master

**AC:**
- `AppVersion` em `build/installer.iss` sincronizado com `__version__` (processo documentado — nao e automatico)
- Build PyInstaller inclui pacote `voice/` completo (~26 modulos)
- Instalador testado em Windows 10 e Windows 11 limpo (sem Python instalado)
- `VoiceCommanderSetup.exe` gerado e testado end-to-end com todos os 7 modos

---

### Story 5.4 — ui.py: separar Onboarding e Settings

**Prioridade:** P2 — qualidade de codigo, facilita manutencao futura
**Estimativa:** 1 dia
**Agente:** @dev
**Dependencias:** Epic 4.5 concluido (base estavel)

**AC:**
- `voice/ui.py` refatorado em:
  - `voice/onboarding.py` — fluxo de primeiro uso (API key + licenca)
  - `voice/settings.py` — janela de configuracoes (acessivel pelo menu tray)
- Imports atualizados em todos os modulos que referenciam `ui.py`
- `python -m pytest tests/ -v` passa com zero falhas apos refactoring
- Funcionalidade identica — zero regressao

---

### Sequencia de Execucao — Epic 5

```
[PRE-REQUISITO] Merge de feature/SM-3-gemini-model em master
  ↓
5.1 (server-side license)   ← design de API com @architect primeiro
  ↓
5.2 (auto-update)           ← depende de 5.1 (reusa endpoint)
5.3 (instalador atualizado) ← depende de branch mergeado (paralelo com 5.2)
5.4 (separar ui.py)         ← pode ser paralelo a 5.1/5.2
```

---

## 9. Backlog

Itens identificados mas sem sprint definida. Revisao a cada Epic concluido.

| Item | Prioridade | Motivo do Adiamento |
|------|------------|---------------------|
| Story 4.5.6 — GEMINI_MODEL_QUALITY separado | P3 | Baixo impacto imediato — comportamento atual funcional |
| BOM UTF-16 no clipboard | Baixa | Nenhum problema reportado em producao com apps modernos — aguardar feedback real |
| Dois modelos Whisper em memoria (tiny + small) | Baixa | Complexidade de 2 instancias concorrentes — aguardar feedback de latencia do usuario |
| Dashboard web de historico (`history.jsonl`) | Baixa | Fora do escopo de ferramenta pessoal MVP — avaliar se ha demanda real |
| Suporte macOS/Linux | Nao priorizado | Bloqueado por `ctypes.windll`, `winsound` e Named Mutex Win32 — arquitetura precisaria ser reescrita |
| Whisper large-v3 como opcao default | Baixa | RAM e latencia — avaliar com feedback de usuarios reais |
| Modo Translate: mapa de idiomas expandido | Baixa | Funcional com PT/EN — expandir com feedback de uso real |
| Pipeline streaming Gemini | Baixa | Alto esforco, ganho marginal em maquinas rapidas — avaliar com metricas de latencia reais |

---

## 10. Metricas de Sucesso

### Epic 4 [DONE]
- `python -m pytest tests/ -v` — 243 testes, 0 falhas
- CI GitHub Actions — badge verde no `README.md`
- Pacote `voice/` modular com ~26 modulos
- 7 modos sem regressao em `pythonw.exe`

### Epic 4.5 [6/7 DONE]
- Overlay de feedback operacional (4.5.1) — nao rouba foco, 3 estados visuais
- Cobertura de testes: 243 testes (4.5.2)
- Hotkey de ciclo funcional (4.5.3)
- Clipboard context, busca no historico, screenshot+voice (4.5.4, 4.5.5, 4.5.7) — todos operacionais
- Story 4.5.6 em backlog P3 — nao bloqueante para Epic 5

### Epic 5 (quando executado)
- Licenca server-side — 100% das ativacoes validadas online (fallback offline acionado apenas em falhas de rede documentadas)
- Auto-update — notificacao exibida em menos de 3s apos startup quando nova versao disponivel
- Zero dados pessoais no payload de validacao de licenca
- Instalador testado em Windows 10 e 11 limpos (sem Python)

---

*JP Labs Creative Studio — Voice Commander PRD v1.1*
*Owner: JP | Criado: 2026-02-24 | Atualizado: 2026-03-02 | Versao do produto: 1.0.14*

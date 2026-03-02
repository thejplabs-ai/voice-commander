# Voice Commander — Roadmap

**Versao:** 1.0.14
**Data:** 2026-03-02
**Status:** Epic 4 concluido | Epic 4.5 DONE (6/7) | Epic 4.6 EM EXECUCAO | Epic 5 BLOQUEADO
**Branch atual:** feature/epic-4.6-polish

---

## Estado Real do Projeto (2026-03-02)

Epic 4 foi entregue e superado. Epic 4.5 concluido (6/7 stories). Branch `feature/SM-3-gemini-model` mergeado em `master` (2026-03-02). Epic 4.6 em execucao.

| Entregue | Status |
|----------|--------|
| Modularizacao completa (`voice/`) | DONE — 26 modulos |
| CI GitHub Actions | DONE — `.github/workflows/ci.yml` |
| Pytest 243 testes em 19 arquivos | DONE |
| Gemini model configuravel (SM-3) | DONE |
| 7 modos de operacao (antes: 4) | DONE |
| OpenAI como AI provider alternativo | DONE |
| Wake word | DONE |
| GPU/CUDA fallback automatico | DONE |
| Ciclo de modos (`CYCLE_HOTKEY`) | DONE |
| Overlay de feedback visual | DONE — `voice/overlay.py` |
| Busca no historico | DONE — `voice/history_search.py` |
| Screenshot + Voice | DONE — `voice/screenshot.py` |
| User Profile | DONE — `voice/user_profile.py` |
| Window Context | DONE — `voice/window_context.py` |
| Briefing Matinal | DONE — `voice/briefing.py` |
| Pipeline Composto | DONE — via `PIPELINE_HOTKEY` |
| Quick Wins QW-1 a QW-8 | DONE — commit `eee3857` |

---

## Quick Wins QW-1 a QW-8 [DONE — commit eee3857]

Todos os quick wins foram entregues. Referencia: `eee3857 feat(ux): Quick Wins QW-1 a QW-8 + Epic 4.5 UX features`.

| QW | Descricao | Status |
|----|-----------|--------|
| QW-1 | Fix cooldown 2s apos modo query | DONE |
| QW-2 | Pin de versao openai em requirements.txt | DONE |
| QW-3 | Wake word — dependencia ausente em requirements.txt | DONE |
| QW-4 | `beam_size` e `PASTE_DELAY_MS` configuravel | DONE |
| QW-5 | OpenAI startup check com fallback | DONE |
| QW-6 | Tray: duracao de gravacao no tooltip | DONE |
| QW-7 | Housekeeping: temp file cleanup no startup | DONE |
| QW-8 | ui.py — winfo_exists() check antes de interagir com Settings | DONE |

---

## Epic 4.5 — UX & Qualidade [6/7 DONE]

**Objetivo:** Fechar gaps de UX criticos e elevar cobertura de testes antes de distribuir comercialmente.
**Status:** 6/7 stories DONE. Story 4.5.6 em backlog P3 (nao bloqueante).
**Estimativa total:** 8-10 dias de desenvolvimento
**Agente principal:** @dev (DEX), @qa (QUINN) para validacao

---

### Story 4.5.1 — Overlay/toast de feedback pos-hotkey (P1)

**Prioridade:** P1 — maior impacto de UX, esforco medio
**Estimativa:** 2 dias
**Agente:** @dev
**Dependencias:** nenhuma

**Contexto:** Atualmente o usuario pressiona o hotkey e nao tem feedback visual algum — so audio (bip). Em maquinas mais lentas ou com ruido ambiente, o usuario nao sabe se o sistema registrou o comando.

**AC:**
- Toast/overlay nao-bloqueante aparece imediatamente ao pressionar hotkey de inicio
  - Estado "Gravando": indicador vermelho pulsante + texto "Gravando..." + tecla de parada
  - Estado "Processando": spinner + texto "Processando..."
  - Estado "Pronto": checkmark verde + preview das primeiras 60 chars do output (2s auto-dismiss)
- Overlay nao rouba foco da janela ativa (o texto continua sendo colado no lugar certo)
- Implementado com `ctypes`/win32 ou tkinter sem focus steal (testar ambas as abordagens — escolher a mais estavel)
- Posicao: canto inferior direito (configuravel via `.env`: `OVERLAY_POSITION`, default `bottom-right`)
- `OVERLAY_ENABLED=true` no `.env.example` (pode desativar)
- Testado com `pythonw.exe` — sem crashes se overlay for fechado durante processamento

**Dependencias tecnicas a validar no dia 1:**
- Janela `tkinter` sem taskbar entry: `wm_overrideredirect(True)` + `wm_attributes("-topmost", True)`
- Focus steal: usar `wm_attributes("-toolwindow", 1)` no Windows
- Se tkinter causar conflito com customtkinter existente: isolar em thread separada com fila de mensagens

---

### Story 4.5.2 — Testes: audio, gemini, ai_provider (P1)

**Prioridade:** P1 — gap critico de cobertura (identificado no Epic 4)
**Estimativa:** 2 dias
**Agente:** @dev + @qa
**Dependencias:** nenhuma (mocks — nao requer hardware)

**Contexto:** `voice/audio.py`, `voice/gemini.py` e `voice/ai_provider.py` sao os modulos mais criticos do produto e os menos cobertos por testes. Qualquer refactoring futuro neles e de alto risco.

**AC:**

`tests/test_audio.py`:
- `record()`: mock `sounddevice.InputStream` — verificar que frames sao acumulados corretamente
- Timeout `MAX_RECORD_SECONDS`: simular timeout, verificar que gravacao encerra
- Bip de aviso: mock `winsound.Beep` — verificar chamada 5s antes do timeout
- VAD threshold: verificar que frames abaixo do threshold sao filtrados
- Cooldown pos-query: verificar que segundo hotkey dentro de 2s e ignorado (apos QW-1)

`tests/test_gemini.py`:
- `_get_gemini_client()`: singleton — duas chamadas retornam a mesma instancia
- Cada modo de processamento (transcricao, prompt simples, COSTAR, query): mock `client.models.generate_content` → verificar prompt enviado e output processado
- Fallback sem API key: verificar comportamento esperado

`tests/test_ai_provider.py` (expandir existente):
- Switch Gemini → OpenAI: verificar que `load_provider()` retorna provider correto por config
- Fallback quando provider nao disponivel: verificar log `[WARN]` e fallback para Gemini
- Cada metodo do provider: `transcribe()`, `process()` com mocks

`CI verde apos`: `python -m pytest tests/ -v` passa com zero falhas

---

### Story 4.5.3 — Hotkey de ciclo de modo (P1 — se nao implementado)

**Prioridade:** P1 — UX de alta alavancagem, esforco baixo
**Estimativa:** 0.5 dia
**Agente:** @dev
**Dependencias:** nenhuma

**Contexto:** ATLAS identificou que usuarios precisam memorizar 7 hotkeys. Um hotkey de ciclo reduz a carga cognitiva.

**Verificar antes de implementar:** Git log indica que single hotkey ja pode ter sido implementado em `2d73992 feat: 10 melhorias — single hotkey, 7 modos`. Se ja implementado, esta story e DONE — apenas documentar no README.

**AC (se nao implementado):**
- `CYCLE_HOTKEY` no `.env.example` (default: `ctrl+shift+tab`)
- Pressionar cicla entre os modos disponiveis em ordem circular
- Tray tooltip atualiza imediatamente com novo modo ativo
- Bip distinto ao ciclar (frequencia e duracao unicas)
- README atualizado com nova hotkey

**AC (se ja implementado):**
- Documentar no README com exemplo de uso
- Adicionar ao startup log: `[INFO] Modo atual: {modo} | Ciclar: {hotkey}`

---

### Story 4.5.4 — Modo "Clipboard Context" (P2)

**Prioridade:** P2 — alto impacto, esforco medio
**Estimativa:** 1.5 dias
**Agente:** @dev
**Dependencias:** Story 4.5.1 concluida (overlay exibira contexto carregado)

**Contexto:** Usuario copia texto, pressiona hotkey, dita instrucao em voz — Gemini processa a instrucao tendo o clipboard como contexto. Fluxo: "copiei esse email, [pressiona hotkey], responde formalmente pedindo prazo de 15 dias".

**AC:**
- Novo modo `clipboard-context` (ou integrado ao modo query existente via flag)
- No inicio da gravacao: capturar conteudo atual do clipboard (max 2000 chars — truncar com aviso no log)
- Prompt para Gemini: `[CONTEXTO DO CLIPBOARD]\n{clipboard_content}\n\n[INSTRUCAO]\n{transcricao}`
- `CLIPBOARD_CONTEXT_MAX_CHARS` no `.env.example` (default: `2000`)
- Se clipboard vazio: fallback para modo query normal com log `[INFO] Clipboard vazio — modo query direto`
- Overlay (4.5.1) exibe "Clipboard carregado (X chars)" no estado "Gravando"

---

### Story 4.5.5 — Busca no historico (overlay CTk) (P2)

**Prioridade:** P2 — valor real, esforco medio
**Estimativa:** 1.5 dias
**Agente:** @dev
**Dependencias:** `history.jsonl` (ja implementado em Epic 3)

**Contexto:** `history.jsonl` existe mas e inacessivel sem abrir o arquivo manualmente. Uma busca rapida via hotkey fecha esse gap.

**AC:**
- Hotkey `HISTORY_HOTKEY` no `.env.example` (default: `ctrl+shift+h`)
- Abre overlay customtkinter com campo de busca + lista de resultados
- Busca em tempo real no `history.jsonl` — filtra por `raw_text` e `processed_text`
- Selecionar resultado: cola `processed_text` no campo ativo (via `_paste_via_sendinput()`)
- Exibe: timestamp, modo, preview de 80 chars
- Overlay fecha com ESC ou apos colar
- Testado com `pythonw.exe` — janela nao aparece na taskbar

---

### Story 4.5.6 — GEMINI_MODEL_QUALITY separado (P3)

**Prioridade:** P3 — quick win de config, esforco baixo
**Estimativa:** 0.5 dia
**Agente:** @dev
**Dependencias:** SM-3 concluida (GEMINI_MODEL ja configuravel)

**AC:**
- `GEMINI_MODEL_QUALITY` no `.env.example` — permite usar modelo diferente para tarefas leves
  - Ex: `GEMINI_MODEL=gemini-2.0-pro` para query, `GEMINI_MODEL_QUALITY=gemini-2.0-flash` para correcao ortografica
- Se ausente: usa `GEMINI_MODEL` para tudo (comportamento atual preservado)
- Startup log: `[INFO] Gemini: {model} (quality: {quality_model})`

---

### Story 4.5.7 — Modo Screenshot + Voice (P3)

**Prioridade:** P3 — diferencial, esforco medio
**Estimativa:** 2 dias
**Agente:** @dev
**Dependencias:** Story 4.5.1 (overlay feedback), Gemini multimodal ja disponivel via google-genai

**Contexto:** Gemini 2.0 Flash suporta input de imagem. Usuario tira screenshot, pressiona hotkey, dita "explica o que esta acontecendo aqui" — Gemini processa imagem + voz.

**AC:**
- Novo modo `screenshot-voice`
- No inicio da gravacao: capturar screenshot da janela ativa (ou monitor inteiro)
- Usar `PIL.ImageGrab.grab()` para captura
- Enviar screenshot + transcricao para Gemini via `Part.from_bytes()` (padrao ja estabelecido no codebase — ver commit `66217da`)
- `SCREENSHOT_MONITOR` no `.env.example` (default: `active` — janela ativa; alternativa: `all` — monitor inteiro)
- Overlay (4.5.1) exibe "Screenshot capturado" no estado "Gravando"
- Sem dependencia nova — `Pillow` ja esta em `requirements.txt`

---

## Epic 4.6 — Polish & Estabilidade [EM EXECUCAO]

**Objetivo:** Transformar o Voice Commander de "funciona mas incomoda" para "ferramenta que confio e gosto de usar."
**Branch:** `feature/epic-4.6-polish`
**Iniciado:** 2026-03-02
**Agentes:** DEX (todas as stories), NEXUS (spec 4.6.3), QUINN (smoke test 4.6.7)

### Decisoes Editoriais

| Decisao | Motivo |
|---------|--------|
| `BRIEFING_ENABLED=false` por padrao | Usuario confirmou: ruido na experiencia |
| `USER_PROFILE_ENABLED=false` por padrao | Feature de nicho — ativar conscientemente |
| `VISUAL_HOTKEY` vazio por padrao | Modo especializado — nao descoberto organicamente |
| `PIPELINE_HOTKEY` vazio por padrao | Idem |
| Ciclo: 7 → 5 modos | transcribe, email, simple, prompt, query |

### Stories

| Story | Descricao | Prioridade | Agente | Estimativa | Status |
|-------|-----------|------------|--------|------------|--------|
| 4.6.1 | Whisper tiny + beam_size=1 por padrao — latencia <5s | P1 | DEX | 0.5d | PENDENTE |
| 4.6.2 | Indicador de modo ativo no tray + overlay ao ciclar | P1 | DEX | 0.5d | PENDENTE |
| 4.6.3 | Redesign da janela Settings (NEXUS spec + DEX implementa) | P1 | NEXUS+DEX | 4-5d | PENDENTE |
| 4.6.4 | Ciclo reduzido para 5 modos (CYCLE_MODES configuravel) | P1 | DEX | 0.5d | PENDENTE |
| 4.6.5 | Defaults limpos — desativar features de nicho | P2 | DEX | 0.5d | PENDENTE |
| 4.6.6 | Log de timing por fase [PERF] | P2 | DEX | 0.5d | PENDENTE |
| 4.6.7 | Smoke test 5 modos + corrigir bugs recorrentes | P2 | QUINN+DEX | 1-2d | PENDENTE |

**Estimativa total:** 7-10 dias

### Story 4.6.1 — Whisper tiny + beam_size=1 por padrao [PENDENTE]

**Prioridade:** P1
**Estimativa:** 0.5 dia
**Agente:** @dev

**AC:**
- `WHISPER_MODEL=tiny` no `.env.example` (era `small`)
- `WHISPER_BEAM_SIZE=1` no `.env.example` (era `5`)
- Startup log: `[INFO] Whisper: {model} | beam_size={beam_size}`
- Transcricao <3s em CPU em fala de 10s (validado com 4.6.6)

---

### Story 4.6.2 — Indicador de modo ativo no tray + overlay ao ciclar [PENDENTE]

**Prioridade:** P1
**Estimativa:** 0.5 dia
**Agente:** @dev

**AC:**
- Tooltip do tray: `Voice Commander | Modo: Transcricao`
- Ao ciclar (`CYCLE_HOTKEY`): overlay exibe modo novo por 2s (`voice/overlay.py` existente)
- Menu tray: item "Modo: {nome}" no topo (informativo, nao clicavel)

---

### Story 4.6.3 — Redesign da janela Settings [PENDENTE]

**Prioridade:** P1
**Estimativa:** 4-5 dias
**Agentes:** NEXUS (spec) + DEX (implementacao)
**Dependencias:** spec NEXUS aprovado antes da implementacao DEX

**AC:**
- Spec NEXUS entregue: wireframe com abas ou grupos
- Abas sugeridas: Geral | Modos | Avancado | Perfil
- `CTkTabview` do customtkinter
- Salvar com feedback visual ("Salvo!" por 2s)
- Zero regressao nos testes

---

### Story 4.6.4 — Ciclo reduzido para 5 modos [PENDENTE]

**Prioridade:** P1
**Estimativa:** 0.5 dia
**Agente:** @dev

**AC:**
- Ciclo default: `transcribe → email → simple → prompt → query`
- `CYCLE_MODES` no `.env.example` — lista separada por virgula
- Modos `visual` e `pipeline` excluidos do ciclo (hotkey dedicado ainda funciona)
- Startup log: `[INFO] Ciclo de modos: {lista dos modos ativos}`

---

### Story 4.6.5 — Defaults limpos [PENDENTE]

**Prioridade:** P2
**Estimativa:** 0.5 dia
**Agente:** @dev

**AC:**
- `.env.example` atualizado: `BRIEFING_ENABLED=false`, `USER_PROFILE_ENABLED=false`, `VISUAL_HOTKEY=` vazio, `PIPELINE_HOTKEY=` vazio
- `load_config()` trata vazio como "desabilitado"

---

### Story 4.6.6 — Log de timing por fase [PERF] [PENDENTE]

**Prioridade:** P2
**Estimativa:** 0.5 dia
**Agente:** @dev

**AC:**
- Novo prefixo: `[PERF]`
- Fases: `gravacao`, `transcricao`, `gemini`, `paste`, `total`
- Formato: `[PERF] transcricao: 2.34s | gemini: 1.12s | total: 4.01s`
- Ativo apenas se `DEBUG_PERF=true` no `.env` (silencioso por padrao)

---

### Story 4.6.7 — Smoke test 5 modos + bugs recorrentes [PENDENTE]

**Prioridade:** P2
**Estimativa:** 1-2 dias
**Agentes:** QUINN (validacao) + DEX (correcao)
**Dependencias:** 4.6.1 e 4.6.4 concluidas

**Criterio de conclusao do Epic 4.6:**
- Latencia media modos rapidos < 5s (evidencia via `[PERF]`)
- Zero crashes em 20 execucoes por modo (relatorio QUINN)
- Janela Settings redesenhada
- Tooltip exibe modo ativo sem abrir nenhuma janela
- Features de nicho desativadas por padrao
- CI verde em master

---

## Epic 5 — Comercializacao [BLOQUEADO — aguardando Epic 4.6]

**Prerequisito inegociavel:** Epic 4.6 concluido e mergeado em master.
**Justificativa:** Distribuir antes do Epic 4.6 = produto com latencia ~30s e UX degradada para usuarios pagantes.
**Estimativa total:** 12-16 dias
**Agentes:** @dev (DEX), @architect (design de API), @devops (GAGE para infra)

---

### Story 5.1 — Server-side license validation (LT-1)

**Prioridade:** P1 — bloqueante para comercializacao
**Estimativa:** 5-8 dias
**Agentes:** @dev + @architect
**Dependencias:** endpoint `voice.jplabs.ai` operacional (infra GAGE)

**AC (mantido do PRD original):**
- Endpoint `POST /validate` em `voice.jplabs.ai` — recebe chave, retorna `{valid, expires_at, plan}`
- HMAC local vira fallback offline (timeout 72h — atual)
- Diagrama de estados documentado: online-valid / online-invalid / offline-grace / offline-expired
- Chave como identificador de sessao (zero dados pessoais no payload)
- Retry com backoff exponencial (3 tentativas, timeout 5s por tentativa)
- Log: `[OK] Licenca validada (server) | expira em X dias`

**Nota de arquitetura:** @architect deve definir o schema do endpoint antes do DEX implementar o cliente. Dependencia de sequencia: design primeiro.

---

### Story 5.2 — Auto-update simplificado (version.txt) (P1)

**Prioridade:** P1 — necessario para distribuicao sustentavel
**Estimativa:** 1-2 dias
**Agente:** @dev
**Dependencias:** Story 5.1 concluida (reusa endpoint `voice.jplabs.ai`)

**Contexto (revisao ATLAS):** Auto-update via `version.txt` publico e mais simples do que o plano original (que dependia totalmente da API de licenca). As duas abordagens podem coexistir.

**AC:**
- `GET https://voice.jplabs.ai/version.txt` no startup — retorna ultima versao disponivel
- Comparacao com `__version__` local
- Se nova versao: notificacao nao-intrusiva via tray balloon ou menu item "Atualizacao disponivel (vX.Y.Z)"
- Timeout da verificacao: 3s — nao bloqueia startup
- `AUTO_UPDATE_CHECK=true` no `.env.example` (pode desativar)
- Sem auto-instalacao — usuario clica e e redirecionado para pagina de download

---

### Story 5.3 — Instalador Inno Setup atualizado (P1)

**Prioridade:** P1 — prerequisito para distribuicao
**Estimativa:** 1 dia
**Agentes:** @dev + @devops
**Dependencias:** Epic 4.6 concluido e mergeado em master

**AC:**
- `AppVersion` em `build/installer.iss` sincronizado com `__version__` (processo documentado — nao e automatico)
- Build PyInstaller inclui pacote `voice/` completo (~26 modulos)
- Instalador testado em Windows 10 e Windows 11 limpo (sem Python instalado)
- `VoiceCommanderSetup.exe` gerado e testado end-to-end com os 5 modos canonicos do Epic 4.6

---

### Story 5.4 — ui.py: separar Onboarding e Settings (P2)

**Prioridade:** P2 — qualidade de codigo, facilita manutencao futura
**Estimativa:** 1 dia
**Agente:** @dev
**Dependencias:** Epic 4.6 concluido (base estavel — Settings redesenhada)

**AC:**
- `voice/ui.py` refatorado em:
  - `voice/onboarding.py` — fluxo de primeiro uso (API key + licenca)
  - `voice/settings.py` — janela de configuracoes (ja pode ser acessada pelo menu tray)
- Imports atualizados em todos os modulos que referenciam `ui.py`
- `python -m pytest tests/ -v` passa com zero falhas apos refactoring
- Funcionalidade identica — zero regressao

---

## Backlog (apos Epic 5)

Itens sem sprint definida. Revisao apos Epic 5 concluido.

| Item | Justificativa do adiamento |
|------|--------------------------|
| Modo Translate: mapa de idiomas expandido | Funcional com PT/EN — expandir com feedback de uso real |
| BOM UTF-16 no clipboard | Zero problemas reportados em apps modernos |
| Dashboard web de historico (`history.jsonl`) | Fora do escopo de ferramenta pessoal — avaliar demanda real |
| Suporte macOS/Linux | Bloqueado por ctypes.windll — reescrita de arquitetura necessaria |
| Whisper large-v3 como option default | RAM e latencia — aguardar feedback de usuarios reais |
| Dois modelos Whisper em memoria (tiny + small) | Complexidade de 2 instancias concorrentes |
| Pipeline streaming Gemini | Alto esforco, ganho marginal em maquinas rapidas — avaliar com metricas de latencia reais |

---

## Sequencia de Execucao

```
[DONE] Quick Wins QW-1 a QW-8
  commit eee3857

[DONE] Epic 4.5 (6/7 stories)
  4.5.1 overlay        DONE
  4.5.2 testes         DONE
  4.5.3 ciclo          DONE
  4.5.4 clipboard ctx  DONE
  4.5.5 historico      DONE
  4.5.6 model quality  BACKLOG P3
  4.5.7 screenshot     DONE

[AGORA] Epic 4.6 — branch feature/epic-4.6-polish
  4.6.1 (whisper tiny + beam_size=1)    ← P1, iniciar imediatamente
  4.6.2 (modo no tray + overlay ciclar) ← P1, paralelo com 4.6.1
  4.6.4 (ciclo 5 modos)                 ← P1, paralelo
  4.6.5 (defaults limpos)               ← P2, rapido
  4.6.6 (log [PERF])                    ← P2, paralelo — suporte para 4.6.7
    ↓
  4.6.3 (Settings redesign)             ← P1 — NEXUS spec primeiro, DEX implementa
    ↓
  4.6.7 (smoke test QUINN)              ← depende de 4.6.1 + 4.6.4

[DEPOIS] Epic 5 — aguarda Epic 4.6 mergeado em master
  5.1 (server-side license)   ← design de API com @architect primeiro
  5.2 (auto-update)           ← depende de 5.1 (reusa endpoint)
  5.3 (instalador atualizado) ← depende de Epic 4.6 mergeado
  5.4 (separar ui.py)         ← pode ser paralelo a 5.1/5.2
```

---

## Definition of Done (todas as stories)

- [ ] Codigo commitado no branch `feature/{story-id}` e mergeado em `master`
- [ ] `python -m py_compile voice/*.py` sem erros
- [ ] 5 modos canonicos sem regressao (testado manualmente — Epic 4.6+)
- [ ] Testado com `pythonw.exe` (sem console — stdout/stderr sao None)
- [ ] `.env.example` atualizado se nova variavel adicionada
- [ ] `README.md` atualizado se feature visivel ao usuario
- [ ] `python -m pytest tests/ -v` passa com zero falhas
- [ ] CI verde no PR antes do merge
- [ ] Prefixos de log respeitados: `[OK]`, `[...]`, `[WARN]`, `[ERRO]`, `[REC]`, `[STOP]`, `[SKIP]`, `[INFO]`, `[PERF]` (a partir do Epic 4.6)

---

*Voice Commander — JP Labs*
*Analise: ATLAS | Roadmap: MORGAN | Data: 2026-03-02*

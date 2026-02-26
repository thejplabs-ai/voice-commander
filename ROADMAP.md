# Voice Commander — Roadmap

**Versão:** 1.0.14
**Data:** 2026-02-26
**Status:** Epic 4 concluido | Epic 4.5 planejado | Epic 5 revisado
**Branch atual:** feature/SM-3-gemini-model

---

## Estado Real do Projeto (2026-02-26)

Epic 4 foi entregue e **superado**. O codebase evoluiu muito além do planejado:

| Entregue | Status |
|----------|--------|
| Modularizacao completa (`voice/`) | OK — 19 modulos |
| CI GitHub Actions | OK — `.github/workflows/ci.yml` |
| Pytest com cobertura ampla | OK — 14 arquivos de test |
| Gemini model via `.env` (SM-3) | OK — branch atual |
| 7 modos de operacao (antes: 4) | OK — expandido |
| OpenAI como AI provider alternativo | OK — `voice/ai_provider.py` |
| Wake word | OK — `voice/wakeword.py` |
| GPU/CUDA fallback automatico | OK |
| Single hotkey (ciclo de modos) | OK |

**Gaps identificados pelo ATLAS ainda abertos:**

| Gap | Modulo afetado |
|-----|---------------|
| `audio.py`, `ai_provider.py` sem cobertura pytest | `tests/` |
| `openai` sem versao pinada em `requirements.txt` | `openai>=1.0.0` (sem pin) |
| Cooldown 2s em modo query — bug ativo | `voice/app.py` |
| Wake word: requirements.txt incompleto | dependencia ausente |

---

## Quick Wins — Fazer antes de qualquer nova feature

**Criterio de entrada:** cada item < 4h. Podem ser agrupados num unico PR "housekeeping".
**Agente:** @dev (DEX)
**Prazo sugerido:** 1 dia

### QW-1 — Fix: cooldown silencioso 2s apos modo query

**Problema:** Modo query dispara processamento duas vezes (hotkey stop registrado como novo start).
**AC:**
- Cooldown de 2s implementado apos processamento de query — hotkey ignorado nesse intervalo
- Sem regressao nos demais modos
- Log: `[SKIP] Cooldown ativo — ignorando hotkey`

**Agente:** @dev
**Dependencias:** nenhuma

---

### QW-2 — Fix: pin de versao do openai em requirements.txt

**Problema:** `openai>=1.0.0` sem pin exato — viola a politica de versoes pinadas do projeto.
**AC:**
- `pip show openai` no ambiente atual → extrair versao exata
- `requirements.txt` atualizado com versao pinada (`openai==X.Y.Z`)
- Comentario de data do pin adicionado

**Agente:** @dev
**Dependencias:** nenhuma

---

### QW-3 — Fix: wake word — dependencia ausente em requirements.txt

**Problema:** `voice/wakeword.py` usa biblioteca que nao esta em `requirements.txt`.
**AC:**
- Identificar import(s) faltantes em `wakeword.py`
- Adicionar com versao pinada em `requirements.txt`
- `python -m py_compile voice/wakeword.py` sem erros em ambiente limpo

**Agente:** @dev
**Dependencias:** nenhuma

---

### QW-4 — Config: `beam_size` e `PASTE_DELAY_MS` configuravel

**Problema:** `beam_size` do Whisper e delay de paste estao hardcoded.
**AC:**
- `WHISPER_BEAM_SIZE` no `.env.example` (default: `5`, aceita `1`-`10`)
- `PASTE_DELAY_MS` no `.env.example` (default: `50`, em ms)
- `load_config()` carrega e valida ambos com fallback seguro
- Log de startup exibe valores ativos

**Agente:** @dev
**Dependencias:** nenhuma

---

### QW-5 — Config: OpenAI startup check

**Problema:** Se `OPENAI_API_KEY` configurada mas openai nao instalado, erro ocorre em runtime.
**AC:**
- No startup, se `AI_PROVIDER=openai`: verificar se pacote `openai` importavel
- Falha: `[WARN] openai nao instalado — fallback para Gemini`
- Sem crash no startup

**Agente:** @dev
**Dependencias:** QW-2 (pin primeiro)

---

### QW-6 — Tray: duracao de gravacao no tooltip

**Problema:** Tooltip nao exibe quanto tempo o usuario esta gravando.
**AC:**
- Durante gravacao: tooltip atualiza a cada 1s com tempo decorrido (`Gravando: 0:12`)
- Estado Idle: tooltip volta ao padrao (nome do app + modo ativo)
- Testado com `pythonw.exe`

**Agente:** @dev
**Dependencias:** nenhuma

---

### QW-7 — Housekeeping: temp file cleanup no startup

**Problema:** Arquivos `.wav` temporarios podem acumular se processo encerrado abruptamente.
**AC:**
- No startup: limpar arquivos `*.wav` temporarios em `_BASE_DIR`
- Log: `[INFO] X arquivo(s) temporario(s) removidos` (so se X > 0)
- Nao remover arquivos com mais de 24h (paranoia — poderiam ser de outro processo)

**Agente:** @dev
**Dependencias:** nenhuma

---

### QW-8 — Fix: ui.py — winfo_exists() check antes de interagir com Settings Window

**Problema:** Crash se Settings Window destruida antes do callback ser chamado.
**AC:**
- Todos os callbacks de `ui.py` que interagem com a janela verificam `window.winfo_exists()` antes
- Zero crashes ao fechar Settings rapidamente

**Agente:** @dev
**Dependencias:** nenhuma

---

## Epic 4.5 — UX & Qualidade

**Objetivo:** Fechar gaps de UX criticos e elevar cobertura de testes antes de distribuir comercialmente.
**Premissa do ATLAS (endossada):** Sem feedback visual claro, Epic 5 distribui um produto que o usuario percebe como "lento e opaco". UX primeiro.
**Prerequisito:** Quick Wins concluidos (especialmente QW-1).
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

## Epic 5 — Comercializacao (Revisado)

**Objetivo original:** Licenciamento server-side + distribuicao.
**Revisao ATLAS:** Adicionar auto-update simplificado e prep de UX antes de distribuir.

**Prerequisito inegociavel:** Epic 4.5 concluido (especialmente 4.5.1 — overlay).
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
**Dependencias:** todas as features de Epic 4.5 mergeadas em master

**AC:**
- `AppVersion` em `build/installer.iss` sincronizado com `__version__` (processo documentado — nao e automatico)
- Build PyInstaller inclui pacote `voice/` completo (todos os 19 modulos)
- Instalador testado em Windows 10 e Windows 11 limpo (sem Python instalado)
- `VoiceCommanderSetup.exe` gerado e testado end-to-end com todos os 7 modos

---

### Story 5.4 — ui.py: separar Onboarding e Settings (P2)

**Prioridade:** P2 — qualidade de codigo, facilita manutencao futura
**Estimativa:** 1 dia
**Agente:** @dev
**Dependencias:** Epic 4.5 concluido (base estavel)

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
[AGORA] Quick Wins (QW-1 a QW-8)
  — 1 dia — @dev — PR unico "housekeeping"

[PROXIMO] Epic 4.5
  4.5.2 (testes audio/gemini/ai_provider)   ← iniciar junto com 4.5.1
  4.5.1 (overlay)                           ← P1, iniciar imediatamente
  4.5.3 (ciclo de modo — verificar se ja feito)
    ↓
  4.5.4 (clipboard context)   ← depende de 4.5.1
  4.5.5 (busca historico)     ← independente
  4.5.6 (GEMINI_MODEL_QUALITY)← independente, quickest
    ↓
  4.5.7 (screenshot + voice)  ← depende de 4.5.1

[DEPOIS] Epic 5
  5.1 (server-side license)   ← design de API com @architect primeiro
  5.2 (auto-update)           ← depende de 5.1 (reusa endpoint)
  5.3 (instalador atualizado) ← depende de 4.5 mergeado
  5.4 (separar ui.py)         ← pode ser paralelo a 5.1/5.2
```

---

## Definition of Done (todas as stories)

- [ ] Codigo commitado no branch `feature/{story-id}` e mergeado em `master`
- [ ] `python -m py_compile voice/*.py` sem erros
- [ ] 7 modos existentes sem regressao (testado manualmente)
- [ ] Testado com `pythonw.exe` (sem console — stdout/stderr sao None)
- [ ] `.env.example` atualizado se nova variavel adicionada
- [ ] `README.md` atualizado se feature visivel ao usuario
- [ ] `python -m pytest tests/ -v` passa com zero falhas
- [ ] CI verde no PR antes do merge
- [ ] Prefixos de log respeitados: `[OK]`, `[...]`, `[WARN]`, `[ERRO]`, `[REC]`, `[STOP]`, `[SKIP]`, `[INFO]`

---

*Voice Commander — JP Labs*
*Analise: ATLAS | Roadmap: MORGAN | Data: 2026-02-26*

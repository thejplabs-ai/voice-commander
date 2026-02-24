# PRD — Voice Commander

**Versão do Produto:** 1.0.11
**Tipo:** Ferramenta pessoal (uso interno JP Labs)
**Owner:** JP
**PRD criado em:** 2026-02-24
**Repositório:** `thejplabs/voice-commander`

---

## Nota sobre Nomenclatura

> Os documentos anteriores (commits, DEX MEMORY, changelogs) usam o termo "Sprint N" para se referir aos ciclos de entrega iniciais. A partir deste PRD, a nomenclatura canônica passa a ser **Epic N**. O mapeamento retroativo é:
>
> - Sprint 1 = Epic 1
> - Sprint 2 = Epic 2
> - Sprint 3 = Epic 3
>
> Epic 4 em diante segue a nomenclatura nova. Ao referenciar trabalho passado, ambos os termos são válidos.

---

## 1. Overview

**Voice Commander** é uma ferramenta voice-to-text para Windows que captura áudio via hotkey global, transcreve localmente com Whisper, processa com Gemini e cola o resultado diretamente onde o cursor estiver — sem janela visível, sem distração.

O produto resolve um fluxo real de trabalho do JP: ditar comandos, prompts e texto corrido em qualquer aplicativo do Windows com latência mínima e sem depender de serviços cloud para a transcrição.

### Modos de Operação

| Hotkey | Modo | Comportamento |
|--------|------|---------------|
| `Ctrl+Shift+Space` | Transcrição pura | Transcreve e corrige erros de pronúncia via Gemini |
| `Ctrl+Alt+Space` | Prompt simples | Transcreve e organiza em bullet points |
| `Ctrl+CapsLock+Space` | Prompt estruturado | Formata em SYSTEM + USER com XML tags (framework COSTAR) |
| `Ctrl+Shift+Alt+Space` | Query direta Gemini | Transcreve e envia ao Gemini — cola a resposta direto |

Hotkey do modo 4 é configurável via `.env` (`QUERY_HOTKEY`).

---

## 2. Constraints Tecnicas (BLOQUEANTES)

> Estas constraints são inegociáveis para Epic 1-4. Revisão apenas a partir de Epic 5+.

### Windows-Only por Design

| Constraint | Detalhe |
|------------|---------|
| **Sistema Operacional** | Windows 10 / 11 exclusivo |
| **ctypes.windll** | Usado para `SendInput` (paste), `winsound` (beeps de feedback), `Named Mutex Win32` (singleton) |
| **SendInput** | Cola texto via simulação de teclado — sem equivalente cross-platform simples |
| **winsound** | Beeps de feedback auditivo — API exclusiva do Windows |
| **Named Mutex Win32** | Garante instância única — usa `CreateMutexW` da win32 API |

**Suporte macOS/Linux: fora do escopo até Epic 5+.** Qualquer story que proponha abstrair ctypes.windll deve ser movida para o backlog com justificativa de negócio clara.

### Runtime e Dependências

| Constraint | Valor |
|------------|-------|
| **Python** | 3.13 exclusivo — dependências testadas nesta versão |
| **Versões pinadas** | `requirements.txt` com versões fixas — não atualizar sem ciclo de teste |
| **Dependências principais** | faster-whisper 1.2.1, google-genai 1.63.0, keyboard 0.13.5, sounddevice 0.5.5, numpy 2.4.2, pystray 0.19.5, Pillow 11.1.0, customtkinter 5.2.2 |
| **Modelo Whisper** | `small` por default (~244 MB, baixado na 1ª execução) |
| **Execução sem console** | `pythonw.exe` — stdout/stderr são None, verificar antes de escrever |

---

## 3. Estado Atual — Epics 1-3 Entregues

### Epic 1 (Sprint 1) — Fundacao

Estabeleceu o núcleo funcional do produto.

**Entregas:**
- Gravação de áudio via `sounddevice` com toggle por hotkey
- Transcrição local com `faster-whisper` (modelo `small`)
- 3 modos de output: transcrição pura, prompt simples, prompt estruturado
- Paste via `ctypes.SendInput` — zero dependência de clipboard
- Singleton via Named Mutex Win32 (instância única garantida)
- Log em arquivo (`voice.log`)
- Cache de API key + configuração centralizada via `.env`
- Timeout de gravação `MAX_RECORD_SECONDS` com bip de aviso 5s antes
- Consolidação dos launchers VBS (`launch_voice.vbs` com path absoluto + fallback)
- Dependências pinadas em `requirements.txt`

---

### Epic 2 (Sprint 2) — UX e Modos

Adicionou visibilidade de estado e expandiu os modos de operação.

**Entregas:**
- System tray com 3 estados visuais via `pystray`:
  - Cinza = aguardando
  - Vermelho = gravando
  - Amarelo = processando
- Menu tray: Status (modo + configurações ativas), Encerrar
- Modo 4: Query Direta Gemini (`Ctrl+Shift+Alt+Space`, configurável via `QUERY_HOTKEY`)
- Validação de microfone no startup (falha com log `[ERRO]` se dispositivo indisponível)
- Loop de resiliência de hotkeys (re-registro automático em caso de falha)

---

### Epic 3 (Sprint 3) — Observabilidade

Adicionou rastreabilidade completa de transcrições e logs robustos.

**Entregas:**

**Story 3.1 — Histórico de transcrições (`history.jsonl`)**
- Arquivo append-only com todas as transcrições
- Campos: `timestamp`, `mode`, `raw_text`, `processed_text`, `duration_seconds`, `chars`
- Erros registrados com `"error": true` e `"processed_text": null`
- Trim automático ao atingir `HISTORY_MAX_ENTRIES` (default: 500)
- Ignorado pelo git (dado pessoal)

**Story 3.2 — Rotação de log por sessão**
- Log anterior renomeado para `voice.YYYY-MM-DD_HH-MM-SS.log` a cada startup
- `LOG_KEEP_SESSIONS` controla quantas sessões manter (default: 5)
- Sessões mais antigas deletadas automaticamente

**Story 3.3 — Graceful shutdown**
- Aguarda transcrição finalizar se gravação ativa no momento do shutdown
- Thread-safe: usa `_toggle_lock` para ler estado de gravação
- Timeout de 10s para transcrição de shutdown — após isso, aborta com `[WARN]`
- `try/finally` garante `_release_named_mutex()` em qualquer cenário
- Reutilizado no Ctrl+C e no menu tray (Encerrar)

---

### Quick Wins 2026-02-24 (fora de sprint, entregues avulso)

| Item | Detalhe |
|------|---------|
| `.gitignore` | `history.jsonl` + `logs/` adicionados — dados pessoais não versionados |
| Singleton Gemini | `_get_gemini_client()` — instância única em memória, inicializada sob demanda |
| `__version__` em `voice.py` | Source única de verdade para a versão — sem duplicação |
| Clipboard via ctypes | `_paste_via_sendinput()` — refatoração que consolida o método de paste |

---

## 4. Definition of Done

Critérios aplicáveis a todas as stories do Epic 4 em diante:

- [ ] Código commitado no branch `feature/{story-id}` e mergeado em `master`
- [ ] `python -m py_compile voice.py` sem erros
- [ ] 4 modos existentes sem regressão (testado manualmente — modos 1, 2, 3, 4)
- [ ] Testado com `pythonw.exe` (sem console — stdout/stderr são None)
- [ ] `.env.example` atualizado se nova variável de configuração adicionada
- [ ] `README.md` atualizado se a feature é visível ao usuário
- [ ] Prefixos de log respeitados: `[OK]`, `[...]`, `[WARN]`, `[ERRO]`, `[REC]`, `[STOP]`, `[SKIP]`, `[INFO]`

---

## 5. Epic 4 — Qualidade e Distribuicao (Sprint 4)

**Objetivo:** Tornar o codebase testável, modular e com CI automatizado — fundação obrigatória antes de qualquer trabalho de comercialização.

**Pré-requisito para iniciar:** nenhum (Epic 3 concluído).

**Sequência obrigatória de execução:** 4.1 → (4.2 e 4.3 em paralelo) → 4.4

> 4.2 depende de 4.1 como safety net. 4.3 depende de 4.1 para ter testes para rodar no CI. 4.4 depende de 4.2 porque `load_config` muda de lugar na modularização.

---

### Story 4.1 — Testes pytest (SM-2)

**Estimativa:** 2 dias
**Agente:** DEX
**Dependências:** nenhuma
**Branch:** `feature/SM-2-pytest`

**Contexto:** O codebase atual não tem testes automatizados. Qualquer refactoring (Story 4.2) sem uma suite de testes é de alto risco. Esta story cria o safety net antes.

**Acceptance Criteria:**

1. `pytest` adicionado a `requirements.txt` com versão pinada
2. Diretório `tests/` criado com `tests/test_voice.py`
3. Testes implementados cobrindo:
   - Validação de chave de licença (HMAC) — formatos válidos e inválidos
   - `load_config()` retorna defaults corretos quando `.env` ausente
   - `load_config()` respeita variáveis definidas no `.env`
   - Detecção de `GEMINI_API_KEY` ausente — comportamento de fallback esperado
   - Append e leitura de `history.jsonl` — campos obrigatórios presentes, trim funciona
4. Testes de hardware (`sounddevice`, `keyboard`) usam mocks — nenhum teste requer microfone real ou hotkey física
5. `python -m pytest tests/ -v` passa com zero falhas em ambiente limpo
6. `README.md` atualizado com seção "Rodando os testes": `python -m pytest tests/ -v`

---

### Story 4.2 — Modularizacao (SM-1)

**Estimativa:** 3 dias
**Agente:** DEX
**Dependência OBRIGATORIA:** Story 4.1 CONCLUIDA antes de iniciar

> A suite de testes da 4.1 é o safety net para este refactoring. Iniciar 4.2 sem 4.1 concluída é BLOCK.

**Aviso de estimativa:** 3 dias é estimativa otimista. O estado global do `voice.py` atual é complexo (mutex, tray thread, hotkey callbacks, graceful_shutdown interdependente). Alocar buffer de 1 dia adicional se necessário.

**Branch:** `feature/SM-1-modularize`

**Contexto:** `voice.py` atual tem mais de 600 linhas com responsabilidades misturadas. A modularização facilita manutenção, testes isolados e o build PyInstaller para distribuição.

**Acceptance Criteria:**

1. Pacote `voice/` criado com os seguintes módulos:

   | Módulo | Responsabilidade |
   |--------|-----------------|
   | `voice/config.py` | `load_config()`, `_BASE_DIR`, `.env` loading |
   | `voice/license.py` | Validação HMAC, parsing de chave `vc-{expiry_b64}-{sig}` |
   | `voice/audio.py` | `sounddevice` recording, `MAX_RECORD_SECONDS`, bips `winsound` |
   | `voice/transcribe.py` | `faster-whisper`, `_append_history()` |
   | `voice/gemini.py` | `_get_gemini_client()`, 4 modos de processamento Gemini |
   | `voice/tray.py` | `pystray`, 3 estados visuais, menu |
   | `voice/onboarding.py` | `customtkinter`, UI de primeiro uso (API key + licença) |
   | `voice/shutdown.py` | `graceful_shutdown()`, `_release_named_mutex()` |

2. `voice.py` na raiz se torna entry point slim com menos de 50 linhas (imports + `main()`)

3. Todos os pitfalls documentados em `.claude/agent-memory/dev/MEMORY.md` preservados após refactoring:
   - `suppress=False` nos hotkeys (sem latência em Ctrl/Shift/Alt globais)
   - `os._exit(0)` no tray quit (pystray daemon threads travam exit normal)
   - Idempotência de `_release_named_mutex()` (checar `if _mutex_handle` antes de liberar)
   - `current_mode` salvo no início da gravação (não no fim — race condition)
   - Onboarding executado ANTES do mutex (não bloquear se usuário abandona onboarding)

4. `build/build.bat` atualizado para PyInstaller com o novo pacote `voice/`

5. `python -m pytest tests/ -v` passa com zero falhas após o refactoring

6. Testado manualmente com `pythonw.exe` — os 4 modos funcionam sem regressão

---

### Story 4.3 — CI GitHub Actions (LT-3)

**Estimativa:** 1 dia
**Agentes:** DEX + GAGE
**Dependência:** Story 4.1 concluída
**Branch:** `feature/LT-3-ci`

**Contexto:** Sem CI, qualquer push pode quebrar silenciosamente os 4 modos. A suite de testes da 4.1 precisa rodar automaticamente em cada PR e push para `master`.

**Acceptance Criteria:**

1. `.github/workflows/ci.yml` criado
2. Jobs configurados:
   - **lint:** `flake8` ou `ruff` — zero erros bloqueantes
   - **test:** `python -m pytest tests/ -v` — zero falhas
   - **build-check:** `python -m py_compile voice.py` — zero erros de sintaxe
3. Runner: `windows-latest` (compatibilidade com ctypes.windll e dependências Windows)
4. Cache de pip configurado para builds rápidos
5. Badge de status CI adicionado ao início do `README.md`

---

### Story 4.4 — Gemini model abstraction (SM-3)

**Estimativa:** 1 dia
**Agente:** DEX
**Dependência recomendada:** Story 4.2 concluída
**Branch:** `feature/SM-3-gemini-model`

> Após a modularização, `load_config()` muda de `voice.py` para `voice/config.py`. Implementar 4.4 antes de 4.2 cria merge conflict. Recomendado, mas não obrigatório se escopo for limitado ao `.env.example` apenas.

**Contexto:** O nome do modelo Gemini está hardcoded no código. Trocar de modelo exige editar `voice.py` (ou `voice/gemini.py` após 4.2) — deveria ser configuração.

**Acceptance Criteria:**

1. `GEMINI_MODEL` adicionado ao `.env.example` com valor default `gemini-2.0-flash` e comentário explicativo
2. Nenhum nome de modelo Gemini hardcoded em `voice.py` (ou nos módulos após 4.2)
3. Modelo logado no startup: `[INFO] Gemini model: {model}`
4. Documentação da variável no `.env.example`:
   ```
   # Modelo Gemini a usar (default: gemini-2.0-flash)
   # Alternativas: gemini-1.5-pro, gemini-2.0-pro
   GEMINI_MODEL=gemini-2.0-flash
   ```

---

### Sequencia de Execucao — Epic 4

```
4.1 (pytest)        ← iniciar imediatamente
    ↓
4.2 (modularização) ← aguardar 4.1
4.3 (CI)            ← aguardar 4.1 (paralelo com 4.2)
    ↓
4.4 (Gemini model)  ← aguardar 4.2
```

**Critério de conclusão do Epic 4:**
- `python -m pytest tests/ -v` passa com zero falhas
- CI verde em `master`
- `voice.py` como entry point slim (< 50 linhas)
- 4 modos sem regressão em `pythonw.exe`

---

## 6. Epic 5 — Comercializacao (Sprint 5 — Futuro)

**Status:** Planejado — não iniciar antes de Epic 4 concluído integralmente.

**Pré-requisito inegociável:** Epic 4 concluído (CI verde, testes passando, codebase modular).

**Objetivo:** Transformar a ferramenta pessoal em produto vendável com licenciamento server-side e distribuição via instalador.

---

### Story 5.1 — Server-side license validation (LT-1)

**Estimativa:** 5-8 dias
**Agentes:** DEX + @architect (para design da API)
**Dependências:** Epic 4 concluído, endpoint `voice.jplabs.ai` operacional

**Descrição:** O sistema HMAC local atual (`vc-{expiry_b64}-{sig}`) valida apenas a assinatura — não verifica revogação, não rastreia uso, não permite renovação sem novo binário. A validação server-side resolve isso.

**Escopo:**
- Endpoint `POST /validate` em `voice.jplabs.ai` — recebe chave, retorna status + expiry
- HMAC local vira fallback para cenários offline (timeout de 72h)
- Lógica de retry + fallback documentada com diagrama de estados
- Chave de licença usada como identificador de sessão (sem dados pessoais)

---

### Story 5.2 — Auto-update (LT-2)

**Estimativa:** 3-5 dias
**Agente:** DEX
**Dependências:** Epic 4 concluído, Story 5.1 concluída (reusa endpoint `voice.jplabs.ai`)

**Descrição:** No startup, verificar via API se há nova versão disponível. Notificar via tray tooltip ou dialog customtkinter. Download opcional do novo instalador.

**Escopo:**
- Verificação de versão no startup (request leve, não bloquear inicialização)
- Notificação não intrusiva (tray balloon ou menu item "Atualização disponível")
- Download do instalador quando usuário confirma
- Sem auto-instalação silenciosa — usuário controla quando instalar

---

## 7. Backlog

Itens identificados mas sem sprint definida. Revisão a cada Epic concluído.

| Item | Prioridade | Motivo do Adiamento |
|------|------------|---------------------|
| BOM UTF-16 no clipboard | Baixa | Nenhum problema reportado em produção com apps modernos — aguardar feedback real |
| Dois modelos Whisper em memória (tiny + small) | Baixa | Complexidade de 2 instâncias concorrentes — aguardar feedback de latência do usuário |
| Dashboard web de histórico (`history.jsonl`) | Baixa | Fora do escopo de ferramenta pessoal MVP — avaliar se há demanda real |
| Suporte macOS/Linux | Não priorizado | Bloqueado por `ctypes.windll`, `winsound` e Named Mutex Win32 — arquitetura precisaria ser reescrita |
| Whisper large-v3 como opção default | Baixa | RAM e latência — avaliar com feedback de usuários reais |
| Histórico com busca (UI) | Baixa | `history.jsonl` atual é suficiente para o uso pessoal — complexidade alta para ganho incerto |

---

## 8. Metricas de Sucesso

### Epic 4
- `python -m pytest tests/ -v` — 0 falhas, 100% dos critérios das stories testados
- CI GitHub Actions — badge verde no `README.md`
- `voice.py` entry point — menos de 50 linhas após modularização
- Regressão — 0 bugs nos 4 modos em `pythonw.exe` após 4.2

### Epic 5 (quando executado)
- Licença server-side — 100% das ativações validadas online (fallback offline acionado apenas em falhas de rede documentadas)
- Auto-update — notificação exibida em menos de 3s após startup quando nova versão disponível
- Zero dados pessoais no payload de validação de licença

---

*JP Labs Creative Studio — Voice Commander PRD v1.0*
*Owner: JP | Criado: 2026-02-24 | Versão do produto: 1.0.11*
